"""Map OTLP/JSON spans to rows for the `spans` table.

AI citation: drafted by Claude (Anthropic) against the schema that Nuri designed.

This is the only file that knows OpenTelemetry attribute names. The GenAI
semantic conventions still have the status "Development", so names can change.
When they do, change this file; the schema, the diff, and the UI stay the same.
"""
import json

KINDS = {"invoke_agent", "chat", "execute_tool"}

# column in `spans`  <-  attribute name(s), first match wins
COLUMNS = {
    "model": ["gen_ai.request.model", "gen_ai.response.model"],
    "input_tokens": ["gen_ai.usage.input_tokens"],
    "output_tokens": ["gen_ai.usage.output_tokens"],
    "finish_reasons": ["gen_ai.response.finish_reasons"],
    "tool_name": ["gen_ai.tool.name"],
    "tool_call_id": ["gen_ai.tool.call.id"],
    "tool_arguments": ["gen_ai.tool.call.arguments"],
    "tool_result": ["gen_ai.tool.call.result"],
    "error_type": ["error.type"],
}
RUN_NAME = "gen_ai.conversation.id"
RUN_AGENT = "gen_ai.agent.name"
RUN_TASK = "demo.task"


def _value(v):
    """Convert one OTLP AnyValue to a Python value."""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])  # OTLP/JSON writes 64-bit integers as strings
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _value(kv["value"]) for kv in v["kvlistValue"].get("values", [])}
    return None


def attributes(span):
    """Return the span attributes as a plain dict."""
    return {a["key"]: _value(a["value"]) for a in span.get("attributes", [])}


def _text(value):
    """Lists and dicts go into TEXT columns as JSON."""
    return json.dumps(value) if isinstance(value, (list, dict)) else value


def map_span(span):
    """Return a dict with one key for each data column of `spans`."""
    attrs = attributes(span)
    op = attrs.get("gen_ai.operation.name")
    row = {
        "span_id": span["spanId"],
        "parent_span_id": span.get("parentSpanId") or None,
        "kind": op if op in KINDS else "other",
        "started_at": int(span["startTimeUnixNano"]),
        "ended_at": int(span["endTimeUnixNano"]),
        "status_code": span.get("status", {}).get("code", 0),
        "attributes": json.dumps(attrs),
    }
    for column, names in COLUMNS.items():
        row[column] = next((_text(attrs[n]) for n in names if n in attrs), None)
    return row


def map_run(trace_id, root):
    """Return the columns of `runs` from the root span of a trace."""
    attrs = attributes(root)
    return {
        "trace_id": trace_id,
        "name": attrs.get(RUN_NAME) or trace_id,  # display label only
        "agent_name": attrs.get(RUN_AGENT),
        "task": attrs.get(RUN_TASK),
    }
