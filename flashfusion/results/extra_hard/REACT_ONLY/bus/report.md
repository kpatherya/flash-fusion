# Flash-Fusion Benchmark Report

Generated: 2026-09-15T19:17:05+00:00

## Summary Table

| Baseline   |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-----------|-------------------:|------------------:|-----------------:|
| REACT_ONLY |             0.5833 |            8.0151 |           0.0012 |

## Typed-Operator Coverage

| Baseline   |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject | Typed avg latency (s)   | Fallback avg latency (s)   |
|:-----------|----------:|--------:|:-----------|-----------------:|-------------------:|:------------------------|:---------------------------|
| REACT_ONLY |        12 |       0 | 0%         |                0 |                  0 | -                       | -                          |

## Per-Query Results

### Q17: Filter the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 16:00:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 9.25s | Cost: $0.00171

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive['window'] = df_aggressive['timestamp'].dt.floor('5T')
grouped = df_aggressive.groupby('window')['instability_score'].mean()
result = grouped.idxmax()
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.groupby(pd.Grouper(freq='5min'))
mean_instability = grouped['instability_score'].mean()
result = mean_instability.idxmax()
Observation: 2025-06-06 16:00:00
Final Answer: The result is: 2025-06-06 16:00:00
```

**Final Code Executed**

```python
df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.groupby(pd.Grouper(freq='5min'))
mean_instability = grouped['instability_score'].mean()
result = mean_instability.idxmax()
```

---

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 16:00:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 10.34s | Cost: $0.00104

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Filter rows labeled 'aggressive'
aggressive_df = df[df['behavior'] == 'aggressive']

# Group into 5-minute windows and compute mean instability_score
aggressive_df = aggressive_df.set_index('timestamp')
grouped = aggressive_df.resample('5T')['instability_score'].mean()

# Find the window with the highest mean instability_score
max_window = grouped.idxmax()

result = max_window
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive['timestamp'] = pd.to_datetime(df_aggressive['timestamp'])
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.resample('5min')['instability_score'].mean()
result = grouped.idxmax()
Observation: 2025-06-06 16:00:00
Final Answer: The result is: 2025-06-06 16:00:00
```

**Final Code Executed**

```python
df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive['timestamp'] = pd.to_datetime(df_aggressive['timestamp'])
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.resample('5min')['instability_score'].mean()
result = grouped.idxmax()
```

---

#### REACT_ONLY

**Answer:** The result is: (Timestamp('2025-06-06 16:00:00'), np.float64(0.594))

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 9.59s | Cost: $0.00099

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: aggressive_df = df[df['behavior'] == 'aggressive'].copy()
aggressive_df['timestamp_window'] = aggressive_df['timestamp'].dt.floor('5T')
window_means = aggressive_df.groupby('timestamp_window')['instability_score'].mean()
result = window_means.idxmax()
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.groupby(pd.Grouper(freq='5min'))
mean_instability = grouped['instability_score'].mean()
result_window = mean_instability.idxmax()
result = (result_window, mean_instability.loc[result_window])
Observation: (Timestamp('2025-06-06 16:00:00'), np.float64(0.594))
Final Answer: The result is: (Timestamp('2025-06-06 16:00:00'), np.float64(0.594))
```

**Final Code Executed**

```python
df_aggressive = df[df['behavior'] == 'aggressive'].copy()
df_aggressive.set_index('timestamp', inplace=True)
grouped = df_aggressive.groupby(pd.Grouper(freq='5min'))
mean_instability = grouped['instability_score'].mean()
result_window = mean_instability.idxmax()
result = (result_window, mean_instability.loc[result_window])
```

---

### Q18: Derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Split the route at the median latitude and report the absolute difference between the northern and southern halves' mean peak magnitudes.

#### REACT_ONLY

**Answer:** The result is: 0.5267201826219985

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 6.10s | Cost: $0.00168

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: import numpy as np

# Compute peak acceleration magnitude using p99 values for x, y, z
df['peak_accel_mag'] = np.sqrt(
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
)

# Compute median latitude
median_lat = df['latitude'].median()

# Split into northern and southern halves
northern = df[df['latitude'] >= median_lat]
southern = df[df['latitude'] < median_lat]

# Compute mean peak magnitudes for each half
mean_north = northern['peak_accel_mag'].mean()
mean_south = southern['peak_accel_mag'].mean()

# Absolute difference
result = abs(mean_north - mean_south)
Observation: 0.5267201826219985
Final Answer: The result is: 0.5267201826219985
```

**Final Code Executed**

```python
import numpy as np

# Compute peak acceleration magnitude using p99 values for x, y, z
df['peak_accel_mag'] = np.sqrt(
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
)

# Compute median latitude
median_lat = df['latitude'].median()

# Split into northern and southern halves
northern = df[df['latitude'] >= median_lat]
southern = df[df['latitude'] < median_lat]

# Compute mean peak magnitudes for each half
mean_north = northern['peak_accel_mag'].mean()
mean_south = southern['peak_accel_mag'].mean()

# Absolute difference
result = abs(mean_north - mean_south)
```

---

#### REACT_ONLY

**Answer:** The result is: 0.5267201826219985

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 7.23s | Cost: $0.00085

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute peak acceleration magnitude
df['peak_accel_magnitude'] = (
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
) ** 0.5

# Find median latitude
median_lat = df['latitude'].median()

# Split into northern and southern halves
northern = df[df['latitude'] >= median_lat]
southern = df[df['latitude'] < median_lat]

# Compute mean peak magnitudes for each half
mean_north = northern['peak_accel_magnitude'].mean()
mean_south = southern['peak_accel_magnitude'].mean()

# Compute absolute difference
result = abs(mean_north - mean_south)
Observation: 0.5267201826219985
Final Answer: The result is: 0.5267201826219985
```

**Final Code Executed**

```python
# Compute peak acceleration magnitude
df['peak_accel_magnitude'] = (
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
) ** 0.5

# Find median latitude
median_lat = df['latitude'].median()

# Split into northern and southern halves
northern = df[df['latitude'] >= median_lat]
southern = df[df['latitude'] < median_lat]

# Compute mean peak magnitudes for each half
mean_north = northern['peak_accel_magnitude'].mean()
mean_south = southern['peak_accel_magnitude'].mean()

# Compute absolute difference
result = abs(mean_north - mean_south)
```

---

#### REACT_ONLY

**Answer:** The result is: 0.5267201826219985

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 6.32s | Cost: $0.00085

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute peak acceleration magnitude
df['peak_accel_magnitude'] = (
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
) ** 0.5

# Find median latitude
median_lat = df['latitude'].median()

# Split into northern and southern halves
northern = df[df['latitude'] >= median_lat]
southern = df[df['latitude'] < median_lat]

# Compute mean peak magnitudes for each half
mean_north = northern['peak_accel_magnitude'].mean()
mean_south = southern['peak_accel_magnitude'].mean()

# Compute absolute difference
result = abs(mean_north - mean_south)
Observation: 0.5267201826219985
Final Answer: The result is: 0.5267201826219985
```

**Final Code Executed**

```python
# Compute peak acceleration magnitude
df['peak_accel_magnitude'] = (
    df['accel_stats_x_p99']**2 +
    df['accel_stats_y_p99']**2 +
    df['accel_stats_z_p99']**2
) ** 0.5

# Find median latitude
median_lat = df['latitude'].median()

# Split into northern and southern halves
northern = df[df['latitude'] >= median_lat]
southern = df[df['latitude'] < median_lat]

# Compute mean peak magnitudes for each half
mean_north = northern['peak_accel_magnitude'].mean()
mean_south = southern['peak_accel_magnitude'].mean()

# Compute absolute difference
result = abs(mean_north - mean_south)
```

---

### Q19: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Compute its mean separately for aggressive and calm behavior labels, then report the aggressive-minus-calm difference.

#### REACT_ONLY

**Answer:** The result is: 3.436505507474431

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 5.35s | Cost: $0.00139

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Compute mean for aggressive and calm behavior
aggressive_mean = df[df['behavior'] == 'aggressive']['vertical_shock_range'].mean()
calm_mean = df[df['behavior'] == 'calm']['vertical_shock_range'].mean()

# Calculate the difference
result = aggressive_mean - calm_mean
Observation: 3.436505507474431
Final Answer: The result is: 3.436505507474431
```

**Final Code Executed**

```python
# Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Compute mean for aggressive and calm behavior
aggressive_mean = df[df['behavior'] == 'aggressive']['vertical_shock_range'].mean()
calm_mean = df[df['behavior'] == 'calm']['vertical_shock_range'].mean()

# Calculate the difference
result = aggressive_mean - calm_mean
```

---

#### REACT_ONLY

**Answer:** The result is: 3.436505507474431

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 5.26s | Cost: $0.00062

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Compute mean vertical shock range for aggressive and calm behavior
aggressive_mean = df[df['behavior'] == 'aggressive']['vertical_shock_range'].mean()
calm_mean = df[df['behavior'] == 'calm']['vertical_shock_range'].mean()

# Calculate the difference (aggressive minus calm)
result = aggressive_mean - calm_mean
Observation: 3.436505507474431
Final Answer: The result is: 3.436505507474431
```

**Final Code Executed**

```python
# Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Compute mean vertical shock range for aggressive and calm behavior
aggressive_mean = df[df['behavior'] == 'aggressive']['vertical_shock_range'].mean()
calm_mean = df[df['behavior'] == 'calm']['vertical_shock_range'].mean()

# Calculate the difference (aggressive minus calm)
result = aggressive_mean - calm_mean
```

---

#### REACT_ONLY

**Answer:** The result is: 3.436505507474431

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 5.10s | Cost: $0.00060

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Compute mean for aggressive and calm behavior labels
aggressive_mean = df[df['behavior'] == 'aggressive']['vertical_shock_range'].mean()
calm_mean = df[df['behavior'] == 'calm']['vertical_shock_range'].mean()

# Calculate the difference
result = aggressive_mean - calm_mean
Observation: 3.436505507474431
Final Answer: The result is: 3.436505507474431
```

**Final Code Executed**

```python
# Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Compute mean for aggressive and calm behavior labels
aggressive_mean = df[df['behavior'] == 'aggressive']['vertical_shock_range'].mean()
calm_mean = df[df['behavior'] == 'calm']['vertical_shock_range'].mean()

# Calculate the difference
result = aggressive_mean - calm_mean
```

---

### Q20: Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Filter to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 16:00:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 6.16s | Cost: $0.00152

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
grouped = aggressive_df.groupby(pd.Grouper(freq='5Min'))['vertical_shock_range'].mean()

# Find the window with the highest mean
max_window = grouped.idxmax()

result = max_window
Observation: 2025-06-06 16:00:00
Final Answer: The result is: 2025-06-06 16:00:00
```

**Final Code Executed**

```python
# Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior
aggressive_df = df[df['behavior'].isin(['aggressive', 'very_aggressive'])]

# Group into 5-minute windows and compute mean vertical shock range
aggressive_df = aggressive_df.set_index('timestamp')
grouped = aggressive_df.groupby(pd.Grouper(freq='5Min'))['vertical_shock_range'].mean()

# Find the window with the highest mean
max_window = grouped.idxmax()

result = max_window
```

---

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 16:00:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 12.48s | Cost: $0.00168

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior
aggressive_df = df[df['behavior'] == 'aggressive'].copy()

# Create 5-minute windows
aggressive_df['window'] = aggressive_df['timestamp'].dt.floor('5T')

# Group by window and calculate mean vertical shock range
window_means = aggressive_df.groupby('window')['vertical_shock_range'].mean()

# Find the window with the highest mean
result_window = window_means.idxmax()

# Return the window with the highest mean vertical shock range
result = result_window
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior (including both 'aggressive' and 'very_aggressive')
aggressive_df = df[df['behavior'].isin(['aggressive', 'very_aggressive'])].copy()

# Group into 5-minute windows using pd.Grouper with correct frequency string
aggressive_df.set_index('timestamp', inplace=True)
grouped = aggressive_df.groupby(pd.Grouper(freq='5min'))

# Calculate mean vertical shock range for each window
window_means = grouped['vertical_shock_range'].mean()

# Find the window with the highest mean
max_window = window_means.idxmax()

# Return the window timestamp with the highest mean
result = max_window
Observation: 2025-06-06 16:00:00
Final Answer: The result is: 2025-06-06 16:00:00
```

**Final Code Executed**

```python
# Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior (including both 'aggressive' and 'very_aggressive')
aggressive_df = df[df['behavior'].isin(['aggressive', 'very_aggressive'])].copy()

# Group into 5-minute windows using pd.Grouper with correct frequency string
aggressive_df.set_index('timestamp', inplace=True)
grouped = aggressive_df.groupby(pd.Grouper(freq='5min'))

# Calculate mean vertical shock range for each window
window_means = grouped['vertical_shock_range'].mean()

# Find the window with the highest mean
max_window = window_means.idxmax()

# Return the window timestamp with the highest mean
result = max_window
```

---

#### REACT_ONLY

**Answer:** The result is: 2025-06-06 16:00:00

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 13.00s | Cost: $0.00163

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior
aggressive_df = df[df['behavior'] == 'aggressive'].copy()

# Create 5-minute windows
aggressive_df['window'] = aggressive_df['timestamp'].dt.floor('5T')

# Group by window and calculate mean vertical shock range
window_means = aggressive_df.groupby('window')['vertical_shock_range'].mean()

# Find the window with the highest mean
result_window = window_means.idxmax()

# Return the window with the highest mean vertical shock range
result = result_window
Observation: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")
Thought: Attempt 2: generate executable pandas code
Action: python_exec
Action Input: # Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior (including both 'aggressive' and 'very_aggressive')
aggressive_df = df[df['behavior'].isin(['aggressive', 'very_aggressive'])].copy()

# Group into 5-minute windows and compute mean vertical shock range per window
aggressive_df.set_index('timestamp', inplace=True)
windowed = aggressive_df.groupby(pd.Grouper(freq='5min'))['vertical_shock_range'].mean()

# Find the window with the highest mean vertical shock range
max_window = windowed.idxmax()

# Return the window timestamp with the highest mean
result = max_window
Observation: 2025-06-06 16:00:00
Final Answer: The result is: 2025-06-06 16:00:00
```

**Final Code Executed**

```python
# Derive vertical shock range
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']

# Filter to aggressive behavior (including both 'aggressive' and 'very_aggressive')
aggressive_df = df[df['behavior'].isin(['aggressive', 'very_aggressive'])].copy()

# Group into 5-minute windows and compute mean vertical shock range per window
aggressive_df.set_index('timestamp', inplace=True)
windowed = aggressive_df.groupby(pd.Grouper(freq='5min'))['vertical_shock_range'].mean()

# Find the window with the highest mean vertical shock range
max_window = windowed.idxmax()

# Return the window timestamp with the highest mean
result = max_window
```

---
