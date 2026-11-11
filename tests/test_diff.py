"""Tests for diff.py.

AI citation: drafted with Claude (Anthropic); the assertions are the
acceptance checks from the milestone 2 brief.
"""
import pathlib

import pytest

import diff
import ingest

LOGS = pathlib.Path(__file__).parent.parent / "sample_logs"


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "t.db"
    for log in sorted(LOGS.glob("*.jsonl")):
        ingest.load(log, db_path).close()
    db = ingest.connect(db_path)
    yield db
    db.close()


def run_id(db, name):
    return ingest.get_run(db, name)["run_id"]


def test_diff_a_b_diverges_at_2(db):
    result = diff.diff_runs(db, run_id(db, "run_diff_a"), run_id(db, "run_diff_b"))
    assert result["diverged_at"] == 2


def test_run_against_itself_is_same(db):
    rid = run_id(db, "run_diff_a")
    result = diff.diff_runs(db, rid, rid)
    assert result["diverged_at"] is None
    assert all(row["same"] for row in result["rows"])


def test_tail_realigns_after_divergence(db):
    """Both runs end with the same run_tests call and a final answer; the
    LCS alignment must show that tail as matching, not as four changed rows."""
    result = diff.diff_runs(db, run_id(db, "run_diff_a"), run_id(db, "run_diff_b"))
    assert [row["same"] for row in result["rows"][-2:]] == [True, True]


def test_shorter_run_gets_none_padding(db):
    result = diff.diff_runs(db, run_id(db, "run_diff_a"), run_id(db, "run_ok"))
    assert any(row["b"] is None for row in result["rows"])
    # Every step of the longer run appears exactly once, in order.
    assert [row["a"]["index"] for row in result["rows"] if row["a"]] == list(range(6))


def test_unknown_run_raises(db):
    with pytest.raises(ValueError):
        diff.diff_runs(db, run_id(db, "run_ok"), 9999)


def test_align_handles_long_runs():
    """Added in review: two 600-step runs with nothing in common.

    _align needs no database, so the steps are made by hand.
    """
    a = [{"index": i, "tools": [{"name": f"a{i}", "arguments": None}]} for i in range(600)]
    b = [{"index": i, "tools": [{"name": f"b{i}", "arguments": None}]} for i in range(600)]
    rows = diff._align(a, b)
    assert len(rows) == 600 and not any(row["same"] for row in rows)
