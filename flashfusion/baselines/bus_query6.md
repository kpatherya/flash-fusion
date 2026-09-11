You are in plan mode. Do not edit files yet.

Repository: kpatherya/flash-fusion/flashfusion

Task: diagnose and propose the smallest implementation plan to make this Flash-Fusion Bus query execute correctly and deterministically through typed operators:

Query:
“If we group the data into 1-minute intervals, which time window has the highest mean instability score?”

Expected reference result:
“The 1-minute window starting at 2025-06-06 16:01:00 had the highest mean instability score of 5.8690.”

Reference computation:

```python
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df = df.dropna().reset_index(drop=True)

instability_by_minute = (
    df.groupby(pd.Grouper(key="timestamp", freq="1min"))["instability_score"]
      .mean()
      .dropna()
)
q8_bin = instability_by_minute.idxmax()
q8_mean = float(instability_by_minute.max())
```

Current typed plan:

```text
DERIVE_BIN(timestamp, width=60000000000.0, result="minute_window")
→ GROUP_AGGREGATE(group_by=["minute_window"], aggregate="mean",
                  column="instability_score")
→ RANK_GROUPS(max)
```

Current generated execution trace:

```python
df["minute_window"] = (
    df["timestamp"] // 60000000000.0
) * 60000000000.0

result = df.groupby("minute_window")["instability_score"].mean()
result = grouped.idxmax()
result = df["minute_window"].tolist()
```

Observed problems:

1. `DERIVE_BIN` performs generic numeric floor division on `timestamp`, producing fragile/inaccurate temporal behavior and potentially epoch-looking dates such as 1970 timestamps.
2. The grouped aggregate is not preserved as a typed execution artifact; `RANK_GROUPS` appears to rely on an implicit/undefined `grouped` variable.
3. `RANK_GROUPS` returns only the winning key, not the mean value needed for the expected answer.
4. A later operation overwrites the ranked result with all `minute_window` values.
5. The final answer renderer cannot reliably produce both the winning time window and the mean score.
6. The implementation must preserve existing numeric binning behavior for non-temporal columns.

Relevant file:
- `flashfusion/pipeline/operators.py`

Potentially relevant integration files:
- `flashfusion/baselines/flash_fusion.py`
- prompt/template files importing `OPERATOR_VOCABULARY_SPEC`
- operator and baseline tests

Please inspect the actual repository code and return a plan only. Your plan must include:

1. Exact files, symbols, and data models to modify.
2. The minimum schema change to make `DERIVE_BIN` type-aware:
   - temporal mode, e.g., `kind="temporal"` and `freq="1min"`
   - numeric mode retaining width-based binning
   - explicit handling when a timestamp is numeric epoch data versus `datetime64`
   - no silent unit guessing.
3. The exact executor semantics for temporal binning. Prefer behavior equivalent to:
   ```python
   df["minute_window"] = df["timestamp"].dt.floor("1min")
   ```
   when the source is datetime.
4. A minimal execution-state change so `GROUP_AGGREGATE` preserves a typed grouped aggregate result, including group keys, measure name, aggregate type, and grouped `Series`.
5. A minimal `RANK_GROUPS` change so it consumes that grouped result and returns both:
   ```python
   {
       "minute_window": Timestamp(...),
       "mean_instability_score": float(...)
   }
   ```
6. A deterministic tie-breaking policy. Match pandas `idxmax()` behavior if possible; otherwise specify and test a stable policy, preferably earliest window.
7. A guard preventing a later generic operation from overwriting a finalized `RANK_GROUPS` result.
8. The smallest update to `OPERATOR_VOCABULARY_SPEC` that teaches this canonical template:
   ```text
   temporal bin
   → grouped aggregate
   → ranked group output containing both key and aggregate value
   ```
   Do not add a new LLM stage or broad query-rewrite layer.
9. Unit and integration tests, including:
   - the provided timestamp/mean ground-truth case;
   - numeric bin backward compatibility;
   - datetime input with `freq="1min"`;
   - numeric timestamp input requiring an explicit epoch unit;
   - empty/all-null grouped results;
   - tie handling;
   - result schema and final natural-language rendering;
   - assertion that the final plan returns the window and mean rather than a list of all bins.
10. Any `PLAN_VERSION` migration/cache invalidation implications.

Constraints:

- Prefer the Occam’s-razor solution: localized operator/schema/executor/result-rendering changes only.
- Do not add a semantic cache, a new planning stage, or a generic compiler framework.
- Do not rely on another LLM call to repair this query.
- Do not modify source code until the plan is presented and approved.
- Clearly distinguish confirmed facts from assumptions after inspecting the code.