# Bus Q17-Q20 discrepancy analysis

## Q20: quartile instability ratio

**Classification:** benchmark construction and artifact-synchronization failure, not evidence that both baselines independently failed the same valid task.

The canonical query asked for a multi-stage calculation:

1. Aggregate `accel_mean` and `accel_variance` per minute.
2. Compute quartiles over the derived per-minute variance.
3. Select top and bottom quartiles.
4. Aggregate `instability_score` within those selected minute sets.
5. Return a ratio rounded to two decimals.

The ground-truth builder did none of those operations. Its Q20 code instead derived `vertical_shock`, filtered aggressive rows, grouped into five-minute windows, and ranked the highest mean. Thus the query text and reference answer described different questions. Neither baseline could match that reference by correctly answering the visible query.

The quartile query also exceeds the current closed typed vocabulary. `GROUP_AGGREGATE` creates an internal series consumable only by `RANK_GROUPS` or `AGGREGATE_GROUPS`; it cannot materialize multiple per-minute metrics for a later quartile split. `SPLIT_BY_THRESHOLD` supports mean, median, min, and max, but not quartiles. Flash-Fusion should therefore return `plan: null` for that wording. ReAct can write the pandas operations, but the intended quartile convention (`qcut` versus numeric quantile boundaries and tie handling) still needs to be specified in ground truth.

## Resolution

Q20 is restored to the already validated typed-compatible query: derive vertical shock range, filter aggressive behavior, aggregate in five-minute windows, and return the highest-mean window. This matches the existing builder and staging harness. It tests composition without requiring an unsupported quartile operator.

If quartile analysis is desired as a future benchmark, add a typed quantile/partition operator first and specify boundary and tie semantics before generating its reference answer.

## Other queries

No discrepancy was identified for bus Q17-Q19.
