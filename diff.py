"""Diff two runs step by step: which tool calls match, and where they diverge.

AI citation: drafted with Claude (Anthropic); the three diff decisions
(sameness = tool names + arguments, LCS re-alignment, None padding) chosen
by Nuri.

A step's identity is what the agent did: its tool calls, as (name, arguments)
pairs, in order. Tokens and durations never match between two runs, so they
are not compared. After the first difference the remaining steps are
re-aligned with a longest-common-subsequence (week 3: dynamic programming)
rather than paired by position, because runs that take different paths often
re-converge — run_diff_a and run_diff_b both finish with the same run_tests
call and a final answer, and the diff should show that shared tail as
matching instead of marking everything after the divergence as different.
Where one run has a step the other lacks, the missing side is None.

CLI check:  python diff.py traces.db run_diff_a run_diff_b
"""
import json
import sys
from itertools import zip_longest

from steps import load_steps


def diff_runs(db, run_id_a, run_id_b):
    """Return {"diverged_at": first differing step index or None,
               "rows": [{"a": step_or_None, "b": step_or_None, "same": bool}, ...]}.

    Raises ValueError when either run id does not exist.
    """
    rows = _align(load_steps(db, run_id_a), load_steps(db, run_id_b))
    diverged_at = None
    for row in rows:
        if not row["same"]:
            diverged_at = (row["a"] or row["b"])["index"]
            break
    return {"diverged_at": diverged_at, "rows": rows}


def _signature(step):
    """What makes two steps "the same": their tool calls, not their cost."""
    return tuple((t["name"], _canonical(t["arguments"])) for t in step["tools"])


def _canonical(arguments):
    """Compare arguments as JSON, so key order and whitespace do not matter."""
    try:
        return json.dumps(json.loads(arguments), sort_keys=True)
    except (TypeError, ValueError):
        return arguments


def _align(a, b):
    """Pair the two step lists on their longest common subsequence.

    Steps on the LCS become same=True rows. The stretches between two
    matches are paired by position, and the longer side's extra steps get
    None on the other side.
    """
    sig_a = [_signature(s) for s in a]
    sig_b = [_signature(s) for s in b]
    return _build_rows(a, b, _match_pairs(sig_a, sig_b))


def _match_pairs(sig_a, sig_b):
    """Index pairs (i, j) of a longest common subsequence of the two
    signature lists. Ties skip an a-step first, so a's extra steps land
    ahead of b's inside the gaps."""
    # suffix[i][j] = length of the LCS of sig_a[i:] and sig_b[j:].
    # Filled iteratively: the recursive version was one stack frame per
    # step and overflowed on runs of more than ~500 steps each.
    suffix = [[0] * (len(sig_b) + 1) for _ in range(len(sig_a) + 1)]
    for i in reversed(range(len(sig_a))):
        for j in reversed(range(len(sig_b))):
            if sig_a[i] == sig_b[j]:
                suffix[i][j] = 1 + suffix[i + 1][j + 1]
            else:
                suffix[i][j] = max(suffix[i + 1][j], suffix[i][j + 1])

    pairs = []
    i = j = 0
    while i < len(sig_a) and j < len(sig_b):
        if sig_a[i] == sig_b[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif suffix[i + 1][j] >= suffix[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def _build_rows(a, b, pairs):
    """Interleave a same=True row per matched pair with the gap before
    it, each gap paired off by position with None on the short side."""
    rows = []
    start_a = start_b = 0
    # The sentinel pair past both ends flushes the trailing gap.
    for i, j in [*pairs, (len(a), len(b))]:
        for step_a, step_b in zip_longest(a[start_a:i], b[start_b:j]):
            rows.append({"a": step_a, "b": step_b, "same": False})
        if i < len(a):
            rows.append({"a": a[i], "b": b[j], "same": True})
        start_a, start_b = i + 1, j + 1
    return rows


def _resolve(db, ref):
    """A run id, or the newest run with this display name."""
    if ref.isdigit():
        return int(ref)
    row = db.execute(
        "SELECT id FROM runs WHERE name = ? ORDER BY started_at DESC, id DESC "
        "LIMIT 1", (ref,)).fetchone()
    if row is None:
        raise ValueError(f"no run named {ref!r}")
    return row["id"]


def _cell(step):
    if step is None:
        return "-"
    return f"step {step['index']}: " + (", ".join(step["tool_names"]) or "(no tools)")


if __name__ == "__main__":
    import ingest

    if len(sys.argv) != 4:
        sys.exit("Usage: python diff.py DATABASE RUN_A RUN_B   (run id or name)")
    db = ingest.connect(sys.argv[1])
    result = diff_runs(db, _resolve(db, sys.argv[2]), _resolve(db, sys.argv[3]))
    print("diverged_at:", result["diverged_at"])
    for row in result["rows"]:
        mark = "=" if row["same"] else "!"
        print(f"  {_cell(row['a']):40} {mark}  {_cell(row['b'])}")
