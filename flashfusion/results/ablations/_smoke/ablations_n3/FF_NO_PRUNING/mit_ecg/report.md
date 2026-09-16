# Flash-Fusion Benchmark Report

Generated: 2026-09-16T18:34:06+00:00

## Summary Table

| Baseline      |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:--------------|-------------------:|------------------:|-----------------:|
| FF_NO_PRUNING |             1.0000 |            3.6581 |           0.0014 |

## Typed-Operator Coverage

| Baseline      |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:--------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FF_NO_PRUNING |         3 |       2 | 67%        |                0 |                  1 |                    4.67 | -                          |

## Per-Query Results

### Q1: What is the minimum MLII value recorded for record_id 101?

#### FF_NO_PRUNING

**Answer:** The result is -3.175

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,AGGREGATE_COLUMN
- Latency: 5.59s | Cost: $0.00201

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['record_id'].isin([101])]
Observation: rows=650000
Thought: typed operator step 2 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['MLII'].min()
Observation: -3.175
Final Answer: -3.175
```

**Final Code Executed**

```python
df = df[df['record_id'].isin([101])]
result = df['MLII'].min()
```

---

### Q5: For record_id 208, what is the average count of rows with a non-empty annotation in each 60-second time_s bin?

#### FF_NO_PRUNING

**Answer:** The result is 98.06451612903226

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: FILTER_IN,FILTER_NOT_EMPTY,DERIVE_BIN,GROUP_AGGREGATE,AGGREGATE_GROUPS
- Latency: 3.74s | Cost: $0.00107

**Agent Trace**

```
Thought: typed operator step 1 (FILTER_IN)
Action: typed_operator_exec
Action Input: df = df[df['record_id'].isin([208])]
Observation: rows=650000
Thought: typed operator step 2 (FILTER_NOT_EMPTY)
Action: typed_operator_exec
Action Input: df = df[df['annotation'].notna() & df['annotation'].astype(str).str.strip().ne('')]
Observation: rows=3040
Thought: typed operator step 3 (DERIVE_BIN)
Action: typed_operator_exec
Action Input: df['time_bin'] = (df['time_s'] // 60.0) * 60.0
Observation: derived 'time_bin' (kind=numeric width=60.0)
Thought: typed operator step 4 (GROUP_AGGREGATE)
Action: typed_operator_exec
Action Input: result = df.groupby('time_bin').size()
Observation: {'0.0': 111, '60.0': 105, '120.0': 106, '180.0': 109, '240.0': 106, '300.0': 109, '360.0': 108, '420.0': 95, '480.0': 94, '540.0': 97, '600.0': 101, '660.0': 98, '720.0': 95, '780.0': 98, '840.0': 99, '900.0': 103, '960.0': 97, '1020.0': 97, '1080.0': 94, '1140.0': 106, '1200.0': 112, '1260.0': 103, '1320.0': 103, '1380.0': 107, '1440.0': 103, '1500.0': 108, '1560.0': 93, '1620.0': 93, '1680.0': 89, '1740.0': 92, '1800.0': 9}
Thought: typed operator step 5 (AGGREGATE_GROUPS)
Action: typed_operator_exec
Action Input: result = result.mean()
Observation: 98.06451612903226
Final Answer: 98.06451612903226
```

**Final Code Executed**

```python
df = df[df['record_id'].isin([208])]
df = df[df['annotation'].notna() & df['annotation'].astype(str).str.strip().ne('')]
df['time_bin'] = (df['time_s'] // 60.0) * 60.0
result = df.groupby('time_bin').size()
result = result.mean()
```

---

### Q9: Did the patient corresponding to record_id 101 experience a fatal cardiac event within a year?

#### FF_NO_PRUNING

**Answer:** Query rejected. Reason: The question requires external knowledge about the patient's medical history and the definition of a fatal cardiac event, which is not present in the provided schema.. This request is not supported by the current dataset schema or task scope.

- Executed: False | Rejected: True | Judge: N/A
- Stages: guardrail_plan
- Path: guardrail_reject
- Latency: 1.64s | Cost: $0.00103

**Alignment Explanation**

Rejected by the guardrail because the query cannot be answered from available dataset fields. Reason: The question requires external knowledge about the patient's medical history and the definition of a fatal cardiac event, which is not present in the provided schema.

**Rejection Reasoning**

- The question requires external knowledge about the patient's medical history and the definition of a fatal cardiac event, which is not present in the provided schema.

---
