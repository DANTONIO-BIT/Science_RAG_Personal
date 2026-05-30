"""
File system watcher — auto-ingest documents dropped into data/ directories.

Watches:
  data/public/    → routes to collection "public"
  data/private/   → routes to collection "private"
  data/ngs/       → routes to collection "public" (processed NGS outputs)

Ignores:
  .DS_Store, hidden files, unsupported extensions, raw NGS formats.

Run: python -m infra.rag.src.watcher   (from repo root)
     python watcher.py                 (from this directory)
"""
from __future__ import annotations

import logging
import time
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
REPO_ROOT = Path(__file__).parent.parent.parent.parent

# Raw NGS extensions to always ignore
_RAW_NGS = {".fastq", ".bam", ".cram", ".gz"}
_HIDDEN_PREFIXES = {".", "~"}


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _get_watch_roots(cfg: dict) -> list[Path]:
    """
    Return the list of absolute directories to monitor.

    Monitored trees:
      data/public/    — shared papers, inbox, ngs
      data/private/   — global private notes
      data/ngs/       — processed NGS outputs
      projects/       — all project subdirs (inbox/ and private/ per project)

    The routing to ChromaDB collection + project_id is resolved inside ingest.py
    based on the actual file path — the watcher just feeds files in.
    """
    roots: list[Path] = []

    # data/ branches from config
    for rel_path in cfg["data"]["watch_dirs"].values():
        abs_path = REPO_ROOT / rel_path
        abs_path.mkdir(parents=True, exist_ok=True)
        roots.append(abs_path)

    # projects/ — watch top-level so new project folders are automatically picked up
    projects_root = REPO_ROOT / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    roots.append(projects_root)

    return roots


def start() -> None:
    """Start the watchdog observer on all configured directories. Blocks until interrupted."""
    try:
        from watchdog.observers import Observer
    except ImportError:
        raise ImportError("watchdog is required. Run: pip install watchdog")

    from .ingest import ingest_file

    cfg = _load_config()
    supported = set(cfg["data"]["supported_extensions"])
    watch_roots = _get_watch_roots(cfg)

    observer = Observer()
    for abs_path in watch_roots:
        handler = DocumentHandler(supported_extensions=supported, ingest_fn=ingest_file)
        observer.schedule(handler, str(abs_path), recursive=True)
        logger.info("Watching %s (recursive)", abs_path)

    observer.start()
    logger.info("Watcher running — drop files into projects/{name}/inbox/ or data/. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("Stopping watcher…")
    finally:
        observer.stop()
        observer.join()


class DocumentHandler:
    """Watchdog FileSystemEventHandler. Routes new files to ingest pipeline."""

    def __init__(self, supported_extensions: set[str], ingest_fn) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise ImportError("watchdog is required. Run: pip install watchdog")
        # Dynamic inheritance to avoid import error at module load time
        self.__class__ = type(
            "DocumentHandler",
            (FileSystemEventHandler, DocumentHandler),
            dict(DocumentHandler.__dict__),
        )
        self.supported_extensions = supported_extensions
        self.ingest_fn = ingest_fn

    def on_created(self, event) -> None:
        """Called when a new file appears. Skips directories and ignored patterns."""
        if event.is_directory:
            return
        path = event.src_path
        if self._should_ignore(path):
            return
        logger.info("New file detected: %s", path)
        try:
            count = self.ingest_fn(path)
            logger.info("Auto-ingested %s → %d chunks", path, count)
        except Exception as e:
            logger.error("Failed to ingest %s: %s", path, e)

    def on_moved(self, event) -> None:
        """Called when a file is renamed/moved into a watched directory."""
        if event.is_directory:
            return
        dest = event.dest_path
        if self._should_ignore(dest):
            return
        logger.info("File moved to watched dir: %s", dest)
        try:
            count = self.ingest_fn(dest)
            logger.info("Auto-ingested (moved) %s → %d chunks", dest, count)
        except Exception as e:
            logger.error("Failed to ingest moved file %s: %s", dest, e)

    def _should_ignore(self, path: str) -> bool:
        """Return True for hidden files, unsupported extensions, raw NGS formats."""
        p = Path(path)
        # Hidden files and macOS artifacts
        if p.name.startswith(tuple(_HIDDEN_PREFIXES)):
            return True
        # Raw NGS binary/large formats
        suffix = p.suffix.lower()
        if suffix in _RAW_NGS:
            return True
        # Also catch .fastq.gz
        if p.name.lower().endswith(".fastq.gz"):
            return True
        # Not in supported list
        if suffix not in self.supported_extensions:
            logger.debug("Ignoring unsupported extension: %s", p.name)
            return True
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    start()
