"""Tests for GET /api/tools/lark endpoint."""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from everstaff.api.tools import make_router


@pytest.fixture
def client():
    config = MagicMock()
    config.tools_dirs = []
    app = FastAPI()
    app.include_router(make_router(config), prefix="/api")
    return TestClient(app)


def test_list_lark_tools(client):
    resp = client.get("/api/tools/lark")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    assert "im" in data["categories"]
    assert "docs" in data["categories"]
    assert "calendar" in data["categories"]
    assert "tasks" in data["categories"]


def test_list_lark_tools_has_names(client):
    resp = client.get("/api/tools/lark")
    data = resp.json()
    im_tools = data["categories"]["im"]
    names = [t["name"] for t in im_tools]
    assert "feishu_send_message" in names
    assert "feishu_list_messages" in names


def test_list_lark_tools_filter_category(client):
    resp = client.get("/api/tools/lark?categories=im,docs")
    assert resp.status_code == 200
    data = resp.json()
    assert "im" in data["categories"]
    assert "docs" in data["categories"]
    assert "tasks" not in data["categories"]
    assert "calendar" not in data["categories"]


def test_list_lark_tools_single_category(client):
    resp = client.get("/api/tools/lark?categories=tasks")
    data = resp.json()
    assert list(data["categories"].keys()) == ["tasks"]
    names = [t["name"] for t in data["categories"]["tasks"]]
    assert "feishu_create_task" in names
