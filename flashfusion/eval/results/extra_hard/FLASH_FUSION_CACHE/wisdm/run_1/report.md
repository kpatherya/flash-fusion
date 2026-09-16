# Flash-Fusion Benchmark Report

Generated: 2026-09-15T23:10:25+00:00

## Summary Table

| Baseline           |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-------------------|-------------------:|------------------:|-----------------:|
| FLASH_FUSION_CACHE |             0.5000 |            9.6708 |           0.0022 |

## Typed-Operator Coverage

| Baseline           |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:-------------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FLASH_FUSION_CACHE |         4 |       3 | 75%        |                0 |                  0 |                   10.26 | -                          |

Fallback causes: structural=1

## Per-Query Results

### Q20: For every subject_id, derive elapsed seconds from timestamp, then compute total locomotion duration (Walking, Jogging, Upstairs, Downstairs) and total resting duration (Sitting, Standing). Among subjects with more locomotion than resting time, return the subject_id with the largest locomotion-minus-resting duration.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'subject_id': 19, 'locomotion_duration': 131357.35168599998, 'resting_duration': 266.179779, 'duration_delta': 131091.17190699998}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,DERIVE_DURATION_SECONDS,PARALLEL_AGGREGATE,DERIVE_BINARY,FILTER_COMPARE,RANK_ROWS
- Latency: 10.64s | Cost: $0.00266

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_NOT_EMPTY)
Action: typed_operator_exec
Action Input: df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
Observation: rows=1098198
Thought: typed operator step 2 (DERIVE_DURATION_SECONDS)
Action: typed_operator_exec
Action Input: df = df.sort_values(['subject_id', 'timestamp']); df['dt_s'] = df.groupby(['subject_id'])['timestamp'].diff().dt.total_seconds().clip(lower=0).fillna(0.0)
Observation: derived 'dt_s' (rows=1098198, total=841190.608454s)
Thought: typed operator step 3 (PARALLEL_AGGREGATE)
Action: typed_operator_exec
Action Input: # PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['dt_s'].sum()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['dt_s'].sum()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
merged[['locomotion_duration', 'resting_duration']] = merged[['locomotion_duration', 'resting_duration']].fillna(0)
Observation: {'groups': 36, 'columns': ['subject_id', 'locomotion_duration', 'resting_duration']}
Thought: typed operator step 4 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['duration_delta'] = df['locomotion_duration'] - df['resting_duration']
Observation: derived 'duration_delta' (rows=36)
Thought: typed operator step 5 (FILTER_COMPARE)
Action: typed_operator_exec
Action Input: df = df[df['duration_delta'] > 0]
Observation: rows=33
Thought: typed operator step 6 (RANK_ROWS)
Action: typed_operator_exec
Action Input: idx = df['duration_delta'].idxmax(); result = df.loc[idx, ['subject_id', 'locomotion_duration', 'resting_duration', 'duration_delta']].to_dict()
Observation: {'subject_id': 19, 'locomotion_duration': 131357.35168599998, 'resting_duration': 266.179779, 'duration_delta': 131091.17190699998}
Final Answer: {'subject_id': 19, 'locomotion_duration': 131357.35168599998, 'resting_duration': 266.179779, 'duration_delta': 131091.17190699998}
```

**Final Code Executed**

```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df = df.sort_values(['subject_id', 'timestamp']); df['dt_s'] = df.groupby(['subject_id'])['timestamp'].diff().dt.total_seconds().clip(lower=0).fillna(0.0)
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['dt_s'].sum()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['dt_s'].sum()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
merged[['locomotion_duration', 'resting_duration']] = merged[['locomotion_duration', 'resting_duration']].fillna(0)
df['duration_delta'] = df['locomotion_duration'] - df['resting_duration']
df = df[df['duration_delta'] > 0]
idx = df['duration_delta'].idxmax(); result = df.loc[idx, ['subject_id', 'locomotion_duration', 'resting_duration', 'duration_delta']].to_dict()
```

---

### Q19: For every subject_id, compute mean acceleration magnitude while Jogging and while Walking. Report whether subjects who jog harder also walk harder, ranking subjects consistently across both activities.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'subject_id': 23, 'mean_jogging_magnitude': 17.04236300315029, 'mean_walking_magnitude': 12.89231971710706}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,DERIVE_VECTOR_MAGNITUDE,PARALLEL_AGGREGATE,RANK_ROWS
- Latency: 11.42s | Cost: $0.00209

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_NOT_EMPTY)
Action: typed_operator_exec
Action Input: df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
Observation: rows=1098198
Thought: typed operator step 2 (DERIVE_VECTOR_MAGNITUDE)
Action: typed_operator_exec
Action Input: df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
Observation: derived 'acceleration_magnitude' (rows=1098198)
Thought: typed operator step 3 (PARALLEL_AGGREGATE)
Action: typed_operator_exec
Action Input: # PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
Observation: {'groups': 36, 'columns': ['subject_id', 'mean_jogging_magnitude', 'mean_walking_magnitude']}
Thought: typed operator step 4 (RANK_ROWS)
Action: typed_operator_exec
Action Input: idx = df['mean_jogging_magnitude'].idxmax(); result = df.loc[idx, ['subject_id', 'mean_jogging_magnitude', 'mean_walking_magnitude']].to_dict()
Observation: {'subject_id': 23, 'mean_jogging_magnitude': 17.04236300315029, 'mean_walking_magnitude': 12.89231971710706}
Final Answer: {'subject_id': 23, 'mean_jogging_magnitude': 17.04236300315029, 'mean_walking_magnitude': 12.89231971710706}
```

**Final Code Executed**

```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
idx = df['mean_jogging_magnitude'].idxmax(); result = df.loc[idx, ['subject_id', 'mean_jogging_magnitude', 'mean_walking_magnitude']].to_dict()
```

---

### Q18: For every subject_id, compute x-acceleration variance separately while Jogging and while Walking. Return the subject_id for whom Jogging pulls furthest ahead of Walking.

#### FLASH_FUSION_CACHE

**Answer:** 

- Executed: False | Rejected: False | Judge: N/A
- Stages: hybrid_semantic_ambiguous_candidates,cache_miss_or_validation_failure,guardrail_plan,typed_plan_unavailable
- Path: typed_plan_unavailable
- Fallback (structural): structural: 1 validation error for GuardrailAndPlan
plan.steps.2.DERIVE_BINARY.operation
  Input should be 'add', 'subtract', 'multiply', 'divide' or 'abs_difference' [type=literal_error, input_value='difference', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/literal_error
- Latency: 7.92s | Cost: $0.00173

**Alignment Explanation**

Flash-Fusion could not produce a valid typed plan and ReAct fallback is disabled. Reason: structural: 1 validation error for GuardrailAndPlan
plan.steps.2.DERIVE_BINARY.operation
  Input should be 'add', 'subtract', 'multiply', 'divide' or 'abs_difference' [type=literal_error, input_value='difference', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/literal_error

---

### Q17: For every subject_id, compute mean acceleration magnitude separately for dynamic activities (Walking, Jogging, Upstairs, Downstairs) and resting activities (Sitting, Standing). Return the subject_id with the largest dynamic-minus-resting mean magnitude.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'subject_id': 24, 'dynamic_mean_mag': 13.872703393647935, 'resting_mean_mag': 9.133463315662746, 'mean_mag_difference': 4.739240077985189}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,DERIVE_VECTOR_MAGNITUDE,PARALLEL_AGGREGATE,DERIVE_BINARY,RANK_ROWS
- Latency: 8.70s | Cost: $0.00230

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_NOT_EMPTY)
Action: typed_operator_exec
Action Input: df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
Observation: rows=1098198
Thought: typed operator step 2 (DERIVE_VECTOR_MAGNITUDE)
Action: typed_operator_exec
Action Input: df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
Observation: derived 'acceleration_magnitude' (rows=1098198)
Thought: typed operator step 3 (PARALLEL_AGGREGATE)
Action: typed_operator_exec
Action Input: # PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
Observation: {'groups': 36, 'columns': ['subject_id', 'dynamic_mean_mag', 'resting_mean_mag']}
Thought: typed operator step 4 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['mean_mag_difference'] = df['dynamic_mean_mag'] - df['resting_mean_mag']
Observation: derived 'mean_mag_difference' (rows=36)
Thought: typed operator step 5 (RANK_ROWS)
Action: typed_operator_exec
Action Input: idx = df['mean_mag_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_mag', 'resting_mean_mag', 'mean_mag_difference']].to_dict()
Observation: {'subject_id': 24, 'dynamic_mean_mag': 13.872703393647935, 'resting_mean_mag': 9.133463315662746, 'mean_mag_difference': 4.739240077985189}
Final Answer: {'subject_id': 24, 'dynamic_mean_mag': 13.872703393647935, 'resting_mean_mag': 9.133463315662746, 'mean_mag_difference': 4.739240077985189}
```

**Final Code Executed**

```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['mean_mag_difference'] = df['dynamic_mean_mag'] - df['resting_mean_mag']
idx = df['mean_mag_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_mag', 'resting_mean_mag', 'mean_mag_difference']].to_dict()
```

---
