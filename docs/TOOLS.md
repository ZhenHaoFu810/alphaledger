# Tools

Four tools, all namespaced as `mcp__alphaledger__<name>` by the host. The descriptions
below are the ones the model actually sees.

## `fingerprint`

> Identify a factor WITHOUT consuming a trial. Returns the value fingerprint, whether
> the ledger has seen it, and its position if so. Call this before writing new factor
> code to avoid re-testing something already counted.

```json
{"factor": {"path": "f.npz", "key": "factor"}, "forward": {"path": "r.npz"},
 "horizon": 5, "expr": "rank(close/delay(close,20))"}
```

`forward` is required: identity is scoped to the panel, so the same factor tested on a
different universe is a different trial. (An earlier build hashed the factor as if it
were the panel, which made this tool disagree with `evaluate` on every input.)

```json
{"fp": "v1:400df0a53…", "orientation": 1, "seen_before": true, "trial_index": 12,
 "n_evals": 3, "expr_fingerprint": "e1:9a2c…", "note": "fingerprint does not consume a trial"}
```

## `evaluate`

> Measure one factor and record it as a trial. Returns cross-sectional RankIC,
> Newey-West t, single-test p, the trial's index within its family, and the
> family-adjusted verdict. This is the only supported way to produce evidence.

```json
{"factor": {"path": "f.npz"}, "forward": {"path": "r.npz"}, "horizon": 5,
 "alpha": 0.05, "label": "mom_20", "expr": "close/delay(close,20)", "with_gate": true}
```

```json
{"fp": "v1:400df0a53…", "trial_index": 137, "n_family": 200, "n_evals": 1, "created": true,
 "stats": {"n_dates": 250, "ic_mean": 0.0105, "ic_std": 0.0548, "t_iid": 3.03, "t_nw": 3.27,
           "p_single": 0.00274, "skew": -0.11, "kurt": 3.2},
 "gate": {"verdict": "REJECT", "reason_code": "family_not_significant", "p_family": 0.32,
          "bar_q95": 3.67, "n_family": 200, "alpha": 0.05},
 "summary": "Trial #137 of 200 — REJECT. IC=+0.0105, t=3.03, p_single=0.0027. p_family=0.32 > 0.05; needed |t|>3.67, got 3.03."}
```

`forward[t]` must already be shifted: it is the return earned *after* acting on
`factor[t]`. The server never shifts anything.

## `gate`

> Re-judge an already-recorded trial against its family, optionally at a different
> alpha. Use after importing more trials or to ask "how much better would this need to
> be".

```json
{"fp": "v1:400df0a53…", "alpha": 0.01}
```

Returns the same `gate` object plus `required_ic_mean` on a rejection: the IC the
factor would have needed, which is also the honest way to report how strong an edge
this study could have detected at all.

`p_family` is computed for *this* trial's |t| against the family's null distribution
of the maximum. It is not the family's own p-value: a family containing one very
strong factor must not make every later weak trial look significant.

## `ledger_stats`

> How much has been tried, and where the session is going in circles.

```json
{"totals": {"trials": 214, "evaluations": 301},
 "families": [{"panel_id": 1, "horizon": 5, "n_trials": 200, "n_evals": 280}],
 "churn": {"top_reevaluated": [{"fp": "v1:9f…", "n_evals": 9}], "repeated_evaluations": 87,
           "events": {"sign_flip": 3}},
 "cross_family": {"n_families": 3, "effective_alpha": 0.1426}}
```

`effective_alpha` is the thing to read twice: three families at 5% each is a 14% chance
of at least one false positive somewhere.

## Error codes

Errors come back as `isError: true` with a JSON body the agent can branch on.

| code | meaning | what the agent should do |
|---|---|---|
| `PATH_NOT_FOUND` | panel path did not resolve | read `resolved_path` and `cwd` from the error, fix the path |
| `PANEL_SHAPE_MISMATCH` | factor and forward differ | they are (dates × names) and must align exactly |
| `TOO_MANY_INLINE_VALUES` | > 200×200 inline | write the panel to `.npz` and pass a path |
| `BAD_PANEL_REF` | missing/unreadable ref, unknown format, absent npz key | the message lists what is available |
| `UNKNOWN_FP` | `gate` called with a fingerprint not in this ledger | fingerprints are ledger-local |
| `NO_SERIES` | trial has no stored IC series | re-run `evaluate` |
| `INTERNAL_ERROR` | a bug | report it; stderr has the traceback |

Protocol-level errors use standard JSON-RPC codes (`-32700` parse, `-32601` unknown
method, `-32602` bad params). A malformed line does not kill the server.

## Wiring it into a host

Any MCP client works. For DeepSeek Harness, one patch line:

```yaml
- insert:
    - id: alphaledger
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: alphaledger
        transport: stdio
        command: uvx
        args: ['alphaledger-mcp']
        failOnStartupError: true
```

For Claude Code:

```bash
claude mcp add alphaledger -- uvx alphaledger-mcp
```
