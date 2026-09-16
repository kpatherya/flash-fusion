# Flash-Fusion Benchmark Report

Generated: 2026-09-15T23:09:17+00:00

## Summary Table

| Baseline           |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-------------------|-------------------:|------------------:|-----------------:|
| FLASH_FUSION_CACHE |             0.7500 |            9.0229 |           0.0027 |

## Typed-Operator Coverage

| Baseline           |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:-------------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FLASH_FUSION_CACHE |         4 |       4 | 100%       |                0 |                  0 |                    9.02 | -                          |

## Per-Query Results

### Q19: For every 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and Determine its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'higher': 'aggressive', 'lower': 'calm', 'aggressive': 5.0055000000000005, 'calm': 1.291285714285714, 'aggressive_metric': 'aggressive_shock_range mean', 'calm_metric': 'calm_shock_range mean', 'difference': 3.7142142857142866}

- Executed: True | Rejected: False | Judge: N/A
- Stages: hybrid_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_BIN,PARALLEL_AGGREGATE,DERIVE_BINARY,DERIVE_BINARY,AGGREGATE_COLUMN,AGGREGATE_COLUMN,COMPARE_VALUES
- Latency: 12.75s | Cost: $0.00384

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_BIN)
Action: typed_operator_exec
Action Input: df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
Observation: derived 'timestamp_5min' (kind=temporal freq='5min' source=datetime)
Thought: typed operator step 2 (PARALLEL_AGGREGATE)
Action: typed_operator_exec
Action Input: # PARALLEL_AGGREGATE branches:
branch_0 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['accel_stats_z_p99'].mean()
branch_1 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['accel_stats_z_p1'].mean()
branch_2 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['accel_stats_z_p99'].mean()
branch_3 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['accel_stats_z_p1'].mean()
merged = branch_0.merge(branch_1, on=['timestamp_5min'], how='outer')
Observation: {'groups': 9, 'columns': ['timestamp_5min', 'aggressive_p99', 'aggressive_p1', 'calm_p99', 'calm_p1']}
Thought: typed operator step 3 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['aggressive_shock_range'] = df['aggressive_p99'] - df['aggressive_p1']
Observation: derived 'aggressive_shock_range' (rows=9)
Thought: typed operator step 4 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['calm_shock_range'] = df['calm_p99'] - df['calm_p1']
Observation: derived 'calm_shock_range' (rows=9)
Thought: typed operator step 5 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['aggressive_shock_range'].mean()
Observation: 5.0055000000000005
Thought: typed operator step 6 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['calm_shock_range'].mean()
Observation: 1.291285714285714
Thought: typed operator step 7 (COMPARE_VALUES)
Action: typed_operator_exec
Action Input: result = compare(aggressive=5.0055000000000005, calm=1.291285714285714, mode='difference')
Observation: {'higher': 'aggressive', 'lower': 'calm', 'aggressive': 5.0055000000000005, 'calm': 1.291285714285714, 'aggressive_metric': 'aggressive_shock_range mean', 'calm_metric': 'calm_shock_range mean', 'difference': 3.7142142857142866}
Final Answer: {'higher': 'aggressive', 'lower': 'calm', 'aggressive': 5.0055000000000005, 'calm': 1.291285714285714, 'aggressive_metric': 'aggressive_shock_range mean', 'calm_metric': 'calm_shock_range mean', 'difference': 3.7142142857142866}
```

**Final Code Executed**

```python
df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['accel_stats_z_p99'].mean()
branch_1 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['accel_stats_z_p1'].mean()
branch_2 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['accel_stats_z_p99'].mean()
branch_3 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['accel_stats_z_p1'].mean()
merged = branch_0.merge(branch_1, on=['timestamp_5min'], how='outer')
df['aggressive_shock_range'] = df['aggressive_p99'] - df['aggressive_p1']
df['calm_shock_range'] = df['calm_p99'] - df['calm_p1']
result = df['aggressive_shock_range'].mean()
result = df['calm_shock_range'].mean()
result = compare(aggressive=5.0055000000000005, calm=1.291285714285714, mode='difference')
```

---

### Q18: For every recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'higher': 'north', 'lower': 'south', 'metric': 'mean peak_accel_magnitude', 'north': 11.722590691852952, 'south': 11.194853285218633, 'abs_difference': 0.5277374066343192}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_VECTOR_MAGNITUDE,SPLIT_BY_THRESHOLD,SPLIT_BY_THRESHOLD,AGGREGATE_PARTITIONS,COMPARE_PARTITIONS
- Latency: 8.26s | Cost: $0.00258

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_VECTOR_MAGNITUDE)
Action: typed_operator_exec
Action Input: df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
Observation: derived 'peak_accel_magnitude' (rows=1219)
Thought: typed operator step 2 (SPLIT_BY_THRESHOLD)
Action: typed_operator_exec
Action Input: north = df[df['latitude'] gt df['latitude'].median()]
Observation: north: rows=609 (latitude gt median=33.776676)
Thought: typed operator step 3 (SPLIT_BY_THRESHOLD)
Action: typed_operator_exec
Action Input: south = df[df['latitude'] lte df['latitude'].median()]
Observation: south: rows=610 (latitude lte median=33.776676)
Thought: typed operator step 4 (AGGREGATE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = {label: agg(partition) for label in partitions}
Observation: {'north': 11.722590691852952, 'south': 11.194853285218633}
Thought: typed operator step 5 (COMPARE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = compare(north, south, mode='abs_difference')
Observation: {'higher': 'north', 'lower': 'south', 'metric': 'mean peak_accel_magnitude', 'north': 11.722590691852952, 'south': 11.194853285218633, 'abs_difference': 0.5277374066343192}
Final Answer: {'higher': 'north', 'lower': 'south', 'metric': 'mean peak_accel_magnitude', 'north': 11.722590691852952, 'south': 11.194853285218633, 'abs_difference': 0.5277374066343192}
```

**Final Code Executed**

```python
df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
north = df[df['latitude'] gt df['latitude'].median()]
south = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(north, south, mode='abs_difference')
```

---

### Q17: Restrict the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'timestamp_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,DERIVE_BIN,GROUP_AGGREGATE,RANK_GROUPS
- Latency: 7.33s | Cost: $0.00209

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['behavior'].isin(['aggressive'])]
Observation: rows=164
Thought: typed operator step 2 (DERIVE_BIN)
Action: typed_operator_exec
Action Input: df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
Observation: derived 'timestamp_bin' (kind=temporal freq='5min' source=datetime)
Thought: typed operator step 3 (GROUP_AGGREGATE)
Action: typed_operator_exec
Action Input: result = df.groupby('timestamp_bin')['instability_score'].mean()
Observation: {'2025-06-06T11:05:00': 0.21, '2025-06-06T11:10:00': 0.574, '2025-06-06T11:15:00': 0.574, '2025-06-06T11:45:00': 0.336, '2025-06-06T16:00:00': 0.594, '2025-06-06T16:05:00': 0.594}
Thought: typed operator step 4 (RANK_GROUPS)
Action: typed_operator_exec
Action Input: result = result.idxmax()
Observation: {'timestamp_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}
Final Answer: {'timestamp_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}
```

**Final Code Executed**

```python
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['instability_score'].mean()
result = result.idxmax()
```

---

### Q20: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Restrict to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'timestamp_bin': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,DERIVE_BINARY,DERIVE_BIN,GROUP_AGGREGATE,RANK_GROUPS
- Latency: 7.75s | Cost: $0.00231

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['behavior'].isin(['aggressive'])]
Observation: rows=164
Thought: typed operator step 2 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
Observation: derived 'vertical_shock_range' (rows=164)
Thought: typed operator step 3 (DERIVE_BIN)
Action: typed_operator_exec
Action Input: df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
Observation: derived 'timestamp_bin' (kind=temporal freq='5min' source=datetime)
Thought: typed operator step 4 (GROUP_AGGREGATE)
Action: typed_operator_exec
Action Input: result = df.groupby('timestamp_bin')['vertical_shock_range'].mean()
Observation: {'2025-06-06T11:05:00': 7.355, '2025-06-06T11:10:00': 3.371000000000001, '2025-06-06T11:15:00': 3.3710000000000004, '2025-06-06T11:45:00': 4.290000000000001, '2025-06-06T16:00:00': 5.8229999999999995, '2025-06-06T16:05:00': 5.8229999999999995}
Thought: typed operator step 5 (RANK_GROUPS)
Action: typed_operator_exec
Action Input: result = result.idxmax()
Observation: {'timestamp_bin': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}
Final Answer: {'timestamp_bin': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}
```

**Final Code Executed**

```python
df = df[df['behavior'].isin(['aggressive'])]
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['vertical_shock_range'].mean()
result = result.idxmax()
```

---
