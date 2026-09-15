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

**Query text:** Derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Split the route at the median latitude and report the absolute difference between the northern and southern halves' mean peak magnitudes.

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
      "label": "northern"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "lte",
      "threshold": "median",
      "label": "southern"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "northern",
        "southern"
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
        "label": "northern"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "lte",
        "threshold": "median",
        "label": "southern"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "northern",
          "southern"
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
northern = df[df['latitude'] gt df['latitude'].median()]
southern = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(northern, southern, mode='abs_difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 1)

**Query text:** Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Compute its mean separately for aggressive and calm behavior labels, then report the aggressive-minus-calm difference.

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
      "op": "SPLIT_BY_VALUES",
      "column": "behavior",
      "values": [
        "aggressive"
      ],
      "label": "aggressive"
    },
    {
      "op": "SPLIT_BY_VALUES",
      "column": "behavior",
      "values": [
        "calm"
      ],
      "label": "calm"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "aggressive",
        "calm"
      ],
      "aggregate": "mean",
      "column": "vertical_shock_range"
    },
    {
      "op": "COMPARE_PARTITIONS",
      "mode": "difference"
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
        "op": "SPLIT_BY_VALUES",
        "column": "behavior",
        "values": [
          "aggressive"
        ],
        "label": "aggressive"
      },
      {
        "op": "SPLIT_BY_VALUES",
        "column": "behavior",
        "values": [
          "calm"
        ],
        "label": "calm"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "aggressive",
          "calm"
        ],
        "aggregate": "mean",
        "column": "vertical_shock_range"
      },
      {
        "op": "COMPARE_PARTITIONS",
        "mode": "difference"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
aggressive = df[df['behavior'].isin(['aggressive'])]
calm = df[df['behavior'].isin(['calm'])]
result = {label: agg(partition) for label in partitions}
result = compare(aggressive, calm, mode='difference')
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
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
df = df[df['behavior'].isin(['aggressive'])]
df['timestamp_5min'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.floor('5min')
result = df.groupby('timestamp_5min')['vertical_shock_range'].mean()
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

**Query text:** Derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Partition the route at the median latitude and report the absolute difference between the northern and southern halves' mean peak magnitudes.

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
      "label": "northern"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "lte",
      "threshold": "median",
      "label": "southern"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "northern",
        "southern"
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
        "label": "northern"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "lte",
        "threshold": "median",
        "label": "southern"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "northern",
          "southern"
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
northern = df[df['latitude'] gt df['latitude'].median()]
southern = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(northern, southern, mode='abs_difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 2)

**Query text:** Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Calculate its mean separately for aggressive and calm behavior labels, then report the aggressive-minus-calm difference.

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
      "op": "SPLIT_BY_VALUES",
      "column": "behavior",
      "values": [
        "aggressive"
      ],
      "label": "aggressive_group"
    },
    {
      "op": "SPLIT_BY_VALUES",
      "column": "behavior",
      "values": [
        "calm"
      ],
      "label": "calm_group"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "aggressive_group",
        "calm_group"
      ],
      "aggregate": "mean",
      "column": "vertical_shock_range"
    },
    {
      "op": "COMPARE_PARTITIONS",
      "mode": "difference"
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
        "op": "SPLIT_BY_VALUES",
        "column": "behavior",
        "values": [
          "aggressive"
        ],
        "label": "aggressive_group"
      },
      {
        "op": "SPLIT_BY_VALUES",
        "column": "behavior",
        "values": [
          "calm"
        ],
        "label": "calm_group"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "aggressive_group",
          "calm_group"
        ],
        "aggregate": "mean",
        "column": "vertical_shock_range"
      },
      {
        "op": "COMPARE_PARTITIONS",
        "mode": "difference"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
aggressive_group = df[df['behavior'].isin(['aggressive'])]
calm_group = df[df['behavior'].isin(['calm'])]
result = {label: agg(partition) for label in partitions}
result = compare(aggressive_group, calm_group, mode='difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

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

**Query text:** Derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Divide the route at the median latitude and report the absolute difference between the northern and southern halves' mean peak magnitudes.

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
      "label": "northern"
    },
    {
      "op": "SPLIT_BY_THRESHOLD",
      "column": "latitude",
      "comparator": "lte",
      "threshold": "median",
      "label": "southern"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "northern",
        "southern"
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
        "label": "northern"
      },
      {
        "op": "SPLIT_BY_THRESHOLD",
        "column": "latitude",
        "comparator": "lte",
        "threshold": "median",
        "label": "southern"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "northern",
          "southern"
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
northern = df[df['latitude'] gt df['latitude'].median()]
southern = df[df['latitude'] lte df['latitude'].median()]
result = {label: agg(partition) for label in partitions}
result = compare(northern, southern, mode='abs_difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

---

## Query 19 (run 3)

**Query text:** Derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1. Determine its mean separately for aggressive and calm behavior labels, then report the aggressive-minus-calm difference.

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
      "op": "SPLIT_BY_VALUES",
      "column": "behavior",
      "values": [
        "aggressive"
      ],
      "label": "aggressive"
    },
    {
      "op": "SPLIT_BY_VALUES",
      "column": "behavior",
      "values": [
        "calm"
      ],
      "label": "calm"
    },
    {
      "op": "AGGREGATE_PARTITIONS",
      "partitions": [
        "aggressive",
        "calm"
      ],
      "aggregate": "mean",
      "column": "vertical_shock_range"
    },
    {
      "op": "COMPARE_PARTITIONS",
      "mode": "difference"
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
        "op": "SPLIT_BY_VALUES",
        "column": "behavior",
        "values": [
          "aggressive"
        ],
        "label": "aggressive"
      },
      {
        "op": "SPLIT_BY_VALUES",
        "column": "behavior",
        "values": [
          "calm"
        ],
        "label": "calm"
      },
      {
        "op": "AGGREGATE_PARTITIONS",
        "partitions": [
          "aggressive",
          "calm"
        ],
        "aggregate": "mean",
        "column": "vertical_shock_range"
      },
      {
        "op": "COMPARE_PARTITIONS",
        "mode": "difference"
      }
    ]
  }
}
```

**Final executed code:**
```python
df['vertical_shock_range'] = df['accel_stats_z_p99'] - df['accel_stats_z_p1']
aggressive = df[df['behavior'].isin(['aggressive'])]
calm = df[df['behavior'].isin(['calm'])]
result = {label: agg(partition) for label in partitions}
result = compare(aggressive, calm, mode='difference')
```

**Stages run:** exact_cache_hit → cache_light_grounding → cache_miss_or_validation_failure → guardrail_plan → plan_validated → typed_exec

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

