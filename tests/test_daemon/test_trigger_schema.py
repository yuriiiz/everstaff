"""Tests for extended TriggerConfig schema."""
import pytest
from everstaff.schema.autonomy import TriggerConfig


def test_webhook_trigger():
    t = TriggerConfig(id="gh-pr", type="webhook", task="handle PR")
    assert t.type == "webhook"
    assert t.task == "handle PR"


def test_file_watch_trigger():
    t = TriggerConfig(
        id="cfg-watch",
        type="file_watch",
        task="config changed",
        watch_paths=["config/", "agents/"],
    )
    assert t.type == "file_watch"
    assert t.watch_paths == ["config/", "agents/"]


def test_internal_trigger():
    t = TriggerConfig(
        id="self-reflect",
        type="internal",
        task="analyze episodes",
        condition="episode_count",
        threshold=5,
    )
    assert t.type == "internal"
    assert t.condition == "episode_count"
    assert t.threshold == 5


def test_internal_trigger_default_threshold():
    t = TriggerConfig(id="x", type="internal", condition="episode_count")
    assert t.threshold == 5


def test_cron_trigger_unchanged():
    t = TriggerConfig(id="daily", type="cron", schedule="0 9 * * *", task="check")
    assert t.schedule == "0 9 * * *"
