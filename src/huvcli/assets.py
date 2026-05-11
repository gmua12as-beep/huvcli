from __future__ import annotations

from importlib.resources import files


def assets_root():
    return files("huvcli").joinpath("agent_assets")


def list_asset_skills() -> list[str]:
    root = assets_root()
    names: list[str] = []
    for item in root.rglob("SKILL.md"):
        names.append(str(item.relative_to(root)).replace("\\", "/"))
    return sorted(names)
