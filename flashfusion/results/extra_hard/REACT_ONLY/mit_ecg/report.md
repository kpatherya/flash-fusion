# Flash-Fusion Benchmark Report

Generated: 2026-09-15T19:27:32+00:00

## Summary Table

| Baseline   |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:-----------|-------------------:|------------------:|-----------------:|
| REACT_ONLY |             0.5833 |           12.1301 |           0.0008 |

## Typed-Operator Coverage

| Baseline   |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject | Typed avg latency (s)   | Fallback avg latency (s)   |
|:-----------|----------:|--------:|:-----------|-----------------:|-------------------:|:------------------------|:---------------------------|
| REACT_ONLY |        12 |       0 | 0%         |                0 |                  0 | -                       | -                          |

## Per-Query Results

### Q17: Among rows whose annotation is one of the known MIT-ECG annotation codes, divide time_s into 10-second bins. For each (record_id, bin) pair, compute MLII RMS. Return the (record_id, bin) pair with the greatest RMS.

#### REACT_ONLY

**Answer:** The result is: (np.int32(116), np.int64(140))

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 13.10s | Cost: $0.00102

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Filter rows with non-empty annotation
filtered_df = df[df['annotation'] != '']

# Define 10-second bins for time_s
filtered_df = filtered_df.copy()
filtered_df['bin'] = (filtered_df['time_s'] // 10).astype(int)

# Group by record_id and bin, compute RMS of MLII
grouped = filtered_df.groupby(['record_id', 'bin'])['MLII'].apply(lambda x: (x**2).mean()**0.5)

# Find the (record_id, bin) pair with the greatest RMS
max_pair = grouped.idxmax()

result = max_pair
Observation: (np.int32(116), np.int64(140))
Final Answer: The result is: (np.int32(116), np.int64(140))
```

**Final Code Executed**

```python
# Filter rows with non-empty annotation
filtered_df = df[df['annotation'] != '']

# Define 10-second bins for time_s
filtered_df = filtered_df.copy()
filtered_df['bin'] = (filtered_df['time_s'] // 10).astype(int)

# Group by record_id and bin, compute RMS of MLII
grouped = filtered_df.groupby(['record_id', 'bin'])['MLII'].apply(lambda x: (x**2).mean()**0.5)

# Find the (record_id, bin) pair with the greatest RMS
max_pair = grouped.idxmax()

result = max_pair
```

---

#### REACT_ONLY

**Answer:** The result is: (np.int32(116), np.int64(1400))

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 15.69s | Cost: $0.00113

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Filter rows with non-empty annotation
df_filtered = df[df['annotation'] != '']

# Define MIT-ECG annotation codes (excluding empty string)
mit_ecg_codes = {'+', 'N', '~', '|', 'Q', 'A', 'V', '/', 'x', 'F', 'j', 'L', 'a', 'R', 'J', '[', '!', ']', 'E', 'S', '"', 'f', 'e'}

# Further filter to only include rows with known MIT-ECG annotation codes
df_mit = df_filtered[df_filtered['annotation'].isin(mit_ecg_codes)]

# Create 10-second bins for time_s
df_mit = df_mit.copy()
df_mit['bin'] = (df_mit['time_s'] // 10).astype(int) * 10

# Group by record_id and bin, compute RMS of MLII
def rms(x):
    return (x ** 2).mean() ** 0.5

grouped = df_mit.groupby(['record_id', 'bin'])['MLII'].apply(rms)

# Find the (record_id, bin) pair with the greatest RMS
max_pair = grouped.idxmax()

result = max_pair
Observation: (np.int32(116), np.int64(1400))
Final Answer: The result is: (np.int32(116), np.int64(1400))
```

**Final Code Executed**

```python
# Filter rows with non-empty annotation
df_filtered = df[df['annotation'] != '']

# Define MIT-ECG annotation codes (excluding empty string)
mit_ecg_codes = {'+', 'N', '~', '|', 'Q', 'A', 'V', '/', 'x', 'F', 'j', 'L', 'a', 'R', 'J', '[', '!', ']', 'E', 'S', '"', 'f', 'e'}

# Further filter to only include rows with known MIT-ECG annotation codes
df_mit = df_filtered[df_filtered['annotation'].isin(mit_ecg_codes)]

# Create 10-second bins for time_s
df_mit = df_mit.copy()
df_mit['bin'] = (df_mit['time_s'] // 10).astype(int) * 10

# Group by record_id and bin, compute RMS of MLII
def rms(x):
    return (x ** 2).mean() ** 0.5

grouped = df_mit.groupby(['record_id', 'bin'])['MLII'].apply(rms)

# Find the (record_id, bin) pair with the greatest RMS
max_pair = grouped.idxmax()

result = max_pair
```

---

#### REACT_ONLY

**Answer:** The result is: (np.int32(116), np.int64(140))

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 23.29s | Cost: $0.00107

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Filter rows with non-empty annotation
df_filtered = df[df['annotation'] != '']

# Define 10-second bins for time_s
df_filtered = df_filtered.copy()
df_filtered['bin'] = (df_filtered['time_s'] // 10).astype(int)

# Group by record_id and bin, compute RMS of MLII
def rms(series):
    return (series ** 2).mean() ** 0.5

rms_values = df_filtered.groupby(['record_id', 'bin'])['MLII'].apply(rms)

# Find the (record_id, bin) pair with the greatest RMS
max_pair = rms_values.idxmax()

result = max_pair
Observation: (np.int32(116), np.int64(140))
Final Answer: The result is: (np.int32(116), np.int64(140))
```

**Final Code Executed**

```python
# Filter rows with non-empty annotation
df_filtered = df[df['annotation'] != '']

# Define 10-second bins for time_s
df_filtered = df_filtered.copy()
df_filtered['bin'] = (df_filtered['time_s'] // 10).astype(int)

# Group by record_id and bin, compute RMS of MLII
def rms(series):
    return (series ** 2).mean() ** 0.5

rms_values = df_filtered.groupby(['record_id', 'bin'])['MLII'].apply(rms)

# Find the (record_id, bin) pair with the greatest RMS
max_pair = rms_values.idxmax()

result = max_pair
```

---

### Q18: For every record_id, independently compute maximum and minimum MLII. Define MLII span as maximum minus minimum. Return the record_id with the largest MLII span.

#### REACT_ONLY

**Answer:** The result is: 116

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 10.04s | Cost: $0.00063

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

#### REACT_ONLY

**Answer:** The result is: 116

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 11.05s | Cost: $0.00063

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

#### REACT_ONLY

**Answer:** The result is: 116

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 16.40s | Cost: $0.00063

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
- Latency: 4.76s | Cost: $0.00058

**Agent Trace**

```
Thought: Scope check rejected the request before code generation
Final Answer: REJECT: Missing required dataset concept(s): known annotation-code list.
```

**Rejection Reasoning**

- Missing required dataset concept(s): known annotation-code list.

---

#### REACT_ONLY

**Answer:** REJECT: Missing required dataset concept(s): known annotation-code list.

- Executed: False | Rejected: True | Judge: N/A
- Stages: react_agent
- Path: react_reject
- Latency: 4.90s | Cost: $0.00058

**Agent Trace**

```
Thought: Scope check rejected the request before code generation
Final Answer: REJECT: Missing required dataset concept(s): known annotation-code list.
```

**Rejection Reasoning**

- Missing required dataset concept(s): known annotation-code list.

---

#### REACT_ONLY

**Answer:** REJECT: Missing required dataset concept(s): known annotation-code list.

- Executed: False | Rejected: True | Judge: N/A
- Stages: react_agent
- Path: react_reject
- Latency: 9.53s | Cost: $0.00101

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
- Latency: 11.91s | Cost: $0.00083

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute variance of MLII and V1 for each record_id
mlII_var = df.groupby('record_id')['MLII'].var()
v1_var = df.groupby('record_id')['V1'].var()

# Sum the variances to get total lead variability
total_variability = mlII_var + v1_var

# Find the record_id with the largest total lead variability
result = total_variability.idxmax()
Observation: 107
Final Answer: The result is: 107
```

**Final Code Executed**

```python
# Compute variance of MLII and V1 for each record_id
mlII_var = df.groupby('record_id')['MLII'].var()
v1_var = df.groupby('record_id')['V1'].var()

# Sum the variances to get total lead variability
total_variability = mlII_var + v1_var

# Find the record_id with the largest total lead variability
result = total_variability.idxmax()
```

---

#### REACT_ONLY

**Answer:** The result is: 107

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 13.12s | Cost: $0.00083

**Agent Trace**

```
Thought: Attempt 1: generate executable pandas code
Action: python_exec
Action Input: # Compute variance of MLII and V1 for each record_id
mlII_var = df.groupby('record_id')['MLII'].var()
v1_var = df.groupby('record_id')['V1'].var()

# Sum the variances to get total lead variability
total_variability = mlII_var + v1_var

# Find the record_id with the largest total lead variability
result = total_variability.idxmax()
Observation: 107
Final Answer: The result is: 107
```

**Final Code Executed**

```python
# Compute variance of MLII and V1 for each record_id
mlII_var = df.groupby('record_id')['MLII'].var()
v1_var = df.groupby('record_id')['V1'].var()

# Sum the variances to get total lead variability
total_variability = mlII_var + v1_var

# Find the record_id with the largest total lead variability
result = total_variability.idxmax()
```

---

#### REACT_ONLY

**Answer:** The result is: 107

- Executed: True | Rejected: False | Judge: N/A
- Stages: react_agent
- Path: react_agent
- Latency: 11.77s | Cost: $0.00083

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
