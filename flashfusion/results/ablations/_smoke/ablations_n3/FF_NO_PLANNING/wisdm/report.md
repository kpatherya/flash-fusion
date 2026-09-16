# Flash-Fusion Benchmark Report

Generated: 2026-09-16T19:16:41+00:00

## Summary Table

| Baseline       |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:---------------|-------------------:|------------------:|-----------------:|
| FF_NO_PLANNING |             1.0000 |            4.0371 |           0.0015 |

## Typed-Operator Coverage

| Baseline       |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:---------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FF_NO_PLANNING |         3 |       2 | 67%        |                0 |                  1 |                    4.78 | -                          |

## Per-Query Results

### Q1: What is the maximum recorded x-acceleration for user 15?

#### FF_NO_PLANNING

**Answer:** The result is 19.57

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,AGGREGATE_COLUMN
- Latency: 3.58s | Cost: $0.00177

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['subject_id'].isin([15])]
Observation: rows=28154
Thought: typed operator step 2 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['x'].max()
Observation: 19.57
Final Answer: 19.57
```

**Final Code Executed**

```python
df = df[df['subject_id'].isin([15])]
result = df['x'].max()
```

---

### Q5: Compare the overall acceleration magnitude between dynamic (walking,jogging,upstairs,downstairs) and resting (sitting,standing) states.

#### FF_NO_PLANNING

**Answer:** The result is {'higher': 'dynamic', 'lower': 'resting', 'metric': 'mean acceleration_magnitude', 'dynamic': 11.962538760453763, 'resting': 9.8327917626509, 'difference': 2.1297469978028634}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: DERIVE_VECTOR_MAGNITUDE,SPLIT_BY_VALUES,SPLIT_BY_VALUES,AGGREGATE_PARTITIONS,COMPARE_PARTITIONS
- Latency: 5.97s | Cost: $0.00098

**Agent Trace**

```
Thought: typed operator step 1 (DERIVE_VECTOR_MAGNITUDE)
Action: typed_operator_exec
Action Input: df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
Observation: derived 'acceleration_magnitude' (rows=1098198)
Thought: typed operator step 2 (SPLIT_BY_VALUES)
Action: typed_operator_exec
Action Input: dynamic = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])]
Observation: dynamic: rows=989865
Thought: typed operator step 3 (SPLIT_BY_VALUES)
Action: typed_operator_exec
Action Input: resting = df[df['activity_label'].isin(['Sitting', 'Standing'])]
Observation: resting: rows=108333
Thought: typed operator step 4 (AGGREGATE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = {label: agg(partition) for label in partitions}
Observation: {'dynamic': 11.962538760453763, 'resting': 9.8327917626509}
Thought: typed operator step 5 (COMPARE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = compare(dynamic, resting, mode='difference')
Observation: {'higher': 'dynamic', 'lower': 'resting', 'metric': 'mean acceleration_magnitude', 'dynamic': 11.962538760453763, 'resting': 9.8327917626509, 'difference': 2.1297469978028634}
Final Answer: {'higher': 'dynamic', 'lower': 'resting', 'metric': 'mean acceleration_magnitude', 'dynamic': 11.962538760453763, 'resting': 9.8327917626509, 'difference': 2.1297469978028634}
```

**Final Code Executed**

```python
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
dynamic = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])]
resting = df[df['activity_label'].isin(['Sitting', 'Standing'])]
result = {label: agg(partition) for label in partitions}
result = compare(dynamic, resting, mode='difference')
```

---

### Q9: How does the average walking speed in miles per hour correlate with the age of the users?

#### FF_NO_PLANNING

**Answer:** Query rejected. Reason: The dataset does not contain information about the age of the users, which is necessary to answer the question about correlation with average walking speed.. This request is not supported by the current dataset schema or task scope.

- Executed: False | Rejected: True | Judge: N/A
- Stages: guardrail_plan
- Path: guardrail_reject
- Latency: 2.56s | Cost: $0.00176

**Alignment Explanation**

Rejected by the guardrail because the query cannot be answered from available dataset fields. Reason: The dataset does not contain information about the age of the users, which is necessary to answer the question about correlation with average walking speed.

**Rejection Reasoning**

- The dataset does not contain information about the age of the users, which is necessary to answer the question about correlation with average walking speed.

---
