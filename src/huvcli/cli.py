from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .agent import run_agent
from .assets import assets_root, list_asset_skills
from .provider import ApiClient
from .storage import ensure_workspace, recent_history, set_pref


def _chat(yes: bool, verbose: bool, save: bool) -> int:
    print("Huv chat. Ctrl+C to exit.")
    while True:
        try:
            prompt = input("\nhuv> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            return 0
        print(run_agent(prompt, Path.cwd(), yes=yes, verbose=verbose, save=save))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="huv", description="CLI coding agent")
    parser.add_argument("prompt", nargs="*", help="Task for the agent, or 'chat'/'models'/'assets'/'history'/'prefs'")
    parser.add_argument("--yes", "-y", action="store_true", help="approve file writes and commands")
    parser.add_argument("--verbose", "-v", action="store_true", help="show raw tool output")
    parser.add_argument("--no-save", action="store_true", help="do not save this conversation to .huvcli")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    words = args.prompt
    if not words or words == ["chat"]:
        return _chat(args.yes, args.verbose, not args.no_save)
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
    try:
        print(run_agent(prompt, Path.cwd(), yes=args.yes, verbose=args.verbose, save=not args.no_save))
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
