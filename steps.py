"""Group the spans of one run into steps. The timeline and the diff both use this.

AI citation: drafted by Claude (Anthropic); the grouping rule comes from the
schema that Nuri designed (a step is one model call plus the tool calls after it).
"""
NS_PER_MS = 1_000_000


def load_steps(db, run_id):
    """Return one dict per step, in order. Raises ValueError for an unknown run id.

    Each step has: index, model, input_tokens, output_tokens, duration_ms,
    has_error, tools (name, arguments, error_type), tool_names, and spans
    (the span rows as dicts, each with duration_ms).
    """
    if not db.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone():
        raise ValueError(f"no run with id {run_id}")
    rows = db.execute(
        "SELECT * FROM spans WHERE run_id = ? AND step_index IS NOT NULL "
        "ORDER BY started_at, id", (run_id,)).fetchall()
    steps = {}
    for row in rows:
        span = dict(row)
        span["duration_ms"] = (row["ended_at"] - row["started_at"]) / NS_PER_MS
        step = steps.setdefault(row["step_index"], {
            "index": row["step_index"], "model": None, "input_tokens": 0,
            "output_tokens": 0, "duration_ms": 0, "has_error": False,
            "tools": [], "spans": []})
        step["spans"].append(span)
        step["duration_ms"] += span["duration_ms"]
        step["has_error"] = step["has_error"] or row["status_code"] == 2
        if row["kind"] == "chat":
            step["model"] = row["model"]
            step["input_tokens"] += row["input_tokens"] or 0
            step["output_tokens"] += row["output_tokens"] or 0
        elif row["kind"] == "execute_tool":
            step["tools"].append({"name": row["tool_name"],
                                  "arguments": row["tool_arguments"],
                                  "error_type": row["error_type"]})
    for step in steps.values():
        step["tool_names"] = [t["name"] for t in step["tools"]]
    return [steps[i] for i in sorted(steps)]
