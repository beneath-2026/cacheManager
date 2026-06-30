import os
from pathlib import Path


def delete_cache_files(
    target: str,
    preserve_extensions: list,
    is_protected,
) -> dict:
    """Delete cache files under `target`, keeping folder structure and
    files with extensions in `preserve_extensions` (e.g. .json).

    `is_protected(path: str) -> bool` is called for every folder visited.
    If a folder is protected, it and its subtree are skipped entirely.

    Returns stats: {"deleted_files": int, "freed_bytes": int,
                    "skipped_protected": [paths], "errors": [(path, msg)]}.
    """
    preserve = {e.lower() for e in preserve_extensions}
    stats = {
        "deleted_files": 0,
        "freed_bytes": 0,
        "skipped_protected": [],
        "errors": [],
    }

    target_path = Path(target)
    if not target_path.exists():
        stats["errors"].append((str(target_path), "path does not exist"))
        return stats

    if is_protected(str(target_path).replace("\\", "/")):
        stats["skipped_protected"].append(str(target_path).replace("\\", "/"))
        return stats

    for dirpath, dirnames, filenames in os.walk(target_path):
        norm_dir = str(Path(dirpath)).replace("\\", "/")
        if is_protected(norm_dir):
            stats["skipped_protected"].append(norm_dir)
            dirnames[:] = []
            continue
        # Filter subdirs: skip any protected child so os.walk won't descend
        kept = []
        for d in dirnames:
            child = str(Path(dirpath) / d).replace("\\", "/")
            if is_protected(child):
                stats["skipped_protected"].append(child)
            else:
                kept.append(d)
        dirnames[:] = kept

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in preserve:
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = 0
            try:
                os.remove(fpath)
                stats["deleted_files"] += 1
                stats["freed_bytes"] += size
            except OSError as exc:
                stats["errors"].append((fpath, str(exc)))
    return stats


def format_bytes(n: int) -> str:
    if n is None:
        return ""
    step = 1024.0
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    v = float(n)
    for u in units:
        if v < step:
            return f"{v:.1f} {u}" if u != "B" else f"{int(v)} B"
        v /= step
    return f"{v:.1f} EB"
