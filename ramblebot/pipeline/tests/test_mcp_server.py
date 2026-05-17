import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport

from pipeline.mcp_server import create_app, IDENTITY_URI


@pytest.fixture
def ramblebot_home(tmp_path):
    home = tmp_path / "ramblebot"
    distilled = home / "distilled"
    distilled.mkdir(parents=True)
    doc = distilled / "ramblebot-2026-05-16.md"
    doc.write_text("# RambleBot\nFrank prefers Python.")
    symlink = home / "ramblebot.md"
    symlink.symlink_to(doc)
    chroma = home / "chroma"
    chroma.mkdir()
    return home


def test_app_routes_exist(ramblebot_home):
    mock_collection = MagicMock()
    mock_chroma = MagicMock()
    mock_chroma.get_or_create_collection.return_value = mock_collection
    mock_voyage = MagicMock()

    with patch("pipeline.mcp_server.chromadb.PersistentClient", return_value=mock_chroma), \
         patch("pipeline.mcp_server.voyageai.Client", return_value=mock_voyage):
        app = create_app(ramblebot_home, voyage_api_key="test")

    route_paths = {r.path for r in app.routes}
    assert "/sse" in route_paths
    assert "/messages" in route_paths
