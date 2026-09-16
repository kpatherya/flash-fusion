# Cache Grounding Issues

Reported 12 FLASH_FUSION_CACHE grounding failure(s) where the cached skeleton could not be reused directly.

## Query 17 (run 1)

**Query text:** Filter the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

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
      "column": "behavior",
      "values": [
        "aggressive"
      ]
    },
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "timestamp_bin"
      ],
      "aggregate": "mean",
      "column": "instability_score",
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
        "op": "FILTER_IN",
        "column": "behavior",
        "values": [
          "aggressive"
        ]
      },
      {
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "timestamp_bin"
        ],
        "aggregate": "mean",
        "column": "instability_score"
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
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['instability_score'].mean()
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 1)

**Query text:** For each recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "accel_stats_x_p99",
        "accel_stats_y_p99",
        "accel_stats_z_p99"
      ],
      "result": "peak_accel_magnitude"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "gt",
      "threshold": "median",
      "label": "north"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "lte",
      "threshold": "median",
      "label": "south"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "north",
        "south"
      ],
      "aggregate": "mean",
      "column": "peak_accel_magnitude"
    },
    {
      "op": "COMPARE_PARTITIONS",
      "mode": "abs_difference"
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
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "accel_stats_x_p99",
          "accel_stats_y_p99",
          "accel_stats_z_p99"
        ],
        "result": "peak_accel_magnitude"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "gt",
        "threshold": "median",
        "label": "north"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "lte",
        "threshold": "median",
        "label": "south"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "north",
          "south"
        ],
        "aggregate": "mean",
        "column": "peak_accel_magnitude"
      },
      {
        "op": "COMPARE_PARTITIONS",
        "mode": "abs_difference"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
north = df[df['latitude'] gt df['latitude'].median()]
south = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(north, south, mode='abs_difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 1)

**Query text:** For each 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and compute its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "time_bin"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "behavior",
          "filter_values": [
            "aggressive"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p99",
          "result_column": "aggressive_p99"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "aggressive"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p1",
          "result_column": "aggressive_p1"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "calm"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p99",
          "result_column": "calm_p99"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "calm"
          ],
          "group_by": [
            "time_bin"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p1",
          "result_column": "calm_p1"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "aggressive_p99",
      "right": "aggressive_p1",
      "operation": "subtract",
      "result": "aggressive_range"
    },
    {
      "op": "DERIVE_BINARY",
      "left": "calm_p99",
      "right": "calm_p1",
      "operation": "subtract",
      "result": "calm_range"
    },
    {
      "op": "AGGREGATE_COLUMN",
      "column": "aggressive_range",
      "aggregate": "mean"
    },
    {
      "op": "AGGREGATE_COLUMN",
      "column": "calm_range",
      "aggregate": "mean"
    },
    {
      "op": "COMPARE_VALUES",
      "mode": "difference",
      "label_a": "aggressive",
      "label_b": "calm"
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
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "time_bin"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "behavior",
            "filter_values": [
              "aggressive"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p99",
            "result_column": "aggressive_p99"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "aggressive"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p1",
            "result_column": "aggressive_p1"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "calm"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p99",
            "result_column": "calm_p99"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "calm"
            ],
            "group_by": [
              "time_bin"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p1",
            "result_column": "calm_p1"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "aggressive_p99",
        "right": "aggressive_p1",
        "operation": "subtract",
        "result": "aggressive_range"
      },
      {
        "op": "DERIVE_BINARY",
        "left": "calm_p99",
        "right": "calm_p1",
        "operation": "subtract",
        "result": "calm_range"
      },
      {
        "op": "AGGREGATE_COLUMN",
        "column": "aggressive_range",
        "aggregate": "mean"
      },
      {
        "op": "AGGREGATE_COLUMN",
        "column": "calm_range",
        "aggregate": "mean"
      },
      {
        "op": "COMPARE_VALUES",
        "mode": "difference",
        "label_a": "aggressive",
        "label_b": "calm"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['time_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['behavior'].isin(['aggressive'])].groupby(['time_bin'])['accel_stats_z_p99'].mean()
branch_1 = df[df['behavior'].isin(['aggressive'])].groupby(['time_bin'])['accel_stats_z_p1'].mean()
branch_2 = df[df['behavior'].isin(['calm'])].groupby(['time_bin'])['accel_stats_z_p99'].mean()
branch_3 = df[df['behavior'].isin(['calm'])].groupby(['time_bin'])['accel_stats_z_p1'].mean()
merged = branch_0.merge(branch_1, on=['time_bin'], how='outer')
df['aggressive_range'] = df['aggressive_p99'] - df['aggressive_p1']
df['calm_range'] = df['calm_p99'] - df['calm_p1']
result = df['aggressive_range'].mean()
result = df['calm_range'].mean()
result = compare(aggressive=5.0055000000000005, calm=1.291285714285714, mode='difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 1)

**Query text:** Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Filter to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_BINARY",
      "left": "accel_stats_z_p99",
      "right": "accel_stats_z_p1",
      "operation": "subtract",
      "result": "vertical_shock_range"
    },
    {
      "op": "FILTER_IN",
      "column": "behavior",
      "values": [
        "aggressive"
      ]
    },
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_5min_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "timestamp_5min_bin"
      ],
      "aggregate": "mean",
      "column": "vertical_shock_range",
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
        "op": "DERIVE_BINARY",
        "left": "accel_stats_z_p99",
        "right": "accel_stats_z_p1",
        "operation": "subtract",
        "result": "vertical_shock_range"
      },
      {
        "op": "FILTER_IN",
        "column": "behavior",
        "values": [
          "aggressive"
        ]
      },
      {
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_5min_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "timestamp_5min_bin"
        ],
        "aggregate": "mean",
        "column": "vertical_shock_range"
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
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_5min_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_5min_bin')['vertical_shock_range'].mean()
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 17 (run 2)

**Query text:** Restrict the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

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
      "column": "behavior",
      "values": [
        "aggressive"
      ]
    },
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "timestamp_bin"
      ],
      "aggregate": "mean",
      "column": "instability_score",
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
        "op": "FILTER_IN",
        "column": "behavior",
        "values": [
          "aggressive"
        ]
      },
      {
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "timestamp_bin"
        ],
        "aggregate": "mean",
        "column": "instability_score"
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
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['instability_score'].mean()
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 2)

**Query text:** For every recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude.

**Failure reason:** `cache: semantic: semantic_low_confidence_winner`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "accel_stats_x_p99",
        "accel_stats_y_p99",
        "accel_stats_z_p99"
      ],
      "result": "peak_accel_magnitude"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "gt",
      "threshold": "median",
      "label": "north"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "lte",
      "threshold": "median",
      "label": "south"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "north",
        "south"
      ],
      "aggregate": "mean",
      "column": "peak_accel_magnitude"
    },
    {
      "op": "COMPARE_PARTITIONS",
      "mode": "abs_difference"
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
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "accel_stats_x_p99",
          "accel_stats_y_p99",
          "accel_stats_z_p99"
        ],
        "result": "peak_accel_magnitude"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "gt",
        "threshold": "median",
        "label": "north"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "lte",
        "threshold": "median",
        "label": "south"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "north",
          "south"
        ],
        "aggregate": "mean",
        "column": "peak_accel_magnitude"
      },
      {
        "op": "COMPARE_PARTITIONS",
        "mode": "abs_difference"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
north = df[df['latitude'] gt df['latitude'].median()]
south = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(north, south, mode='abs_difference')
```

**Stages run:** hybrid_semantic_low_confidence_winner → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 2)

**Query text:** For every 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and Calculate its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route.

**Failure reason:** `execution: DERIVE_BIN: ValueError: Invalid frequency: 5T. Failed to parse with error message: ValueError("Invalid frequency: T. Failed to parse with error message: KeyError('T'). Did you mean min?")`

**Execution path after fallback:** `typed_plan_unavailable`

**Plan source after fallback:** `llm`

**Plan validation stage failed:** `execution`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5T",
      "epoch_unit": null,
      "result": "timestamp_5min"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "behavior",
          "filter_values": [
            "aggressive"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p99",
          "result_column": "aggressive_p99"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "aggressive"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p1",
          "result_column": "aggressive_p1"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "calm"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p99",
          "result_column": "calm_p99"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "calm"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p1",
          "result_column": "calm_p1"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "aggressive_p99",
      "right": "aggressive_p1",
      "operation": "subtract",
      "result": "aggressive_shock_range"
    },
    {
      "op": "DERIVE_BINARY",
      "left": "calm_p99",
      "right": "calm_p1",
      "operation": "subtract",
      "result": "calm_shock_range"
    },
    {
      "op": "AGGREGATE_COLUMN",
      "column": "aggressive_shock_range",
      "aggregate": "mean"
    },
    {
      "op": "AGGREGATE_COLUMN",
      "column": "calm_shock_range",
      "aggregate": "mean"
    },
    {
      "op": "COMPARE_VALUES",
      "mode": "difference",
      "label_a": "aggressive",
      "label_b": "calm"
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
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5T",
        "result": "timestamp_5min"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "behavior",
            "filter_values": [
              "aggressive"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p99",
            "result_column": "aggressive_p99"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "aggressive"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p1",
            "result_column": "aggressive_p1"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "calm"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p99",
            "result_column": "calm_p99"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "calm"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p1",
            "result_column": "calm_p1"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "aggressive_p99",
        "right": "aggressive_p1",
        "operation": "subtract",
        "result": "aggressive_shock_range"
      },
      {
        "op": "DERIVE_BINARY",
        "left": "calm_p99",
        "right": "calm_p1",
        "operation": "subtract",
        "result": "calm_shock_range"
      },
      {
        "op": "AGGREGATE_COLUMN",
        "column": "aggressive_shock_range",
        "aggregate": "mean"
      },
      {
        "op": "AGGREGATE_COLUMN",
        "column": "calm_shock_range",
        "aggregate": "mean"
      },
      {
        "op": "COMPARE_VALUES",
        "mode": "difference",
        "label_a": "aggressive",
        "label_b": "calm"
      }
    ]
  }
}
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_plan_unavailable

---

## Query 20 (run 2)

**Query text:** Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Restrict to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

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
      "column": "behavior",
      "values": [
        "aggressive"
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "accel_stats_z_p99",
      "right": "accel_stats_z_p1",
      "operation": "subtract",
      "result": "vertical_shock_range"
    },
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_5min"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "timestamp_5min"
      ],
      "aggregate": "mean",
      "column": "vertical_shock_range",
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
        "op": "FILTER_IN",
        "column": "behavior",
        "values": [
          "aggressive"
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "accel_stats_z_p99",
        "right": "accel_stats_z_p1",
        "operation": "subtract",
        "result": "vertical_shock_range"
      },
      {
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_5min"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "timestamp_5min"
        ],
        "aggregate": "mean",
        "column": "vertical_shock_range"
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
df = df[df['behavior'].isin(['aggressive'])]
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_5min')['vertical_shock_range'].mean()
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 17 (run 3)

**Query text:** Restrict the route to rows labeled aggressive, group them into 5-minute timestamp windows, and return the window with the highest mean instability_score.

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
      "column": "behavior",
      "values": [
        "aggressive"
      ]
    },
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "timestamp_bin"
      ],
      "aggregate": "mean",
      "column": "instability_score",
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
        "op": "FILTER_IN",
        "column": "behavior",
        "values": [
          "aggressive"
        ]
      },
      {
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "timestamp_bin"
        ],
        "aggregate": "mean",
        "column": "instability_score"
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
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['instability_score'].mean()
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 18 (run 3)

**Query text:** For every recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_VECTOR_MAGNITUDE",
      "columns": [
        "accel_stats_x_p99",
        "accel_stats_y_p99",
        "accel_stats_z_p99"
      ],
      "result": "peak_accel_magnitude"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "gt",
      "threshold": "median",
      "label": "north"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "lte",
      "threshold": "median",
      "label": "south"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "north",
        "south"
      ],
      "aggregate": "mean",
      "column": "peak_accel_magnitude"
    },
    {
      "op": "COMPARE_PARTITIONS",
      "mode": "abs_difference"
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
        "op": "DERIVE_VECTOR_MAGNITUDE",
        "columns": [
          "accel_stats_x_p99",
          "accel_stats_y_p99",
          "accel_stats_z_p99"
        ],
        "result": "peak_accel_magnitude"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "gt",
        "threshold": "median",
        "label": "north"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "lte",
        "threshold": "median",
        "label": "south"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "north",
          "south"
        ],
        "aggregate": "mean",
        "column": "peak_accel_magnitude"
      },
      {
        "op": "COMPARE_PARTITIONS",
        "mode": "abs_difference"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['peak_accel_magnitude'] = (df['accel_stats_x_p99']**2 + df['accel_stats_y_p99']**2 + df['accel_stats_z_p99']**2)**0.5
north = df[df['latitude'] gt df['latitude'].median()]
south = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(north, south, mode='abs_difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 3)

**Query text:** For every 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and Determine its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route.

**Failure reason:** `cache: light model returned empty content`

**Execution path after fallback:** `typed_operator`

**Plan source after fallback:** `llm`

**Typed plan executed after fallback:**
```json
{
  "version": "1",
  "steps": [
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_5min"
    },
    {
      "op": "PARALLEL_AGGREGATE",
      "branches": [
        {
          "filter_column": "behavior",
          "filter_values": [
            "aggressive"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p99",
          "result_column": "aggressive_p99"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "aggressive"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p1",
          "result_column": "aggressive_p1"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "calm"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p99",
          "result_column": "calm_p99"
        },
        {
          "filter_column": "behavior",
          "filter_values": [
            "calm"
          ],
          "group_by": [
            "timestamp_5min"
          ],
          "aggregate": "mean",
          "column": "accel_stats_z_p1",
          "result_column": "calm_p1"
        }
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "aggressive_p99",
      "right": "aggressive_p1",
      "operation": "subtract",
      "result": "aggressive_shock_range"
    },
    {
      "op": "DERIVE_BINARY",
      "left": "calm_p99",
      "right": "calm_p1",
      "operation": "subtract",
      "result": "calm_shock_range"
    },
    {
      "op": "AGGREGATE_COLUMN",
      "column": "aggressive_shock_range",
      "aggregate": "mean"
    },
    {
      "op": "AGGREGATE_COLUMN",
      "column": "calm_shock_range",
      "aggregate": "mean"
    },
    {
      "op": "COMPARE_VALUES",
      "mode": "difference",
      "label_a": "aggressive",
      "label_b": "calm"
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
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_5min"
      },
      {
        "op": "PARALLEL_AGGREGATE",
        "branches": [
          {
            "filter_column": "behavior",
            "filter_values": [
              "aggressive"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p99",
            "result_column": "aggressive_p99"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "aggressive"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p1",
            "result_column": "aggressive_p1"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "calm"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p99",
            "result_column": "calm_p99"
          },
          {
            "filter_column": "behavior",
            "filter_values": [
              "calm"
            ],
            "group_by": [
              "timestamp_5min"
            ],
            "aggregate": "mean",
            "column": "accel_stats_z_p1",
            "result_column": "calm_p1"
          }
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "aggressive_p99",
        "right": "aggressive_p1",
        "operation": "subtract",
        "result": "aggressive_shock_range"
      },
      {
        "op": "DERIVE_BINARY",
        "left": "calm_p99",
        "right": "calm_p1",
        "operation": "subtract",
        "result": "calm_shock_range"
      },
      {
        "op": "AGGREGATE_COLUMN",
        "column": "aggressive_shock_range",
        "aggregate": "mean"
      },
      {
        "op": "AGGREGATE_COLUMN",
        "column": "calm_shock_range",
        "aggregate": "mean"
      },
      {
        "op": "COMPARE_VALUES",
        "mode": "difference",
        "label_a": "aggressive",
        "label_b": "calm"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
# PARALLEL_AGGREGATE branches:
branch_0 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['accel_stats_z_p99'].mean()
branch_1 = df[df['behavior'].isin(['aggressive'])].groupby(['timestamp_5min'])['accel_stats_z_p1'].mean()
branch_2 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['accel_stats_z_p99'].mean()
branch_3 = df[df['behavior'].isin(['calm'])].groupby(['timestamp_5min'])['accel_stats_z_p1'].mean()
merged = branch_0.merge(branch_1, on=['timestamp_5min'], how='outer')
df['aggressive_shock_range'] = df['aggressive_p99'] - df['aggressive_p1']
df['calm_shock_range'] = df['calm_p99'] - df['calm_p1']
result = df['aggressive_shock_range'].mean()
result = df['calm_shock_range'].mean()
result = compare(aggressive=5.0055000000000005, calm=1.291285714285714, mode='difference')
```

**Stages run:** hybrid_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 20 (run 3)

**Query text:** Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Restrict to aggressive behavior, group rows into 5-minute timestamp windows, and return the window with the highest mean vertical shock range.

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
      "column": "behavior",
      "values": [
        "aggressive"
      ]
    },
    {
      "op": "DERIVE_BINARY",
      "left": "accel_stats_z_p99",
      "right": "accel_stats_z_p1",
      "operation": "subtract",
      "result": "vertical_shock_range"
    },
    {
      "op": "DERIVE_BIN",
      "column": "timestamp",
      "kind": "temporal",
      "width": null,
      "freq": "5min",
      "epoch_unit": null,
      "result": "timestamp_bin"
    },
    {
      "op": "GROUP_AGGREGATE",
      "group_by": [
        "timestamp_bin"
      ],
      "aggregate": "mean",
      "column": "vertical_shock_range",
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
        "op": "FILTER_IN",
        "column": "behavior",
        "values": [
          "aggressive"
        ]
      },
      {
        "op": "DERIVE_BINARY",
        "left": "accel_stats_z_p99",
        "right": "accel_stats_z_p1",
        "operation": "subtract",
        "result": "vertical_shock_range"
      },
      {
        "op": "DERIVE_BIN",
        "column": "timestamp",
        "kind": "temporal",
        "freq": "5min",
        "result": "timestamp_bin"
      },
      {
        "op": "GROUP_AGGREGATE",
        "group_by": [
          "timestamp_bin"
        ],
        "aggregate": "mean",
        "column": "vertical_shock_range"
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
df = df[df['behavior'].isin(['aggressive'])]
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df['timestamp_bin'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_bin')['vertical_shock_range'].mean()
result = result.idxmax()
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

