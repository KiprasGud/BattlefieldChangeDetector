"""Folder ingestion: name pairing, content-based media detection, and the watch-folder service
(ingest.watcher, imported on its own because it depends on the batch pipeline)."""
from .media import content_hash, load_still, media_kind
from .naming import SCHEME, Inbox, MediaName, pairs_for, parse_name

__all__ = ["Inbox", "MediaName", "SCHEME", "content_hash", "load_still", "media_kind", "pairs_for", "parse_name"]
