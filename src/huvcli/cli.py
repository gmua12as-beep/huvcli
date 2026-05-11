from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .agent import run_agent
from .assets import assets_root, list_asset_skills
from .provider import ApiClient


def _chat(yes: bool, verbose: bool) -> int:
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
        print(run_agent(prompt, Path.cwd(), yes=yes, verbose=verbose))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="huv", description="CLI coding agent")
    parser.add_argument("prompt", nargs="*", help="Task for the agent, or 'chat'/'models'/'assets'")
    parser.add_argument("--yes", "-y", action="store_true", help="approve file writes and commands")
    parser.add_argument("--verbose", "-v", action="store_true", help="show raw tool output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    words = args.prompt
    if not words or words == ["chat"]:
        return _chat(args.yes, args.verbose)
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

    prompt = " ".join(words)
    try:
        print(run_agent(prompt, Path.cwd(), yes=args.yes, verbose=args.verbose))
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
