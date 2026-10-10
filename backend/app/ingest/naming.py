"""Pair media files by name alone: <key>_<tag>, tag = Before, After or Day<N> (any letter case).

Site_A_Day1.mp4 pairs with Site_A_Day2.mov, ProjectX_Before.jpg with ProjectX_After.png. Everything from the first
dot on is ignored, so the extension never matters; file size, dates and EXIF are never read either.
"""
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

NAME_RE = re.compile(r"^(?P<key>.+)_(?P<tag>before|after|day(?P<day>\d+))$", re.IGNORECASE)
SCHEME = "<key>_<Before|After|DayN>, e.g. Site_A_Day1.mp4 or ProjectX_Before.jpg"


@dataclass(frozen=True)
class MediaName:
    path: Path
    key: str            # site / project, as written: "Site_A"
    tag: str            # epoch, as written: "Day1", "Before"

    @property
    def site(self) -> str:
        """Grouping key: names differing only in letter case belong to the same site."""
        return self.key.casefold()

    @property
    def order(self) -> tuple[int, int]:
        """Before < Day1 < Day2 < ... < After."""
        tag = self.tag.casefold()
        if tag == "before":
            return (0, 0)
        if tag == "after":
            return (2, 0)
        return (1, int(tag[3:]))


def logical_name(path) -> str:
    """File name up to its first dot: the extension (and anything after it) is ignored."""
    return Path(path).name.split(".", 1)[0]


def parse_name(path) -> Optional[MediaName]:
    m = NAME_RE.match(logical_name(path))
    return MediaName(Path(path), m["key"], m["tag"]) if m else None


def pairs_for(items: list[MediaName]) -> list[tuple[MediaName, MediaName]]:
    """Consecutive (earlier, later) pairs of one site: Day1 -> Day2, Day2 -> Day3."""
    ordered = sorted(items, key=lambda m: m.order)
    return list(zip(ordered, ordered[1:]))


class Inbox:
    """Files currently in the watch folder, grouped by site. Thread-safe.

    One file per (site, epoch) slot: a second file for an occupied slot (Site_A_Day1.mp4 next to Site_A_Day1.jpg,
    or Day1 next to Day01) is a conflict and is ignored until the first one is removed."""

    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[tuple[str, tuple[int, int]], MediaName] = {}
        self._rejected: dict[Path, str] = {}

    def add(self, path) -> list[MediaName]:
        """Register a file; returns every file of its site in epoch order (the caller batches the site as one project
        and skips legs already done). Empty when the file is rejected."""
        path = Path(path)
        item = parse_name(path)
        with self._lock:
            self._rejected.pop(path, None)
            if item is None:
                self._rejected[path] = f"name does not follow {SCHEME}"
                return []
            slot = (item.site, item.order)
            current = self._slots.get(slot)
            if current is not None and current.path != path:
                self._rejected[path] = f"conflicts with {current.path.name} (same site and epoch)"
                return []
            self._slots[slot] = item
            return sorted((m for (site, _), m in self._slots.items() if site == item.site), key=lambda m: m.order)

    def groups(self) -> list[list[MediaName]]:
        """Every site with at least two epochs, each in epoch order: the projects that can be batched."""
        with self._lock:
            sites: dict[str, list[MediaName]] = {}
            for (site, _), item in self._slots.items():
                sites.setdefault(site, []).append(item)
        return [sorted(items, key=lambda m: m.order) for _, items in sorted(sites.items()) if len(items) > 1]

    def remove(self, path) -> None:
        path = Path(path)
        with self._lock:
            self._rejected.pop(path, None)
            for slot, item in list(self._slots.items()):
                if item.path == path:
                    del self._slots[slot]

    def snapshot(self) -> dict:
        """Files waiting for a partner, files paired, and rejected names with the reason."""
        with self._lock:
            sites: dict[str, list[MediaName]] = {}
            for (site, _), item in self._slots.items():
                sites.setdefault(site, []).append(item)
            waiting = sorted(items[0].path.name for items in sites.values() if len(items) == 1)
            paired = sorted(m.path.name for items in sites.values() if len(items) > 1 for m in items)
            rejected = [{"name": p.name, "reason": r} for p, r in sorted(self._rejected.items())]
        return {"waiting": waiting, "paired": paired, "rejected": rejected}
