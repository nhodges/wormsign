# Wormsign

#### Video Demo: <https://youtu.be/kecg8r798Zo>

#### Description:

*See what moves beneath.*

In Dune, wormsign is the ripple on the sand that tells you something enormous
is moving underneath. Wormsign is a small Flask app that does the same for AI
agents: it loads OTLP/JSON traces of agent runs into SQLite and shows a run
list, a per-run timeline with a token cost view, and a step-by-step diff of
two runs.

AI citation: schema, ingest, and routes drafted with Claude (Anthropic), and
also the first version of the diff. Nuri chose the design decisions and
rewrote the diff alignment in `diff.py`. Each file states its own AI use in a
comment at the top.

```bash
pip install -r requirements.txt
python ingest.py traces.db sample_logs/*.jsonl
flask run
```

## Files

- `ingest.py` — CLI that loads OTLP/JSON trace files into SQLite; `connect()`
  lives here with the per-connection PRAGMAs.
- `schema.sql` — the `runs` and `spans` tables and the `run_totals` view.
- `otel_map.py` — maps OTLP spans to `spans` rows; the only file that knows
  OpenTelemetry attribute names, so convention changes stay contained here.
- `steps.py` — groups one run's spans into steps (one model call plus the
  tool calls after it); the timeline and the diff both read steps through it.
- `diff.py` — the step-by-step diff of two runs; also runs from the command
  line.
- `app.py` — the Flask routes: run list, timeline with the cost view, and the
  diff page.
- `templates/` — `layout.html` is the shared shell; `runs.html`,
  `timeline.html`, and `diff.html` are one page per route.
- `static/` — `style.css`, and `compare.js`, which enables the Compare button
  only when exactly two runs are checked.
- `tests/` — the pytest suite (29 tests) covering ingest, diff, and routes;
  `conftest.py` lets it import from the project root.
- `tools/make_fixtures.py` — generates the OTLP/JSON fixtures in
  `sample_logs/`; not part of the app.

## Schema

The schema is two tables, `runs` and `spans`, with a `kind` column instead of
separate `steps` and `tool_calls` tables, because that matches the source data:
every line in the log is a flat span under one root. A "step" (one model call
plus the tool calls that follow it) is not a real object in the logs, so
instead of inventing a table for it, ingest.py computes a `step_index` while
walking spans in `(started_at, id)` order. Spans whose operation isn't one of
the three known kinds are kept as `kind = 'other'` rather than dropped, and
every span keeps its raw attribute JSON in `attributes`, so the viewer never
silently hides data. Run-level numbers are aggregated from `spans` at query
time in the `run_totals` view, so they can never disagree with the spans.
`runs.trace_id` is the only real identity and is `UNIQUE`, so loading the same
file twice cannot create a second run; `name` is just a display label.

## Timeline and cost view

The per-run page reads the same steps twice. The timeline lays every span out
as a bar on the run's time axis, so a slow tool call is visible before any
number is read. Above it, the cost view gives each step an input-token and an
output-token bar scaled against the largest step, plus its share of the run's
total — the fastest answer to "where did the tokens go?". Shares are shown in
tokens, not money, for the reason under known limits.

## Diff

`diff.py` compares two runs step by step. Two steps are "the same" when they
made the same tool calls — names **and** arguments, in order — because
`read_file` on two different paths is two different actions; tokens and
durations are never compared, since they never match between runs. After the
first difference the remaining steps are re-aligned with a longest common
subsequence (week 3: dynamic programming) rather than paired by position,
because runs that take different paths usually re-converge — in the sample
data both diff runs finish with the same `run_tests` call and a final answer,
and the diff shows that shared tail as matching. Where one run has a step the
other lacks, the missing side is `None`.

The LCS code has been written three times. The first draft filled a table
bottom-up. The second computed the suffix
lengths with a top-down recursion behind `functools.lru_cache`: lazy, since
it touched only the cells the traceback actually needed, and it read like the
definition of the problem. It also crashed. The recursion costs one Python
stack frame per step, the interpreter gives up near a depth of 1,000, and two
600-step runs with nothing in common raised `RecursionError`. Runs of several
hundred steps are normal for agents, so that was a bug, not a corner case.
The current version goes back to an iterative fill of the whole table from
the end: complete
instead of lazy, slightly less elegant, and indifferent to input size.
`test_align_handles_long_runs` in `tests/test_diff.py` pins the fix.

```bash
python diff.py traces.db run_diff_a run_diff_b   # diverged_at: 2
```

## Known limits (v1)

- Costs are reported in tokens, not money. A per-model price table goes stale;
  tokens are always true.
- `step_index` assumes one agent in one loop. With sub-agents or parallel
  model calls, time order mixes the steps.
- Timestamps are unix **nanoseconds** (~1.8 × 10¹⁸). JS numbers are only exact
  to ~9 × 10¹⁵, so Flask converts to milliseconds before sending them to the
  browser.
- Two spans can share a start time; all ordering (timeline, `step_index`)
  sorts by `(started_at, id)` so it stays stable.
- The diff table needs memory in proportion to steps × steps. Two runs of
  2,000 steps are fine; two runs of 20,000 steps are not.
- `PRAGMA foreign_keys = ON` is per-connection in SQLite, so it lives in
  `ingest.connect()`, not in schema.sql.

## Licence

[MIT](LICENSE).
