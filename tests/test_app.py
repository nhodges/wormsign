"""Tests for the Flask routes.

AI citation: drafted by Claude (Anthropic).
"""
import pathlib

import pytest

import app as viewer
import ingest

LOGS = pathlib.Path(__file__).parent.parent / "sample_logs"


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    for log in sorted(LOGS.glob("*.jsonl")):
        ingest.load(log, db_path).close()
    viewer.app.config.update(DATABASE=str(db_path), TESTING=True)
    return viewer.app.test_client()


def test_run_list_shows_all_runs(client):
    page = client.get("/").get_data(as_text=True)
    for name in ("run_ok", "run_tool_error", "run_diff_a", "run_diff_b"):
        assert name in page
    assert page.count('badge err">error') == 1


def test_timeline_shows_steps_and_error(client):
    db = ingest.connect(viewer.app.config["DATABASE"])
    run_id = ingest.get_run(db, "run_tool_error")["run_id"]
    page = client.get(f"/runs/{run_id}").get_data(as_text=True)
    assert "Step 3" in page and "Step 4" not in page
    assert "tool · http_get" in page and "timeout" in page


def test_unknown_run_is_404(client):
    assert client.get("/runs/9999").status_code == 404


def run_id(name):
    db = ingest.connect(viewer.app.config["DATABASE"])
    return ingest.get_run(db, name)["run_id"]


def test_diff_page_marks_the_divergence(client):
    a, b = run_id("run_diff_a"), run_id("run_diff_b")
    page = client.get(f"/diff?run={a}&run={b}").get_data(as_text=True)
    assert "diverge at <strong>step 3</strong>" in page
    assert page.count("Runs diverge here") == 1
    assert "4 of 6 aligned rows match" in page


def test_diff_page_same_run(client):
    a = run_id("run_ok")
    page = client.get(f"/diff?run={a}&run={a}").get_data(as_text=True)
    assert "took the same actions" in page and "Runs diverge here" not in page


def test_diff_needs_two_known_runs(client):
    assert client.get("/diff?run=1").status_code == 400
    assert client.get("/diff?run=1&run=9999").status_code == 404


def test_diff_warns_when_tasks_differ(client):
    a, b, c = run_id("run_diff_a"), run_id("run_diff_b"), run_id("run_ok")
    assert "different tasks" in client.get(f"/diff?run={a}&run={c}").get_data(as_text=True)
    assert "different tasks" not in client.get(f"/diff?run={a}&run={b}").get_data(as_text=True)


def test_cost_view_flags_the_largest_step(client):
    page = client.get(f"/runs/{run_id('run_diff_a')}").get_data(as_text=True)
    assert "Tokens by step" in page
    assert page.count('badge warn">largest') == 1
    # Step 6 of run_diff_a: 4,200 in + 95 out is the largest of the run.
    largest = page.split('cost-row largest')[1].split("</a>")[0]
    assert "Step 6" in largest and "4,295" in largest
