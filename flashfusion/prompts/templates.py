"""
prompts/templates.py — Canonical prompt strings for Flash-Fusion.

All prompts are module-level string constants.
Placeholders (e.g. {column_metadata}) are filled via str.format() at call-time
inside the stage/executor that owns each prompt — never at import time.

DO NOT MODIFY these prompts without updating CLAUDE.md and re-running the full
benchmark to verify that scoring does not regress.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stage 1 — Concept Extraction
# Classifies every distinct semantic concept in the user query into one of
# three buckets: COLUMN (literal column), DERIVED_STAT (mechanically computable
# via a standard operation over one or more columns), or PROXY (qualitative
# idea requiring a heuristic column substitution).
# ---------------------------------------------------------------------------
CONCEPT_EXTRACTION_PROMPT: str = """\
You are a concept extraction specialist for time-series and sensor data queries.

Given the user's natural language query, identify every distinct semantic concept
and classify each as one of:

CRITICAL minimality rule:
  - Extract only concepts that are strictly required to answer this specific query.
  - Do not invent structural or auxiliary concepts (for example identifier,
    timestamp, or generic measurement labels) unless the query explicitly
    requires them.
  - Prefer the smallest sufficient concept set.

  COLUMN        — a measurable quantity that maps directly, by name or obvious
                  synonym, to a single dataset column with no computation needed.
                  Examples: "timestamp", "identifier", "latitude", "acceleration
                  variance", "signal amplitude"

  DERIVED_STAT  — a concept computable from column(s) via ONE of a fixed set of
                  standard statistical/procedural operations. This bucket exists
                  precisely so operations like "median" or "average" are never
                  treated as if they were themselves columns needing a lookup.
                  Standard operations: MEDIAN, MEAN/AVERAGE, SUM/TOTAL, COUNT,
                  MIN, MAX, STD, VARIANCE, PERCENTILE, THRESHOLD_SPLIT
                  (above/below/greater-than/less-than a value or a statistic),
                  DIFFERENCE/DELTA between two quantities, GROUP_COMPARE
                  (comparing an aggregate between two or more groups),
                  VECTOR_MAGNITUDE (combining two or more raw axis/component
                  columns into a single scalar via the Euclidean norm, e.g. a
                  3-axis acceleration/velocity/field "magnitude" or "overall
                  strength" derived from its x/y/z or similarly-named
                  component columns).
                  Examples: "median", "average", "the top half", "northern half
                  (latitude above median)", "how many are above X", "the
                  difference between A and B", "is A rougher than B",
                  "acceleration magnitude", "overall vibration strength"

  Generalization rule for VECTOR_MAGNITUDE: whenever a concept names a single
  combined quantity that is formulaically derivable by taking the Euclidean
  norm of two or more raw per-axis/per-component columns already in the
  schema (regardless of the exact wording — "magnitude", "overall
  acceleration", "total force", "combined signal strength", etc.), classify
  it as DERIVED_STAT, never PROXY. Use PROXY only when no such formulaic
  combination of existing columns is evident.

  PROXY         — a qualitative idea with NO formulaic operation that instead
                  requires a heuristic column substitution, or a semantic
                  grouping that requires codebook resolution.
                  Examples: "intensity", "similarity", "outlier", "unusual",
                  "roughness" (as a standalone unquantified idea), "most
                  similar", "predict next", "anomalous patterns"

Disambiguation rule:
  - If a concept literally matches a dataset field/header token named in the
    query, classify that concept as COLUMN, not DERIVED_STAT or PROXY. Keep
    any surrounding operation words separate (for example, in "average
    annotation count", classify "annotation" as COLUMN and "average"/"count"
    as DERIVED_STAT as needed).
  - If the query already names the metric/column to use for a qualitative idea
    (e.g. "rougher ... based on average acceleration variance"), classify the
    named metric as COLUMN, the aggregation word ("average") as DERIVED_STAT,
    and do NOT additionally emit a PROXY concept for that idea — the metric is
    already fully specified, no proxy substitution is needed.
  - Only use PROXY when the query gives no explicit column/metric to ground the
    qualitative idea to.

Output format — output ONLY these three lines, nothing else:
COLUMN: <comma-separated list of column concepts, or NONE>
DERIVED_STAT: <comma-separated list of derived-stat concepts, or NONE>
PROXY: <comma-separated list of proxy concepts, or NONE>\
"""

# ---------------------------------------------------------------------------
# Stage 2 — Schema Grounding
# Maps COLUMN concepts to actual columns; maps DERIVED_STAT concepts to
# OPERATION(column) expressions from a fixed operation vocabulary; maps PROXY
# concepts to concrete column+operation heuristic substitutions.
# Placeholder: {column_metadata}
# ---------------------------------------------------------------------------
# Schema Grounding
SCHEMA_GROUNDING_PROMPT: str = """\
You are a schema grounding specialist for time-series and sensor datasets.

Dataset columns and metadata:
{column_metadata}

IMPORTANT — reading the metadata:
  - ``values=[...]`` means the list is COMPLETE (every unique value is shown).
  - ``sample=[...]`` means the list is a partial sample only.
  When mapping a semantic group concept such as 'dynamic', 'resting', 'stationary',
  or 'active locomotion', you MUST inspect ALL entries in a ``values=`` list and
  include every value that belongs to that group in your mapping. Do NOT infer
  group membership solely from examples given in the query text.

You receive COLUMN, DERIVED_STAT, and PROXY concepts extracted from a user query.

Your tasks and the REQUIRED output grammar for each concept type:

1. COLUMN concepts — identify the best matching column(s) from the dataset schema.
   Output format (bare column name, no wrapper):
     <concept> → <column_name>
   CRITICAL: <column_name> MUST be copied EXACTLY, character-for-character, from
   the dataset columns and metadata list above. NEVER invent a plausible-looking
   column name by lightly rewording the concept (e.g. do NOT output
   "acceleration_variance" if the concept is "acceleration variance" — first
   search the metadata for the real column, which may be abbreviated (e.g.
   "accel_variance"). If no real column matches even approximately, mark the
   concept UNMAPPABLE instead of fabricating a name.

2. DERIVED_STAT concepts — these are standard operations, not columns. NEVER
   ground a DERIVED_STAT concept to a bare column name and NEVER invent a
   substitute column merely because its name sounds statistically similar
   (e.g. a percentile column such as ``foo_p90`` is NEVER a valid stand-in for
   "median" or "variance" — those are different operations entirely). Ground
   each DERIVED_STAT concept to an explicit call from this fixed vocabulary,
   always wrapping the EXACT column the concept refers to:
     MEDIAN(column), MEAN(column), SUM(column), COUNT(column), MIN(column),
     MAX(column), STD(column), VARIANCE(column), PERCENTILE(column, p),
     DIFFERENCE(column_a, column_b), VECTOR_MAGNITUDE(column_a, column_b[, column_c, ...])
   VECTOR_MAGNITUDE grounds any "magnitude"/"overall strength"/"combined
   signal" concept to the Euclidean norm of its exact raw axis/component
   columns (e.g. VECTOR_MAGNITUDE(x, y, z) for a 3-axis acceleration
   magnitude). List EVERY component column that exists in the schema for
   that quantity — never fewer, never a placeholder. Do NOT wrap a
   VECTOR_MAGNITUDE result in another VECTOR_MAGNITUDE call, and never mark
   such a concept UNMAPPABLE or PROXY when its component columns are present
   in the schema.
   Threshold/split concepts compare a column to a value or to another
   DERIVED_STAT call, e.g.:
     <concept> → <column> > MEDIAN(<column>)
     <concept> → <column> <= MEDIAN(<column>)
     <concept> → <column> > <value>
   Group-comparison concepts (e.g. "is A rougher than B") use:
     <concept> → GROUP_COMPARE(<split_expression>, <metric_column>, <agg>)
   where <agg> is one of mean/median/sum/count/max/min. GROUP_COMPARE is ONLY
   for comparing an aggregate between two or more DERIVED groups (e.g. rows
   split by a median threshold, or split by a categorical label). It is NEVER
   used for a plain per-record subtraction between two named columns — use
   DIFFERENCE(column_a, column_b) for that instead.
   CRITICAL — already-computed column rule (narrows S2's scope): if a single
   dataset column ALREADY IS the exact statistic the concept names (for
   example a column literally named/described as a 99th-percentile or
   1st-percentile value, a precomputed mean/variance column, etc.), ground the
   concept as a BARE column reference, exactly like a COLUMN concept:
     <concept> → <column_name>
   Do NOT re-wrap an already-computed statistic column in PERCENTILE(...),
   MEDIAN(...), MEAN(...), etc. — that would recompute a statistic of a
   statistic. Only use the operation vocabulary when the computation still
   needs to happen over a raw, non-aggregated column. Likewise, when a
   DERIVED_STAT concept is simply "the difference between" two columns that
   already independently exist in the schema (no grouping, splitting, or
   further aggregation implied), ground it directly as
   DIFFERENCE(column_a, column_b) using those two exact columns — do not
   route it through GROUP_COMPARE or invent an intermediate split. As soon as
   a concept can be satisfied by a direct reference or comparison between
   existing columns, ground it and stop — do not add extra operation layers
   that aren't required to reach Stage 3.
   CRITICAL consistency rule: if the query already names a specific column for
   a metric (e.g. "average acceleration variance" names "acceleration
   variance"), you MUST reuse that EXACT SAME column in every DERIVED_STAT
   mapping that refers to it. Do not silently swap in a different column.
   CRITICAL completeness rule: a DERIVED_STAT concept MUST NOT be marked
   UNMAPPABLE if any COLUMN concept in this same request is a plausible
   operand for it — always emit a MAPPINGS line grounding it to that column
   via the operation vocabulary above. Only mark it UNMAPPABLE if no column,
   grounded or ungrounded, could serve as its argument.

3. PROXY concepts — define a concrete proxy: which column(s) and what
   operation(s) approximate the qualitative idea. Output format:
     <concept> → PROXY(<column>[, <operation>])
   Heuristics:
     - Combine raw columns with standard operations where appropriate (e.g.
       Euclidean distance, root mean square, difference).
     - Any column not present → UNMAPPABLE, UNLESS the query explicitly
       provides a mathematical or procedural way to derive it from available
       columns (e.g., estimating an unknown metric from a count and duration).

4. If any concept cannot be mapped to any available column and has no explicit
   derivation, mark it UNMAPPABLE.

Output format — output ONLY the following structure, nothing else:
MAPPINGS:
  <concept> → <column(s) and/or operation description>
  <concept> → <column(s) and/or operation description>
UNMAPPABLE: <comma-separated list of unmappable concepts, or NONE>\
"""

# ---------------------------------------------------------------------------
# Stage 3 — Sub-query Generation
# Decomposes an abstract query into 2–4 concrete, column-grounded sub-questions.
# Each sub-question is independently answerable by a pandas DataFrame agent.
# Placeholders: {column_metadata}, {grounding}
# ---------------------------------------------------------------------------
# Sub-query Generation
SUBQUERY_GENERATION_PROMPT: str = """\
You are a query decomposition specialist for time-series data analysis.

Dataset column metadata:
{column_metadata}

Schema grounding (concept → column/operation mappings):
{grounding}

Decompose the original user query into 2–4 concrete sub-questions.

CRITICAL — typed output only, NEVER prose: each sub-question body MUST be a
single pipe-separated `key=value` list — never a natural-language sentence.
This lets code generation parse each step deterministically instead of
re-reading English. Use exact column names from the metadata above as values.

Allowed operation tags and their REQUIRED key=value schema:

  [FILTER]   column=<col> | comparator=<eq|gt|gte|lt|lte|in> | value=<literal, PREV, or comma-list for in>
             Example: column=accel_stats_z_p99 | comparator=gt | value=5.0
             Example: column=behavior | comparator=in | value=[walking,running]
             Example: column=accel_mean | comparator=eq | value=PREV   (PREV = result of the previous sub-query)

  [AGGREGATE] column=<col> | stat=<max|min|mean|median|sum|count>
             Example: column=accel_variance | stat=max

  [DERIVE]   column_a=<col> | column_b=<col> | op=<subtract|add|multiply|divide> | result=<new_column_name>
             Use this for any per-record combination of two existing columns
             (e.g. a difference/delta between two columns). Never express this
             as prose — always emit column_a/column_b/op/result.
             Example: column_a=accel_stats_z_p99 | column_b=accel_stats_z_p1 | op=subtract | result=z_p99_p1_diff

  [GROUPBY]  group_column=<col> | value_column=<col> | stat=<max|min|mean|median|sum|count> | freq=<optional pandas offset alias>
             Use freq=... ONLY when the query asks to bucket/bin a datetime
             column into fixed-size time windows (e.g. "1-minute intervals",
             "5-minute windows", "hourly"): group_column MUST then be the
             datetime column, and freq is a pandas offset alias such as
             1min, 5min, 1H. Omit freq entirely for a normal categorical groupby.
             Example: group_column=behavior | value_column=accel_mean | stat=mean
             Example: group_column=timestamp | value_column=accel_stats_z_p99 | stat=max | freq=1min

  [RANK]     metric=<col_or_prior_result_column> | stat=<max|min> | return=<col1,col2,...>
             `metric` must be a real column name (either an original dataset
             column or a `result=` column produced by a prior [DERIVE] step, or
             the `value_column=` produced by a prior [GROUPBY] step).
             `return` MUST list every identifier column requested by the
             original query PLUS the metric column itself, so the result dict
             carries both the winning entity and the metric value. When ranking
             a [GROUPBY] result, `return=` should list the `group_column=` used
             in that step plus the metric column.
             Example: metric=z_p99_p1_diff | stat=max | return=latitude,longitude,z_p99_p1_diff

  [SELECT]   columns=<col1,col2,...> | as=<list|dict>
             Example: columns=timestamp | as=list

Rules:
  - Every sub-question line is exactly one `[OPERATION] key=value | key=value | ...` line — no extra words before or after the key=value pairs.
  - CRITICAL: For every restriction or qualifying clause in the original question, include an explicit [FILTER] step that executes before any [GROUPBY], [DERIVE], or [AGGREGATE] step.
  - CRITICAL: Do NOT emit a [FILTER] step unless the original question states a genuine restriction (e.g. a threshold, a category, a time range). Never invent a placeholder/filler filter (such as comparing an identifier or timestamp column to 0) merely to satisfy this rule — if there is no real restriction, omit [FILTER] entirely.
  - CRITICAL: Do NOT add a [FILTER] step to remove null values unless the original query explicitly mentions missing data or data quality. pandas aggregation functions (max, min, mean, etc.) skip nulls by default.
  - CRITICAL: When the question asks to group/bin by a time interval (e.g. "1-minute intervals"), use a single [GROUPBY] step with freq=<offset alias> on the datetime column — do not emit a [FILTER] step for this.
  - CRITICAL: A [RANK] step's `return=` list must include every identifier column the question asks for (e.g. both latitude and longitude) plus the metric column — never a bare scalar.
  - CRITICAL: When a [FILTER] targets a semantic category, enumerate ALL matching values from the schema's ``values=`` list in the `value=` list — never rely solely on examples given in the query text.

Also provide a one-line SYNTHESIS_HINT: how to combine the sub-answers into a
final natural-language response to the original query.

Output format — output ONLY the following lines, nothing else:
SUB_Q1: [OPERATION] key=value | key=value | ...
SUB_Q2: [OPERATION] key=value | key=value | ...
[SUB_Q3: [OPERATION] key=value | key=value | ...]
[SUB_Q4: [OPERATION] key=value | key=value | ...]
SYNTHESIS_HINT: <one-line instruction for combining all sub-answers>\
"""

# ---------------------------------------------------------------------------
# Guardrail + Plan — single structured round-trip (Flash-Fusion default path)
# Returns BOTH the scope verdict and a candidate typed-operator plan, so the
# common case costs one LLM call instead of guardrail + concept extraction +
# schema grounding + sub-query generation.
#
# The STATIC half of this prompt (role, scope rules, operator vocabulary, output
# contract) lives in ``flashfusion.pipeline.operators.FLASH_FUSION_PLANNER_PREFIX``
# so it stays byte-identical across requests and can be served from a provider
# prompt cache. Only the request-specific block below varies.
# Placeholders: {dataset}, {schema_fingerprint}, {column_metadata}, {query}
# ---------------------------------------------------------------------------
PLANNER_DYNAMIC_SUFFIX_TEMPLATE: str = """\
DATASET: {dataset}
SCHEMA_FINGERPRINT: {schema_fingerprint}
SCHEMA:
{column_metadata}

QUESTION: {query}\
"""

# ---------------------------------------------------------------------------
# Guardrail — Pre-execution Feasibility Gate
# Decides whether a query can be answered using available columns.
# Placeholders: {column_metadata}, {grounding}
# The query is passed as the human message at runtime.
# ---------------------------------------------------------------------------
GUARDRAIL_PROMPT: str = """\
You are a strict query feasibility gatekeeper for time-series and sensor datasets.

Available columns and metadata:
{column_metadata}

Schema grounding produced by upstream concept-extraction and schema-grounding
stages for THIS query (concept → column/operation mappings, plus any concepts
that could not be mapped):
{grounding}

Decide whether the user's query can be answered using ONLY the available columns.

How to use the schema grounding above:
  - Treat any concept that was grounded to a real column, a derived-statistic
    operation, or a proxy substitution as available for this query.
  - Treat any concept listed as unmappable as NOT available, UNLESS the query
    text itself explicitly supplies a computable derivation for that concept
    from columns that ARE available.
  - If the query's core intent depends on one or more unmappable concepts with
    no explicit in-query derivation, REJECT — do not attempt to invent a
    substitute mapping yourself.
  - The grounding section is advisory context, not a hard override: if it is
    empty, missing, or does not cover a concept, fall back to reasoning
    directly over the column metadata above.

PROCEED if:
  - All required data can be derived from available columns.
  - The query requires aggregation, filtering, grouping, correlation, ranking, or
    statistical analysis of the available data.
  - The query asks about patterns, comparisons, or distributions across entities.
  - The query requires columns that do not exist BUT explicitly explains how to derive them using mathematically possible operations on available data.

REJECT if:
  - The query requires external data columns that do not exist and cannot be derived.
  - The query's core intent depends on one or more concepts the schema grounding
    could not map to any available column, derived statistic, or proxy, and the
    query text provides no explicit derivation for them.
  - The query requests a prediction, classification, anomaly detection, clustering, or temporal forecast
    but the required inputs or target cannot be derived from the available columns and the procedure
    described in the query.
  - The query asks for future outcomes that depend on external information not represented in the data.
  - The query requires internet access or domain knowledge not in the dataset or query text.
  - The query asks for personally identifying information beyond identifiers present in the schema.

PROCEED for in-dataset predictive tasks when the available data and the query define a
computable procedure. This includes training a model on a specified historical or held-out
subset, predicting a known in-dataset timestamp or record, detecting anomalies, clustering,
or forecasting the next observed in-dataset value from an ordered sequence.

Output format — output ONLY one of these two options, nothing else:
PROCEED
or
REJECT: <one-sentence explanation of why the query cannot be answered>\
"""

# ---------------------------------------------------------------------------
# Synthesis — Combine Sub-answers into Natural Language
# All context is passed in the human message at runtime.
# ---------------------------------------------------------------------------
SYNTHESIS_PROMPT: str = """\
You convert machine-style query outputs into a clear human-readable answer.

Task:
  - Read the original question and the provided sub-answers.
  - Return a direct response that answers the original question.

Rules:
  - Use 1-3 short sentences.
  - Preserve important numbers, counts, labels, and comparisons.
  - Keep it plain and readable.
  - Do not mention implementation details (columns, pandas, sub-queries, code).
  - Do not add caveats or extra commentary.\
"""

# ---------------------------------------------------------------------------
# Judge — Post-execution Intent Alignment
# Checks whether the agent's result correctly answers the original question.
# All context is passed in the human message at runtime.
# ---------------------------------------------------------------------------
JUDGE_PROMPT: str = """\
You are a strict intent-alignment judge for a data analytics pipeline.

You receive:
  - The original user question
  - The ground-truth answer
  - The candidate's final answer

Evaluate whether the candidate's final answer CORRECTLY and COMPLETELY matches
the ground-truth answer in the context of the original question.

Flag FAIL if ANY of the following are true:
  - The final numeric result differs materially from the ground truth.
  - The final answer has a genuinely different semantic referent, such as a
    different entity, aggregation level, time scope, statistic, or unit.
  - The final answer is empty, None, or NaN when the ground truth has a result.

Do NOT penalize equivalent mathematical formulations, intermediate code
representations, variable naming, execution traces, or formatting differences.
Treat numerically equivalent values, including trailing-zero differences and
minor rounding differences below 0.01, as PASS.

Output format — output ONLY the following structure, nothing else:
VERDICT: PASS
or
VERDICT: FAIL
ISSUE: <one-sentence description of the specific problem>
SUGGESTION: <one-sentence fix that would make the result correct>\
"""

# ---------------------------------------------------------------------------
# Plan Judge — Pre-execution Plan Alignment
# Checks whether Stage-3 decomposition is sufficient to answer the question.
# All context is passed in the human message at runtime.
# ---------------------------------------------------------------------------
PLAN_JUDGE_PROMPT: str = """\
You are a strict pre-execution plan judge for a data analytics pipeline.

You receive:
  - The original user question
  - The schema-grounding mappings
  - The Stage-3 sub-query plan
  - The synthesis hint

Evaluate whether the plan would likely produce a correct final answer before
any code is executed.
You must explicitly extract all filters, derivations, and ranking targets from the original question into a CHECKLIST before determining the verdict.

Flag FAIL if ANY of the following are true:
  - The plan misses an explicit [FILTER] step for any qualifying/restricting clause from the original question.
  - Any [RANK] or argmax sub-query doesn't explicitly request returning BOTH the target entity identifier and the metric value used.
  - The plan misses a required part of the question intent.
  - Sub-queries are out of order for the requested analysis
    (e.g. aggregate before required filter/group split).
  - A sub-query is vague or not executable against df.
  - The plan conflicts with schema-grounding mappings.
  - The synthesis hint would not combine results into the asked output.
  - A [FILTER] step uses a semantic category but does NOT enumerate all matching values from the schema's ``values=`` list.

Output format — output ONLY the following structure, nothing else:
CHECKLIST:
  [ ] Filter present: <description>
  [ ] Grouping present: <description>
  [ ] Rank context: explicitly returns BOTH winning entity and metric value (if applicable)
  [ ] Categorical completeness: all matching label values for each semantic group are explicitly listed (if applicable)
VERDICT: PASS
or
VERDICT: FAIL
ISSUE: <one-sentence description of the specific problem>
SUGGESTION: <one-sentence refinement instruction for Stage-3 regeneration>\
"""


# ---------------------------------------------------------------------------
# Static Fast-Path Semantic Router
# A lightweight, highly conservative zero-shot planner limited to five strict
# skeletons. It exists to shortcut the most common query shapes with a single
# cheap LLM call; anything it is not 100% confident about must return
# {"fallback": true} so the full guardrail+planner path runs instead. The
# argument specs below mirror the exact typed operator schemas in
# pipeline/operators.py — do NOT drift them or the router will emit plans that
# fail Gate 1 and waste a round-trip.
# ---------------------------------------------------------------------------
FAST_PATH_PLANNER_TEMPLATE: str = """\
You are a highly conservative fast-path query router.
Schema: {meta_str}
Query: {query}

Your job is to map the query to one of the 6 EXACT plan skeletons below. You may NOT invent operators, change the sequence, or add derivation steps (no DeriveVectorMagnitude, no DeriveBin).
If the query requires ANY computation not perfectly described by these skeletons, or if you are not 100% confident, output exactly: {{"fallback": true}}

Allowed Skeletons (each step is one JSON object; use the EXACT field names and enum values shown):
1. Simple Aggregate:
   [{{"op": "AGGREGATE_COLUMN", "column": <str>, "aggregate": <agg>}}]
2. Filtered Aggregate (FILTER_IN once or twice, then aggregate):
   [{{"op": "FILTER_IN", "column": <str>, "values": [<scalar>, ...]}}, ... , {{"op": "AGGREGATE_COLUMN", "column": <str>, "aggregate": <agg>}}]
3. Filtered Count (either branch):
   [{{"op": "FILTER_COMPARE", "column": <str>, "comparator": <cmp>, "value": <scalar>}}, {{"op": "COUNT_ROWS"}}]
   OR
   [{{"op": "FILTER_IN", "column": <str>, "values": [<scalar>, ...]}}, {{"op": "COUNT_DISTINCT", "column": <str>}}]
4. Partition Compare (exactly two SPLIT_BY_VALUES, then aggregate partitions, then compare):
   [{{"op": "SPLIT_BY_VALUES", "column": <str>, "values": [<scalar>, ...], "label": <str>}}, {{"op": "SPLIT_BY_VALUES", "column": <str>, "values": [<scalar>, ...], "label": <str>}}, {{"op": "AGGREGATE_PARTITIONS", "partitions": [<label>, <label>], "aggregate": <agg>, "column": <str>}}, {{"op": "COMPARE_PARTITIONS", "mode": <mode>}}]
5. Group & Rank:
   [{{"op": "GROUP_AGGREGATE", "group_by": [<str>], "aggregate": <agg>, "column": <str>}}, {{"op": "AGGREGATE_GROUPS", "aggregate": <agg>}}, {{"op": "RANK_GROUPS", "direction": <dir>}}]
6. Chronological Predictive Pipeline (exactly one step):
  [{{"op": "PREDICTIVE_PIPELINE", "model": <predictive_model>, "feature_columns": [<str>, ...], "target_column": <str>, "sort_by": [<str>, ...], "train_fraction": 0.8, "holdout_row": "first", "filter_column": <str|null>, "filter_value": <scalar|null>, "target_from_non_empty": <bool>, "target_label": <str>}}]

Enum values:
  <agg> is one of: "min", "max", "mean", "median", "sum", "count", "std", "var", "nunique", "rms"
  <cmp> is one of: "eq", "ne", "gt", "gte", "lt", "lte"
  <mode> is one of: "difference", "abs_difference", "ratio"
  <dir> is one of: "max", "min"
  <predictive_model> is one of: "logistic_regression", "random_forest", "one_nearest_neighbor", "hist_gradient_boosting"

Rules:
  - Use only column names that appear verbatim in the Schema above.
  - Do not add, remove, or reorder steps relative to the chosen skeleton.
  - For skeleton 5, GROUP_AGGREGATE "column" may be omitted only when its "aggregate" is "count".
  - Use skeleton 6 ONLY for an explicit in-dataset chronological train/holdout prediction request. All feature, target, sort, filter, and target-presence fields must be stated or unambiguously named in the query and Schema.
  - For benchmark-equivalent predictive queries, the operator fields must be identical except for the requested <predictive_model>. Do not substitute, add, remove, or reorder feature_columns or sort_by fields.
  - Set target_from_non_empty=true only when the query asks whether target_column is present or non-empty; otherwise set it false.
  - When in any doubt, output {{"fallback": true}}.

If confident, output valid JSON matching the DeterministicPlan schema: {{"version": "1", "steps": [{{...}}]}}.
Output ONLY JSON.\
"""
