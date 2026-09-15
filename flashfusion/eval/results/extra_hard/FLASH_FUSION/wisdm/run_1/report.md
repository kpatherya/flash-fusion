# Flash-Fusion Benchmark Report

Generated: 2026-09-15T20:30:08+00:00

## Summary Table

| Baseline     |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-------------|-------------------:|------------------:|-----------------:|
| FLASH_FUSION |             1.0000 |            6.4755 |           0.0023 |

## Typed-Operator Coverage

| Baseline     |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:-------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FLASH_FUSION |         4 |       4 | 100%       |                0 |                  0 |                    6.48 | -                          |

## Per-Query Results

### Q17: For every subject_id, compute mean acceleration magnitude separately for dynamic activities (Walking, Jogging, Upstairs, Downstairs) and resting activities (Sitting, Standing). Return the subject_id with the largest dynamic-minus-resting mean magnitude.

#### FLASH_FUSION

**Answer:** The result is {'subject_id': 24, 'dynamic_mean_magnitude': 13.872703393647935, 'resting_mean_magnitude': 9.133463315662746, 'magnitude_difference': 4.739240077985189}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,DERIVE_VECTOR_MAGNITUDE,PARALLEL_AGGREGATE,DERIVE_BINARY,RANK_ROWS
- Latency: 6.57s | Cost: $0.00223

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
Observation: {'groups': 36, 'columns': ['subject_id', 'dynamic_mean_magnitude', 'resting_mean_magnitude']}
Thought: typed operator step 4 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['magnitude_difference'] = df['dynamic_mean_magnitude'] - df['resting_mean_magnitude']
Observation: derived 'magnitude_difference' (rows=36)
Thought: typed operator step 5 (RANK_ROWS)
Action: typed_operator_exec
Action Input: idx = df['magnitude_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_magnitude', 'resting_mean_magnitude', 'magnitude_difference']].to_dict()
Observation: {'subject_id': 24, 'dynamic_mean_magnitude': 13.872703393647935, 'resting_mean_magnitude': 9.133463315662746, 'magnitude_difference': 4.739240077985189}
Final Answer: {'subject_id': 24, 'dynamic_mean_magnitude': 13.872703393647935, 'resting_mean_magnitude': 9.133463315662746, 'magnitude_difference': 4.739240077985189}
```

**Final Code Executed**

```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['magnitude_difference'] = df['dynamic_mean_magnitude'] - df['resting_mean_magnitude']
idx = df['magnitude_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_magnitude', 'resting_mean_magnitude', 'magnitude_difference']].to_dict()
```

---

### Q18: For every subject_id, compute x-acceleration variance separately while Jogging and while Walking. Among subject_id values whose Jogging variance exceeds their Walking variance, return the subject_id with the largest Jogging-minus-Walking variance difference.

#### FLASH_FUSION

**Answer:** The result is {'subject_id': 31, 'jogging_var': 109.50167848631395, 'walking_var': 7.69762219970115, 'var_diff': 101.8040562866128}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,PARALLEL_AGGREGATE,DERIVE_BINARY,FILTER_COMPARE,RANK_ROWS
- Latency: 6.10s | Cost: $0.00226

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_NOT_EMPTY)
Action: typed_operator_exec
Action Input: df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
Observation: rows=1098198
Thought: typed operator step 2 (PARALLEL_AGGREGATE)
Action: typed_operator_exec
Action Input: # PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['x'].var()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['x'].var()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
Observation: {'groups': 36, 'columns': ['subject_id', 'jogging_var', 'walking_var']}
Thought: typed operator step 3 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['var_diff'] = df['jogging_var'] - df['walking_var']
Observation: derived 'var_diff' (rows=36)
Thought: typed operator step 4 (FILTER_COMPARE)
Action: typed_operator_exec
Action Input: df = df[df['var_diff'] > 0]
Observation: rows=30
Thought: typed operator step 5 (RANK_ROWS)
Action: typed_operator_exec
Action Input: idx = df['var_diff'].idxmax(); result = df.loc[idx, ['subject_id', 'jogging_var', 'walking_var', 'var_diff']].to_dict()
Observation: {'subject_id': 31, 'jogging_var': 109.50167848631395, 'walking_var': 7.69762219970115, 'var_diff': 101.8040562866128}
Final Answer: {'subject_id': 31, 'jogging_var': 109.50167848631395, 'walking_var': 7.69762219970115, 'var_diff': 101.8040562866128}
```

**Final Code Executed**

```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['x'].var()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['x'].var()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['var_diff'] = df['jogging_var'] - df['walking_var']
df = df[df['var_diff'] > 0]
idx = df['var_diff'].idxmax(); result = df.loc[idx, ['subject_id', 'jogging_var', 'walking_var', 'var_diff']].to_dict()
```

---

### Q19: For every subject_id, compute mean acceleration magnitude while Jogging and while Walking. Return the Pearson correlation between the two per-subject mean-magnitude columns.

#### FLASH_FUSION

**Answer:** The result is 0.7491948405475501

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,DERIVE_VECTOR_MAGNITUDE,PARALLEL_AGGREGATE,CORRELATE_COLUMNS
- Latency: 5.30s | Cost: $0.00213

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
Thought: typed operator step 4 (CORRELATE_COLUMNS)
Action: typed_operator_exec
Action Input: result = df['mean_jogging_magnitude'].corr(df['mean_walking_magnitude'], method='pearson')
Observation: 0.7491948405475501
Final Answer: 0.7491948405475501
```

**Final Code Executed**

```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
result = df['mean_jogging_magnitude'].corr(df['mean_walking_magnitude'], method='pearson')
```

---

### Q20: For every subject_id, derive elapsed seconds from timestamp, then compute total locomotion duration (Walking, Jogging, Upstairs, Downstairs) and total resting duration (Sitting, Standing). Among subjects with more locomotion than resting time, return the subject_id with the largest locomotion-minus-resting duration.

#### FLASH_FUSION

**Answer:** The result is {'subject_id': 19, 'locomotion_duration': 131357.35168599998, 'resting_duration': 266.179779, 'duration_delta': 131091.17190699998}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_NOT_EMPTY,DERIVE_DURATION_SECONDS,PARALLEL_AGGREGATE,DERIVE_BINARY,FILTER_COMPARE,RANK_ROWS
- Latency: 7.94s | Cost: $0.00256

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
