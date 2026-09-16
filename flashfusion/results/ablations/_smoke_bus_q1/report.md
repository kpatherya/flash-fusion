# Flash-Fusion Benchmark Report

Generated: 2026-09-16T18:06:08+00:00

## Summary Table

| Baseline       |   Avg LLM Accuracy |   Avg Latency (s) |   Avg Cost (USD) |
|:---------------|-------------------:|------------------:|-----------------:|
| FF_NO_PLANNING |             1.0000 |            2.0435 |           0.0094 |
| FF_NO_PRUNING  |             1.0000 |            2.6059 |           0.0096 |
| FLASH_FUSION   |             1.0000 |            1.9137 |           0.0014 |

## Typed-Operator Coverage

| Baseline       |   Queries |   Typed | Coverage   |   ReAct fallback |   Guardrail reject |   Typed avg latency (s) | Fallback avg latency (s)   |
|:---------------|----------:|--------:|:-----------|-----------------:|-------------------:|------------------------:|:---------------------------|
| FLASH_FUSION   |         1 |       1 | 100%       |                0 |                  0 |                    1.91 | -                          |
| FF_NO_PRUNING  |         1 |       1 | 100%       |                0 |                  0 |                    2.61 | -                          |
| FF_NO_PLANNING |         1 |       1 | 100%       |                0 |                  0 |                    2.04 | -                          |

## Per-Query Results

### Q1: What is the maximum accel_variance observed in this dataset?

#### FLASH_FUSION

**Answer:** The result is 5.869

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: AGGREGATE_COLUMN
- Latency: 1.91s | Cost: $0.00142

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

#### FF_NO_PRUNING

**Answer:** The result is 5.869

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: AGGREGATE_COLUMN
- Latency: 2.61s | Cost: $0.00964

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

#### FF_NO_PLANNING

**Answer:** The result is 5.869

- Executed: True | Rejected: False | Judge: N/A
- Stages: guardrail_plan,plan_validated,typed_exec
- Path: typed_operator
- Operators: AGGREGATE_COLUMN
- Latency: 2.04s | Cost: $0.00935

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
