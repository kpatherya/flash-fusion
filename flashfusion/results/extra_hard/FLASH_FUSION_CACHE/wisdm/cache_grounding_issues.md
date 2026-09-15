# Cache Grounding Issues

Reported 12 FLASH_FUSION_CACHE grounding failure(s) where the cached skeleton could not be reused directly.

## Query 17 (run 1)

**Query text:** For every subject_id, compute mean acceleration magnitude separately for dynamic activities (Walking, Jogging, Upstairs, Downstairs) and resting activities (Sitting, Standing). Return the subject_id with the largest dynamic-minus-resting mean magnitude.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "x",
        "y",
        "z"
      ],
      "result": "acceleration_magnitude"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Downstairs",
            "Jogging",
            "Upstairs",
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "dynamic_mean_magnitude"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Sitting",
            "Standing"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "resting_mean_magnitude"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "dynamic_mean_magnitude",
      "right": "resting_mean_magnitude",
      "operation": "subtract",
      "result": "magnitude_difference"
    },
    {
      "op": "RANK_ROWS",
      "column": "magnitude_difference",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "dynamic_mean_magnitude",
        "resting_mean_magnitude",
        "magnitude_difference"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "x",
          "y",
          "z"
        ],
        "result": "acceleration_magnitude"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking",
              "Jogging",
              "Upstairs",
              "Downstairs"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "dynamic_mean_magnitude"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Sitting",
              "Standing"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "resting_mean_magnitude"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "dynamic_mean_magnitude",
        "right": "resting_mean_magnitude",
        "operation": "subtract",
        "result": "magnitude_difference"
      },
      {
        "op": "RANK_ROWS",
        "column": "magnitude_difference",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "dynamic_mean_magnitude",
          "resting_mean_magnitude",
          "magnitude_difference"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['magnitude_difference'] = df['dynamic_mean_magnitude'] - df['resting_mean_magnitude']
idx = df['magnitude_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_magnitude', 'resting_mean_magnitude', 'magnitude_difference']].to_dict()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 1)

**Query text:** For every subject_id, compute x-acceleration variance separately while Jogging and while Walking. Among subject_id values whose Jogging variance exceeds their Walking variance, return the subject_id with the largest Jogging-minus-Walking variance difference.

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
      "column": "activity_label"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Jogging"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "var",
          "column": "x",
          "result_column": "jogging_var"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "var",
          "column": "x",
          "result_column": "walking_var"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "jogging_var",
      "right": "walking_var",
      "operation": "subtract",
      "result": "var_diff"
    },
    {
      "op": "FILTER_COMPARE",
      "column": "var_diff",
      "comparator": "gt",
      "value": 0
    },
    {
      "op": "RANK_ROWS",
      "column": "var_diff",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "jogging_var",
        "walking_var",
        "var_diff"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Jogging"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "var",
            "column": "x",
            "result_column": "jogging_var"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "var",
            "column": "x",
            "result_column": "walking_var"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "jogging_var",
        "right": "walking_var",
        "operation": "subtract",
        "result": "var_diff"
      },
      {
        "op": "FILTER_COMPARE",
        "column": "var_diff",
        "comparator": "gt",
        "value": 0
      },
      {
        "op": "RANK_ROWS",
        "column": "var_diff",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "jogging_var",
          "walking_var",
          "var_diff"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['x'].var()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['x'].var()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['var_diff'] = df['jogging_var'] - df['walking_var']
df = df[df['var_diff'] > 0]
idx = df['var_diff'].idxmax(); result = df.loc[idx, ['subject_id', 'jogging_var', 'walking_var', 'var_diff']].to_dict()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 1)

**Query text:** For every subject_id, compute mean acceleration magnitude while Jogging and while Walking. Return the Pearson correlation between the two per-subject mean-magnitude columns.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "x",
        "y",
        "z"
      ],
      "result": "acceleration_magnitude"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Jogging"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "mean_jogging_magnitude"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "mean_walking_magnitude"
        }
      ]
    },
    {
      "op": "CORRELATE_COLUMNS",
      "left": "mean_jogging_magnitude",
      "right": "mean_walking_magnitude",
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "x",
          "y",
          "z"
        ],
        "result": "acceleration_magnitude"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Jogging"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "mean_jogging_magnitude"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "mean_walking_magnitude"
          }
        ]
      },
      {
        "op": "CORRELATE_COLUMNS",
        "left": "mean_jogging_magnitude",
        "right": "mean_walking_magnitude",
        "method": "pearson"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
result = df['mean_jogging_magnitude'].corr(df['mean_walking_magnitude'], method='pearson')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 1)

**Query text:** For every subject_id, derive elapsed seconds from timestamp, then compute total locomotion duration (Walking, Jogging, Upstairs, Downstairs) and total resting duration (Sitting, Standing). Among subjects with more locomotion than resting time, return the subject_id with the largest locomotion-minus-resting duration.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_DURATION_SECONDS",
      "timestamp_column": "timestamp",
      "group_by": [
        "subject_id"
      ],
      "result": "dt_s",
      "clip_negative": true,
      "fill_first": 0.0
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Downstairs",
            "Jogging",
            "Upstairs",
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "sum",
          "column": "dt_s",
          "result_column": "locomotion_duration"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Sitting",
            "Standing"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "sum",
          "column": "dt_s",
          "result_column": "resting_duration"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "locomotion_duration",
      "right": "resting_duration",
      "operation": "subtract",
      "result": "duration_delta"
    },
    {
      "op": "FILTER_COMPARE",
      "column": "duration_delta",
      "comparator": "gt",
      "value": 0
    },
    {
      "op": "RANK_ROWS",
      "column": "duration_delta",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "locomotion_duration",
        "resting_duration",
        "duration_delta"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_DURATION_SECONDS",
        "timestamp_column": "timestamp",
        "group_by": [
          "subject_id"
        ],
        "result": "dt_s",
        "clip_negative": true,
        "fill_first": 0.0
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking",
              "Jogging",
              "Upstairs",
              "Downstairs"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "sum",
            "column": "dt_s",
            "result_column": "locomotion_duration"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Sitting",
              "Standing"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "sum",
            "column": "dt_s",
            "result_column": "resting_duration"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "locomotion_duration",
        "right": "resting_duration",
        "operation": "subtract",
        "result": "duration_delta"
      },
      {
        "op": "FILTER_COMPARE",
        "column": "duration_delta",
        "comparator": "gt",
        "value": 0
      },
      {
        "op": "RANK_ROWS",
        "column": "duration_delta",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "locomotion_duration",
          "resting_duration",
          "duration_delta"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df = df.sort_values(['subject_id', 'timestamp']); df['dt_s'] = df.groupby(['subject_id'])['timestamp'].diff().dt.total_seconds().clip(lower=0).fillna(0.0)
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['dt_s'].sum()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['dt_s'].sum()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
merged[['locomotion_duration', 'resting_duration']] = merged[['locomotion_duration', 'resting_duration']].fillna(0)
df['duration_delta'] = df['locomotion_duration'] - df['resting_duration']
df = df[df['duration_delta'] > 0]
idx = df['duration_delta'].idxmax(); result = df.loc[idx, ['subject_id', 'locomotion_duration', 'resting_duration', 'duration_delta']].to_dict()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 17 (run 2)

**Query text:** For every subject_id, Calculate mean acceleration magnitude separately for dynamic activities (Walking, Jogging, Upstairs, Downstairs) and resting activities (Sitting, Standing). Return the subject_id with the largest dynamic-minus-resting mean magnitude.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "x",
        "y",
        "z"
      ],
      "result": "acceleration_magnitude"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Downstairs",
            "Jogging",
            "Upstairs",
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "dynamic_mean_magnitude"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Sitting",
            "Standing"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "resting_mean_magnitude"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "dynamic_mean_magnitude",
      "right": "resting_mean_magnitude",
      "operation": "subtract",
      "result": "magnitude_difference"
    },
    {
      "op": "RANK_ROWS",
      "column": "magnitude_difference",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "dynamic_mean_magnitude",
        "resting_mean_magnitude",
        "magnitude_difference"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "x",
          "y",
          "z"
        ],
        "result": "acceleration_magnitude"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking",
              "Jogging",
              "Upstairs",
              "Downstairs"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "dynamic_mean_magnitude"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Sitting",
              "Standing"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "resting_mean_magnitude"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "dynamic_mean_magnitude",
        "right": "resting_mean_magnitude",
        "operation": "subtract",
        "result": "magnitude_difference"
      },
      {
        "op": "RANK_ROWS",
        "column": "magnitude_difference",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "dynamic_mean_magnitude",
          "resting_mean_magnitude",
          "magnitude_difference"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['magnitude_difference'] = df['dynamic_mean_magnitude'] - df['resting_mean_magnitude']
idx = df['magnitude_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_magnitude', 'resting_mean_magnitude', 'magnitude_difference']].to_dict()
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 2)

**Query text:** For every subject_id, Calculate x-acceleration variance separately while Jogging and while Walking. Among subject_id values whose Jogging variance exceeds their Walking variance, return the subject_id with the largest Jogging-minus-Walking variance difference.

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
      "column": "activity_label"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Jogging"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "var",
          "column": "x",
          "result_column": "jogging_var"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "var",
          "column": "x",
          "result_column": "walking_var"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "jogging_var",
      "right": "walking_var",
      "operation": "subtract",
      "result": "var_diff"
    },
    {
      "op": "FILTER_COMPARE",
      "column": "var_diff",
      "comparator": "gt",
      "value": 0
    },
    {
      "op": "RANK_ROWS",
      "column": "var_diff",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "jogging_var",
        "walking_var",
        "var_diff"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Jogging"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "var",
            "column": "x",
            "result_column": "jogging_var"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "var",
            "column": "x",
            "result_column": "walking_var"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "jogging_var",
        "right": "walking_var",
        "operation": "subtract",
        "result": "var_diff"
      },
      {
        "op": "FILTER_COMPARE",
        "column": "var_diff",
        "comparator": "gt",
        "value": 0
      },
      {
        "op": "RANK_ROWS",
        "column": "var_diff",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "jogging_var",
          "walking_var",
          "var_diff"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['x'].var()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['x'].var()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['var_diff'] = df['jogging_var'] - df['walking_var']
df = df[df['var_diff'] > 0]
idx = df['var_diff'].idxmax(); result = df.loc[idx, ['subject_id', 'jogging_var', 'walking_var', 'var_diff']].to_dict()
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 2)

**Query text:** For every subject_id, Calculate mean acceleration magnitude while Jogging and while Walking. Return the Pearson correlation between the two per-subject mean-magnitude columns.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "x",
        "y",
        "z"
      ],
      "result": "acceleration_magnitude"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Jogging"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "mean_jogging_mag"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "mean_walking_mag"
        }
      ]
    },
    {
      "op": "CORRELATE_COLUMNS",
      "left": "mean_jogging_mag",
      "right": "mean_walking_mag",
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "x",
          "y",
          "z"
        ],
        "result": "acceleration_magnitude"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Jogging"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "mean_jogging_mag"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "mean_walking_mag"
          }
        ]
      },
      {
        "op": "CORRELATE_COLUMNS",
        "left": "mean_jogging_mag",
        "right": "mean_walking_mag",
        "method": "pearson"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
result = df['mean_jogging_mag'].corr(df['mean_walking_mag'], method='pearson')
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 2)

**Query text:** For every subject_id, derive elapsed seconds from timestamp, then Calculate total locomotion duration (Walking, Jogging, Upstairs, Downstairs) and total resting duration (Sitting, Standing). Among subjects with more locomotion than resting time, return the subject_id with the largest locomotion-minus-resting duration.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_DURATION_SECONDS",
      "timestamp_column": "timestamp",
      "group_by": [
        "subject_id"
      ],
      "result": "dt_s",
      "clip_negative": true,
      "fill_first": 0.0
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Downstairs",
            "Jogging",
            "Upstairs",
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "sum",
          "column": "dt_s",
          "result_column": "locomotion_duration"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Sitting",
            "Standing"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "sum",
          "column": "dt_s",
          "result_column": "resting_duration"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "locomotion_duration",
      "right": "resting_duration",
      "operation": "subtract",
      "result": "duration_delta"
    },
    {
      "op": "FILTER_COMPARE",
      "column": "duration_delta",
      "comparator": "gt",
      "value": 0
    },
    {
      "op": "RANK_ROWS",
      "column": "duration_delta",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "locomotion_duration",
        "resting_duration",
        "duration_delta"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_DURATION_SECONDS",
        "timestamp_column": "timestamp",
        "group_by": [
          "subject_id"
        ],
        "result": "dt_s",
        "clip_negative": true,
        "fill_first": 0.0
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking",
              "Jogging",
              "Upstairs",
              "Downstairs"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "sum",
            "column": "dt_s",
            "result_column": "locomotion_duration"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Sitting",
              "Standing"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "sum",
            "column": "dt_s",
            "result_column": "resting_duration"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "locomotion_duration",
        "right": "resting_duration",
        "operation": "subtract",
        "result": "duration_delta"
      },
      {
        "op": "FILTER_COMPARE",
        "column": "duration_delta",
        "comparator": "gt",
        "value": 0
      },
      {
        "op": "RANK_ROWS",
        "column": "duration_delta",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "locomotion_duration",
          "resting_duration",
          "duration_delta"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df = df.sort_values(['subject_id', 'timestamp']); df['dt_s'] = df.groupby(['subject_id'])['timestamp'].diff().dt.total_seconds().clip(lower=0).fillna(0.0)
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['dt_s'].sum()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['dt_s'].sum()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
merged[['locomotion_duration', 'resting_duration']] = merged[['locomotion_duration', 'resting_duration']].fillna(0)
df['duration_delta'] = df['locomotion_duration'] - df['resting_duration']
df = df[df['duration_delta'] > 0]
idx = df['duration_delta'].idxmax(); result = df.loc[idx, ['subject_id', 'locomotion_duration', 'resting_duration', 'duration_delta']].to_dict()
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 17 (run 3)

**Query text:** For every subject_id, Determine mean acceleration magnitude separately for dynamic activities (Walking, Jogging, Upstairs, Downstairs) and resting activities (Sitting, Standing). Return the subject_id with the largest dynamic-minus-resting mean magnitude.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "x",
        "y",
        "z"
      ],
      "result": "acceleration_magnitude"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Downstairs",
            "Jogging",
            "Upstairs",
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "dynamic_mean_magnitude"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Sitting",
            "Standing"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "resting_mean_magnitude"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "dynamic_mean_magnitude",
      "right": "resting_mean_magnitude",
      "operation": "subtract",
      "result": "magnitude_difference"
    },
    {
      "op": "RANK_ROWS",
      "column": "magnitude_difference",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "dynamic_mean_magnitude",
        "resting_mean_magnitude",
        "magnitude_difference"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "x",
          "y",
          "z"
        ],
        "result": "acceleration_magnitude"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking",
              "Jogging",
              "Upstairs",
              "Downstairs"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "dynamic_mean_magnitude"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Sitting",
              "Standing"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "resting_mean_magnitude"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "dynamic_mean_magnitude",
        "right": "resting_mean_magnitude",
        "operation": "subtract",
        "result": "magnitude_difference"
      },
      {
        "op": "RANK_ROWS",
        "column": "magnitude_difference",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "dynamic_mean_magnitude",
          "resting_mean_magnitude",
          "magnitude_difference"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['magnitude_difference'] = df['dynamic_mean_magnitude'] - df['resting_mean_magnitude']
idx = df['magnitude_difference'].idxmax(); result = df.loc[idx, ['subject_id', 'dynamic_mean_magnitude', 'resting_mean_magnitude', 'magnitude_difference']].to_dict()
```

**Stages run:** hybrid_semantic_ambiguous_candidates → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 3)

**Query text:** For every subject_id, Determine x-acceleration variance separately while Jogging and while Walking. Among subject_id values whose Jogging variance exceeds their Walking variance, return the subject_id with the largest Jogging-minus-Walking variance difference.

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
      "column": "activity_label"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Jogging"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "var",
          "column": "x",
          "result_column": "jogging_var"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "var",
          "column": "x",
          "result_column": "walking_var"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "jogging_var",
      "right": "walking_var",
      "operation": "subtract",
      "result": "var_diff"
    },
    {
      "op": "FILTER_COMPARE",
      "column": "var_diff",
      "comparator": "gt",
      "value": 0
    },
    {
      "op": "RANK_ROWS",
      "column": "var_diff",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "jogging_var",
        "walking_var",
        "var_diff"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Jogging"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "var",
            "column": "x",
            "result_column": "jogging_var"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "var",
            "column": "x",
            "result_column": "walking_var"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "jogging_var",
        "right": "walking_var",
        "operation": "subtract",
        "result": "var_diff"
      },
      {
        "op": "FILTER_COMPARE",
        "column": "var_diff",
        "comparator": "gt",
        "value": 0
      },
      {
        "op": "RANK_ROWS",
        "column": "var_diff",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "jogging_var",
          "walking_var",
          "var_diff"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['x'].var()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['x'].var()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
df['var_diff'] = df['jogging_var'] - df['walking_var']
df = df[df['var_diff'] > 0]
idx = df['var_diff'].idxmax(); result = df.loc[idx, ['subject_id', 'jogging_var', 'walking_var', 'var_diff']].to_dict()
```

**Stages run:** hybrid_semantic_ambiguous_candidates → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 3)

**Query text:** For every subject_id, Determine mean acceleration magnitude while Jogging and while Walking. Return the Pearson correlation between the two per-subject mean-magnitude columns.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "x",
        "y",
        "z"
      ],
      "result": "acceleration_magnitude"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Jogging"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "mean_jogging_magnitude"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "mean",
          "column": "acceleration_magnitude",
          "result_column": "mean_walking_magnitude"
        }
      ]
    },
    {
      "op": "CORRELATE_COLUMNS",
      "left": "mean_jogging_magnitude",
      "right": "mean_walking_magnitude",
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "x",
          "y",
          "z"
        ],
        "result": "acceleration_magnitude"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Jogging"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "mean_jogging_magnitude"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "mean",
            "column": "acceleration_magnitude",
            "result_column": "mean_walking_magnitude"
          }
        ]
      },
      {
        "op": "CORRELATE_COLUMNS",
        "left": "mean_jogging_magnitude",
        "right": "mean_walking_magnitude",
        "method": "pearson"
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df['acceleration_magnitude'] = (df['x']**2 + df['y']**2 + df['z']**2)**0.5
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Jogging'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
branch_1 = df[df['activity_label'].isin(['Walking'])].groupby(['subject_id'])['acceleration_magnitude'].mean()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
result = df['mean_jogging_magnitude'].corr(df['mean_walking_magnitude'], method='pearson')
```

**Stages run:** hybrid_semantic_ambiguous_candidates → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 3)

**Query text:** For every subject_id, derive elapsed seconds from timestamp, then Determine total locomotion duration (Walking, Jogging, Upstairs, Downstairs) and total resting duration (Sitting, Standing). Among subjects with more locomotion than resting time, return the subject_id with the largest locomotion-minus-resting duration.

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
      "column": "activity_label"
    },
    {
      "op": "DERIVE_DURATION_SECONDS",
      "timestamp_column": "timestamp",
      "group_by": [
        "subject_id"
      ],
      "result": "dt_s",
      "clip_negative": true,
      "fill_first": 0.0
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Downstairs",
            "Jogging",
            "Upstairs",
            "Walking"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "sum",
          "column": "dt_s",
          "result_column": "locomotion_duration"
        },
        {
          "filter_column": "activity_label",
          "filter_values": [
            "Sitting",
            "Standing"
          ],
          "group_by": [
            "subject_id"
          ],
          "aggregate": "sum",
          "column": "dt_s",
          "result_column": "resting_duration"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "locomotion_duration",
      "right": "resting_duration",
      "operation": "subtract",
      "result": "duration_delta"
    },
    {
      "op": "FILTER_COMPARE",
      "column": "duration_delta",
      "comparator": "gt",
      "value": 0
    },
    {
      "op": "RANK_ROWS",
      "column": "duration_delta",
      "direction": "max",
      "return_columns": [
        "subject_id",
        "locomotion_duration",
        "resting_duration",
        "duration_delta"
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
        "op": "FILTER_NOT_EMPTY",
        "column": "activity_label"
      },
      {
        "op": "DERIVE_DURATION_SECONDS",
        "timestamp_column": "timestamp",
        "group_by": [
          "subject_id"
        ],
        "result": "dt_s",
        "clip_negative": true,
        "fill_first": 0.0
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Walking",
              "Jogging",
              "Upstairs",
              "Downstairs"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "sum",
            "column": "dt_s",
            "result_column": "locomotion_duration"
          },
          {
            "filter_column": "activity_label",
            "filter_values": [
              "Sitting",
              "Standing"
            ],
            "group_by": [
              "subject_id"
            ],
            "aggregate": "sum",
            "column": "dt_s",
            "result_column": "resting_duration"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "locomotion_duration",
        "right": "resting_duration",
        "operation": "subtract",
        "result": "duration_delta"
      },
      {
        "op": "FILTER_COMPARE",
        "column": "duration_delta",
        "comparator": "gt",
        "value": 0
      },
      {
        "op": "RANK_ROWS",
        "column": "duration_delta",
        "direction": "max",
        "return_columns": [
          "subject_id",
          "locomotion_duration",
          "resting_duration",
          "duration_delta"
        ]
      }
    ]
  }
}
```

**Final executed code:**
```python
df = df[df['activity_label'].notna() & df['activity_label'].astype(str).str.strip().ne('')]
df = df.sort_values(['subject_id', 'timestamp']); df['dt_s'] = df.groupby(['subject_id'])['timestamp'].diff().dt.total_seconds().clip(lower=0).fillna(0.0)
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['activity_label'].isin(['Downstairs', 'Jogging', 'Upstairs', 'Walking'])].groupby(['subject_id'])['dt_s'].sum()
branch_1 = df[df['activity_label'].isin(['Sitting', 'Standing'])].groupby(['subject_id'])['dt_s'].sum()
merged = branch_0.merge(branch_1, on=['subject_id'], how='outer')
merged[['locomotion_duration', 'resting_duration']] = merged[['locomotion_duration', 'resting_duration']].fillna(0)
df['duration_delta'] = df['locomotion_duration'] - df['resting_duration']
df = df[df['duration_delta'] > 0]
idx = df['duration_delta'].idxmax(); result = df.loc[idx, ['subject_id', 'locomotion_duration', 'resting_duration', 'duration_delta']].to_dict()
```

**Stages run:** hybrid_semantic_ambiguous_candidates → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

