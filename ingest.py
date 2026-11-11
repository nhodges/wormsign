"""Load OTLP/JSON trace files into SQLite.

AI citation: drafted by Claude (Anthropic) against the schema that Nuri designed.

Usage: python ingest.py traces.db sample_logs/*.jsonl
"""
import json
import pathlib
import sqlite3
import sys

import otel_map

SCHEMA = pathlib.Path(__file__).parent / "schema.sql"
SPAN_COLUMNS = [
    "run_id", "span_id", "parent_span_id", "kind", "started_at", "ended_at",
    "status_code", "error_type", "model", "input_tokens", "output_tokens",
    "finish_reasons", "tool_name", "tool_call_id", "tool_arguments",
    "tool_result", "attributes",
]


def connect(db_path):
    """Open the database. Create the tables if the file is new."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")  # per connection; see schema.sql
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'runs'").fetchone():
        db.executescript(SCHEMA.read_text())
    return db


def read_spans(path):
    """Yield each span in the file. One line is one export batch."""
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        for resource in json.loads(line).get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                yield from scope.get("spans", [])


def find_root(spans):
    """The root has no parent in this trace. If there is none, use the first span."""
    ids = {s["spanId"] for s in spans}
    for s in spans:
        if s.get("parentSpanId") not in ids:
            return s
    return spans[0]


def set_step_indexes(db, run_id, root_span_id):
    """A chat span starts a new step. Other spans go with the chat before them."""
    rows = db.execute(
        "SELECT id, kind FROM spans WHERE run_id = ? AND span_id != ? "
        "ORDER BY started_at, id", (run_id, root_span_id))
    step = -1
    for row in rows.fetchall():
        if row["kind"] == "chat":
            step += 1
        db.execute("UPDATE spans SET step_index = ? WHERE id = ?", (max(step, 0), row["id"]))


def load(path, db_path):
    """Load one file. A second load of the same file changes nothing."""
    db = connect(db_path)
    traces = {}
    for span in read_spans(path):
        traces.setdefault(span["traceId"], []).append(span)

    with db:  # one transaction for the file
        for trace_id, spans in traces.items():
            spans.sort(key=lambda s: int(s["startTimeUnixNano"]))
            root = find_root(spans)
            run = otel_map.map_run(trace_id, root)
            run["started_at"] = min(int(s["startTimeUnixNano"]) for s in spans)
            run["ended_at"] = max(int(s["endTimeUnixNano"]) for s in spans)
            # trace_id is the identity. A later batch can make the run longer.
            db.execute(
                "INSERT INTO runs (trace_id, name, agent_name, task, started_at, ended_at) "
                "VALUES (:trace_id, :name, :agent_name, :task, :started_at, :ended_at) "
                "ON CONFLICT (trace_id) DO UPDATE SET "
                "started_at = MIN(started_at, excluded.started_at), "
                "ended_at = MAX(ended_at, excluded.ended_at)", run)
            run_id = db.execute(
                "SELECT id FROM runs WHERE trace_id = ?", (trace_id,)).fetchone()["id"]
            for span in spans:
                row = otel_map.map_span(span)
                row["run_id"] = run_id
                db.execute(
                    f"INSERT OR IGNORE INTO spans ({', '.join(SPAN_COLUMNS)}) "
                    f"VALUES ({', '.join(':' + c for c in SPAN_COLUMNS)})", row)
            set_step_indexes(db, run_id, root["spanId"])
    return db


def get_run(db, name):
    """Return the totals of the newest run with this display name, or None."""
    return db.execute(
        "SELECT t.* FROM run_totals t JOIN runs r ON r.id = t.run_id "
        "WHERE t.name = ? ORDER BY r.started_at DESC, r.id DESC LIMIT 1", (name,)).fetchone()


def count_runs(db):
    return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: python ingest.py DATABASE FILE...")
    for file in sys.argv[2:]:
        load(file, sys.argv[1])
    print(count_runs(connect(sys.argv[1])), "runs in", sys.argv[1])
