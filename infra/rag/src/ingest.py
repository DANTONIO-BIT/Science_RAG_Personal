"""
Ingest pipeline: file → parse → chunk → embed → ChromaDB.

Collection routing is determined by source path:
  data/public/**  → collection "public"
  data/private/** → collection "private"
  data/ngs/**     → collection "public"  (processed outputs, not raw)

After successful ingest, PDFs in inbox/ are moved to indexed/.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import yaml
from pathlib import Path

import chromadb

from .embed import get_embeddings_batch

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _rel(path: Path) -> str:
    """Repo-relative path string. Keeps chunk ids + citations portable across
    machines (absolute paths would change the id hash when the repo moves)."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)

# Raw NGS extensions that must never be ingested
_RAW_NGS_EXTENSIONS = {".fastq", ".fastq.gz", ".bam", ".cram"}

# FASTA guard thresholds
_FASTA_MAX_SEQUENCES = 500
_FASTA_MAX_TOTAL_LEN = 500_000  # chars

_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def _get_chroma_client() -> chromadb.PersistentClient:
    cfg = _load_config()
    persist_dir = Path(CONFIG_PATH).parent.parent.parent / cfg["chroma"]["persist_directory"].lstrip("/")
    # Resolve relative to repo root (two levels up from infra/rag/src)
    repo_root = Path(__file__).parent.parent.parent.parent
    persist_path = repo_root / cfg["chroma"]["persist_directory"]
    persist_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_path))


def _get_collection(name: str) -> chromadb.Collection:
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def ingest_file(path: str | Path) -> int:
    """
    Detect file type, parse, chunk, embed, and store in the correct collection.
    Returns number of chunks written.
    Raises ValueError for unsupported formats or raw NGS files (FASTQ, BAM, CRAM).
    """
    path = Path(path).resolve()
    suffix = path.suffix.lower()

    # Block raw NGS
    if suffix in _RAW_NGS_EXTENSIONS or path.name.endswith(".fastq.gz"):
        raise ValueError(f"Raw NGS file not allowed in RAG: {path.name}")

    collection = _resolve_collection(path)

    if suffix == ".pdf":
        count = ingest_pdf(path, collection)
    elif suffix == ".md":
        count = ingest_markdown(path, collection)
    elif suffix in {".fasta", ".fa", ".fna", ".faa"}:
        count = ingest_fasta(path, collection)
    elif suffix in {".vcf", ".bed", ".tsv", ".csv", ".html"}:
        count = ingest_ngs_result(path)
    elif suffix == ".txt":
        text = path.read_text(errors="replace")
        count = _write_chunks(path, collection, text)
    else:
        cfg = _load_config()
        allowed = cfg["data"]["supported_extensions"]
        raise ValueError(f"Unsupported file type '{suffix}'. Allowed: {allowed}")

    # Auto-move PDFs from inbox to indexed
    if suffix == ".pdf" and "inbox" in path.parts:
        move_to_indexed(path)

    logger.info("Ingested %s → collection '%s' (%d chunks)", path.name, collection, count)
    return count


def ingest_pdf(path: Path, collection: str) -> int:
    """Parse PDF with pypdf, chunk, embed, store. Returns chunk count."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("pypdf is required. Run: pip install pypdf")

    reader = PdfReader(str(path))
    pages_text: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text)

    full_text = "\n\n".join(pages_text)
    return _write_chunks(path, collection, full_text)


def ingest_markdown(path: Path, collection: str) -> int:
    """Parse .md file, chunk on headers and paragraphs, embed, store."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Split on H1/H2/H3 headers so each section becomes a natural boundary
    sections = re.split(r"(?m)^#{1,3} ", text)
    # Re-attach the stripped '#' prefix to non-empty sections
    reconstructed = "\n\n".join(s.strip() for s in sections if s.strip())

    # Wiki nodes carry a provenance tag. A node derived from private notes
    # (_source: private / private+public) must keep the cloud privacy gate,
    # which keys on _source == "private". Public nodes stay cloud-safe ("wiki").
    source_override = None
    if collection == "wiki":
        if re.search(r"_source:\s*(private\+public|private)", text, re.IGNORECASE):
            source_override = "private"
        else:
            source_override = "wiki"

    return _write_chunks(path, collection, reconstructed, source_override)


def ingest_ngs_result(path: Path) -> int:
    """
    Parse processed NGS output (VCF/BED/TSV/FastQC HTML).
    Always stores in "public" collection with source metadata.
    """
    suffix = path.suffix.lower()
    if suffix == ".html":
        try:
            from html.parser import HTMLParser

            class _TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.chunks: list[str] = []
                    self._skip = False

                def handle_starttag(self, tag, attrs):
                    if tag in {"script", "style"}:
                        self._skip = True

                def handle_endtag(self, tag):
                    if tag in {"script", "style"}:
                        self._skip = False

                def handle_data(self, data):
                    if not self._skip and data.strip():
                        self.chunks.append(data.strip())

            extractor = _TextExtractor()
            extractor.feed(path.read_text(errors="replace"))
            text = "\n".join(extractor.chunks)
        except Exception as e:
            logger.warning("HTML parse failed for %s: %s", path.name, e)
            text = path.read_text(errors="replace")
    else:
        text = path.read_text(errors="replace")

    return _write_chunks(path, "public", text)


def ingest_fasta(path: Path, collection: str) -> int:
    """
    Parse FASTA. Only short sequences (genes, proteins) — not whole genomes.
    Raises if sequence count or total length exceeds threshold.
    """
    text = path.read_text(errors="replace")
    records = re.split(r"(?m)^>", text)
    records = [r for r in records if r.strip()]

    if len(records) > _FASTA_MAX_SEQUENCES:
        raise ValueError(
            f"FASTA has {len(records)} sequences (max {_FASTA_MAX_SEQUENCES}). "
            "Whole-genome FASTAs are not embeddable."
        )

    chunks: list[str] = []
    total_seq_len = 0
    for record in records:
        lines = record.strip().split("\n")
        header = lines[0].strip()
        seq = "".join(lines[1:]).replace(" ", "")
        total_seq_len += len(seq)
        if total_seq_len > _FASTA_MAX_TOTAL_LEN:
            raise ValueError(
                f"FASTA total sequence length exceeds {_FASTA_MAX_TOTAL_LEN} chars. "
                "Use annotated outputs (VCF/BED) for whole-genome data."
            )
        entry = f">{header}\n{seq}"
        chunks.append(entry)

    return _store_chunks(chunks, path, collection)


def _resolve_collection(path: Path) -> str:
    """
    Determine ChromaDB collection from file path.

    Routing rules (first match wins):
      wiki/**                     → "wiki"      (auto-generated synthesis nodes)
      projects/{name}/private/**  → "private"
      projects/{name}/inbox/**    → "public"
      projects/{name}/**          → "public"   (any other subdir inside a project)
      data/private/**             → "private"
      data/public/**              → "public"
      data/ngs/**                 → "public"
    """
    parts = path.parts

    # wiki/auto_generated/ → wiki (the RAG feedback loop)
    if "wiki" in parts:
        return "wiki"

    # projects/{name}/private/ → private
    if "projects" in parts:
        proj_idx = parts.index("projects")
        sub_parts = parts[proj_idx + 2:]  # everything after projects/{name}/
        if sub_parts and sub_parts[0] == "private":
            return "private"
        return "public"  # inbox/, metaanalisis_pipeline/, or any other project subdir

    # data/ tree
    if "data" in parts:
        data_idx = parts.index("data")
        if data_idx + 1 < len(parts):
            branch = parts[data_idx + 1]
            if branch == "private":
                return "private"
            return "public"  # public/, ngs/, shared/ all go public

    raise ValueError(
        f"Cannot resolve collection for path: {path}. "
        "File must be under projects/{{name}}/ or data/."
    )


def _extract_project_id(path: Path) -> str:
    """
    Derive a project_id string from the file path.
      projects/{name}/...  → {name}
      data/public/shared/  → "shared"
      data/private/        → "private_global"
      data/ngs/            → "ngs"
      anything else        → "untagged"
    """
    parts = path.parts

    if "wiki" in parts:
        return "wiki"

    if "projects" in parts:
        proj_idx = parts.index("projects")
        if proj_idx + 1 < len(parts):
            return parts[proj_idx + 1]  # the project folder name

    if "data" in parts:
        data_idx = parts.index("data")
        sub_parts = parts[data_idx + 1:]
        if sub_parts:
            if sub_parts[0] == "ngs":
                return "ngs"
            if sub_parts[0] == "private":
                return "private_global"
            # data/public/shared/ → "shared", data/public/papers/ → "shared"
            return "shared"

    return "untagged"


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks of `size` chars."""
    if not text.strip():
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _build_metadata(
    path: Path, collection: str, chunk_index: int, source_override: str | None = None
) -> dict:
    """
    Build chunk metadata dict.
    Always includes: source_path, collection, chunk_index, file_type, _source, project_id.

    source_override decouples the privacy tag (_source) from the collection name.
    Used for wiki nodes: a private-derived node lives in the "wiki" collection but
    carries _source="private" so the cloud privacy gate (keyed on _source) blocks it.

    project_id enables per-project filtering at query time:
      query_public(text, filter={"project_id": "salmonella_hfq"})
      query_public(text, filter={"project_id": {"$in": ["salmonella_hfq", "shared"]}})
    """
    return {
        "source_path": _rel(path),      # repo-relative → portable citations + ids
        "filename": path.name,
        "collection": collection,
        "chunk_index": chunk_index,
        "file_type": path.suffix.lower().lstrip("."),
        "_source": source_override or collection,   # "public" | "private" | "wiki"
        "project_id": _extract_project_id(path),
    }


def _write_chunks(
    path: Path, collection: str, text: str, source_override: str | None = None
) -> int:
    """Chunk text, embed, and store. Returns number of stored chunks."""
    cfg = _load_config()
    chunks = _chunk_text(
        text,
        size=cfg["chunking"]["size"],
        overlap=cfg["chunking"]["overlap"],
    )
    return _store_chunks(chunks, path, collection, source_override)


def _store_chunks(
    chunks: list[str], path: Path, collection: str, source_override: str | None = None
) -> int:
    """Embed chunks and upsert into ChromaDB collection."""
    if not chunks:
        logger.warning("No chunks produced for %s", path.name)
        return 0

    col = _get_collection(collection)
    embeddings = get_embeddings_batch(chunks)

    rel = _rel(path)
    ids: list[str] = []
    metadatas: list[dict] = []
    for i, chunk in enumerate(chunks):
        meta = _build_metadata(path, collection, i, source_override)
        # Stable ID: hash of (repo-relative path, chunk_index) so re-ingest is
        # idempotent AND portable across machines (absolute path would not be).
        uid = hashlib.sha256(f"{rel}::{i}".encode()).hexdigest()[:32]
        ids.append(uid)
        metadatas.append(meta)

    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )
    return len(chunks)


def move_to_indexed(source_path: Path) -> None:
    """Move a file from papers/inbox/ to papers/indexed/ after successful ingest."""
    if "inbox" not in source_path.parts:
        return
    parts = list(source_path.parts)
    inbox_idx = parts.index("inbox")
    parts[inbox_idx] = "indexed"
    dest = Path(*parts)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(dest))
    logger.info("Moved %s → %s", source_path.name, dest)
