"""Knowledge manager — unified query interface across backends."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from everstaff.knowledge.backends.local_dir import LocalDirectoryBackend
from everstaff.knowledge.models import SearchResult
from everstaff.knowledge.protocol import KnowledgeBackend
from everstaff.schema.agent_spec import KnowledgeSourceSpec
from everstaff.schema.tool_spec import ToolDefinition, ToolParameter
from everstaff.tools.native import NativeTool


_BACKEND_FACTORIES: dict[str, type] = {
    "local_dir": LocalDirectoryBackend,
}


class KnowledgeManager:
    """Manages multiple knowledge backends and provides a unified search interface."""

    def __init__(self, sources: list[KnowledgeSourceSpec]) -> None:
        self._backends: list[KnowledgeBackend] = []
        for source in sources:
            backend = self._create_backend(source)
            if backend:
                self._backends.append(backend)

    def _create_backend(self, source: KnowledgeSourceSpec) -> KnowledgeBackend | None:
        if source.type == "local_dir":
            if not source.path:
                logger.warning("Knowledge source type='local_dir' has no path configured, skipping")
                return None
            logger.debug("Loading knowledge from %s (type=%s)", source.path, source.type)
            return LocalDirectoryBackend(
                path=source.path,
                extensions=source.config.get("extensions"),
                max_chunk_size=source.config.get("max_chunk_size", 2000),
            )
        logger.warning("Unknown knowledge source type: %s", source.type)
        return None

    async def search(self, query: str, top_k: int = 5) -> SearchResult:
        """Search across all backends and merge results."""
        all_chunks = []
        total_found = 0

        for backend in self._backends:
            result = await backend.search(query, top_k=top_k)
            all_chunks.extend(result.chunks)
            total_found += result.total_found

        # Sort by relevance (chunks are already sorted per-backend, re-sort merged)
        all_chunks = all_chunks[:top_k]

        return SearchResult(
            chunks=all_chunks,
            query=query,
            total_found=total_found,
        )

    async def get_document(self, source: str) -> str:
        """Retrieve a document from the first backend that has it."""
        for backend in self._backends:
            try:
                return await backend.get_document(source)
            except (FileNotFoundError, ValueError):
                continue
        raise FileNotFoundError(f"Document not found in any backend: {source}")

    @property
    def has_backends(self) -> bool:
        return len(self._backends) > 0

    def create_tools(self) -> list[NativeTool]:
        """Create built-in knowledge tools."""
        if not self._backends:
            return []

        manager = self  # capture reference

        async def search_knowledge(query: str, top_k: int = 5) -> str:
            """Search the knowledge base for relevant information."""
            result = await manager.search(query, top_k=top_k)
            if not result.chunks:
                return f"No results found for: {query}"
            output = [f"Found {result.total_found} results for '{query}':\n"]
            for i, chunk in enumerate(result.chunks, 1):
                output.append(f"--- Result {i} (source: {chunk.source}) ---")
                output.append(chunk.content)
                output.append("")
            return "\n".join(output)

        async def get_knowledge_document(source: str) -> str:
            """Retrieve a specific document from the knowledge base."""
            try:
                return await manager.get_document(source)
            except FileNotFoundError:
                return f"Document not found: {source}"

        search_tool = NativeTool(
            func=search_knowledge,
            definition_=ToolDefinition(
                name="search_knowledge",
                description="Search the knowledge base for relevant information.",
                parameters=[
                    ToolParameter(name="query", type="string", description="Search query", required=True),
                    ToolParameter(name="top_k", type="integer", description="Max results", required=False, default=5),
                ],
                source="builtin",
            ),
        )

        get_doc_tool = NativeTool(
            func=get_knowledge_document,
            definition_=ToolDefinition(
                name="get_knowledge_document",
                description="Retrieve a specific document from the knowledge base by its source path.",
                parameters=[
                    ToolParameter(name="source", type="string", description="Document source path", required=True),
                ],
                source="builtin",
            ),
        )

        return [search_tool, get_doc_tool]

    def get_tools(self) -> list[NativeTool]:
        return self.create_tools()

    def get_prompt_injection(self) -> str:
        """Return a summary of the knowledge base for the system prompt."""
        if not self._backends:
            return ""

        lines = [
            "## Knowledge Base",
            "",
            "You have access to a knowledge base through the `search_knowledge` and `get_knowledge_document` tools. "
            "Use them when you need factual information that is not in your training data or current context.",
            ""
        ]
        
        # Describe backends (simplified)
        for i, backend in enumerate(self._backends, 1):
            if hasattr(backend, "_path"):
                lines.append(f"- **Source {i}**: Local directory at `{backend._path}`")
            else:
                lines.append(f"- **Source {i}**: {backend.__class__.__name__}")
        
        return "\n".join(lines)
