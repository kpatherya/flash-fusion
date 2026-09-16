# Cache Grounding Issues

Reported 12 FLASH_FUSION_CACHE grounding failure(s) where the cached skeleton could not be reused directly.

## Query 17 (run 1)

**Query text:** Among rows whose annotation is one of the known MIT-ECG annotation codes, partition each record_id's time_s values into consecutive groups of width 10. For each group, compute MLII RMS. Return the group with the greatest RMS.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "FILTER_NOT_EMPTY",
      "column": "annotation"
    },
    {
      "op": "DERIVE_BIN",
      "column": "time_s",
      "kind": "numeric",
      "width": 10.0,
      "freq": null,
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "record_id",
        "time_bin"
      ],
      "aggregate": "rms",
      "column": "MLII",
      "freq": null
    },
    {
      "op": "RANK_GROUPS",
      "direction": "max"
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "FILTER_NOT_EMPTY",
        "column": "annotation"
      },
      {
        "op": "DERIVE_BIN",
        "column": "time_s",
        "width": 10.0,
        "result": "time_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "record_id",
          "time_bin"
        ],
        "aggregate": "rms",
        "column": "MLII"
      },
      {
        "op": "RANK_GROUPS",
        "direction": "max"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['annotation'].notna() & df['annotation'].astype(str).str.strip().ne('')]
df['time_bin'] = (df['time_s'] // 10.0) * 10.0
result = df.groupby(['record_id', 'time_bin'])['MLII'].apply(rms)
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 1)

**Query text:** For every record_id, independently compute maximum and minimum MLII. Define MLII span as maximum minus minimum. Return the record_id with the largest MLII span.

**Failure reason:** `structural: 1 validation error for GuardrailAndPlan
plan.steps.1.DERIVE_BINARY.operation
  Input should be 'add', 'subtract', 'multiply', 'divide' or 'abs_difference' [type=literal_error, input_value='difference', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/literal_error`

**Execution path after fallback:** `typed_plan_unavailable`

**Plan source after fallback:** `llm`

**Plan validation stage failed:** `structural`

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → typed_plan_unavailable

---

## Query 19 (run 1)

**Query text:** For record_id 101, divide time_s into 10-second bins. For each bin, compute annotated-row rate as rows with an annotation in the known annotation-code list divided by all rows in the bin. Return the Pearson correlation between bin index and annotated-row rate.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "FILTER_IN",
      "column": "record_id",
      "values": [
        101
      ]
    },
    {
      "op": "DERIVE_BIN",
      "column": "time_s",
      "kind": "numeric",
      "width": 10.0,
      "freq": null,
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "annotation",
          "filter_values": [
            "!",
            "\"",
            "+",
            "/",
            "A",
            "E",
            "F",
            "J",
            "L",
            "N",
            "Q",
            "R",
            "S",
            "V",
            "[",
            "]",
            "a",
            "e",
            "f",
            "j",
            "x",
            "|",
            "~"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "count",
          "column": null,
          "result_column": "annotated_count"
        },
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "time_bin"
          ],
          "aggregate": "count",
          "column": null,
          "result_column": "total_count"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "annotated_count",
      "right": "total_count",
      "operation": "divide",
      "result": "annotated_rate"
    },
    {
      "op": "CORRELATE_COLUMNS",
      "left": "time_bin",
      "right": "annotated_rate",
      "method": "pearson"
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "FILTER_IN",
        "column": "record_id",
        "values": [
          101
        ]
      },
      {
        "op": "DERIVE_BIN",
        "column": "time_s",
        "kind": "numeric",
        "width": 10.0,
        "result": "time_bin"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "annotation",
            "filter_values": [
              "+",
              "N",
              "~",
              "|",
              "Q",
              "A",
              "V",
              "/",
              "x",
              "F",
              "j",
              "L",
              "a",
              "R",
              "J",
              "[",
              "!",
              "]",
              "E",
              "S",
              "\"",
              "f",
              "e"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "count",
            "column": null,
            "result_column": "annotated_count"
          },
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "time_bin"
            ],
            "aggregate": "count",
            "column": null,
            "result_column": "total_count"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "annotated_count",
        "right": "total_count",
        "operation": "divide",
        "result": "annotated_rate"
      },
      {
        "op": "CORRELATE_COLUMNS",
        "left": "time_bin",
        "right": "annotated_rate",
        "method": "pearson"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['record_id'].isin([101])]
df['time_bin'] = (df['time_s'] // 10.0) * 10.0
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['annotation'].isin(['!', '"', '+', '/', 'A', 'E', 'F', 'J', 'L', 'N', 'Q', 'R', 'S', 'V', '[', ']', 'a', 'e', 'f', 'j', 'x', '|', '~'])].groupby(['time_bin']).size()
branch_1 = df.groupby(['time_bin']).size()
merged = branch_0.merge(branch_1, on=['time_bin'], how='outer')
merged[['annotated_count', 'total_count']] = merged[['annotated_count', 'total_count']].fillna(0)
df['annotated_rate'] = df['annotated_count'] / df['total_count']
result = df['time_bin'].corr(df['annotated_rate'], method='pearson')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 1)

**Query text:** For every record_id, independently compute MLII variance and V1 variance. Define total lead variability as their sum. Return the record_id with the largest total lead variability.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "record_id"
          ],
          "aggregate": "var",
          "column": "MLII",
          "result_column": "mlii_var"
        },
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "record_id"
          ],
          "aggregate": "var",
          "column": "V1",
          "result_column": "v1_var"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "mlii_var",
      "right": "v1_var",
      "operation": "add",
      "result": "total_lead_variability"
    },
    {
      "op": "RANK_ROWS",
      "column": "total_lead_variability",
      "direction": "max",
      "return_columns": [
        "record_id",
        "total_lead_variability"
      ]
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "record_id"
            ],
            "aggregate": "var",
            "column": "MLII",
            "result_column": "mlii_var"
          },
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "record_id"
            ],
            "aggregate": "var",
            "column": "V1",
            "result_column": "v1_var"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "mlii_var",
        "right": "v1_var",
        "operation": "add",
        "result": "total_lead_variability"
      },
      {
        "op": "RANK_ROWS",
        "column": "total_lead_variability",
        "direction": "max",
        "return_columns": [
          "record_id",
          "total_lead_variability"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
# PARALLEL_AGGREGATE branches:
branch_0 = df.groupby(['record_id'])['MLII'].var()
branch_1 = df.groupby(['record_id'])['V1'].var()
merged = branch_0.merge(branch_1, on=['record_id'], how='outer')
df['total_lead_variability'] = df['mlii_var'] + df['v1_var']
idx = df['total_lead_variability'].idxmax(); result = df.loc[idx, ['record_id', 'total_lead_variability']].to_dict()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 17 (run 2)

**Query text:** Among rows whose annotation is one of the known MIT-ECG annotation codes, partition each record_id's time_s values into consecutive groups of width 10. For every group, Calculate MLII RMS. Return the group with the greatest RMS.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "FILTER_NOT_EMPTY",
      "column": "annotation"
    },
    {
      "op": "DERIVE_BIN",
      "column": "time_s",
      "kind": "numeric",
      "width": 10.0,
      "freq": null,
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "record_id",
        "time_bin"
      ],
      "aggregate": "rms",
      "column": "MLII",
      "freq": null
    },
    {
      "op": "RANK_GROUPS",
      "direction": "max"
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "FILTER_NOT_EMPTY",
        "column": "annotation"
      },
      {
        "op": "DERIVE_BIN",
        "column": "time_s",
        "width": 10.0,
        "result": "time_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "record_id",
          "time_bin"
        ],
        "aggregate": "rms",
        "column": "MLII"
      },
      {
        "op": "RANK_GROUPS",
        "direction": "max"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['annotation'].notna() & df['annotation'].astype(str).str.strip().ne('')]
df['time_bin'] = (df['time_s'] // 10.0) * 10.0
result = df.groupby(['record_id', 'time_bin'])['MLII'].apply(rms)
result = result.idxmax()
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 2)

**Query text:** For every record_id, independently Calculate maximum and minimum MLII. Define MLII span as maximum minus minimum. Return the record_id with the largest MLII span.

**Failure reason:** `structural: 1 validation error for GuardrailAndPlan
plan.steps.1.DERIVE_BINARY.operation
  Input should be 'add', 'subtract', 'multiply', 'divide' or 'abs_difference' [type=literal_error, input_value='difference', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/literal_error`

**Execution path after fallback:** `typed_plan_unavailable`

**Plan source after fallback:** `llm`

**Plan validation stage failed:** `structural`

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → typed_plan_unavailable

---

## Query 19 (run 2)

**Query text:** For record_id 101, divide time_s into 10-second bins. For every bin, Calculate annotated-row rate as rows with an annotation in the known annotation-code list divided by all rows in the bin. Return the Pearson correlation between bin index and annotated-row rate.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "FILTER_COMPARE",
      "column": "record_id",
      "comparator": "eq",
      "value": 101
    },
    {
      "op": "DERIVE_BIN",
      "column": "time_s",
      "kind": "numeric",
      "width": 10.0,
      "freq": null,
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "annotation",
          "filter_values": [
            "!",
            "\"",
            "+",
            "/",
            "A",
            "E",
            "F",
            "J",
            "L",
            "N",
            "Q",
            "R",
            "S",
            "V",
            "[",
            "]",
            "a",
            "e",
            "f",
            "j",
            "x",
            "|",
            "~"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "count",
          "column": null,
          "result_column": "annotated_count"
        },
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "time_bin"
          ],
          "aggregate": "count",
          "column": null,
          "result_column": "total_count"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "annotated_count",
      "right": "total_count",
      "operation": "divide",
      "result": "annotated_rate"
    },
    {
      "op": "CORRELATE_COLUMNS",
      "left": "time_bin",
      "right": "annotated_rate",
      "method": "pearson"
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "FILTER_COMPARE",
        "column": "record_id",
        "comparator": "eq",
        "value": 101
      },
      {
        "op": "DERIVE_BIN",
        "column": "time_s",
        "kind": "numeric",
        "width": 10.0,
        "result": "time_bin"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "annotation",
            "filter_values": [
              "+",
              "N",
              "~",
              "|",
              "Q",
              "A",
              "V",
              "/",
              "x",
              "F",
              "j",
              "L",
              "a",
              "R",
              "J",
              "[",
              "!",
              "]",
              "E",
              "S",
              "\"",
              "f",
              "e"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "count",
            "column": null,
            "result_column": "annotated_count"
          },
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "time_bin"
            ],
            "aggregate": "count",
            "column": null,
            "result_column": "total_count"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "annotated_count",
        "right": "total_count",
        "operation": "divide",
        "result": "annotated_rate"
      },
      {
        "op": "CORRELATE_COLUMNS",
        "left": "time_bin",
        "right": "annotated_rate",
        "method": "pearson"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['record_id'] == 101]
df['time_bin'] = (df['time_s'] // 10.0) * 10.0
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['annotation'].isin(['!', '"', '+', '/', 'A', 'E', 'F', 'J', 'L', 'N', 'Q', 'R', 'S', 'V', '[', ']', 'a', 'e', 'f', 'j', 'x', '|', '~'])].groupby(['time_bin']).size()
branch_1 = df.groupby(['time_bin']).size()
merged = branch_0.merge(branch_1, on=['time_bin'], how='outer')
merged[['annotated_count', 'total_count']] = merged[['annotated_count', 'total_count']].fillna(0)
df['annotated_rate'] = df['annotated_count'] / df['total_count']
result = df['time_bin'].corr(df['annotated_rate'], method='pearson')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 2)

**Query text:** For every record_id, independently Calculate MLII variance and V1 variance. Define total lead variability as their sum. Return the record_id with the largest total lead variability.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "record_id"
          ],
          "aggregate": "var",
          "column": "MLII",
          "result_column": "mlii_var"
        },
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "record_id"
          ],
          "aggregate": "var",
          "column": "V1",
          "result_column": "v1_var"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "mlii_var",
      "right": "v1_var",
      "operation": "add",
      "result": "total_lead_variability"
    },
    {
      "op": "RANK_ROWS",
      "column": "total_lead_variability",
      "direction": "max",
      "return_columns": [
        "record_id",
        "total_lead_variability"
      ]
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "record_id"
            ],
            "aggregate": "var",
            "column": "MLII",
            "result_column": "mlii_var"
          },
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "record_id"
            ],
            "aggregate": "var",
            "column": "V1",
            "result_column": "v1_var"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "mlii_var",
        "right": "v1_var",
        "operation": "add",
        "result": "total_lead_variability"
      },
      {
        "op": "RANK_ROWS",
        "column": "total_lead_variability",
        "direction": "max",
        "return_columns": [
          "record_id",
          "total_lead_variability"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
# PARALLEL_AGGREGATE branches:
branch_0 = df.groupby(['record_id'])['MLII'].var()
branch_1 = df.groupby(['record_id'])['V1'].var()
merged = branch_0.merge(branch_1, on=['record_id'], how='outer')
df['total_lead_variability'] = df['mlii_var'] + df['v1_var']
idx = df['total_lead_variability'].idxmax(); result = df.loc[idx, ['record_id', 'total_lead_variability']].to_dict()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 17 (run 3)

**Query text:** Among rows whose annotation is one of the known MIT-ECG annotation codes, partition each record_id's time_s values into consecutive groups of width 10. For every group, Determine MLII RMS. Return the group with the greatest RMS.

**Failure reason:** `cache: semantic: semantic_ambiguous_candidates`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "FILTER_NOT_EMPTY",
      "column": "annotation"
    },
    {
      "op": "DERIVE_BIN",
      "column": "time_s",
      "kind": "numeric",
      "width": 10.0,
      "freq": null,
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "record_id",
        "time_bin"
      ],
      "aggregate": "rms",
      "column": "MLII",
      "freq": null
    },
    {
      "op": "RANK_GROUPS",
      "direction": "max"
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "FILTER_NOT_EMPTY",
        "column": "annotation"
      },
      {
        "op": "DERIVE_BIN",
        "column": "time_s",
        "width": 10.0,
        "result": "time_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "record_id",
          "time_bin"
        ],
        "aggregate": "rms",
        "column": "MLII"
      },
      {
        "op": "RANK_GROUPS",
        "direction": "max"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['annotation'].notna() & df['annotation'].astype(str).str.strip().ne('')]
df['time_bin'] = (df['time_s'] // 10.0) * 10.0
result = df.groupby(['record_id', 'time_bin'])['MLII'].apply(rms)
result = result.idxmax()
```

**Stages run:** hybrid_semantic_ambiguous_candidates → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 3)

**Query text:** For every record_id, independently Determine maximum and minimum MLII. Define MLII span as maximum minus minimum. Return the record_id with the largest MLII span.

**Failure reason:** `structural: 1 validation error for GuardrailAndPlan
plan.steps.1.DERIVE_BINARY.operation
  Input should be 'add', 'subtract', 'multiply', 'divide' or 'abs_difference' [type=literal_error, input_value='difference', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/literal_error`

**Execution path after fallback:** `typed_plan_unavailable`

**Plan source after fallback:** `llm`

**Plan validation stage failed:** `structural`

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → typed_plan_unavailable

---

## Query 19 (run 3)

**Query text:** For record_id 101, divide time_s into 10-second bins. For every bin, Determine annotated-row rate as rows with an annotation in the known annotation-code list divided by all rows in the bin. Return the Pearson correlation between bin index and annotated-row rate.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "FILTER_COMPARE",
      "column": "record_id",
      "comparator": "eq",
      "value": 101
    },
    {
      "op": "DERIVE_BIN",
      "column": "time_s",
      "kind": "numeric",
      "width": 10.0,
      "freq": null,
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "annotation",
          "filter_values": [
            "!",
            "\"",
            "+",
            "/",
            "A",
            "E",
            "F",
            "J",
            "L",
            "N",
            "Q",
            "R",
            "S",
            "V",
            "[",
            "]",
            "a",
            "e",
            "f",
            "j",
            "x",
            "|",
            "~"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "count",
          "column": null,
          "result_column": "annotated_count"
        },
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "time_bin"
          ],
          "aggregate": "count",
          "column": null,
          "result_column": "total_count"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "annotated_count",
      "right": "total_count",
      "operation": "divide",
      "result": "annotated_rate"
    },
    {
      "op": "CORRELATE_COLUMNS",
      "left": "time_bin",
      "right": "annotated_rate",
      "method": "pearson"
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "FILTER_COMPARE",
        "column": "record_id",
        "comparator": "eq",
        "value": 101
      },
      {
        "op": "DERIVE_BIN",
        "column": "time_s",
        "kind": "numeric",
        "width": 10.0,
        "result": "time_bin"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "annotation",
            "filter_values": [
              "+",
              "N",
              "~",
              "|",
              "Q",
              "A",
              "V",
              "/",
              "x",
              "F",
              "j",
              "L",
              "a",
              "R",
              "J",
              "[",
              "!",
              "]",
              "E",
              "S",
              "\"",
              "f",
              "e"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "count",
            "column": null,
            "result_column": "annotated_count"
          },
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "time_bin"
            ],
            "aggregate": "count",
            "column": null,
            "result_column": "total_count"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "annotated_count",
        "right": "total_count",
        "operation": "divide",
        "result": "annotated_rate"
      },
      {
        "op": "CORRELATE_COLUMNS",
        "left": "time_bin",
        "right": "annotated_rate",
        "method": "pearson"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['record_id'] == 101]
df['time_bin'] = (df['time_s'] // 10.0) * 10.0
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['annotation'].isin(['!', '"', '+', '/', 'A', 'E', 'F', 'J', 'L', 'N', 'Q', 'R', 'S', 'V', '[', ']', 'a', 'e', 'f', 'j', 'x', '|', '~'])].groupby(['time_bin']).size()
branch_1 = df.groupby(['time_bin']).size()
merged = branch_0.merge(branch_1, on=['time_bin'], how='outer')
merged[['annotated_count', 'total_count']] = merged[['annotated_count', 'total_count']].fillna(0)
df['annotated_rate'] = df['annotated_count'] / df['total_count']
result = df['time_bin'].corr(df['annotated_rate'], method='pearson')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 3)

**Query text:** For every record_id, independently Determine MLII variance and V1 variance. Define total lead variability as their sum. Return the record_id with the largest total lead variability.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "record_id"
          ],
          "aggregate": "var",
          "column": "MLII",
          "result_column": "mlii_var"
        },
        {
          "filter_column": null,
          "filter_values": null,
          "group_by": [
            "record_id"
          ],
          "aggregate": "var",
          "column": "V1",
          "result_column": "v1_var"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "mlii_var",
      "right": "v1_var",
      "operation": "add",
      "result": "total_lead_variability"
    },
    {
      "op": "RANK_ROWS",
      "column": "total_lead_variability",
      "direction": "max",
      "return_columns": [
        "record_id",
        "total_lead_variability"
      ]
    }
  ]
}
```

**Raw planner output (before normalization):**
```json
{
  "in_scope": true,
  "rejection_reason": null,
  "ambiguous_concepts": [],
  "plan": {
    "version": "1",
    "steps": [
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "record_id"
            ],
            "aggregate": "var",
            "column": "MLII",
            "result_column": "mlii_var"
          },
          {
            "filter_column": null,
            "filter_values": null,
            "group_by": [
              "record_id"
            ],
            "aggregate": "var",
            "column": "V1",
            "result_column": "v1_var"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "mlii_var",
        "right": "v1_var",
        "operation": "add",
        "result": "total_lead_variability"
      },
      {
        "op": "RANK_ROWS",
        "column": "total_lead_variability",
        "direction": "max",
        "return_columns": [
          "record_id",
          "total_lead_variability"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
# PARALLEL_AGGREGATE branches:
branch_0 = df.groupby(['record_id'])['MLII'].var()
branch_1 = df.groupby(['record_id'])['V1'].var()
merged = branch_0.merge(branch_1, on=['record_id'], how='outer')
df['total_lead_variability'] = df['mlii_var'] + df['v1_var']
idx = df['total_lead_variability'].idxmax(); result = df.loc[idx, ['record_id', 'total_lead_variability']].to_dict()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

