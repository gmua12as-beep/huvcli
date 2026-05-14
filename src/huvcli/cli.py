from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from . import __version__
from .agent import SessionState, run_agent
from .assets import assets_root, list_asset_skills
from .hooks import load_hooks
from .mcp import MCPRegistry
from .provider import ApiClient, ApiConfig
from .storage import ensure_workspace, recent_history, set_pref, conversation_path
from .tools import APPROVAL_MODES, ToolContext, revert_files
from .ui import UI


SLASH_COMMANDS = (
    "/help", "/clear", "/history", "/model", "/approval",
    "/cost", "/diff", "/revert", "/assets", "/resume",
    "/completer", "/exit", "/quit",
)


def _readline_backend_name(readline_mod) -> str:
    """Identify which readline implementation is loaded."""
    mod_name = getattr(readline_mod, "__name__", "") or ""
    mod_file = getattr(readline_mod, "__file__", "") or ""
    doc = getattr(readline_mod, "__doc__", None) or ""
    # pyreadline3 ships as a `readline` shim — detect via package presence.
    if "pyreadline" in mod_file.lower():
        return "pyreadline3"
    if "libedit" in doc.lower():
        return "libedit"
    return "GNU readline" if "readline" in mod_name else "readline"


def _try_import_readline():
    """Import readline. On Windows + missing, attempt a one-shot install of
    pyreadline3 with a clear prompt — declared as a dependency in
    pyproject.toml, so the install path here is the fallback for source
    checkouts or partial installs.
    """
    try:
        import readline  # noqa: F401
        return readline
    except ImportError:
        pass
    import os
    import sys
    if sys.platform != "win32" or os.environ.get("HUV_NO_AUTO_INSTALL"):
        return None
    if not sys.stdout.isatty():
        return None
    try:
        answer = input(
            "Tab completion needs `pyreadline3` (Windows). Install it now? [Y/n] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer in {"n", "no"}:
        return None
    print("Installing pyreadline3...")
    import subprocess
    rc = subprocess.call(
        [sys.executable, "-m", "pip", "install", "--quiet", "pyreadline3>=3.4"]
    )
    if rc != 0:
        print("Install failed; continuing without autocomplete.")
        return None
    try:
        import readline  # noqa: F401
        return readline
    except ImportError:
        return None


def _install_completer(get_paths) -> tuple[bool, str]:
    """Install a tab completer for slash commands + their args.

    Returns (enabled, backend_name). `backend_name` is "" when disabled,
    otherwise a friendly label like "pyreadline3" / "GNU readline".
    """
    readline = _try_import_readline()
    if readline is None:
        return False, ""

    approval_modes = sorted(APPROVAL_MODES) + ["all"]

    def complete(text: str, state: int):
        import readline as _rl
        buffer = _rl.get_line_buffer()
        stripped = buffer.lstrip()
        # Argument-position completion for known slash commands.
        if stripped.startswith("/") and " " in stripped:
            cmd, _, _rest = stripped.partition(" ")
            cmd = cmd.lower()
            options: list[str] = []
            if cmd == "/approval":
                options = approval_modes
            elif cmd == "/revert":
                options = list(get_paths()) + ["all"]
            matches = [o for o in options if o.startswith(text)]
            return matches[state] if state < len(matches) else None
        # Command-name completion.
        if stripped.startswith("/") or text.startswith("/"):
            matches = [c for c in SLASH_COMMANDS if c.startswith(text or stripped)]
            return matches[state] if state < len(matches) else None
        return None

    readline.set_completer(complete)
    readline.set_completer_delims(" \t\n")
    # Safe doc check — pyreadline3's module __doc__ can be None.
    doc = getattr(readline, "__doc__", None) or ""
    try:
        if "libedit" in doc.lower():
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
    except Exception:  # noqa: BLE001
        try:
            readline.parse_and_bind("tab: complete")
        except Exception:  # noqa: BLE001
            return False, _readline_backend_name(readline)
    return True, _readline_backend_name(readline)


SLASH_HELP = """Commands:
  /help                Show this help
  /clear               Reset conversation (delete last_conversation)
  /history             Show recent saved prompts
  /model [name]        Show or set HUV_MODEL for this session
  /approval <mode>     suggest | auto-edit | full-auto | plan
  /cost                Show token usage + history size for this session
  /diff                Show files changed across this session
  /revert [path|all]   Restore files to pre-session state
  /completer           Show tab-completion status (and install on Windows)
  /assets              Show bundled skills
  /resume              Resume previous conversation (auto in chat)
  !<cmd>               Run shell command directly (no agent)
  exit | quit          Leave chat

Tab completes slash commands and their arguments.
"""


def _chat(yes: bool, verbose: bool, save: bool, plain: bool, approval: str) -> int:
    import os
    ui = UI(plain=plain)
    model = os.environ.get("HUV_MODEL")
    cwd = Path.cwd()
    print(ui.welcome(cwd, save=save, approval=approval, model=model))

    # Build session resources ONCE so we don't respawn MCP servers + reload
    # hooks every turn.
    session = SessionState(cwd=cwd, mcp=MCPRegistry(cwd), hooks=load_hooks(cwd))
    mcp_count = 0
    if session.mcp.config:
        mcp_schemas = session.mcp.discover()
        mcp_count = len(mcp_schemas)
        if mcp_count:
            print(ui.dim(f"MCP: {mcp_count} tool(s) from {len(session.mcp.config)} server(s)"))
    if not ApiConfig().api_key:
        print(ui.warning("HUV_API_KEY not set — provider requests will likely 401."))

    completer_active, completer_backend = _install_completer(
        lambda: sorted(session.originals.keys())
    )
    if completer_active:
        print(ui.dim(f"Tab completion: ON ({completer_backend})"))
    else:
        import sys as _sys
        if _sys.platform == "win32":
            print(ui.warning(
                "Tab completion: OFF. Install pyreadline3 to enable:"
            ))
            print(ui.dim("    pip install pyreadline3"))
        else:
            print(ui.warning("Tab completion: OFF (readline import failed)."))

    session_started = False
    resume_next = False
    while True:
        try:
            print()
            print(ui.hint_bar(approval, os.environ.get("HUV_MODEL"), mcp_count))
            prompt = input(ui.prompt_label()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            session.close()
            return 0
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            session.close()
            return 0
        if prompt.startswith("!"):
            cmd = prompt[1:].strip()
            if not cmd:
                continue
            try:
                subprocess.run(cmd, shell=True, cwd=Path.cwd())
            except KeyboardInterrupt:
                pass
            continue
        if prompt.startswith("/"):
            parts = prompt[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "help":
                print(ui.section("Commands"))
                print(SLASH_HELP)
            elif cmd == "clear":
                path = conversation_path(Path.cwd())
                if path.exists():
                    path.unlink()
                session_started = False
                print(ui.info("Conversation cleared."))
            elif cmd == "history":
                for row in recent_history(Path.cwd(), 10):
                    print(f"- {row.get('timestamp','')}: {str(row.get('prompt',''))[:100]}")
            elif cmd == "model":
                if arg:
                    os.environ["HUV_MODEL"] = arg
                    print(ui.info(f"Model set: {arg}"))
                else:
                    current = os.environ.get("HUV_MODEL") or ApiConfig().model
                    print(ui.info(f"Current model: {current}"))
            elif cmd == "cost":
                from .compact import COMPACT_THRESHOLD_CHARS
                tokens = session.tokens
                print(ui.section("Session stats"))
                if not any(tokens.values()):
                    print(ui.dim("  tokens:   not reported by provider"))
                else:
                    print(f"  prompt:     {tokens.get('prompt', 0):>10,} tokens")
                    print(f"  completion: {tokens.get('completion', 0):>10,} tokens")
                    print(f"  total:      {tokens.get('total', 0):>10,} tokens")
                print(f"  history:    {session.last_history_chars:>10,} chars")
                print(f"  threshold:  {COMPACT_THRESHOLD_CHARS:>10,} chars  (compaction trigger)")
                print(f"  compactions:{session.compactions:>10,}")
            elif cmd == "diff":
                if not session.changes:
                    print(ui.dim("No files changed in this session."))
                else:
                    print(ui.changed_files(session.changes))
            elif cmd == "revert":
                if not session.originals:
                    print(ui.dim("Nothing to revert — no files touched this session."))
                else:
                    target_arg = arg.strip()
                    paths: list[str] | None
                    if not target_arg or target_arg.lower() == "all":
                        paths = None
                        prompt_str = f"Revert ALL {len(session.originals)} file(s) to pre-session state?"
                    else:
                        paths = [target_arg]
                        prompt_str = f"Revert {target_arg} to pre-session state?"
                    try:
                        confirm = input(f"{prompt_str} [y/N] ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        confirm = ""
                    if confirm in {"y", "yes"}:
                        # Build a transient ToolContext just to invoke the revert helper.
                        tmp_ctx = ToolContext(cwd=cwd, yes=True)
                        tmp_ctx.originals = dict(session.originals)
                        tmp_ctx.changes = dict(session.changes)
                        lines = revert_files(tmp_ctx, tmp_ctx.originals, paths)
                        # Sync the changes back to session.
                        session.originals = tmp_ctx.originals
                        session.changes = tmp_ctx.changes
                        for line in lines:
                            print(line)
                        print(ui.info("Revert complete."))
                    else:
                        print(ui.dim("Revert cancelled."))
            elif cmd == "approval":
                if arg in APPROVAL_MODES:
                    approval = arg
                    print(ui.info(f"Approval mode: {approval}"))
                else:
                    print(ui.info(f"Modes: {', '.join(sorted(APPROVAL_MODES))}"))
            elif cmd == "assets":
                print(f"Assets: {assets_root()}")
                for name in list_asset_skills():
                    print(f"- {name}")
            elif cmd == "resume":
                resume_next = True
                print(ui.info("Will resume previous conversation on next prompt."))
                print(ui.dim("(Note: in chat mode this happens automatically after the first turn.)"))
            elif cmd == "completer":
                # Live re-check + offer to (re)install pyreadline3 on Windows.
                import sys as _sys
                try:
                    import readline as _rl
                    backend = _readline_backend_name(_rl)
                    print(ui.section("Tab completion"))
                    print(f"  status:    {'ENABLED' if completer_active else 'installed but bind failed'}")
                    print(f"  backend:   {backend}")
                    print(f"  module:    {getattr(_rl, '__file__', '?')}")
                    print(f"  python:    {_sys.executable}")
                    print(ui.dim("  Press Tab in the prompt to see completions for / commands."))
                except ImportError:
                    print(ui.section("Tab completion"))
                    print(ui.warning("  status:    DISABLED — `readline` not importable."))
                    if _sys.platform == "win32":
                        try:
                            ans = input("  Install pyreadline3 now? [Y/n] ").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            ans = "n"
                        if ans not in {"n", "no"}:
                            import subprocess
                            rc = subprocess.call(
                                [_sys.executable, "-m", "pip", "install", "pyreadline3>=3.4"]
                            )
                            if rc == 0:
                                print(ui.info("Installed. Restart `huv` to enable tab completion."))
                            else:
                                print(ui.error("pip install failed."))
                    else:
                        print(ui.dim("  Linux/macOS should have readline in stdlib — check your Python build."))
            else:
                print(ui.error(f"Unknown: /{cmd}. Try /help."))
            continue
        # Auto-resume within a chat session so follow-up prompts (like
        # "continue pls") share context with prior turns.
        do_resume = resume_next or session_started
        try:
            answer = run_agent(
                prompt, Path.cwd(),
                yes=yes, verbose=verbose, save=save, plain=plain,
                approval=approval, resume=do_resume, session=session,
            )
        except KeyboardInterrupt:
            print()
            print(ui.warning("Interrupted. Conversation kept — just keep typing to continue."))
            resume_next = False
            session_started = True
            continue
        except Exception as exc:  # noqa: BLE001
            print(ui.error(f"Agent crashed: {exc}"))
            print(ui.dim("Conversation kept; type another prompt to continue."))
            resume_next = False
            session_started = True
            continue
        resume_next = False
        session_started = True
        print(ui.answer(answer))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="huv", description="CLI coding agent")
    parser.add_argument("prompt", nargs="*", help="Task, or chat/models/assets/history/prefs")
    parser.add_argument("--yes", "-y", action="store_true", help="approve writes + commands")
    parser.add_argument("--verbose", "-v", action="store_true", help="show raw tool output")
    parser.add_argument("--plain", action="store_true", help="no colors")
    parser.add_argument("--no-save", action="store_true", help="don't save conversation")
    parser.add_argument("--approval", choices=sorted(APPROVAL_MODES), default="suggest",
                        help="suggest=ask all, auto-edit=auto edits ask commands, full-auto=auto except dangerous")
    parser.add_argument("--continue", "-c", dest="continue_", action="store_true", help="resume last conversation")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    words = args.prompt
    if not words or words == ["chat"]:
        return _chat(args.yes, args.verbose, not args.no_save, args.plain, args.approval)
    if words == ["models"]:
        try:
            print(json.dumps(ApiClient().list_models(), indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"Error: {exc}")
            return 1
        return 0
    if words == ["assets"]:
        print(f"Bundled assets: {assets_root()}")
        for name in list_asset_skills():
            print(f"- {name}")
        return 0
    if words == ["history"]:
        rows = recent_history(Path.cwd(), 10)
        if not rows:
            print("No saved history in .huvcli yet.")
            return 0
        for row in rows:
            print(f"- {row.get('timestamp', '')}: {str(row.get('prompt', '')).splitlines()[0][:100]}")
        return 0
    if words == ["prefs"]:
        print(json.dumps(ensure_workspace(Path.cwd()), indent=2, ensure_ascii=False))
        return 0
    if len(words) == 4 and words[:2] == ["prefs", "set"]:
        print(json.dumps(set_pref(Path.cwd(), words[2], words[3]), indent=2, ensure_ascii=False))
        return 0

    prompt = " ".join(words)
    ui = UI(plain=args.plain)
    try:
        answer = run_agent(
            prompt, Path.cwd(),
            yes=args.yes, verbose=args.verbose,
            save=not args.no_save, plain=args.plain,
            approval=args.approval, resume=args.continue_,
        )
        print(ui.answer(answer))
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
