import os
from pathlib import Path

import chromadb
import uvicorn
import voyageai
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Resource, TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from .embed import COLLECTION_NAME

IDENTITY_URI = "ramblebot://identity"
SEARCH_RESULTS_K = 5


def create_app(ramblebot_home: Path, voyage_api_key: str) -> Starlette:
    ramblebot_md = ramblebot_home / "ramblebot.md"
    chroma_dir = ramblebot_home / "chroma"

    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
    voyage = voyageai.Client(api_key=voyage_api_key)

    server = Server("ramblebot")

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [Resource(
            uri=IDENTITY_URI,
            name="RambleBot Identity",
            description="Frank's building patterns, preferences, and project context",
            mimeType="text/markdown",
        )]

    @server.read_resource()
    async def read_resource(uri) -> list[TextContent]:
        if str(uri) == IDENTITY_URI:
            if ramblebot_md.exists():
                text = ramblebot_md.read_text(encoding="utf-8")
            else:
                text = "# RambleBot\n\n_No distillation available yet. Run distill.py._"
            return [TextContent(type="text", text=text)]
        raise ValueError(f"Unknown resource: {uri}")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(
            name="ramblebot_search",
            description=(
                "Search Frank's historical Claude Code and openclaw conversations "
                "for relevant context, past decisions, or prior solutions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the conversation history",
                    }
                },
                "required": ["query"],
            },
        )]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "ramblebot_search":
            raise ValueError(f"Unknown tool: {name}")

        query = arguments.get("query", "").strip()
        if not query:
            return [TextContent(type="text", text="No query provided.")]

        result = voyage.embed([query], model="voyage-3-lite")
        query_embedding = result.embeddings[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=SEARCH_RESULTS_K,
            include=["documents", "metadatas"],
        )

        if not results["documents"] or not results["documents"][0]:
            return [TextContent(type="text", text="No relevant results found.")]

        parts = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            source = meta.get("source", "unknown")
            host = meta.get("host", "")
            project = meta.get("project", "")
            role = meta.get("role", "")
            ts = meta.get("timestamp", "")[:10]
            parts.append(f"**[{source} | {host} | {project} | {role} | {ts}]**\n{doc}")

        return [TextContent(type="text", text="\n\n---\n\n".join(parts))]

    sse_transport = SseServerTransport("/messages")

    async def handle_sse(request: Request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options(),
            )

    return Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse_transport.handle_post_message),
    ])


if __name__ == "__main__":
    ramblebot_home = Path(os.environ.get("RAMBLEBOT_HOME", Path.home() / "ramblebot"))
    voyage_api_key = os.environ["VOYAGE_API_KEY"]
    port = int(os.environ.get("RAMBLEBOT_PORT", "8765"))
    app = create_app(ramblebot_home, voyage_api_key)
    uvicorn.run(app, host="0.0.0.0", port=port)
