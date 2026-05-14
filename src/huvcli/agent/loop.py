"""run_agent — the main agent loop.

Orchestrates: provider call → tool dispatch (native or XML fallback or JSON
action) → tool execution (via hooks + MCP + local tools) → message-history
update → repeat. Per-turn guards (sweep detector, empty-streak counter,
repeat-call short-circuit, oversized-edit nudge) live alongside.

Almost all logic that isn't this orchestration sits in sibling modules:
- prompt.py  : SYSTEM_PROMPT + project guidance
- parsing.py : think/XML scrubbing, XML/JSON tool-call extraction
- render.py  : status labels, summaries, bad-final detection
- repeat_guard.py : same-call-three-times short-circuit
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..hooks import load_hooks, run_hooks
from ..mcp import MCPRegistry
from ..provider import ApiClient
from ..session import (
    COMPACT_THRESHOLD_CHARS,
    SessionState,
    append_history,
    compact_if_needed,
    ensure_workspace,
    load_conversation,
    needs_compaction,
    save_conversation,
    total_chars,
)
from ..tools import ToolContext, call_tool
from ..tools.registry import schemas_for
from ..ui import UI
from .parsing import (
    TOOL_BLOCK_OPEN_RE,
    TOOL_BLOCK_RE,
    looks_like_garbled_xml_tool,
    parse_action,
    parse_xml_tool_calls,
    scrub_prose,
    strip_think,
)
from .prompt import SYSTEM_PROMPT, project_guidance
from .render import QUIET_PRE_STATUS, STATUS, is_bad_final, result_summary
from .repeat_guard import RepeatGuard


def run_agent(
    prompt: str,
    cwd: Path,
    yes: bool = False,
    max_steps: int | None = None,
    verbose: bool = False,
    save: bool = True,
    plain: bool = False,
    approval: str = "suggest",
    resume: bool = False,
    session: SessionState | None = None,
) -> str:
    # Resolved lazily so the agent package's DEFAULT_MAX_STEPS (env-driven)
    # is the source of truth even after importlib.reload.
    if max_steps is None:
        from . import DEFAULT_MAX_STEPS
        max_steps = DEFAULT_MAX_STEPS
    client = ApiClient()
    ui = UI(plain=plain)
    ctx = ToolContext(cwd=cwd, yes=yes, verbose=verbose, approval=approval)
    prefs = ensure_workspace(cwd)
    if not save:
        prefs["save_history"] = False
    tool_log: list[dict[str, str]] = []

    # Use shared session resources when available (chat mode), else create
    # ephemeral ones for a single-shot invocation.
    owns_session = session is None
    if session is None:
        session = SessionState(cwd=cwd, mcp=MCPRegistry(cwd), hooks=load_hooks(cwd))
    if session.mcp is None:
        session.mcp = MCPRegistry(cwd)
    mcp = session.mcp
    hooks = session.hooks
    # Seed ctx with the session's pristine snapshots so a file edited
    # across multiple turns reverts to its true pre-session bytes.
    ctx.originals = dict(session.originals)
    mcp_schemas = mcp.discover() if mcp.config else []
    if mcp_schemas and owns_session:
        print(ui.dim(f"MCP: {len(mcp_schemas)} tool(s) from {len(mcp.config)} server(s)"))

    # user_prompt hook (can block before sending to model)
    if hooks:
        allowed, output = run_hooks(cwd, hooks, "user_prompt", {"prompt": prompt})
        if not allowed:
            return f"Blocked by user_prompt hook:\n{output}"

    plan_banner = ""
    if approval == "plan":
        plan_banner = (
            "\n\n=== PLAN MODE ===\n"
            "Mutating tools (write_file, edit_file, apply_patch, run_command) are "
            "DISABLED. You can read, grep, glob, webfetch, question — anything that "
            "doesn't change the workspace. End the turn with a concrete plan as the "
            "final answer: which files you would change, what each change is, and "
            "what to verify. The user will re-run in auto-edit mode to execute.\n"
        )
    system = {"role": "system", "content": SYSTEM_PROMPT + plan_banner + project_guidance(cwd)}
    messages: list[dict[str, Any]] = [system]
    if resume:
        prior = load_conversation(cwd)
        if prior:
            messages.extend(prior)
    messages.append({"role": "user", "content": prompt})

    use_native_tools = client.config.use_tools
    all_schemas = schemas_for(approval) + mcp_schemas
    repeat_guard = RepeatGuard()

    def _dispatch(name: str, args: dict[str, Any]) -> str:
        if mcp.has(name):
            return mcp.call(name, args)
        return call_tool(ctx, name, args)

    def _render_tool_result(name: str, result: str, summary: str, ok: bool) -> None:
        if verbose:
            print(ui.tool_call(name, summary, ok=ok))
            print(ui.dim(result[:4000]))
        elif name == "update_plan" and ctx.plan:
            print(ui.tool_call(name, "plan updated", ok=ok))
            print(ui.plan(ctx.plan))
        else:
            print(ui.tool_call(name, summary, ok=ok))

    def _run_tool(name: str, args: dict[str, Any]) -> str:
        nudge = repeat_guard.maybe_short_circuit(name, args)
        if nudge is not None:
            repeat_guard.record(name, args, nudge)
            return f"Tool short-circuited: {nudge}"
        if hooks:
            allowed, hook_out = run_hooks(cwd, hooks, "pre_tool", {"tool": name, "args": args})
            if not allowed:
                return f"Tool blocked by hook: {hook_out}"
            prefix = (hook_out + "\n") if hook_out else ""
        else:
            prefix = ""
        try:
            result = _dispatch(name, args)
        except Exception as exc:  # noqa: BLE001
            result = f"Tool error: {exc}"
        if hooks:
            _, post_out = run_hooks(
                cwd, hooks, "post_tool",
                {"tool": name, "args": args, "result": result[:8000]},
            )
            if post_out:
                result = result + "\n" + post_out
        full = prefix + result
        repeat_guard.record(name, args, full)
        return full

    def _finalize(answer: str) -> str:
        # Belt-and-suspenders: scrub any leaked XML/think envelopes from
        # whatever the model produced before we frame it as the answer.
        answer = strip_think(answer)
        answer = TOOL_BLOCK_RE.sub("", answer)
        open_m = TOOL_BLOCK_OPEN_RE.search(answer)
        if open_m:
            answer = answer[: open_m.start()].rstrip()
        answer = answer.strip() or (
            "(model returned no usable text — see the tool calls above for what "
            "actually happened. Try rephrasing or asking it to summarize what it did.)"
        )
        # Surface remaining plan steps so the user sees what's left.
        if ctx.plan:
            unfinished = [s for s in ctx.plan if s.get("status") != "completed"]
            if unfinished:
                print(ui.section("Plan progress"))
                print(ui.plan(ctx.plan))
                print(ui.warning(f"{len(unfinished)} step(s) not marked complete."))
        # Promote any newly-touched originals into the session store so
        # /revert later in the chat can roll them back.
        for path, original in ctx.originals.items():
            session.originals.setdefault(path, original)
        if ctx.changes:
            print(ui.changed_files(ctx.changes))
            for path, delta in ctx.changes.items():
                prior = session.changes.get(path)
                if prior:
                    if prior["action"] == "added" and delta["action"] == "modified":
                        action = "added"
                    elif prior["action"] == "deleted" or delta["action"] == "deleted":
                        action = "deleted"
                    else:
                        action = delta["action"]
                    session.changes[path] = {
                        "action": action,
                        "adds": prior.get("adds", 0) + delta.get("adds", 0),
                        "dels": prior.get("dels", 0) + delta.get("dels", 0),
                    }
                else:
                    session.changes[path] = dict(delta)
        append_history(cwd, prompt, answer, tool_log, prefs)
        if save:
            save_conversation(cwd, messages)
        if hooks:
            run_hooks(
                cwd, hooks, "stop",
                {"prompt": prompt, "answer": answer, "tools": tool_log, "changes": ctx.changes},
            )
        if owns_session:
            session.close()
        return answer

    empty_streak = 0
    sweep_warned = False
    for _ in range(max_steps):
        if needs_compaction(messages):
            size_before = total_chars(messages)
            print(ui.dim(
                f"[compacting: {size_before:,} chars in history "
                f"(threshold {COMPACT_THRESHOLD_CHARS:,}); summarizing older turns]"
            ))
            messages, did = compact_if_needed(messages, client.summarize)
            if did:
                size_after = total_chars(messages)
                session.compactions += 1
                print(ui.dim(f"[compacted → {size_after:,} chars]"))
        session.last_history_chars = total_chars(messages)
        try:
            with ui.spinner("Thinking..."):
                reply = client.complete(messages, tools=all_schemas if use_native_tools else None)
        except Exception as exc:  # noqa: BLE001
            if save:
                save_conversation(cwd, messages)
            return _finalize(
                f"Aborted: provider error during turn.\n"
                f"{exc}\n\n"
                f"Conversation kept. Type 'continue' (or any follow-up) to resume "
                f"in this chat, or `huv -c` from a fresh shell."
            )
        # Accumulate token usage when provider returns it.
        usage = (reply.get("raw") or {}).get("usage") if isinstance(reply, dict) else None
        if isinstance(usage, dict):
            for k_src, k_dst in (
                ("prompt_tokens", "prompt"),
                ("completion_tokens", "completion"),
                ("total_tokens", "total"),
            ):
                v = usage.get(k_src)
                if isinstance(v, int):
                    session.tokens[k_dst] = session.tokens.get(k_dst, 0) + v
        text = reply.get("text", "")
        tool_calls = reply.get("tool_calls") or []

        # Some models (MiniMax) emit tool calls as XML inside text instead
        # of using native function-calling. Parse + execute them.
        xml_calls: list[dict[str, Any]] = []
        if not tool_calls and text and "<" in text:
            xml_calls = parse_xml_tool_calls(text)

        # Sweep guard: if the model edited >3 files in this single turn and
        # didn't establish a plan first, nudge it once.
        if not sweep_warned and len(ctx.changes) > 3 and len(ctx.plan) == 0:
            sweep_warned = True
            messages.append({
                "role": "user",
                "content": (
                    f"You have already modified {len(ctx.changes)} files in this turn "
                    f"({', '.join(sorted(ctx.changes)[:6])}). Stop and confirm scope. "
                    "If the user asked for a focused change, you may be overreaching. "
                    "Call update_plan to make the remaining scope explicit, or end the "
                    "turn with a final answer summarizing what you changed and ask the "
                    "user whether to continue."
                ),
            })
            continue

        if xml_calls:
            empty_streak = 0
            cleaned = strip_think(TOOL_BLOCK_RE.sub("", text))
            messages.append({"role": "assistant", "content": cleaned or None})
            for tc in xml_calls:
                name = tc["name"]
                label, kind = STATUS.get(name, ("Working...", "think"))
                if name not in QUIET_PRE_STATUS:
                    print(ui.status(label, kind))
                result = _run_tool(name, dict(tc["args"] or {}))
                summary = result_summary(name, result)
                ok = not summary.lower().startswith(("tool error", "command blocked"))
                _render_tool_result(name, result, summary, ok)
                tool_log.append({"tool": name, "summary": summary})
                messages.append({"role": "user", "content": f"Tool result ({name}):\n{result[:24000]}"})
            continue

        if tool_calls:
            empty_streak = 0
            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                name = tc["name"]
                label, kind = STATUS.get(name, ("Working...", "think"))
                if name not in QUIET_PRE_STATUS:
                    print(ui.status(label, kind))
                result = _run_tool(name, dict(tc["args"] or {}))
                summary = result_summary(name, result)
                ok = not summary.lower().startswith(("tool error", "command blocked"))
                _render_tool_result(name, result, summary, ok)
                tool_log.append({"tool": name, "summary": summary})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result[:24000],
                })
            continue

        # JSON-in-prose fallback path.
        messages.append({"role": "assistant", "content": text})
        scrubbed = scrub_prose(text)

        # Guard: garbled XML tool-call attempt — bounce for clean retry.
        if looks_like_garbled_xml_tool(text):
            empty_streak += 1
            if empty_streak >= 3:
                return _finalize(
                    "Stopped: model kept emitting unfinished tool-call XML instead "
                    "of using the native function-calling interface. Try a smaller "
                    "task, a different model (/model <name>), or set HUV_USE_TOOLS=0 "
                    "to force the JSON-action fallback."
                )
            messages.append({
                "role": "user",
                "content": (
                    "Your previous reply contained an unfinished or malformed "
                    "<tool_call> envelope. Reply again using the native function-"
                    "calling interface (no XML, no <think> blocks, no file content "
                    "in prose). If a previous tool call succeeded, continue with "
                    "the next step."
                ),
            })
            continue

        # Empty (or scrubbed-to-empty) reply with no tool calls.
        if not scrubbed:
            empty_streak += 1
            if empty_streak >= 3:
                return _finalize(
                    "Stopped: model returned 3 empty replies in a row. It may be "
                    "stuck or the provider trimmed output. Try rephrasing, breaking "
                    "the task into smaller pieces, or switching model with /model."
                )
            messages.append({
                "role": "user",
                "content": (
                    "Your previous reply was empty after stripping <think> tags. "
                    "Either call a tool to do real work, or send a real final "
                    "answer describing what you found and changed."
                ),
            })
            continue

        try:
            action = parse_action(text)
        except json.JSONDecodeError:
            if is_bad_final(scrubbed):
                empty_streak += 1
                if empty_streak >= 3:
                    return _finalize(
                        "Stopped: model kept returning very short / placeholder "
                        "replies. The task may be unclear — try restating it."
                    )
                messages.append({
                    "role": "user",
                    "content": "Reply with a tool call or a concrete final answer (not just 'done' or 'ok').",
                })
                continue
            empty_streak = 0
            return _finalize(scrubbed)
        if action.get("action") == "final":
            answer = scrub_prose(str(action.get("text", "")))
            if is_bad_final(answer):
                empty_streak += 1
                if empty_streak >= 3:
                    return _finalize(
                        "Stopped: model's final answers were empty or placeholder "
                        "three times in a row."
                    )
                messages.append({
                    "role": "user",
                    "content": "Final too short. Reply with concrete findings, changes, next steps.",
                })
                continue
            empty_streak = 0
            return _finalize(answer)
        if action.get("action") != "tool":
            return _finalize(f"Unknown action: {scrubbed or text}")
        name = str(action["tool"])
        label, kind = STATUS.get(name, ("Working...", "think"))
        if name not in QUIET_PRE_STATUS:
            print(ui.status(label, kind))
        result = _run_tool(name, dict(action.get("args") or {}))
        summary = result_summary(name, result)
        ok = not summary.lower().startswith(("tool error", "command blocked"))
        _render_tool_result(name, result, summary, ok)
        tool_log.append({"tool": name, "summary": summary})
        messages.append({"role": "user", "content": f"Tool result:\n{result[:24000]}"})

    return _finalize(
        f"Stopped: hit the {max_steps}-step safety cap for one turn.\n\n"
        f"This protects against runaway loops. The work so far is saved — type "
        f"'continue' (or any follow-up) to keep going from here. To raise the cap, "
        f"set HUV_MAX_STEPS=<n> in your environment."
    )
