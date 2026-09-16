# Flash-Fusion Benchmark Report

Generated: 2026-09-15T22:33:37+00:00

## Summary Table

| Baseline   |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-----------|-------------------:|------------------:|-----------------:|
| REACT_ONLY |             0.5000 |           11.6871 |           0.0010 |

## Typed-Operator Coverage

| Baseline   |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject | Typed avg latency (s)   | Fallback avg latency (s)   |
|:-----------|----------:|--------:|:-----------|-----------------:|-------------------:|:------------------------|:---------------------------|
| REACT_ONLY |         4 |       0 | 0%         |                0 |                  0 | -                       | -                          |

## Per-Query Results

### Q17: Filter the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 16:00:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 13.67s | Cost: $0.00096

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive['timestamp_window'] = df_aggressive['timestamp'].dt.floor('5T')
grouped = df_aggressive.groupby('timestamp_window')['instability_score'].mean()
result = grouped.idxmax()
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive['timestamp'] = pd.to_datetime(df_aggressive['timestamp'])
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.groupby(pd.Grouper(freq='5min'))['instability_score'].mean()
result = grouped.idxmax()
Observation: 2025-06-06 16:00:00
Final Answer: The result is: 2025-06-06 16:00:00
```

**Final Code Executed**

```python
df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive['timestamp'] = pd.to_datetime(df_aggressive['timestamp'])
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.groupby(pd.Grouper(freq='5min'))['instability_score'].mean()
result = grouped.idxmax()
```

---

### Q18: For each recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude.

#### REACT_ONLY

**Answer:** The result is: 0.5267201826219985

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 8.13s | Cost: $0.00082

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute peak acceleration magnitude per row
df['peak_magnitude'] = (
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
) ** 0.5

# Compute median latitude
median_lat = df['latitude'].median()

# Split into north and south groups
north = df[df['latitude'] >= median_lat]['peak_magnitude']
south = df[df['latitude'] < median_lat]['peak_magnitude']

# Compute mean peak magnitude for each group
mean_north = north.mean()
mean_south = south.mean()

# Compute absolute difference
result = abs(mean_north - mean_south)
Observation: 0.5267201826219985
Final Answer: The result is: 0.5267201826219985
```

**Final Code Executed**

```python
# Compute peak acceleration magnitude per row
df['peak_magnitude'] = (
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
) ** 0.5

# Compute median latitude
median_lat = df['latitude'].median()

# Split into north and south groups
north = df[df['latitude'] >= median_lat]['peak_magnitude']
south = df[df['latitude'] < median_lat]['peak_magnitude']

# Compute mean peak magnitude for each group
mean_north = north.mean()
mean_south = south.mean()

# Compute absolute difference
result = abs(mean_north - mean_south)
```

---

### Q19: For each 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and compute its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route.

#### REACT_ONLY

**Answer:** The result is: 3.43650550747443

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 8.69s | Cost: $0.00081

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute vertical shock range (p99 - p1) for z-axis
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter only 'aggressive' and 'calm' behavior labels
filtered_df = df[df['behavior'].isin(['aggressive', 'calm'])]

# Group by behavior and compute mean vertical shock range
mean_by_behavior = filtered_df.groupby('behavior')['vertical_shock_range'].mean()

# Calculate aggressive-minus-calm difference
aggressive_mean = mean_by_behavior.get('aggressive', 0)
calm_mean = mean_by_behavior.get('calm', 0)
result = aggressive_mean - calm_mean
Observation: 3.43650550747443
Final Answer: The result is: 3.43650550747443
```

**Final Code Executed**

```python
# Compute vertical shock range (p99 - p1) for z-axis
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter only 'aggressive' and 'calm' behavior labels
filtered_df = df[df['behavior'].isin(['aggressive', 'calm'])]

# Group by behavior and compute mean vertical shock range
mean_by_behavior = filtered_df.groupby('behavior')['vertical_shock_range'].mean()

# Calculate aggressive-minus-calm difference
aggressive_mean = mean_by_behavior.get('aggressive', 0)
calm_mean = mean_by_behavior.get('calm', 0)
result = aggressive_mean - calm_mean
```

---

### Q20: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Filter to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 11:05:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 16.26s | Cost: $0.00145

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior
aggressive_df = df[df['behavior'].isin(['aggressive', 'very_aggressive'])]

# Group into 5-minute windows and compute mean vertical shock range
aggressive_df = aggressive_df.set_index('timestamp')
grouped = aggressive_df.groupby(pd.Grouper(freq='5T'))['vertical_shock_range'].mean()

# Find the window with the highest mean
max_window = grouped.idxmax()
result = max_window
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: # Compute vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior
aggressive_df = df[df['behavior'] == 'aggressive'].copy()

# Group into 5-minute windows and compute mean vertical shock range per window
aggressive_df.set_index('timestamp', inplace=True)
grouped = aggressive_df.resample('5min')['vertical_shock_range'].mean()

# Find the window with the highest mean vertical shock range
max_window = grouped.idxmax()

result = max_window
Observation: 2025-06-06 11:05:00
Final Answer: The result is: 2025-06-06 11:05:00
```

**Final Code Executed**

```python
# Compute vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior
aggressive_df = df[df['behavior'] == 'aggressive'].copy()

# Group into 5-minute windows and compute mean vertical shock range per window
aggressive_df.set_index('timestamp', inplace=True)
grouped = aggressive_df.resample('5min')['vertical_shock_range'].mean()

# Find the window with the highest mean vertical shock range
max_window = grouped.idxmax()

result = max_window
```

---
