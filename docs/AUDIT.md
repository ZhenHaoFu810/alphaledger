# Audit: three existing dsh quant tools

Read at source level on 2026-10-20. All three are real projects with real work in
them; the point of this document is not that they are bad, it is to locate precisely
what none of them does. Line numbers refer to the commits that were current that day.

Summary:

| | `helibeiqi/dsh-quant-factor-pipeline` | `Rtyyy233/dsh-factor-mining-plugin` | `pengpengyi92/dsh-quant` |
|---|---|---|---|
| form | MCP server, 1 file, 1167 lines | Python engine + 4 TS packages | plugin, 59 tools, 3091-line index |
| IC | cross-sectional Spearman, per date | cross-sectional, per horizon | **time-series Pearson on a flattened panel** |
| look-ahead | none | noise + NaN perturbation, mandatory | a ">50% step" heuristic |
| OOS lock | none | 60/20/20, one-shot lock, claim file | none |
| multiple testing | **none** | E[max\|X\|] + moment-corrected p, hard gate | deflated Sharpe, but `numTrials` typed in by hand |
| cross-session ledger | overwritten YAML | append-only `trail_engine.json`, internal | none (stateless) |

## 1. The "IC/5 gates" are four data filters and one threshold

`quant-mcp-server.mjs:731-780`. `grep -c gate` returns four hits and none of them is a
gate. What `ic_gate` actually does:

```js
if (s.data.length < 252)      { droppedAge++;     continue; }   // history filter
if (!built)                   { droppedTurnover++; continue; }  // turnover missing -> drop
if (!(amount > 1e8))          continue;                          // liquidity
if (!(price > 3))             continue;                          // penny stock
...
const verdict = (isFinite(rankic) && rankic > 0 && isFinite(nw_t) && Math.abs(nw_t) > 2.0)
  ? 'PASS' : 'REJECT';
```

So: four universe filters plus `rankic > 0 && |NW t| > 2`. There is **no notion of how
many factors have been tested**. `|t| > 2` on a factor chosen from a field of 200 is
not a 5% test; it is roughly a coin flip (see `METHOD.md` §4). Nothing in the project
records that the field had 200 members.

It does do one thing right: an empty cross-section returns `INSUFFICIENT_DATA` rather
than `REJECT` (`:711-722`). Several tools conflate "no data" with "no effect".

Persistence is an overwritten snapshot (`:1060-1067`): `fs.writeFileSync(file, yamlDump(project))`.
The `params_hash` field looks like identity but is metadata; re-running the same factor
twice leaves no trace of the second run.

## 2. The most complete engine in the field — and its hardest-won lesson

`Rtyyy233/dsh-factor-mining-plugin` is the serious one. Two independent leak detectors
before any evaluation (`factor/causality.py:59-132`): replace data after `t0` with
scaled noise and check that the output before `t0` is unchanged; then replace it with
NaN and check that the output before `t0` did not become NaN. The second catches
`shift(-1)`-style direct indexing, which the first can miss. A leak verdict is
`FUTURE_LEAK` and the evaluation does not count as a trial — correct, because a leaked
factor was never a hypothesis.

Its test lock (`bridge.py:5065-5117`) tracks `consumed`, a `claim.pid` against
concurrent use, and only lets registered hashes through. Trial counting is by
`(source_hash, horizon)` deduplication (`:3699-3745`), not by a counter the user keeps.

And then the important part. In `factor/gates.py` the gate parameter is not `n_trials`:

```python
denom = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr
sr0, _ = dsr_sr0(bar_sigma, pool_std)      # sr0 = E[max|X|] * pool_std
t_stat = (abs(sr) - sr0) * (n - 1) ** 0.5 / denom ** 0.5
```

The author's notes record a comparison against 74 real trails: estimating an effective
count spectrally and feeding it to the Bailey–López de Prado deflated Sharpe **under-
estimates selection luck by 3.4×**, and that path was abandoned. `n_trials` survives
only as telemetry. That finding is why alphaledger bootstraps the maximum instead of
estimating `N_eff`; see `METHOD.md` §4 for the replication of the mechanism.

What it does not do: expose any of this. Forty tools, an 18 KB `SKILL.md`, and a
`stateRoot` the tools are welded to. The ledger exists but cannot be queried, compared
or merged.

## 3. A time-series IC on panel data

`pengpengyi92/dsh-quant` is the widest (59 tools) and the only one packaged for
discovery (npm 0.90.0, catalog entry, CI). Its IC is

```ts
// src/dsh-alpha/factor.ts:118-122
const { f, r } = lagPair(factorValues, forwardReturns)   // factor[i] vs ret[i+1]
const ic = pearson(f, r)
const rankIc = spearman(f, r)                            // over the flattened series
```

and `lagPair` (`:64-66`) does `Math.min(factor.length, forwardReturns.length) - 1` with
no date and no asset axis. On a panel, this mixes cross-sectional and time-series
variation: a factor that merely trends upward alongside the market will report a large
"IC" with no cross-sectional information at all. This is the single most consequential
difference between it and the other two.

Its deflated Sharpe implementation is correct — Bailey–López de Prado with moment
corrections — but the trial count is an argument the caller supplies:

```ts
// src/index.ts:1709
numTrials: { type: 'integer', description: 'Number of trials/parameter-combinations tried (default 1)' }
// deflated-sharpe.ts:77-79
if (numTrials === 1) eMaxSharpe = 0        // default = no deflation
```

A model that has just evaluated a hundred variants can pass `numTrials: 1` and the
correction disappears. Worse, DSR lives in `dsh-ml/` and IC in `dsh-alpha/`: nothing
connects a factor's evaluation to a trial count. The numbers exist; the link does not.

## 4. What this leaves

None of the three answers the question the ledger exists to answer: *how many draws
have been taken on this data, by anyone, across sessions, and what does that do to the
threshold?*

- A has no count at all.
- B has a count, but it is internal to one engine and unreachable from outside.
- C has the machinery for a count and asks the user for it.

alphaledger's whole contribution is making that count a first-class, queryable,
mergeable object — and refusing to produce a verdict without it.
