from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from . import __version__
from .agent import run_agent
from .assets import assets_root, list_asset_skills
from .provider import ApiClient
from .storage import ensure_workspace, recent_history, set_pref, conversation_path
from .tools import APPROVAL_MODES
from .ui import UI


SLASH_HELP = """Commands:
  /help              Show this help
  /clear             Reset conversation (delete last_conversation)
  /history           Show recent saved prompts
  /model [name]      Show or set HUV_MODEL for this session
  /approval <mode>   suggest | auto-edit | full-auto
  /assets            Show bundled skills
  /resume            Resume previous conversation on next prompt
  !<cmd>             Run shell command directly (no agent)
  exit | quit        Leave chat
"""


def _chat(yes: bool, verbose: bool, save: bool, plain: bool, approval: str) -> int:
    import os
    ui = UI(plain=plain)
    model = os.environ.get("HUV_MODEL")
    print(ui.welcome(Path.cwd(), save=save, approval=approval, model=model))
    resume_next = False
    while True:
        try:
            print()
            print(ui.hint_bar(approval, os.environ.get("HUV_MODEL"), 0))
            prompt = input(ui.prompt_label()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
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
                print(ui.info("Conversation cleared."))
            elif cmd == "history":
                for row in recent_history(Path.cwd(), 10):
                    print(f"- {row.get('timestamp','')}: {str(row.get('prompt',''))[:100]}")
            elif cmd == "model":
                if arg:
                    os.environ["HUV_MODEL"] = arg
                    print(f"Model set: {arg}")
                else:
                    print(f"Current model: {os.environ.get('HUV_MODEL', '(default)')}")
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
            else:
                print(ui.error(f"Unknown: /{cmd}. Try /help."))
            continue
        answer = run_agent(
            prompt, Path.cwd(),
            yes=yes, verbose=verbose, save=save, plain=plain,
            approval=approval, resume=resume_next,
        )
        resume_next = False
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
