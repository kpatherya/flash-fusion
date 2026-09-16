# Flash-Fusion Benchmark Report

Generated: 2026-09-16T18:34:27+00:00

## Summary Table

| Baseline      |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:--------------|-------------------:|------------------:|-----------------:|
| FF_NO_PRUNING |             1.0000 |            1.8138 |           0.0011 |

## Typed-Operator Coverage

| Baseline      |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:--------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FF_NO_PRUNING |         3 |       2 | 67%        |                0 |                  1 |                    1.97 | -                          |

## Per-Query Results

### Q1: What is the maximum accel_variance observed in this dataset?

#### FF_NO_PRUNING

**Answer:** The result is 5.869

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: AGGREGATE_COLUMN
- Latency: 1.48s | Cost: $0.00117

**Agent Trace**

```
Thought: typed operator step 1 (AGGREGATE_COLUMN)
Action: typed_operator_exec
Action Input: result = df['accel_variance'].max()
Observation: 5.869
Final Answer: 5.869
```

**Final Code Executed**

```python
result = df['accel_variance'].max()
```

---

### Q5: Is the northern half of the route (latitude above median) rougher than the southern half, based on average acceleration variance?

#### FF_NO_PRUNING

**Answer:** The result is {'higher': 'northern_half', 'lower': 'southern_half', 'metric': 'mean accel_variance', 'northern_half': 0.3703333333333333, 'southern_half': 0.16309016393442624, 'difference': 0.20724316939890705}

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: SPLIT_BY_THRESHOLD,SPLIT_BY_THRESHOLD,AGGREGATE_PARTITIONS,COMPARE_PARTITIONS
- Latency: 2.46s | Cost: $0.00114

**Agent Trace**

```
Thought: typed operator step 1 (SPLIT_BY_THRESHOLD)
Action: typed_operator_exec
Action Input: northern_half = df[df['latitude'] gt df['latitude'].median()]
Observation: northern_half: rows=609 (latitude gt median=33.776676)
Thought: typed operator step 2 (SPLIT_BY_THRESHOLD)
Action: typed_operator_exec
Action Input: southern_half = df[df['latitude'] lte df['latitude'].median()]
Observation: southern_half: rows=610 (latitude lte median=33.776676)
Thought: typed operator step 3 (AGGREGATE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = {label: agg(partition) for label in partitions}
Observation: {'northern_half': 0.3703333333333333, 'southern_half': 0.16309016393442624}
Thought: typed operator step 4 (COMPARE_PARTITIONS)
Action: typed_operator_exec
Action Input: result = compare(northern_half, southern_half, mode='difference')
Observation: {'higher': 'northern_half', 'lower': 'southern_half', 'metric': 'mean accel_variance', 'northern_half': 0.3703333333333333, 'southern_half': 0.16309016393442624, 'difference': 0.20724316939890705}
Final Answer: {'higher': 'northern_half', 'lower': 'southern_half', 'metric': 'mean accel_variance', 'northern_half': 0.3703333333333333, 'southern_half': 0.16309016393442624, 'difference': 0.20724316939890705}
```

**Final Code Executed**

```python
northern_half = df[df['latitude'] gt df['latitude'].median()]
southern_half = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(northern_half, southern_half, mode='difference')
```

---

### Q9: How does passenger occupancy correlate with road roughness during this trip?

#### FF_NO_PRUNING

**Answer:** Query rejected. Reason: The question requires external data: passenger occupancy is not present in the schema, and road roughness is not a literal column.. This request is not supported by the current dataset schema or task scope.

- Executed: False | Rejected: True | Judge: N/A
- Stages: guardrail_plan
- Path: guardrail_reject
- Latency: 1.51s | Cost: $0.00109

**Alignment Explanation**

Rejected by the guardrail because the query cannot be answered from available dataset fields. Reason: The question requires external data: passenger occupancy is not present in the schema, and road roughness is not a literal column.

**Rejection Reasoning**

- The question requires external data: passenger occupancy is not present in the schema, and road roughness is not a literal column.

---
