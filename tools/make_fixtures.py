"""Generate sample agent traces as OTLP/JSON lines (one export batch per line).

AI citation: this file was drafted by Claude (Anthropic) for the CS50x final
project of Nuri Hodges. It makes test fixtures only; it is not part of the app.

Format: the OpenTelemetry file-exporter layout. Each line is one
ExportTraceServiceRequest: {"resourceSpans": [{"scopeSpans": [{"spans": [...]}]}]}
Attribute names follow the GenAI semantic conventions (status: Development).
"""
import hashlib, json, pathlib, sys

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "sample_logs")
MODEL = "example-model-1"
T0 = 1_794_000_000_000_000_000  # fixed start time, ns


def hx(seed, n):
    return hashlib.sha256(seed.encode()).hexdigest()[:n]


def attrs(d):
    out = []
    for k, v in d.items():
        if isinstance(v, list):
            val = {"arrayValue": {"values": [{"stringValue": x} for x in v]}}
        else:
            val = {"intValue": str(v)} if isinstance(v, int) else {"stringValue": v}
        out.append({"key": k, "value": val})
    return out


def build(run, task, turns):
    """turns: list of (in_tok, out_tok, [(tool, args, result, ms, error_type|None)])"""
    trace, root = hx(run, 32), hx(run + "root", 16)
    spans, t, n = [], T0, 0

    def span(name, parent, start, end, a, err=None):
        nonlocal n
        n += 1
        sid = root if parent is None else hx(f"{run}{n}", 16)
        s = {"traceId": trace, "spanId": sid, "name": name, "kind": 1,
             "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
             "attributes": attrs(a), "status": {"code": 2 if err else 1}}
        if parent:
            s["parentSpanId"] = parent
        if err:
            s["attributes"] += attrs({"error.type": err})
        spans.append(s)

    failed = None
    body = []
    for i, (tin, tout, tools) in enumerate(turns):
        start, t = t, t + (400 + tout * 12) * 1_000_000
        body.append((f"chat {MODEL}", start, t, {
            "gen_ai.operation.name": "chat", "gen_ai.provider.name": "example",
            "gen_ai.request.model": MODEL, "gen_ai.usage.input_tokens": tin,
            "gen_ai.usage.output_tokens": tout,
            "gen_ai.response.finish_reasons": ["tool_calls" if tools else "stop"]}, None))
        for j, (tool, args, result, ms, err) in enumerate(tools):
            start, t = t, t + ms * 1_000_000
            failed = failed or err
            body.append((f"execute_tool {tool}", start, t, {
                "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool,
                "gen_ai.tool.call.id": f"call_{i}_{j}",
                "gen_ai.tool.call.arguments": json.dumps(args),
                "gen_ai.tool.call.result": result}, err))
    span("invoke_agent demo-agent", None, T0, t, {
        "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "demo-agent",
        "gen_ai.conversation.id": run, "demo.task": task}, failed)
    for name, s, e, a, err in body:
        span(name, root, s, e, a, err)

    res = {"attributes": attrs({"service.name": "demo-harness"})}
    lines = []
    for k in range(0, len(spans), 4):  # exporters send batches; so do we
        lines.append(json.dumps({"resourceSpans": [{"resource": res, "scopeSpans": [
            {"scope": {"name": "demo-harness"}, "spans": spans[k:k + 4]}]}]}))
    (OUT / f"{run}.jsonl").write_text("\n".join(lines) + "\n")
    return len(spans)


TASK = "Fix the failing test in utils/dates.py"
common = [
    (1200, 60, [("read_file", {"path": "tests/test_dates.py"}, "def test_parse_iso(): ...", 35, None)]),
    (1900, 85, [("run_tests", {"target": "tests/test_dates.py"}, "1 failed: test_parse_iso", 2100, None)]),
]
runs = {
    "run_ok": ("Summarise README.md", [
        (800, 40, [("read_file", {"path": "README.md"}, "# Demo project ...", 30, None)]),
        (1500, 220, [])]),
    "run_tool_error": ("Fetch the changelog and list breaking changes", [
        (900, 55, [("http_get", {"url": "https://example.com/changelog"}, "", 5000, "timeout")]),
        (1100, 50, [("http_get", {"url": "https://example.com/changelog"}, "", 5000, "timeout")]),
        (1300, 90, [])]),
    # Pair for the diff view: same first two turns, then they diverge at turn 3.
    "run_diff_a": (TASK, common + [
        (2600, 140, [("read_file", {"path": "utils/dates.py"}, "def parse_iso(s): ...", 30, None)]),
        (3400, 310, [("write_file", {"path": "utils/dates.py"}, "ok", 45, None)]),
        (3900, 70, [("run_tests", {"target": "tests/test_dates.py"}, "1 passed", 1900, None)]),
        (4200, 95, [])]),
    "run_diff_b": (TASK, common + [
        (2600, 180, [("write_file", {"path": "tests/test_dates.py"}, "ok", 45, None)]),
        (3100, 70, [("run_tests", {"target": "tests/test_dates.py"}, "1 passed", 1900, None)]),
        (3400, 110, [])]),
}
OUT.mkdir(exist_ok=True)
for name, (task, turns) in runs.items():
    print(name, build(name, task, turns), "spans")
