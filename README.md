# alphaledger

**A trial ledger for factor research.** Every factor you evaluate is a draw from a
lottery; alphaledger counts the draws, and it will not judge one without knowing how
many came before it.

## The 20-second version

One command, on a panel of 300 names × 250 dates where **every factor is pure noise**:

```
$ python demos/noise_200.py

  best factor     fp=v1:32625af66…
  RankIC          +0.0105
  t (iid / NW)    3.03 / 3.27
  p_single        0.00273   <- looks publishable
  family          200 trials
  bar_q95         3.73      <- what a real factor needed
  p_family        0.351     <- it is luck
  verdict         REJECT

  "Trial #200 of 200 — REJECT. IC=+0.0105, t=3.03, p_single=0.0027, p_family=0.351."
```

A RankIC of 1% is an ordinary magnitude for a real factor, so the size of the effect
cannot tell you whether it is real. **The only discriminating information is how many
times you drew.** A researcher tests five ideas a day and remembers them. An agent
tests two hundred an hour and starts each session with no memory of the last.

## Why not just another toolbox

The existing tools are good at *computing*: 59 tools here, 40 there, IC/ICIR/backtest
everywhere. What none of them has is **state** — they are functions, and a function
cannot tell you that this is the 137th variant of momentum you have tried.

alphaledger is the other thing: a ledger with four tools on top. It refuses to give a
verdict without counting the family, and the count comes from the ledger, never from
the caller. [`docs/AUDIT.md`](docs/AUDIT.md) walks through the three existing
implementations this is positioned against, with line numbers.

## Install

```bash
uvx alphaledger-mcp          # any MCP client can launch it
```

Claude Code:

```bash
claude mcp add alphaledger -- uvx alphaledger-mcp
```

DeepSeek Harness — one patch line in `$DSH_HOME/profiles/<name>/cordis.patch.yml`:

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

Tools then appear as `mcp__alphaledger__evaluate` and friends. No API keys, no network
calls, no data leaves the machine. numpy and the standard library only — scipy would
double the install and add seconds to a cold start.

## The four tools

| tool | what it answers |
|---|---|
| `fingerprint` | Have I tried this factor before? (does not consume a trial) |
| `evaluate` | What is its RankIC, and what is its trial number? |
| `gate` | Does it survive the family correction — and how far off was it? |
| `ledger_stats` | How much have I tried, and where am I going in circles? |

A `PASS` requires `p_family <= alpha`. `p_single` is reported and is never evidence.

## Three things the ledger refuses to do

**It will not count `rank(x)` as a new factor.** Identity is the factor's rank pattern,
hashed as integers, so `x`, `rank(x)`, `log(x)` and `2x+3` are one trial with four
evaluations. Flipping the sign is the same trial too — recorded as a `sign_flip`, the
most common way a family quietly grows.

**It will not merge near-duplicates.** Two factors correlating at 0.97 are reported as
`NEAR_DUPLICATE` and left alone. Merging them would let "I only changed one parameter"
escape the count, which is the whole problem.

**It will not pass a leaked factor.** A factor ranked identically to the forward return
is `LABEL_CONTAMINATION` — checked before significance, because that is the one case
where the numbers look best.

## What it does not do

No data layer (feed it a panel; an akshare adapter is planned), no backtest engine, no
portfolio construction, no UI. It judges one factor's IC series and keeps the books.

## Docs

- [`docs/METHOD.md`](docs/METHOD.md) — every formula, with the function and the test that pins it
- [`docs/TOOLS.md`](docs/TOOLS.md) — schemas, error codes, host wiring
- [`docs/AUDIT.md`](docs/AUDIT.md) — the three existing implementations, read at source level
- [`docs/CALIBRATION.md`](docs/CALIBRATION.md) — measured false-positive rate and power

## Status

0.1.0. Statistics, identity, ledger and the MCP surface are implemented and tested
(91 tests). The akshare adapter, the OOS test lock and the full perturbation protocol
are v0.2.

## License

MIT
