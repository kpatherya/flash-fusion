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