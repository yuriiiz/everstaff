"""Local directory knowledge backend — file-based retrieval with keyword matching."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path

from everstaff.knowledge.models import Chunk, SearchResult

logger = logging.getLogger(__name__)


class LocalDirectoryBackend:
    """Knowledge backend that indexes and searches files in a local directory."""

    def __init__(
        self,
        path: str | Path,
        extensions: list[str] | None = None,
        max_chunk_size: int = 2000,
    ) -> None:
        self._path = Path(path).expanduser().resolve()
        self._extensions = extensions or [".md", ".txt", ".py", ".yaml", ".yml", ".json"]
        self._max_chunk_size = max_chunk_size
        self._index: dict[str, list[Chunk]] | None = None
        self._mtimes: dict[str, float] = {}

    async def search(self, query: str, top_k: int = 5) -> SearchResult:
        self._ensure_indexed()
        assert self._index is not None

        query_terms = self._tokenize(query)
        if not query_terms:
            return SearchResult(query=query, total_found=0)

        # Score all chunks using TF-IDF-like scoring
        scored: list[tuple[float, Chunk]] = []
        for chunks in self._index.values():
            for chunk in chunks:
                score = self._score_chunk(chunk, query_terms)
                if score > 0:
                    scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_chunks = [chunk for _, chunk in scored[:top_k]]

        return SearchResult(
            chunks=top_chunks,
            query=query,
            total_found=len(scored),
        )

    async def list_sources(self) -> list[str]:
        self._ensure_indexed()
        assert self._index is not None
        return sorted(self._index.keys())

    async def get_document(self, source: str) -> str:
        path = Path(source)
        if not path.is_absolute():
            path = self._path / path
        path = path.resolve()

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {source}")
        if not str(path).startswith(str(self._path)):
            raise ValueError(f"Document outside knowledge base directory: {source}")

        return path.read_text(encoding="utf-8")

    def _ensure_indexed(self) -> None:
        """Index files if not already done or if files have changed."""
        if self._index is not None and not self._files_changed():
            return
        self._build_index()

    def _files_changed(self) -> bool:
        """Check if any indexed files have been modified."""
        for file_path, mtime in self._mtimes.items():
            p = Path(file_path)
            if not p.exists() or p.stat().st_mtime != mtime:
                return True
        return False

    def _build_index(self) -> None:
        """Scan directory and index all matching files."""
        self._index = {}
        self._mtimes = {}

        if not self._path.exists():
            logger.warning("Knowledge base directory does not exist: %s", self._path)
            return

        logger.debug("Building knowledge index from: %s", self._path)
        for ext in self._extensions:
            for file_path in self._path.rglob(f"*{ext}"):
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                    rel_path = str(file_path.relative_to(self._path))
                    chunks = self._chunk_text(content, rel_path)
                    self._index[rel_path] = chunks
                    self._mtimes[str(file_path)] = file_path.stat().st_mtime
                except Exception:
                    logger.debug("Failed to index file: %s", file_path, exc_info=True)
                    continue

        logger.debug("Knowledge index built: %d files indexed", len(self._index))

    def _chunk_text(self, text: str, source: str) -> list[Chunk]:
        """Split text into chunks respecting paragraph boundaries."""
        chunks: list[Chunk] = []
        paragraphs = re.split(r"\n\n+", text)

        current = ""
        chunk_idx = 0
        for para in paragraphs:
            if len(current) + len(para) + 2 > self._max_chunk_size and current:
                chunks.append(Chunk(
                    content=current.strip(),
                    source=source,
                    metadata={"chunk_index": chunk_idx},
                ))
                chunk_idx += 1
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para

        if current.strip():
            chunks.append(Chunk(
                content=current.strip(),
                source=source,
                metadata={"chunk_index": chunk_idx},
            ))

        return chunks

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple tokenization: lowercase, split on non-alphanumeric."""
        return [w for w in re.split(r"\W+", text.lower()) if len(w) > 1]

    def _score_chunk(self, chunk: Chunk, query_terms: list[str]) -> float:
        """Score a chunk against query terms using term frequency."""
        chunk_terms = self._tokenize(chunk.content)
        if not chunk_terms:
            return 0.0

        chunk_counter = Counter(chunk_terms)
        total_terms = len(chunk_terms)

        score = 0.0
        for term in query_terms:
            tf = chunk_counter.get(term, 0) / total_terms
            score += tf

        return score
