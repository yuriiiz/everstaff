"""Tests for goal breakdown management."""
import pytest
from everstaff.daemon.goals import GoalBreakdown, SubGoal


def test_create_empty_breakdown():
    gb = GoalBreakdown(goal_id="g1")
    assert gb.goal_id == "g1"
    assert gb.sub_goals == []


def test_add_sub_goals():
    gb = GoalBreakdown(goal_id="g1")
    gb.sub_goals.append(SubGoal(description="step 1", acceptance_criteria="done when X"))
    assert len(gb.sub_goals) == 1
    assert gb.sub_goals[0].status == "pending"


def test_update_sub_goal_progress():
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="step 1"),
        SubGoal(description="step 2"),
    ])
    gb.sub_goals[0].status = "completed"
    gb.sub_goals[0].progress_note = "finished successfully"
    assert gb.sub_goals[0].status == "completed"


def test_completion_ratio():
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="a", status="completed"),
        SubGoal(description="b", status="in_progress"),
        SubGoal(description="c", status="pending"),
    ])
    assert gb.completion_ratio == pytest.approx(1 / 3)


def test_serialization_roundtrip():
    gb = GoalBreakdown(goal_id="g1", sub_goals=[
        SubGoal(description="step 1", status="completed"),
    ])
    data = gb.model_dump()
    gb2 = GoalBreakdown.model_validate(data)
    assert gb2.goal_id == gb.goal_id
    assert len(gb2.sub_goals) == 1
