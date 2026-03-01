"""Tests for flattened config models."""
import pytest


def test_storage_config_defaults_to_local():
    from everstaff.core.config import StorageConfig
    cfg = StorageConfig()
    assert cfg.type == "local"


def test_storage_config_s3_fields_flat():
    from everstaff.core.config import StorageConfig
    cfg = StorageConfig(type="s3", s3_bucket="my-bucket", s3_region="eu-west-1")
    assert cfg.s3_bucket == "my-bucket"
    assert cfg.s3_region == "eu-west-1"
    assert cfg.s3_prefix == "sessions"  # default


def test_storage_config_has_no_nested_s3():
    from everstaff.core.config import StorageConfig
    cfg = StorageConfig()
    assert not hasattr(cfg, "s3"), "StorageConfig must not have nested .s3 sub-model"
    assert not hasattr(cfg, "local"), "StorageConfig must not have nested .local sub-model"


def test_lark_channel_config_fields_flat():
    from everstaff.core.config import LarkChannelConfig
    cfg = LarkChannelConfig(type="lark", app_id="cli_xxx", app_secret="s3cr3t",
                            verification_token="tok", chat_id="oc_abc", bot_name="Bot")
    assert cfg.app_id == "cli_xxx"
    assert cfg.bot_name == "Bot"


def test_lark_channel_config_has_no_nested_lark():
    from everstaff.core.config import LarkChannelConfig
    cfg = LarkChannelConfig(type="lark")
    assert not hasattr(cfg, "lark")


def test_tracer_config_type_required():
    from everstaff.core.config import TracerConfig
    cfg = TracerConfig(type="file")
    assert cfg.type == "file"



def test_framework_config_has_tracers_field():
    from everstaff.core.config import FrameworkConfig
    cfg = FrameworkConfig()
    assert len(cfg.tracers) == 1
    assert cfg.tracers[0].type == "file"
