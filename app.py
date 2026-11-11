"""Wormsign: Flask routes.

AI citation: drafted by Claude (Anthropic). Routes read the schema that Nuri designed.

Run:  python ingest.py traces.db sample_logs/*.jsonl
      flask run            (set TRACE_DB to use a different database file)
"""
import json
import os

from flask import Flask, abort, g, render_template, request

import diff
import ingest
import steps

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get("TRACE_DB", "traces.db")

NS_PER_MS = 1_000_000  # JS cannot hold nanosecond timestamps exactly, so pages get ms


def get_db():
    if "db" not in g:
        g.db = ingest.connect(app.config["DATABASE"])
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.template_filter("duration")
def duration(ms):
    """1234 -> '1.23 s', 87 -> '87 ms'."""
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.0f} ms"


@app.template_filter("pretty")
def pretty(text):
    """Indent JSON text. Text that is not JSON stays as it is."""
    try:
        return json.dumps(json.loads(text), indent=2)
    except (TypeError, ValueError):
        return text or ""


@app.route("/")
def run_list():
    runs = get_db().execute(
        "SELECT r.id, r.name, r.task, r.agent_name, r.started_at, "
        "       (r.ended_at - r.started_at) / ? AS duration_ms, "
        "       t.input_tokens, t.output_tokens, t.tool_call_count, t.has_error "
        "FROM runs r JOIN run_totals t ON t.run_id = r.id "
        "ORDER BY r.started_at DESC, r.id DESC", (NS_PER_MS,)).fetchall()
    return render_template("runs.html", runs=runs)


def get_run(db, run_id):
    """One run with its totals. Unknown id -> 404."""
    run = db.execute(
        "SELECT r.*, (r.ended_at - r.started_at) / ? AS duration_ms, "
        "       t.input_tokens, t.output_tokens, t.tool_call_count, t.has_error "
        "FROM runs r JOIN run_totals t ON t.run_id = r.id WHERE r.id = ?",
        (NS_PER_MS, run_id)).fetchone()
    if run is None:
        abort(404)
    return run


@app.route("/diff")
def diff_view():
    """Compare two runs: /diff?run=1&run=2. The alignment comes from diff.py."""
    ids = request.args.getlist("run", type=int)
    if len(ids) != 2:
        abort(400, "Select exactly two runs to compare.")
    db = get_db()
    run_a, run_b = get_run(db, ids[0]), get_run(db, ids[1])
    result = diff.diff_runs(db, ids[0], ids[1])
    for row in result["rows"]:
        # Same action, but only one side failed: the page marks this.
        row["outcome_differs"] = bool(
            row["same"] and row["a"]["has_error"] != row["b"]["has_error"])
    same = sum(row["same"] for row in result["rows"])
    # Steps with no tool call always match, so two unrelated runs can still
    # share rows. Warn when the tasks are not the same.
    tasks_differ = run_a["task"] != run_b["task"]
    return render_template("diff.html", a=run_a, b=run_b, result=result, tasks_differ=tasks_differ,
                           same_count=same, total=len(result["rows"]))


@app.route("/runs/<int:run_id>")
def timeline(run_id):
    db = get_db()
    run = get_run(db, run_id)
    run_steps = steps.load_steps(db, run_id)
    total = max(run["ended_at"] - run["started_at"], 1)
    for step in run_steps:
        for span in step["spans"]:
            # Position of the bar on the run's time axis, in percent.
            span["left"] = 100 * (span["started_at"] - run["started_at"]) / total
            span["width"] = max(100 * (span["ended_at"] - span["started_at"]) / total, 0.4)
    # Cost view: the bar of each step is relative to the largest step.
    largest = max((s["input_tokens"] + s["output_tokens"] for s in run_steps), default=0)
    run_tokens = run["input_tokens"] + run["output_tokens"]
    for step in run_steps:
        tokens = step["input_tokens"] + step["output_tokens"]
        step["in_width"] = 100 * step["input_tokens"] / largest if largest else 0
        step["out_width"] = 100 * step["output_tokens"] / largest if largest else 0
        step["share"] = 100 * tokens / run_tokens if run_tokens else 0
        step["is_largest"] = bool(largest) and tokens == largest
    return render_template("timeline.html", run=run, steps=run_steps)
