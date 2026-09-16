# Flash-Fusion Benchmark Report

Generated: 2026-09-15T22:45:09+00:00

## Summary Table

| Baseline   |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-----------|-------------------:|------------------:|-----------------:|
| REACT_ONLY |             1.0000 |           20.5769 |           0.0013 |

## Typed-Operator Coverage

| Baseline   |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject | Typed avg latency (s)   | Fallback avg latency (s)   |
|:-----------|----------:|--------:|:-----------|-----------------:|-------------------:|:------------------------|:---------------------------|
| REACT_ONLY |         4 |       0 | 0%         |                0 |                  0 | -                       | -                          |

## Per-Query Results

### Q17: Among rows whose annotation is one of the known MIT-ECG annotation codes, partition each record_id's time_s values into consecutive groups of width 10. For each group, compute MLII RMS. Return the group with the greatest RMS.

#### REACT_ONLY

**Answer:** The result is: {'record_id': np.int32(116), 'time_group_start': np.int64(1400), 'MLII_RMS': np.float64(3.075804772738348)}

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 21.94s | Cost: $0.00144

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Filter rows with non-empty annotation that are among known MIT-ECG codes
# According to the note, empty string indicates missing; all other values in annotation are valid MIT-ECG codes
filtered_df = df[df['annotation'] != ''].copy()

# Create group bins of width 10 for time_s
filtered_df['time_group'] = (filtered_df['time_s'] // 10).astype(int) * 10

# Compute RMS of MLII for each (record_id, time_group)
rms_series = filtered_df.groupby(['record_id', 'time_group'])['MLII'].apply(
    lambda x: (x ** 2).mean() ** 0.5
)

# Find the group with the greatest RMS
max_rms_group = rms_series.idxmax()
max_rms_value = rms_series.max()

# Reconstruct the result as a DataFrame row with record_id, time_group, and RMS
result = {
    'record_id': max_rms_group[0],
    'time_group_start': max_rms_group[1],
    'MLII_RMS': max_rms_value
}
Observation: {'record_id': np.int32(116), 'time_group_start': np.int64(1400), 'MLII_RMS': np.float64(3.075804772738348)}
Final Answer: The result is: {'record_id': np.int32(116), 'time_group_start': np.int64(1400), 'MLII_RMS': np.float64(3.075804772738348)}
```

**Final Code Executed**

```python
# Filter rows with non-empty annotation that are among known MIT-ECG codes
# According to the note, empty string indicates missing; all other values in annotation are valid MIT-ECG codes
filtered_df = df[df['annotation'] != ''].copy()

# Create group bins of width 10 for time_s
filtered_df['time_group'] = (filtered_df['time_s'] // 10).astype(int) * 10

# Compute RMS of MLII for each (record_id, time_group)
rms_series = filtered_df.groupby(['record_id', 'time_group'])['MLII'].apply(
    lambda x: (x ** 2).mean() ** 0.5
)

# Find the group with the greatest RMS
max_rms_group = rms_series.idxmax()
max_rms_value = rms_series.max()

# Reconstruct the result as a DataFrame row with record_id, time_group, and RMS
result = {
    'record_id': max_rms_group[0],
    'time_group_start': max_rms_group[1],
    'MLII_RMS': max_rms_value
}
```

---

### Q18: For every record_id, independently compute maximum and minimum MLII. Define MLII span as maximum minus minimum. Return the record_id with the largest MLII span.

#### REACT_ONLY

**Answer:** The result is: 116

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 18.70s | Cost: $0.00063

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: mlii_span = df.groupby('record_id')['MLII'].agg(lambda x: x.max() - x.min())
result = mlii_span.idxmax()
Observation: 116
Final Answer: The result is: 116
```

**Final Code Executed**

```python
mlii_span = df.groupby('record_id')['MLII'].agg(lambda x: x.max() - x.min())
result = mlii_span.idxmax()
```

---

### Q19: For record_id 101, divide time_s into 10-second bins. For each bin, compute annotated-row rate as rows with an annotation in the known annotation-code list divided by all rows in the bin. Return the Pearson correlation between bin index and annotated-row rate.

#### REACT_ONLY

**Answer:** The result is: -0.4604856890166274

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 22.78s | Cost: $0.00223

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Verify that record_id 101 exists
if 101 not in df['record_id'].values:
    result = float('nan')
else:
    # Filter to record_id 101
    record_df = df[df['record_id'] == 101].copy()
    
    # Define known annotation codes (non-empty strings from the unique values)
    # According to note: empty string indicates missing; so known codes are non-empty
    known_codes = set(['+', 'N', '~', '|', 'Q', 'A', 'V', '/', 'x', 'F', 'j', 'L', 'a', 'R', 'J', '[', '!', ']', 'E', 'S', '"', 'f', 'e'])
    
    # Create 10-second bins
    max_time = record_df['time_s'].max()
    bins = int(max_time // 10) + 1  # Ensure we cover the full range
    
    # Add bin index column
    record_df['bin_idx'] = (record_df['time_s'] // 10).astype(int)
    
    # Group by bin index
    grouped = record_df.groupby('bin_idx')
    
    # Compute annotated-row rate for each bin
    bin_rates = []
    bin_indices = []
    
    for bin_idx, group in grouped:
        total_rows = len(group)
        # Count rows with annotation in known_codes
        annotated_rows = group['annotation'].isin(known_codes).sum()
        rate = annotated_rows / total_rows if total_rows > 0 else 0.0
        bin_rates.append(rate)
        bin_indices.append(bin_idx)
    
    # If fewer than 2 bins, correlation is undefined
    if len(bin_rates) < 2:
        result = float('nan')
    else:
        # Compute Pearson correlation between bin index and annotated-row rate
        import numpy as np
        corr = np.corrcoef(bin_indices, bin_rates)[0, 1]
        result = float(corr) if not np.isnan(corr) else float('nan')
Observation: -0.4604856890166274
Final Answer: The result is: -0.4604856890166274
```

**Final Code Executed**

```python
# Verify that record_id 101 exists
if 101 not in df['record_id'].values:
    result = float('nan')
else:
    # Filter to record_id 101
    record_df = df[df['record_id'] == 101].copy()
    
    # Define known annotation codes (non-empty strings from the unique values)
    # According to note: empty string indicates missing; so known codes are non-empty
    known_codes = set(['+', 'N', '~', '|', 'Q', 'A', 'V', '/', 'x', 'F', 'j', 'L', 'a', 'R', 'J', '[', '!', ']', 'E', 'S', '"', 'f', 'e'])
    
    # Create 10-second bins
    max_time = record_df['time_s'].max()
    bins = int(max_time // 10) + 1  # Ensure we cover the full range
    
    # Add bin index column
    record_df['bin_idx'] = (record_df['time_s'] // 10).astype(int)
    
    # Group by bin index
    grouped = record_df.groupby('bin_idx')
    
    # Compute annotated-row rate for each bin
    bin_rates = []
    bin_indices = []
    
    for bin_idx, group in grouped:
        total_rows = len(group)
        # Count rows with annotation in known_codes
        annotated_rows = group['annotation'].isin(known_codes).sum()
        rate = annotated_rows / total_rows if total_rows > 0 else 0.0
        bin_rates.append(rate)
        bin_indices.append(bin_idx)
    
    # If fewer than 2 bins, correlation is undefined
    if len(bin_rates) < 2:
        result = float('nan')
    else:
        # Compute Pearson correlation between bin index and annotated-row rate
        import numpy as np
        corr = np.corrcoef(bin_indices, bin_rates)[0, 1]
        result = float(corr) if not np.isnan(corr) else float('nan')
```

---

### Q20: For every record_id, independently compute MLII variance and V1 variance. Define total lead variability as their sum. Return the record_id with the largest total lead variability.

#### REACT_ONLY

**Answer:** The result is: 107

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 18.88s | Cost: $0.00085

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute variance of MLII and V1 for each record_id
variances = df.groupby('record_id')[['MLII', 'V1']].var()

# Calculate total lead variability as sum of variances
variances['total_lead_variability'] = variances['MLII'] + variances['V1']

# Find the record_id with the largest total lead variability
result = variances['total_lead_variability'].idxmax()
Observation: 107
Final Answer: The result is: 107
```

**Final Code Executed**

```python
# Compute variance of MLII and V1 for each record_id
variances = df.groupby('record_id')[['MLII', 'V1']].var()

# Calculate total lead variability as sum of variances
variances['total_lead_variability'] = variances['MLII'] + variances['V1']

# Find the record_id with the largest total lead variability
result = variances['total_lead_variability'].idxmax()
```

---
