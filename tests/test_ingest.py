"""Tests for the log parser. Run with: pytest

AI citation: test skeleton drafted by Claude (Anthropic). The expected numbers
come from tools/make_fixtures.py. The step layout in the tests comes from the same generator.
"""
import json
import pathlib

import pytest

import ingest

LOGS = pathlib.Path(__file__).parent.parent / "sample_logs"

# run name -> (span count, input tokens, output tokens, tool calls, has error)
EXPECTED = {
    "run_ok": (4, 2300, 260, 1, False),
    "run_tool_error": (6, 3300, 195, 2, True),
    "run_diff_a": (12, 17200, 760, 5, False),
    "run_diff_b": (10, 12200, 505, 4, False),
}


def raw_spans(name):
    """Read spans straight from the file, with no help from ingest.py."""
    spans = []
    for line in (LOGS / f"{name}.jsonl").read_text().splitlines():
        for rs in json.loads(line)["resourceSpans"]:
            for ss in rs["scopeSpans"]:
                spans.extend(ss["spans"])
    return spans


@pytest.mark.parametrize("name", EXPECTED)
def test_fixture_matches_expected(name):
    assert len(raw_spans(name)) == EXPECTED[name][0]


@pytest.mark.parametrize("name", EXPECTED)
def test_token_totals(name, tmp_path):
    db = ingest.load(LOGS / f"{name}.jsonl", tmp_path / "t.db")
    run = ingest.get_run(db, name)
    assert (run["input_tokens"], run["output_tokens"]) == EXPECTED[name][1:3]


@pytest.mark.parametrize("name", EXPECTED)
def test_tool_calls_and_errors(name, tmp_path):
    db = ingest.load(LOGS / f"{name}.jsonl", tmp_path / "t.db")
    run = ingest.get_run(db, name)
    assert run["tool_call_count"] == EXPECTED[name][3]
    assert bool(run["has_error"]) == EXPECTED[name][4]


def test_load_twice_does_not_duplicate(tmp_path):
    path, db_path = LOGS / "run_ok.jsonl", tmp_path / "t.db"
    ingest.load(path, db_path)
    db = ingest.load(path, db_path)
    assert ingest.count_runs(db) == 1


def test_step_index_groups_tools_with_their_chat(tmp_path):
    db = ingest.load(LOGS / "run_diff_a.jsonl", tmp_path / "t.db")
    rows = db.execute(
        "SELECT kind, step_index FROM spans ORDER BY started_at, id").fetchall()
    assert rows[0]["kind"] == "invoke_agent" and rows[0]["step_index"] is None
    steps = [(r["kind"], r["step_index"]) for r in rows[1:]]
    assert steps[:4] == [("chat", 0), ("execute_tool", 0), ("chat", 1), ("execute_tool", 1)]
    assert steps[-1] == ("chat", 5)  # the last turn has no tool call


def test_unknown_operation_is_kept_as_other(tmp_path):
    span = {"traceId": "t1", "spanId": "s1", "name": "GET /health", "kind": 3,
            "startTimeUnixNano": "1", "endTimeUnixNano": "2",
            "attributes": [{"key": "http.request.method", "value": {"stringValue": "GET"}}]}
    path = tmp_path / "other.jsonl"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}))
    db = ingest.load(path, tmp_path / "t.db")
    row = db.execute("SELECT kind, attributes FROM spans").fetchone()
    assert row["kind"] == "other" and "http.request.method" in row["attributes"]
    assert ingest.get_run(db, "t1") is not None  # name falls back to the trace id
