-- schema.sql — Wormsign (trace viewer), milestone 1
-- AI citation: drafted with Claude (Anthropic); design decisions reviewed and
-- chosen by Nuri.
--
-- Two tables: runs + spans with a `kind` column.
-- A "step" is one model call plus the tool calls that follow it; it is not
-- stored as its own table because the source data has no step grouping
-- (every span is a flat child of the root). Instead ingest.py computes
-- `step_index` while walking spans in (started_at, id) order: it increments
-- on each chat span, and other spans inherit the index of the chat before them.
--
-- NOTE: there is deliberately no PRAGMA foreign_keys here. SQLite applies it
-- per connection, so it must run in the function that opens the database;
-- in this file it would only affect the connection that loads the schema.

CREATE TABLE runs (
    id          INTEGER PRIMARY KEY,
    trace_id    TEXT    NOT NULL UNIQUE,  -- the only real identity; loading a file twice must not duplicate a run
    name        TEXT    NOT NULL,         -- display label: gen_ai.conversation.id, or the trace id when absent (ingest fills the fallback); NOT unique
    agent_name  TEXT,                     -- gen_ai.agent.name
    task        TEXT,                     -- demo.task
    started_at  INTEGER NOT NULL,         -- unix nanoseconds, from the root span
    ended_at    INTEGER NOT NULL
);

CREATE TABLE spans (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    span_id         TEXT    NOT NULL,
    parent_span_id  TEXT,                 -- NULL only for the root span
    kind            TEXT    NOT NULL CHECK (kind IN ('invoke_agent', 'chat', 'execute_tool', 'other')),
                                          -- otel_map.py maps unknown operations to 'other'; the viewer shows them rather than dropping them
    step_index      INTEGER,              -- NULL for the root; set by ingest.py (see note above)
    started_at      INTEGER NOT NULL,     -- unix nanoseconds; convert to ms before sending to JS
    ended_at        INTEGER NOT NULL,
    status_code     INTEGER NOT NULL DEFAULT 1,  -- OTLP status: 1 = ok, 2 = error
    error_type      TEXT,                 -- error.type, e.g. "timeout"

    -- chat spans only
    model           TEXT,                 -- gen_ai.request.model
    input_tokens    INTEGER,              -- gen_ai.usage.input_tokens
    output_tokens   INTEGER,              -- gen_ai.usage.output_tokens
    finish_reasons  TEXT,                 -- gen_ai.response.finish_reasons, stored as the JSON array

    -- execute_tool spans only
    tool_name       TEXT,                 -- gen_ai.tool.name
    tool_call_id    TEXT,                 -- gen_ai.tool.call.id
    tool_arguments  TEXT,                 -- gen_ai.tool.call.arguments (JSON string)
    tool_result     TEXT,                 -- gen_ai.tool.call.result

    -- all spans
    attributes      TEXT,                 -- raw span attributes as JSON; unmapped keys stay visible in the detail pane

    UNIQUE (run_id, span_id)              -- no duplicate spans within a run either
);

-- The timeline reads one run's spans in time order; ties break on id.
CREATE INDEX idx_spans_run_time ON spans (run_id, started_at, id);

-- Run-level numbers are derived from spans so they can never disagree with
-- them; this view writes the aggregation once instead of in every route.
CREATE VIEW run_totals AS
SELECT
    r.id                                      AS run_id,
    r.trace_id,
    r.name,
    COALESCE(SUM(s.input_tokens), 0)          AS input_tokens,
    COALESCE(SUM(s.output_tokens), 0)         AS output_tokens,
    COALESCE(SUM(s.kind = 'execute_tool'), 0) AS tool_call_count,
    COALESCE(MAX(s.status_code = 2), 0)       AS has_error
FROM runs r
LEFT JOIN spans s ON s.run_id = r.id
GROUP BY r.id;
