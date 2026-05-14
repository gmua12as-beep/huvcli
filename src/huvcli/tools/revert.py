"""revert_files — restore files to their pre-session original bytes.

Not exposed to the model — invoked by the CLI's /revert slash command.
"""

from __future__ import annotations

from .context import ToolContext


def revert_files(
    ctx: ToolContext,
    originals: dict[str, bytes | None],
    paths: list[str] | None = None,
) -> list[str]:
    """Restore files to their pre-session state.

    Returns human-readable result lines.
    `paths=None` reverts every tracked file.
    """
    if not originals:
        return ["No tracked changes to revert."]
    if paths:
        wanted: set[str] = set()
        for p in paths:
            normalised = p.replace("\\", "/").lstrip("./")
            for key in originals:
                if key.replace("\\", "/") == normalised:
                    wanted.add(key)
                    break
            else:
                wanted.add(p)  # report as not-tracked below
        targets = sorted(wanted)
    else:
        targets = sorted(originals)

    results: list[str] = []
    for rel in targets:
        if rel not in originals:
            results.append(f"  not tracked: {rel}")
            continue
        original = originals[rel]
        target = (ctx.cwd / rel).resolve()
        try:
            target.relative_to(ctx.cwd.resolve())
        except ValueError:
            results.append(f"  refused (outside project): {rel}")
            continue
        try:
            if original is None:
                if target.exists():
                    target.unlink()
                results.append(f"  removed: {rel}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
                results.append(f"  restored: {rel}")
            ctx.originals.pop(rel, None)
            ctx.changes.pop(rel, None)
            ctx.read_state.pop(str(target.resolve()), None)
        except OSError as exc:
            results.append(f"  FAILED {rel}: {exc}")
    return results
