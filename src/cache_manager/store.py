import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.json"
METADATA_PATH = ROOT / "metadata.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


class MetadataStore:
    def __init__(self, path: Path = METADATA_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data = {"entries": {}}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        self._data.setdefault("entries", {})

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            tmp.replace(self.path)

    @staticmethod
    def key(path: str) -> str:
        return str(Path(path)).replace("\\", "/").rstrip("/")

    def get_entry(self, path: str) -> dict:
        return self._data["entries"].get(self.key(path), {})

    def get_tags(self, path: str) -> list:
        return list(self.get_entry(path).get("tags", []))

    def set_tags(self, path: str, tags: list) -> None:
        k = self.key(path)
        entry = self._data["entries"].setdefault(k, {})
        if tags:
            entry["tags"] = list(dict.fromkeys(tags))
        else:
            entry.pop("tags", None)
            if not entry:
                self._data["entries"].pop(k, None)
        self.save()

    def toggle_tag(self, path: str, tag: str) -> list:
        tags = self.get_tags(path)
        if tag in tags:
            tags.remove(tag)
        else:
            tags.append(tag)
        self.set_tags(path, tags)
        return tags

    def has_protected_tag(self, path: str, protected: list) -> bool:
        tags = self.get_tags(path)
        return any(t in protected for t in tags)
