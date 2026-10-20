# Method

Every formula here is implemented once, in the function named next to it, and pinned
by the test named after it. If a number in the README disagrees with this document,
this document is right.

## 1. Cross-sectional RankIC

For date *t*, over the names present on that date:

```
IC_t = corr( rank(factor[t, :]), rank(forward[t, :]) )
```

`rank` is the 1-based average rank (ties share the mean of the positions they span).
Dates with fewer than `min_stocks` (default 30) usable names are skipped, not zeroed:
a zero would drag the mean toward zero *and* shrink the standard deviation that the
t-statistic divides by, which is worse than dropping the date.

The IC series is `IC_1 … IC_T`; everything downstream treats it as the unit of
observation.

- Implementation: `stats/ic.py:cross_sectional_rank_ic`, `stats/rank.py:average_rank_int`
- Tests: `tests/test_rank_ic.py::test_ic_matches_a_naive_spearman_on_ranks`,
  `::test_thin_dates_are_nan_not_zero`, `::test_constant_factor_yields_nan_rather_than_zero`

**What this is not.** It is not a time-series correlation of a flattened panel.
Flattening mixes cross-sectional and time-series variation and will report a large
"IC" for a factor that merely trends. The popular shortcut is wrong on panel data and
is the single easiest way to fake a result.

## 2. Significance of one trial

```
t_iid = mean(IC) / (std(IC, ddof=1) / sqrt(T))
p_single = P(|T_{T-1}| >= |t_iid|)          # two-sided, Student-t with T-1 df
```

Two-sided always. IC has no inherent direction — a factor can predict negatively and
be just as real — so a one-sided p-value would silently double the apparent
significance. (For `t = 3.03, T = 250`: two-sided `p = 0.00245`, not `0.00122`.)

Newey-West, with Bartlett kernel and bandwidth `L = max(ceil(4 (T/100)^(2/9)), horizon)`:

```
t_nw = mean(IC) / sqrt( S / T ),   S = γ0 + 2 Σ_{l=1..L} (1 - l/(L+1)) γ_l
```

The `horizon` floor matters: an h-day forward return makes the IC series mechanically
MA(h-1), so a bandwidth below h cuts correlation that exists by construction.

- Implementation: `stats/nw.py:newey_west_t`, `:iid_t`, `:student_t_two_sided_p`
- Tests: `tests/test_nw.py::test_autocorrelation_shrinks_the_t_statistic`,
  `::test_student_t_two_sided_matches_exact_values`

## 3. Identity

```
fp = "v1:" + sha256( ALFP1 | panel_fp | T | (n_valid, int32 doubled_ranks)* )[..32]
```

The hash is over **integer ranks**, never floats, and over the min of the forward and
reversed encodings so that `x` and `-x` collide (with `orientation` recorded
separately). Consequences, each a requirement rather than a nicety:

- `x`, `rank(x)`, `log(exp(x))`, `2x+3` → one trial. They rank identically, so they
  produce identical IC, identical t, identical p. Counting them separately invents
  selection pressure.
- `winsorize(x)` → a *different* trial. Clipping creates ties, ties change average
  ranks, and the IC moves. Two factors correlated at 0.99 are still two draws.
- Near-duplicates are reported (`NEAR_DUPLICATE`, `|corr| > 0.95`) and never merged.
  Merging is the loophole that lets "I only changed one parameter" escape the count.

- Implementation: `identity/value_fp.py:value_fingerprint`
- Tests: `tests/test_identity.py::test_strict_monotone_rewrites_are_one_factor`,
  `::test_winsorising_creates_ties_and_is_therefore_a_different_trial`,
  `::test_sign_flip_is_the_same_trial_with_opposite_orientation`

## 4. The selection threshold

Given the family's IC matrix `IC ∈ R^{T×N}` (one column per trial already in the
ledger for this panel and horizon):

1. Centre each column (impose H0: zero mean IC).
2. Draw `B` circular block bootstrap resamples of the `T` dates, block length
   `L = ceil(T^(1/3))`.
3. For each resample `b` and trial `j`, recompute
   `t*_{b,j} = |mean_b(IC_j)| / (sd_j / sqrt(T))`, where `sd_j` is the *original*
   standard deviation (the standard bootstrap-t correction).
4. `D_b = max_j t*_{b,j}` — the null distribution of the best-of-family statistic.
5. `bar_sigma = mean(D)`, `bar_q95 = quantile(D, 1-α)`,
   `p_family = (1 + #{D_b >= t_obs}) / (B+1)`.

**Why not an effective number of trials.** `N_eff` describes the variance of the
*average* trial; selection is about the *maximum*. Two hundred strategies sharing one
common factor still produce a maximum far into the tail. Measured with N = 200 and
pairwise ρ = 0.3: the spectral estimator says 3.3 independent trials, while the true
95th percentile of the maximum moves only 3.66 → 3.60. Reading a table at `N_eff = 3.3`
would drop the threshold to ≈2.4σ — a 1.5σ giveaway. The bootstrap sidesteps the
question: resampling rows preserves whatever correlation the data has, along with
volatility clustering and fat tails, without modelling any of it.

- Implementation: `stats/maxstat.py:max_stat_null`, `:bootstrap_counts`
- Tests: `tests/test_gate.py::test_threshold_matches_the_theory_of_extremes`,
  `::test_false_positive_rate_is_controlled`, `::test_power_on_a_planted_factor`

## 5. The verdict

| order | condition | verdict |
|---|---|---|
| 1 | `RankIC ≡ 1` on every usable date | `LABEL_CONTAMINATION` |
| 2 | `T < 60` | `INSUFFICIENT_DATA` |
| 3 | `expected_direction` set and the IC's sign differs | `REJECT` |
| 4 | `p_family <= α` | `PASS` |
| 5 | otherwise | `REJECT` |

Contamination outranks significance deliberately: a leaked factor can be arbitrarily
significant, and "PASS" there would be the worst failure the tool is capable of.

Family-wise error control, not FDR. The decision unit is a single factor, so there is
no set of discoveries to take a false-discovery proportion of; and an append-only
ledger never has a closed rejection set, which is what Benjamini-Hochberg requires.
BH q-values are still reported for context.

`direction` is the sign of `ic_mean`. It is not the fingerprint's `orientation`, which
is a bit recording which of the two sign conventions a hash landed on and has no
economic meaning — comparing that bit to an expectation rejected correctly-signed
factors about half the time.

- Implementation: `gate/engine.py:decide`, `:cross_family_alpha`, `:required_ic_mean`
- Tests: `tests/test_gate.py::test_leak_outranks_significance`,
  `::test_direction_mismatch_rejects_even_when_significant`

## 6. What is deliberately not modelled

- **Effective sample size of overlapping returns.** Handled implicitly: the forward
  horizons the caller supplies define the series, and the block bootstrap absorbs the
  autocorrelation that results.
- **Factor standard errors** (the two-pass Fama-MacBeth correction). Out of scope: this
  tool judges *one factor's* IC, not a cross-sectional premium.
- **Full look-ahead perturbation.** v0.2. The identity check catches the accidental
  case (`factor == forward`), which is the common one.
