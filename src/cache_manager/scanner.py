import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

WEDGE_RE = re.compile(r"^wedge_\d+$", re.IGNORECASE)
VERSION_RE = re.compile(r"^v\d+$", re.IGNORECASE)


@dataclass
class Node:
    name: str
    path: str
    kind: str  # root | category | hip | solver | version | wedge | folder
    children: list = field(default_factory=list)
    wedge_info: Optional[dict] = None


def _classify(depth_from_root: int, name: str) -> str:
    if WEDGE_RE.match(name):
        return "wedge"
    if VERSION_RE.match(name):
        return "version"
    # depth_from_root: 0=category (e.g. houdini), 1=hip, 2=solver
    return {0: "category", 1: "hip", 2: "solver"}.get(depth_from_root, "folder")


def _load_wedge_json(folder: Path) -> Optional[dict]:
    candidates = list(folder.glob("wedge_*.json"))
    if not candidates:
        return None
    try:
        with open(candidates[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def scan(cache_root: str) -> Node:
    root_path = Path(cache_root)
    root = Node(name=root_path.name or str(root_path),
                path=str(root_path).replace("\\", "/"),
                kind="root")
    if not root_path.exists():
        return root
    _walk(root_path, root, depth_from_root=-1)
    return root


def _walk(folder: Path, parent_node: Node, depth_from_root: int) -> None:
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if not entry.is_dir():
            continue
        kind = _classify(depth_from_root + 1, entry.name)
        node = Node(
            name=entry.name,
            path=str(entry).replace("\\", "/"),
            kind=kind,
        )
        parent_node.children.append(node)
        if kind == "wedge":
            node.wedge_info = _load_wedge_json(entry)
            continue
        _walk(entry, node, depth_from_root + 1)
