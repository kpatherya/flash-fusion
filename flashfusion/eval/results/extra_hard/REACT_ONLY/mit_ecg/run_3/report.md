# Flash-Fusion Benchmark Report

Generated: 2026-09-15T22:47:52+00:00

## Summary Table

| Baseline   |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-----------|-------------------:|------------------:|-----------------:|
| REACT_ONLY |             0.7500 |           16.7018 |           0.0009 |

## Typed-Operator Coverage

| Baseline   |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject | Typed avg latency (s)   | Fallback avg latency (s)   |
|:-----------|----------:|--------:|:-----------|-----------------:|-------------------:|:------------------------|:---------------------------|
| REACT_ONLY |         4 |       0 | 0%         |                0 |                  0 | -                       | -                          |

## Per-Query Results

### Q17: Among rows whose annotation is one of the known MIT-ECG annotation codes, partition each record_id's time_s values into consecutive groups of width 10. For each group, compute MLII RMS. Return the group with the greatest RMS.

#### REACT_ONLY

**Answer:** The result is: record_id    116.000000
group_id     140.000000
rms            3.075805
Name: 1950, dtype: float64

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 21.69s | Cost: $0.00139

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Filter rows with non-empty annotation that are among known MIT-ECG codes
# According to the note, empty string indicates missing; all other values in annotation are valid MIT-ECG codes
filtered_df = df[df['annotation'] != ''].copy()

# Create group_id as floor division of time_s by 10 to form consecutive groups of width 10
filtered_df['group_id'] = (filtered_df['time_s'] // 10).astype(int)

# Compute RMS of MLII for each (record_id, group_id) group
# RMS = sqrt(mean(square(MLII)))
rms_per_group = filtered_df.groupby(['record_id', 'group_id'])['MLII'].apply(
    lambda x: (x ** 2).mean() ** 0.5
).reset_index(name='rms')

# Find the group with the greatest RMS
max_rms_row = rms_per_group.loc[rms_per_group['rms'].idxmax()]

# Return the full group info (record_id, group_id, rms)
result = max_rms_row
Observation: record_id    116.000000
group_id     140.000000
rms            3.075805
Name: 1950, dtype: float64
Final Answer: The result is: record_id    116.000000
group_id     140.000000
rms            3.075805
Name: 1950, dtype: float64
```

**Final Code Executed**

```python
# Filter rows with non-empty annotation that are among known MIT-ECG codes
# According to the note, empty string indicates missing; all other values in annotation are valid MIT-ECG codes
filtered_df = df[df['annotation'] != ''].copy()

# Create group_id as floor division of time_s by 10 to form consecutive groups of width 10
filtered_df['group_id'] = (filtered_df['time_s'] // 10).astype(int)

# Compute RMS of MLII for each (record_id, group_id) group
# RMS = sqrt(mean(square(MLII)))
rms_per_group = filtered_df.groupby(['record_id', 'group_id'])['MLII'].apply(
    lambda x: (x ** 2).mean() ** 0.5
).reset_index(name='rms')

# Find the group with the greatest RMS
max_rms_row = rms_per_group.loc[rms_per_group['rms'].idxmax()]

# Return the full group info (record_id, group_id, rms)
result = max_rms_row
```

---

### Q18: For every record_id, independently compute maximum and minimum MLII. Define MLII span as maximum minus minimum. Return the record_id with the largest MLII span.

#### REACT_ONLY

**Answer:** The result is: 116

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 17.90s | Cost: $0.00063

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

**Answer:** REJECT: Missing required dataset concept(s): known annotation-code list.

- Executed: False | Rejected: True | Judge: N/A
- Stages: react_agent
- Path: react_reject
- Latency: 8.01s | Cost: $0.00058

**Agent Trace**

```
Thought: Scope check rejected the request before code generation
Final Answer: REJECT: Missing required dataset concept(s): known annotation-code list.
```

**Rejection Reasoning**

- Missing required dataset concept(s): known annotation-code list.

---

### Q20: For every record_id, independently compute MLII variance and V1 variance. Define total lead variability as their sum. Return the record_id with the largest total lead variability.

#### REACT_ONLY

**Answer:** The result is: 107

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 19.21s | Cost: $0.00083

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute variance of MLII and V1 for each record_id
grouped = df.groupby('record_id')
ml2_var = grouped['MLII'].var()
v1_var = grouped['V1'].var()

# Calculate total lead variability as sum of variances
total_variability = ml2_var + v1_var

# Find record_id with largest total lead variability
result = total_variability.idxmax()
Observation: 107
Final Answer: The result is: 107
```

**Final Code Executed**

```python
# Compute variance of MLII and V1 for each record_id
grouped = df.groupby('record_id')
ml2_var = grouped['MLII'].var()
v1_var = grouped['V1'].var()

# Calculate total lead variability as sum of variances
total_variability = ml2_var + v1_var

# Find record_id with largest total lead variability
result = total_variability.idxmax()
```

---
