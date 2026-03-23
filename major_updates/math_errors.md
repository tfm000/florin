# Mathematical/Statistical Code Issues

These issues were identified during the Phase 1 codebase audit. Per project rules, no changes
have been made to mathematical or statistical code. These are documented for review and
approval before any fixes are implemented.

## stats/core.py

### 1. Log returns with zero prices (line ~104)
- `np.log(ratios)` where ratios contain 0 creates `-inf`
- Current mitigation: `result[~np.isfinite(result)] = np.nan` replaces infinities
- **Assessment:** Acceptable edge case handling, but could mask data quality issues

### 2. Sharpe ratio with zero volatility (line ~140-143)
- If `std <= 0`, returns 0.0 instead of NaN
- **Risk:** Returns 0.0 for a risk-free asset (which technically has undefined Sharpe ratio)
- **Suggestion:** Consider returning NaN or documenting that 0.0 means "undefined"

### 3. Max drawdown division by zero (line ~201)
- `(peaks - prices) / peaks` could divide by zero if peaks contain 0
- Not explicitly guarded; relies on input data always having positive prices
- **Suggestion:** Guard against zero peaks

## stats/parametric.py

### 1. Arbitrary clipping constant (line ~71)
- Log excess returns clipped at `1e-10` to prevent `log(0)`
- The constant `1e-10` is arbitrary and could distort ratio calculations for very small values
- **Suggestion:** Document the choice or make it configurable

### 2. Student-t VaR extreme tails (line ~103-106)
- Fitted Student-t PPF can produce extreme values with small sample sizes
- Heavy tails could generate unrealistic VaR estimates
- Sample clipping at line 37-38 partially constrains this
- **Suggestion:** Add a sanity check on VaR output (e.g., should not exceed -100%)

## stats/regime.py

### 1. Regime relabeling by volatility (line ~93-99)
- Regimes are relabeled by ascending volatility, which is correct
- **Assessment:** No issue — implementation correctly maps old→new indices

## stats/risk_free.py

### 1. Business day approximation (line ~164-166)
- `(d_end - d_start).days * 5 // 7` is an approximation
- Actual business days could differ by 1-2 days due to holidays
- Used for 60% coverage threshold — margin of error is acceptable
- **Assessment:** Acceptable approximation for its use case

### 2. Fixed day count basis per currency (line ~300)
- Hardcoded basis (ACT/360, ACT/365) per currency
- Doesn't account for historical changes in day count conventions
- **Assessment:** Reasonable simplification for simple overnight rates

### 3. Non-atomic upsert (line ~373-394)
- `select()` then `add()` is not atomic; race condition possible with concurrent inserts
- Could create duplicate rows, though SQLite's transaction model provides some protection
- **Note:** This is more of a concurrency issue than a math issue, but it affects rate data integrity
