"""
RAG package — expose main entry points.
"""
from .ingest import ingest_file, move_to_indexed
from .query import query_public, query_private, query_full, compute_confidence, format_context
from .router import route, PrivacyError
from .embed import get_embedding, get_embeddings_batch

__all__ = [
    "ingest_file",
    "move_to_indexed",
    "query_public",
    "query_private",
    "query_full",
    "compute_confidence",
    "format_context",
    "route",
    "PrivacyError",
    "get_embedding",
    "get_embeddings_batch",
]
