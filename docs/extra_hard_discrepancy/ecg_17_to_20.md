# MIT ECG Q17-Q20 discrepancy analysis

## Q19: annotated-rate correlation for record 101

**Classification:** Flash-Fusion executor state bug. The generated plan is structurally and semantically reasonable; ReAct's result confirms the reference calculation.

The plan first filtered `record_id == 101`, derived a 10-second bin, and then used `PARALLEL_AGGREGATE` to count annotated and total rows. The old executor started each parallel branch from `state.original`, not the filtered working frame. Consequently, the common record filter was discarded and the correlation was calculated from all 40 records pooled by bin. That produced `0.10596356873844755` instead of the record-101 reference `-0.460485689017`.

This was not a schema-gate failure: both gates passed because they validate structure and column compatibility, not runtime frame lineage. It was also not a missing operator. The existing operators express the query exactly.

## Why ICL alone is insufficient

An ICL workaround could teach the planner to postpone the record filter until after `PARALLEL_AGGREGATE` and include `record_id` in every branch's grouping keys. The validated staging plan used that ordering successfully. However, requiring the model to reorder a logically common prefix filter around an executor implementation detail is brittle.

The core fix is for every parallel branch to fork from the same working frame at operator entry. Branches remain independent from one another, but all shared preceding filters and derivations are preserved. A regression test now covers this exact state transition, and the planner contract documents it.

## Other queries

No discrepancy was identified for Q17, Q18, or Q20. Their plans do not depend on preserving a common row filter before `PARALLEL_AGGREGATE`.

# Adversarial re-wording strategy (2026-09-15)

Q17 was deliberately reworded to probe the planner rather than the executor, using the same router-exclusion mechanism confirmed for WISDM Q19 (see `wisdm_17_to_20.md`).

## Q17: router-exclusion trap (temporal binning)

Original wording used explicit binning vocabulary ("bins", "second"), which kept the `derive` operator bucket (and thus `DERIVE_BIN`) in the candidate vocabulary. The rewrite —

> "Among rows whose annotation is one of the known MIT-ECG annotation codes, partition each record_id's time_s values into consecutive groups of width 10. For each group, compute MLII RMS. Return the group with the greatest RMS."

— avoids every `DERIVE_CUES` token (`bin*`, `bucket*`, `window*`, `interval*`, `second*`, ...) while keeping `GROUPING_CUES` ("each") so `GROUP_RANK`/`PARALLEL` stay available. Confirmed directly against `route_operator_bucket`:

```
excluded= ('correlation', 'derive', 'partition_compare', 'predictive')
```

With `DERIVE_BIN` unavailable, the planner has no operator to materialize the width-10 grouping key the query asks for. It either drops the windowing requirement and groups by `record_id` alone, or attempts an operator the closed vocabulary does not have (both are logged as `log_operator_gap` candidates if they reach Gate 1/Gate 2). No ground-truth computation change was needed — the intended correct answer is unchanged (group by `record_id` + 10-wide bin, matching the pre-rewrite Q17 reference answer); only the query wording changed to create the trap.