# Flash-Fusion Benchmark Report

Generated: 2026-09-15T20:39:51+00:00

## Summary Table

| Baseline           |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-------------------|-------------------:|------------------:|-----------------:|
| FLASH_FUSION_CACHE |             1.0000 |            7.1369 |           0.0042 |

## Typed-Operator Coverage

| Baseline           |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:-------------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FLASH_FUSION_CACHE |         4 |       4 | 100%       |                0 |                  0 |                    7.14 | -                          |

## Per-Query Results

### Q20: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Filter to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'timestamp_5min': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_BINARY,FILTER_IN,DERIVE_BIN,GROUP_AGGREGATE,RANK_GROUPS
- Latency: 6.30s | Cost: $0.00236

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
Action Input: df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
Observation: derived 'timestamp_5min' (kind=temporal freq='5min' source=datetime)
Thought: typed operator step 4 (GROUP_AGGREGATE)
Action: typed_operator_exec
Action Input: result = df.groupby('timestamp_5min')['vertical_shock_range'].mean()
Observation: {'2025-06-06T11:05:00': 7.355, '2025-06-06T11:10:00': 3.371000000000001, '2025-06-06T11:15:00': 3.3710000000000004, '2025-06-06T11:45:00': 4.290000000000001, '2025-06-06T16:00:00': 5.8229999999999995, '2025-06-06T16:05:00': 5.8229999999999995}
Thought: typed operator step 5 (RANK_GROUPS)
Action: typed_operator_exec
Action Input: result = result.idxmax()
Observation: {'timestamp_5min': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}
Final Answer: {'timestamp_5min': '2025-06-06T11:05:00', 'mean_vertical_shock_range': 7.355}
```

**Final Code Executed**

```python
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_5min')['vertical_shock_range'].mean()
result = result.idxmax()
```

---

### Q19: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Compute its mean separately for aggressive and calm behavior labels, then report the aggressive-minus-calm difference.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'higher': 'aggressive', 'lower': 'calm', 'metric': 'mean vertical_shock_range', 'aggressive': 4.869682926829269, 'calm': 1.4331774193548388, 'difference': 3.436505507474431}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_BINARY,SPLIT_BY_VALUES,SPLIT_BY_VALUES,AGGREGATE_PARTITIONS,COMPARE_PARTITIONS
- Latency: 7.42s | Cost: $0.00977

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_BINARY)
Action: typed_operator_exec
Action Input: df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
Observation: derived 'vertical_shock_range' (rows=1219)
Thought: typed operator step 2 (SPLIT_BY_VALUES)
Action: typed_operator_exec
Action Input: aggressive = df[df['behavior'].isin(['aggressive'])]
Observation: aggressive: rows=164
Thought: typed operator step 3 (SPLIT_BY_VALUES)
Action: typed_operator_exec
Action Input: calm = df[df['behavior'].isin(['calm'])]
Observation: calm: rows=186
Thought: typed operator step 4 (AGGREGATE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = {label: agg(partition) for label in partitions}
Observation: {'aggressive': 4.869682926829269, 'calm': 1.4331774193548388}
Thought: typed operator step 5 (COMPARE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = compare(aggressive, calm, mode='difference')
Observation: {'higher': 'aggressive', 'lower': 'calm', 'metric': 'mean vertical_shock_range', 'aggressive': 4.869682926829269, 'calm': 1.4331774193548388, 'difference': 3.436505507474431}
Final Answer: {'higher': 'aggressive', 'lower': 'calm', 'metric': 'mean vertical_shock_range', 'aggressive': 4.869682926829269, 'calm': 1.4331774193548388, 'difference': 3.436505507474431}
```

**Final Code Executed**

```python
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
aggressive = df[df['behavior'].isin(['aggressive'])]
calm = df[df['behavior'].isin(['calm'])]
result = {label: agg(partition) for label in partitions}
result = compare(aggressive, calm, mode='difference')
```

---

### Q18: Derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Split the route at the median latitude and report the absolute difference between the northern and southern halves' mean peak magnitudes.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'higher': 'northern', 'lower': 'southern', 'metric': 'mean peak_accel_magnitude', 'northern': 11.722590691852952, 'southern': 11.194853285218633, 'abs_difference': 0.5277374066343192}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_VECTOR_MAGNITUDE,SPLIT_BY_THRESHOLD,SPLIT_BY_THRESHOLD,AGGREGATE_PARTITIONS,COMPARE_PARTITIONS
- Latency: 8.02s | Cost: $0.00260

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_VECTOR_MAGNITUDE)
Action: typed_operator_exec
Action Input: df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
Observation: derived 'peak_accel_magnitude' (rows=1219)
Thought: typed operator step 2 (SPLIT_BY_THRESHOLD)
Action: typed_operator_exec
Action Input: northern = df[df['latitude'] gt df['latitude'].median()]
Observation: northern: rows=609 (latitude gt median=33.776676)
Thought: typed operator step 3 (SPLIT_BY_THRESHOLD)
Action: typed_operator_exec
Action Input: southern = df[df['latitude'] lte df['latitude'].median()]
Observation: southern: rows=610 (latitude lte median=33.776676)
Thought: typed operator step 4 (AGGREGATE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = {label: agg(partition) for label in partitions}
Observation: {'northern': 11.722590691852952, 'southern': 11.194853285218633}
Thought: typed operator step 5 (COMPARE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = compare(northern, southern, mode='abs_difference')
Observation: {'higher': 'northern', 'lower': 'southern', 'metric': 'mean peak_accel_magnitude', 'northern': 11.722590691852952, 'southern': 11.194853285218633, 'abs_difference': 0.5277374066343192}
Final Answer: {'higher': 'northern', 'lower': 'southern', 'metric': 'mean peak_accel_magnitude', 'northern': 11.722590691852952, 'southern': 11.194853285218633, 'abs_difference': 0.5277374066343192}
```

**Final Code Executed**

```python
df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
northern = df[df['latitude'] gt df['latitude'].median()]
southern = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(northern, southern, mode='abs_difference')
```

---

### Q17: Filter the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

#### FLASH_FUSION_CACHE

**Answer:** The result is {'timestamp_bin': '2025-06-06T16:00:00', 'mean_instability_score': 0.594}

- Executed: True | Rejected: False | Judge: N/A
- Stages: exact_cache_hit,cache_light_grounding,cache_miss_or_validation_failure,guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,DERIVE_BIN,GROUP_AGGREGATE,RANK_GROUPS
- Latency: 6.81s | Cost: $0.00212

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
