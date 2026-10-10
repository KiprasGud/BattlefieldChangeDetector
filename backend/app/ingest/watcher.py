"""Watch the input folder: files that finished copying are paired by name and queued as batches.

Runs inside the API (FastAPI lifespan, WATCH_ENABLED=1, the default) or headless. Use one or the other:
    python -m app.ingest.watcher [FOLDER]          # watch WATCH_DIR (or FOLDER) until Ctrl+C
    python -m app.ingest.watcher [FOLDER] --once   # process what is in the folder now, then exit
"""
import argparse
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .. import batch
from ..storage.batches import init_batch_db
from .media import content_hash
from .naming import Inbox

log = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "input"
SETTLE_S = 2.0          # a file is finished when no event arrived for this long ...
POLL_S = 1.0            # ... and its size and mtime did not change between two polls (copy-completion only)
IGNORED_PREFIXES = (".", "~")
IGNORED_NAMES = {"thumbs.db", "desktop.ini"}


def watch_dir() -> Path:
    return Path(os.getenv("WATCH_DIR") or DEFAULT_DIR)


def watch_enabled() -> bool:
    return (os.getenv("WATCH_ENABLED") or "1") == "1"


def _ignored(path: Path) -> bool:
    return path.name.startswith(IGNORED_PREFIXES) or path.name.lower() in IGNORED_NAMES


class Watcher:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.inbox = Inbox()
        self._pending: dict[Path, list] = {}   # path -> [time of last event, last (size, mtime) seen or None]
        self._hashes: dict[Path, str] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._observer: Optional[Observer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "Watcher":
        self.folder.mkdir(parents=True, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.folder), recursive=False)
        self._observer.start()
        for path in self.folder.iterdir():  # files dropped while the service was down
            if path.is_file():
                self.touch(path)
        self._thread = threading.Thread(target=self._loop, name="inbox-settle", daemon=True)
        self._thread.start()
        log.info("Watching %s", self.folder)
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)

    def touch(self, path) -> None:
        """A file appeared or changed: (re)start its settle timer."""
        path = Path(path)
        if path.parent != self.folder or _ignored(path):
            return
        with self._lock:
            self._pending[path] = [time.monotonic(), None]
            self._hashes.pop(path, None)

    def forget(self, path) -> None:
        path = Path(path)
        with self._lock:
            self._pending.pop(path, None)
            self._hashes.pop(path, None)
        self.inbox.remove(path)

    def _loop(self) -> None:
        while not self._stop.wait(POLL_S):
            try:
                self.settle()
            except Exception:
                log.exception("Inbox settle pass failed")

    def settle(self, now: Optional[float] = None) -> list[str]:
        """Register the files that finished copying; returns the ids of the batches this queued."""
        now = time.monotonic() if now is None else now
        ready = []
        with self._lock:
            for path, state in list(self._pending.items()):
                if now - state[0] < SETTLE_S:
                    continue
                try:
                    st = path.stat()
                except OSError:
                    del self._pending[path]  # vanished before it settled
                    continue
                stamp = (st.st_size, st.st_mtime_ns)
                if stamp != state[1]:
                    state[1] = stamp
                    continue
                del self._pending[path]
                ready.append(path)
        created = []
        for path in ready:
            created += self.register(path)
        return created

    def register(self, path, enqueue: bool = True) -> list[str]:
        """Add a finished file to the inbox; create a batch for every pair of its site not processed yet."""
        created = []
        for a, b in self.inbox.add(path):
            try:
                batch_id = batch.create_pair_batch(a, b, self._hash(a.path), self._hash(b.path))
            except OSError as e:
                log.warning("Cannot read %s / %s: %s", a.path.name, b.path.name, e)
                continue
            if batch_id:
                log.info("Queued batch %s: %s -> %s", batch_id, a.path.name, b.path.name)
                created.append(batch_id)
                if enqueue:
                    batch.worker.submit(batch_id)
        return created

    def _hash(self, path: Path) -> str:
        with self._lock:
            cached = self._hashes.get(path)
        if cached:
            return cached
        digest = content_hash(path)
        with self._lock:
            self._hashes[path] = digest
        return digest


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: Watcher):
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.touch(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.touch(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.forget(event.src_path)
            self.watcher.touch(event.dest_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.forget(event.src_path)


_service: Optional[Watcher] = None


def start_service(folder=None) -> Watcher:
    global _service
    if _service is None:
        _service = Watcher(folder or watch_dir()).start()
    return _service


def stop_service() -> None:
    global _service
    if _service is not None:
        _service.stop()
        _service = None


def service() -> Optional[Watcher]:
    return _service


def run_once(folder) -> list[str]:
    """Pair and process every file in the folder now, without waiting for copies to settle."""
    w = Watcher(folder)
    ids = []
    for path in sorted(w.folder.iterdir()):
        if path.is_file() and not _ignored(path):
            ids += w.register(path, enqueue=False)
    for batch_id in ids:
        batch.process_batch(batch_id)
    return ids


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Pair drone media by name (<key>_<Before|After|DayN>) and process it.")
    p.add_argument("folder", nargs="?", help="folder to watch (default: WATCH_DIR or <repo>/input)")
    p.add_argument("--once", action="store_true", help="process the files in the folder now, then exit")
    args = p.parse_args()
    folder = Path(args.folder) if args.folder else watch_dir()
    init_batch_db()
    if args.once:
        ids = run_once(folder)
        print(f"Processed {len(ids)} batch(es): {', '.join(ids) or '-'}")
        return
    batch.resume_interrupted()
    start_service(folder)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_service()


if __name__ == "__main__":
    main()
