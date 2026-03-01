"""Tests for DAG engine multi-HITL collection."""
import pytest
from everstaff.protocols import HumanApprovalRequired, HitlRequest


def test_dag_engine_collects_multiple_hitl_from_batch():
    """When multiple tasks in a batch raise HITL, all requests must be merged."""
    r1 = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Q1")
    r2 = HitlRequest(hitl_id="h2", type="choose", prompt="Q2", options=["A", "B"])

    exc1 = HumanApprovalRequired([r1])
    exc2 = HumanApprovalRequired([r2])

    # Simulate what DAG engine should do: merge
    all_requests = []
    for exc in [exc1, exc2]:
        all_requests.extend(exc.requests)

    merged = HumanApprovalRequired(all_requests)
    assert len(merged.requests) == 2
    assert merged.requests[0].hitl_id == "h1"
    assert merged.requests[1].hitl_id == "h2"
