# Flash-Fusion Benchmark Report

Generated: 2026-09-15T22:53:51+00:00

## Summary Table

| Baseline     |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-------------|-------------------:|------------------:|-----------------:|
| FLASH_FUSION |             0.7500 |            4.6329 |           0.0024 |

## Typed-Operator Coverage

| Baseline     |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:-------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FLASH_FUSION |         4 |       4 | 100%       |                0 |                  0 |                    4.63 | -                          |

## Per-Query Results

### Q17: Filter the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

#### FLASH_FUSION

**Answer:** The result is {'timestamp_5min_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,DERIVE_BIN,GROUP_AGGREGATE,RANK_GROUPS
- Latency: 3.61s | Cost: $0.00204

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['behavior'].isin(['aggressive'])]
Observation: rows=164
Thought: typed operator step 2 (DERIVE_BIN)
Action: typed_operator_exec
Action Input: df['timestamp_5min_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
Observation: derived 'timestamp_5min_bin' (kind=temporal freq='5min' source=datetime)
Thought: typed operator step 3 (GROUP_AGGREGATE)
Action: typed_operator_exec
Action Input: result = df.groupby('timestamp_5min_bin')['instability_score'].mean()
Observation: {'2025-06-06T11:05:00': 0.21, '2025-06-06T11:10:00': 0.574, '2025-06-06T11:15:00': 0.574, '2025-06-06T11:45:00': 0.336, '2025-06-06T16:00:00': 0.594, '2025-06-06T16:05:00': 0.594}
Thought: typed operator step 4 (RANK_GROUPS)
Action: typed_operator_exec
Action Input: result = result.idxmax()
Observation: {'timestamp_5min_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}
Final Answer: {'timestamp_5min_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}
```

**Final Code Executed**

```python
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_5min_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_5min_bin')['instability_score'].mean()
result = result.idxmax()
```

---

### Q18: For each recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude.

#### FLASH_FUSION

**Answer:** The result is {'higher': 'north', 'lower': 'south', 'metric': 'mean peak_accel_magnitude', 'north': 11.722590691852952, 'south': 11.194853285218633, 'abs_difference': 0.5277374066343192}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_VECTOR_MAGNITUDE,SPLIT_BY_THRESHOLD,SPLIT_BY_THRESHOLD,AGGREGATE_PARTITIONS,COMPARE_PARTITIONS
- Latency: 4.84s | Cost: $0.00248

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

### Q19: For each 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and compute its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route.

#### FLASH_FUSION

**Answer:** The result is {'higher': 'aggressive', 'lower': 'calm', 'aggressive': 5.0055000000000005, 'calm': 1.2912857142857141, 'aggressive_metric': 'aggressive_mean_range mean', 'calm_metric': 'calm_mean_range mean', 'difference': 3.714214285714286}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_BIN,DERIVE_BINARY,PARALLEL_AGGREGATE,AGGREGATE_COLUMN,AGGREGATE_COLUMN,COMPARE_VALUES
- Latency: 5.90s | Cost: $0.00302

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_BIN)
Action: typed_operator_exec
Action Input: df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
Observation: derived 'timestamp_5min' (kind=temporal freq='5min' source=datetime)
Thought: typed operator step 2 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
Observation: derived 'vertical_shock_range' (rows=1219)
Thought: typed operator step 3 (PARALLEL_AGGREGATE)
Action: typed_operator_exec
Action Input: # PARALLEL_AGGREGATE branches:
branch_0 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['vertical_shock_range'].mean()
branch_1 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['vertical_shock_range'].mean()
merged = branch_0.merge(branch_1, on=['timestamp_5min'], how='outer')
Observation: {'groups': 9, 'columns': ['timestamp_5min', 'aggressive_mean_range', 'calm_mean_range']}
Thought: typed operator step 4 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['aggressive_mean_range'].mean()
Observation: 5.0055000000000005
Thought: typed operator step 5 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['calm_mean_range'].mean()
Observation: 1.2912857142857141
Thought: typed operator step 6 (COMPARE_VALUES)
Action: typed_operator_exec
Action Input: result = compare(aggressive=5.0055000000000005, calm=1.2912857142857141, mode='difference')
Observation: {'higher': 'aggressive', 'lower': 'calm', 'aggressive': 5.0055000000000005, 'calm': 1.2912857142857141, 'aggressive_metric': 'aggressive_mean_range mean', 'calm_metric': 'calm_mean_range mean', 'difference': 3.714214285714286}
Final Answer: {'higher': 'aggressive', 'lower': 'calm', 'aggressive': 5.0055000000000005, 'calm': 1.2912857142857141, 'aggressive_metric': 'aggressive_mean_range mean', 'calm_metric': 'calm_mean_range mean', 'difference': 3.714214285714286}
```

**Final Code Executed**

```python
df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['vertical_shock_range'].mean()
branch_1 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['vertical_shock_range'].mean()
merged = branch_0.merge(branch_1, on=['timestamp_5min'], how='outer')
result = df['aggressive_mean_range'].mean()
result = df['calm_mean_range'].mean()
result = compare(aggressive=5.0055000000000005, calm=1.2912857142857141, mode='difference')
```

---

### Q20: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Filter to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

#### FLASH_FUSION

**Answer:** The result is {'timestamp_bin': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_BINARY,FILTER_IN,DERIVE_BIN,GROUP_AGGREGATE,RANK_GROUPS
- Latency: 4.18s | Cost: $0.00224

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
Observation: derived 'vertical_shock_range' (rows=1219)
Thought: typed operator step 2 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['behavior'].isin(['aggressive'])]
Observation: rows=164
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
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['vertical_shock_range'].mean()
result = result.idxmax()
```

---
