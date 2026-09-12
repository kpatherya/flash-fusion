"""
eval/queries.py — WISDM benchmark query definitions.

DO NOT MODIFY without re-running the full benchmark and updating CLAUDE.md.

Each query is a dict with:
  id         (int)   1-indexed query identifier
  text       (str)   The exact natural language query fed to each baseline
    complexity (str)   "direct" | "intermediate" | "out_of_scope" | "predictive" | "extra_hard"
  operation  (str)   Primary pandas operation expected (AGGREGATE, FILTER, etc.)
  stress     (str)   Which capability gap this query exposes

EXPECTED_OUTCOMES maps query id → baseline → expected behaviour keyword:
  "executes"  — agent runs code and produces a numerical/tabular result
    "rejects"   — baseline declines execution with an explicit rationale
"""

from __future__ import annotations

DATASET_WISDM = "wisdm"
DATASET_MIT_ECG = "mit_ecg"
DATASET_BUS = "bus"

SUPPORTED_DATASETS = (DATASET_WISDM, DATASET_MIT_ECG, DATASET_BUS)

WISDM_QUERIES: list[dict] = [
    {
        "id": 1,
        "text": "What is the maximum recorded x-acceleration for user 15?",
        "complexity": "direct",
        "operation": "FILTER+AGGREGATE",
        "stress": (
            "direct scalar lookup baseline. All tool-using baselines should execute. "
            "Used to confirm that differences on later queries are due to reasoning depth, "
            "not basic filtering or aggregation failures."
        ),
    },
    {
        "id": 2,
        "text": "How many users have the activity label walking?",
        "complexity": "direct",
        "operation": "FILTER+COUNT",
        "stress": (
            "Category counting with activity-label normalization. "
            "WellMax-Only and Flash-Fusion should align when labels are normalized; "
            "Agent-Only can drift if it misreads label variants."
        ),
    },
    {
        "id": 3,
        "text": "What is the average y-acceleration of user 5 with activity label Sitting?",
        "complexity": "direct",
        "operation": "FILTER+AGGREGATE",
        "stress": (
            "Conjunctive filter (subject + activity) with numeric aggregation. "
            "This separates robust structured filtering from single-column lookups."
        ),
    },
    {
        "id": 4,
        "text": "Which user has the highest total number of recorded data samples?",
        "complexity": "direct",
        "operation": "GROUPBY+RANK",
        "stress": (
            "Groupby+argmax control query. "
            "Expected to execute across all three tool-using baselines and validate "
            "ranking correctness before harder reasoning prompts."
        ),
    },
    {
        "id": 5,
        "text": (
            "Compare the overall acceleration magnitude between dynamic (walking,jogging,upstairs,downstairs) and resting (sitting,standing) states."
        ),
        "complexity": "intermediate",
        "operation": "FILTER+AGGREGATE",
        "stress": (
            "Requires derived feature reasoning (`magnitude`) and semantic grouping of "
            "dynamic vs resting activities. Flash-Fusion should consistently ground this "
            "before execution; Agent-Only and WellMax-Only may collapse to weaker proxies."
        ),
    },
    {
        "id": 6,
        "text": (
            "Identify the user whose total recorded duration of resting states (sitting,standing) "
            "exceeds their duration of dynamic movements (walking,jogging,upstairs,downstairs) by the largest margin."
        ),
        "complexity": "intermediate",
        "operation": "FILTER+GROUPBY+COMPARE",
        "stress": (
            "Multi-step decomposition query: map stationary/locomotion sets, aggregate per user, "
            "then compare totals. Flash-Fusion should execute a faithful analytic chain; "
            "Agent-Only and WellMax-Only may simplify intent or mishandle category mapping."
        ),
    },
    {
        "id": 7,
        "text": (
            "What is the median acceleration magnitude for user 20 with activity label Upstairs?"
        ),
        "complexity": "intermediate",
        "operation": "FILTER+DERIVE+AGGREGATE",
        "stress": (
            "Derived vector magnitude plus median aggregation under activity synonym handling "
            "(ascending steps/upstairs/stairs). Flash-Fusion is expected to preserve the full "
            "intent path; weaker baselines may use raw-axis shortcuts."
        ),
    },
    {
        "id": 8,
        "text": (
            "Calculate the absolute difference between the mean z-axis acceleration of "
            "activity labels Upstairs and Downstairs."
        ),
        "complexity": "intermediate",
        "operation": "FILTER+AGGREGATE+DIFF",
        "stress": (
            "Comparative aggregation across two activity families. "
            "Flash-Fusion should return a computed signed difference; Agent-Only and "
            "WellMax-Only may answer descriptively without robust calculation."
        ),
    },
    {
        "id": 9,
        "text": (
            "How does the average walking speed in miles per hour correlate with the age of the users?"
        ),
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": (
            "Out-of-scope feature request: speed and age are unavailable in WISDM schema. "
            "Flash-Fusion should reject with schema-grounded rationale; Agent-Only and "
            "WellMax-Only are expected to attempt execution anyway."
        ),
    },
    {
        "id": 10,
        "text": "Based on the acceleration data, predict the exact geographic location where user 10 was jogging.",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": (
            "Out-of-scope inference: geolocation is not represented in this dataset. "
            "Flash-Fusion should reject; Agent-Only and WellMax-Only are expected to "
            "proceed despite missing required signals."
        ),
    },
    {
        "id": 11,
        "text": "Are female subjects more likely to have a higher cadence during stair climbing than male subjects?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": (
            "Out-of-scope demographic + cadence analysis. Sex and cadence fields are absent. "
            "Flash-Fusion should reject on schema/feasibility grounds while Agent-Only "
            "and WellMax-Only are expected to attempt execution."
        ),
    },
    {
        "id": 12,
        "text": "Predict whether user 3 will meet the WHO recommended weekly moderate-to-vigorous physical activity guideline next week.",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": (
            "Out-of-scope forecasting task requiring future behavior prediction and an external "
            "public-health guideline threshold not represented in the dataset. Flash-Fusion should "
            "reject on forecasting/scope grounds; Agent-Only and WellMax-Only are expected to "
            "attempt execution anyway."
        ),
    },
    {
        "id": 13,
        "text": (
            "Sort all WISDM rows by timestamp in ascending order, using subject_id as the tie-breaker. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a logistic regression model using the features x, y and z. "
            "Predict the activity label for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 activity prediction with deterministic chronological split.",
    },
    {
        "id": 14,
        "text": (
            "Sort all WISDM rows by timestamp in ascending order, using subject_id as the tie-breaker. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a random forest model using the features x, y and z. "
            "Predict the activity label for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 activity prediction with deterministic chronological split.",
    },
    {
        "id": 15,
        "text": (
            "Sort all WISDM rows by timestamp in ascending order, using subject_id as the tie-breaker. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a 1-nearest-neighbor model using the features x, y and z. "
            "Predict the activity label for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 activity prediction with deterministic chronological split.",
    },
    {
        "id": 16,
        "text": (
            "Sort all WISDM rows by timestamp in ascending order, using subject_id as the tie-breaker. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a hist gradient boosting model using the features x, y and z. "
            "Predict the activity label for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 activity prediction with deterministic chronological split.",
    },
    {
        "id": 17,
        "text": (
            "For each subject_id, derive acceleration magnitude, split rows into a dynamic partition "
            "(Walking, Jogging, Upstairs, Downstairs) and a resting partition (Sitting, Standing), "
            "compute each partition's mean magnitude per subject_id, then compute the per-subject_id "
            "difference (dynamic mean minus resting mean). Rank subject_id values by this difference "
            "in descending order and report the top-ranked subject_id and its difference value rounded to two decimals."
        ),
        "complexity": "extra_hard",
        "operation": "DERIVE+PARALLEL_AGGREGATE+COMPARE+RANK",
        "stress": "Compositional-depth ablation: dynamic/resting per-user comparison and ranking over supported operator concepts.",
    },
    {
        "id": 18,
        "text": (
            "Filter to subject_id values with at least 200 Jogging samples. For each such subject_id, "
            "compute the variance of x-acceleration while Jogging and while Walking. Keep subject_id values "
            "where the Jogging variance exceeds 1.5 times the Walking variance. Among the retained subject_id "
            "values, bin them by whether total Jogging duration is above or below the dataset-wide median Jogging "
            "duration, and report the count of retained subject_id values in each bin."
        ),
        "complexity": "extra_hard",
        "operation": "FILTER+GROUPBY+COMPARE+DERIVE_DURATION+BIN+COUNT",
        "stress": "Compositional-depth ablation: combines sample eligibility, parallel variances, duration derivation, and a median split.",
    },
    {
        "id": 19,
        "text": (
            "Compute the y-acceleration mean for each (subject_id, activity_label) group with at least 50 samples. "
            "Rank groups within each activity_label by mean descending. Report, for each activity_label, the "
            "subject_id ranked first, then compute the correlation between these top subject_id values' overall "
            "sample counts and their average x-acceleration magnitude across all activities."
        ),
        "complexity": "extra_hard",
        "operation": "FILTER+GROUPBY+RANK+SELECT+DERIVE+CORRELATE",
        "stress": "Compositional-depth ablation: group eligibility, within-label ranking, selected-user aggregation, and correlation.",
    },
    {
        "id": 20,
        "text": (
            "Split the WISDM data chronologically by timestamp into 5 equal-sized partitions. Within each partition, "
            "compute the mean acceleration magnitude and the count of distinct subject_id values. Rank the partitions "
            "by mean magnitude descending. Compare the highest-ranked partition to the lowest-ranked partition and "
            "report the ratio of their distinct-subject_id counts."
        ),
        "complexity": "extra_hard",
        "operation": "CHRONO_PARTITION+DERIVE+AGGREGATE+RANK+COMPARE",
        "stress": "Compositional-depth ablation: chronological partitioning, parallel aggregates, ranking, and comparison.",
    },
]

MIT_ECG_QUERIES: list[dict] = [
    {
        "id": 1,
        "text": "What is the minimum MLII value recorded for record_id 101?",
        "complexity": "direct",
        "operation": "FILTER+AGGREGATE",
        "stress": "Single-column min over one record.",
    },
    {
        "id": 2,
        "text": "What is the total recording duration in seconds (maximum time_s) for record_id 234?",
        "complexity": "direct",
        "operation": "FILTER+AGGREGATE",
        "stress": "Max time_s extraction for a single record.",
    },
    {
        "id": 3,
        "text": "For record_id 106, how many samples have MLII > 0?",
        "complexity": "direct",
        "operation": "FILTER+COUNT",
        "stress": "Simple numeric threshold filtering and counting.",
    },
    {
        "id": 4,
        "text": "What is the timestamp (time_s) of the last annotated beat for record_id 221?",
        "complexity": "direct",
        "operation": "FILTER+AGGREGATE",
        "stress": "Annotation-presence filtering followed by max aggregation.",
    },
    {
        "id": 5,
        "text": "For record_id 208, what is the average count of rows with a non-empty annotation in each 60-second time_s bin?",
        "complexity": "intermediate",
        "operation": "FILTER+AGGREGATE+DERIVE",
        "stress": "Multi-step derivation mapping annotation counts to a per-minute rate.",
    },
    {
        "id": 6,
        "text": "Which record_id exhibits the largest difference between maximum and minimum MLII?",
        "complexity": "intermediate",
        "operation": "GROUPBY+AGGREGATE+DERIVE+RANK",
        "stress": "Groupwise derivation of range (max-min) requiring multi-column aggregation before ranking.",
    },
    {
        "id": 7,
        "text": "For record_id 101, which 10-second interval contains the highest number of annotated beats?",
        "complexity": "intermediate",
        "operation": "DERIVE+FILTER+GROUPBY+RANK",
        "stress": "Requires binning/windowing time_s into math-derived intervals (time_s // 10) and grouping by those derived bins.",
    },
    {
        "id": 8,
        "text": "Calculate the root mean square (RMS) of the MLII signal for record_id 106.",
        "complexity": "intermediate",
        "operation": "FILTER+DERIVE+AGGREGATE",
        "stress": "Mathematical transformation mapping a named concept (squaring, mean, root) onto a signal column.",
    },
    {
        "id": 9,
        "text": "Did the patient corresponding to record_id 101 experience a fatal cardiac event within a year?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Patient outcome and longitudinal mortality data are unavailable.",
    },
    {
        "id": 10,
        "text": "Is there a statistical correlation between patient BMI and their maximum MLII amplitude?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Body Mass Index (weight/height) metadata is not in the schema.",
    },
    {
        "id": 11,
        "text": "Which patients in this dataset have a recorded family history of brain cancer?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Family medical history is entirely absent from the dataset.",
    },
    {
        "id": 12,
        "text": "Estimate the patient's weight during the time of the recording for record_id 105.",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Hemodynamic variables like blood pressure are not collected in this dataset.",
    },
    {
        "id": 13,
        "text": (
            "Filter to record_id 101 and sort its rows by time_s in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a logistic regression model using the features MLII and V1. "
            "Predict whether an annotation is present for the first row in the holdout set."
            # "Return the model’s raw predicted annotation value exactly as emitted. Do not map, interpret, or translate labels."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 annotation prediction with deterministic chronological split.",
    },
    {
        "id": 14,
        "text": (
            "Filter to record_id 101 and sort its rows by time_s in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a random forest model using the features MLII and V1. "
            "Predict whether an annotation is present for the first row in the holdout set."
            # "Return the model’s raw predicted annotation value exactly as emitted. Do not map, interpret, or translate labels."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 annotation prediction with deterministic chronological split.",
    },
    {
        "id": 15,
        "text": (
            "Filter to record_id 101 and sort its rows by time_s in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a 1-nearest-neighbor model using the features MLII and V1. "
            "Predict whether an annotation is present for the first row in the holdout set."
            # "Return the model’s raw predicted annotation value exactly as emitted. Do not map, interpret, or translate labels."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 annotation prediction with deterministic chronological split.",
    },
    {
        "id": 16,
        "text": (
            "Filter to record_id 101 and sort its rows by time_s in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a hist gradient boosting model using the features MLII and V1. "
            "Predict whether an annotation is present for the first row in the holdout set."
            # "Return the model’s raw predicted annotation value exactly as emitted. Do not map, interpret, or translate labels."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 annotation prediction with deterministic chronological split.",
    },
    {
        "id": 17,
        "text": (
            "For each record_id, filter to rows with non-empty annotation, then compute the RMS of MLII within "
            "10-second time_s bins. Rank the bins within each record_id by RMS descending, keep the top bin per "
            "record_id, then rank record_id values by their top-bin RMS descending and report the top record_id "
            "and its top-bin RMS."
        ),
        "complexity": "extra_hard",
        "operation": "FILTER+BIN+GROUPBY+RMS+RANK",
        "stress": "Compositional-depth ablation: annotation filtering, temporal binning, RMS aggregation, and nested ranking.",
    },
    {
        "id": 18,
        "text": (
            "For each record_id, compute the difference between maximum and minimum MLII and the count of annotated beats. "
            "Split record_id values into two groups by whether their annotated-beat count is above or below the dataset "
            "median. Within each group, compute the average MLII range. Compare the two group averages and report which "
            "group has the larger range along with the numeric difference."
        ),
        "complexity": "extra_hard",
        "operation": "GROUPBY+DERIVE+FILTER+MEDIAN_SPLIT+AGGREGATE+COMPARE",
        "stress": "Compositional-depth ablation: cross-metric per-record state, a median split, and partition comparison.",
    },
    {
        "id": 19,
        "text": (
            "For record_id 101, bin time_s into 10-second windows, count annotated beats per window, then compute the "
            "correlation between window index and annotated-beat count across the record's duration. Report the correlation "
            "coefficient rounded to three decimals."
        ),
        "complexity": "extra_hard",
        "operation": "FILTER+BIN+FILTER+GROUPBY+SELECT+CORRELATE",
        "stress": "Compositional-depth ablation: record scoping, binning, annotation counting, projection, and correlation.",
    },
    {
        "id": 20,
        "text": (
            "Across all record_id values, compute each record's MLII variance and V1 variance. Rank record_id values by "
            "MLII variance descending and separately by V1 variance descending. Identify record_id values that fall in the "
            "top 5 of both rankings. Among these overlapping record_id values, compute the average duration (maximum time_s) "
            "and compare it to the dataset-wide average duration across all record_id values, reporting the absolute difference."
        ),
        "complexity": "extra_hard",
        "operation": "GROUPBY+RANK+INTERSECT+AGGREGATE+COMPARE",
        "stress": "Compositional-depth ablation: independent ranking streams, top-k intersection, duration aggregation, and comparison.",
    },
]

BUS_QUERIES: list[dict] = [
    {
        "id": 1,
        "text": "What is the maximum accel_variance observed in this dataset?",
        "complexity": "direct",
        "operation": "AGGREGATE",
        "stress": "Single-column max over the entire dataset.",
    },
    {
        "id": 2,
        "text": "What is the average accel_mean across all recorded samples?",
        "complexity": "direct",
        "operation": "AGGREGATE",
        "stress": "Dataset-wide scalar mean computation.",
    },
    {
        "id": 3,
        "text": "List all timestamps where accel_stats_z_p99 reaches its maximum value across the dataset.",
        "complexity": "direct",
        "operation": "AGGREGATE+FILTER+SELECT",
        "stress": "Handles ties: find the max value, then return all timestamps matching that value.",
    },
    {
        "id": 4,
        "text": "How many data samples show an accel_variance strictly greater than 0.20?",
        "complexity": "direct",
        "operation": "FILTER+COUNT",
        "stress": "Simple numeric threshold filtering and row counting.",
    },
    {
        "id": 5,
        "text": "Is the northern half of the route (latitude above median) rougher than the southern half, based on average acceleration variance?",
        "complexity": "intermediate",
        "operation": "DERIVE+FILTER+AGGREGATE+COMPARE",
        "stress": "Requires computing a median threshold, splitting the data spatially, mapping 'rougher' to accel_variance, and comparing the two groups.",
    },
    {
        "id": 6,
        "text": "Which location (latitude, longitude) recorded the largest difference between the 99th and 1st percentile of the z-axis acceleration?",
        "complexity": "intermediate",
        "operation": "DERIVE+RANK+SELECT",
        "stress": "Derivation of a compound feature (z_p99 - z_p1) mapped to a semantic concept, followed by coordinate retrieval.",
    },
    {
        "id": 7,
        "text": "Calculate the average overall magnitude of peak acceleration using the 99th percentiles of the X, Y, and Z axes.",
        "complexity": "intermediate",
        "operation": "DERIVE+AGGREGATE",
        "stress": "Mathematical derivation of a 3D vector magnitude [sqrt(x^2 + y^2 + z^2)] applied to explicit percentile columns.",
    },
    {
        "id": 8,
        "text": "If we group the data into 1-minute intervals, which time window has the highest mean instability_score?",
        "complexity": "intermediate",
        "operation": "DERIVE+GROUPBY+AGGREGATE+RANK",
        "stress": "Requires parsing string timestamps into math-derived time bins (truncating to minutes), grouping, and ranking. The statistic is named explicitly: 'most sustained turbulence' left the reducer (mean vs sum vs max) to the sampler, so the same question produced different plans and different correct-looking answers across runs.",
    },
    {
        "id": 9,
        "text": "How does passenger occupancy correlate with road roughness during this trip?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Passenger occupancy data is entirely unavailable.",
    },
    {
        "id": 10,
        "text": "Did rainy weather cause the roughest segments in this route?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Meteorological and weather condition metadata are absent.",
    },
    {
        "id": 11,
        "text": "Was the bus driver complying with their operating schedule?",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Shift logs and expected arrival times are not included in the dataset.",
    },
    {
        "id": 12,
        "text": "Predict next week's pothole repairs for the road segments in this dataset.",
        "complexity": "out_of_scope",
        "operation": "NONE",
        "stress": "Future maintenance schedules and repair labels are unavailable.",
    },
    {
        "id": 13,
        "text": (
            "Sort all bus rows by timestamp in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a logistic regression model using the acceleration features. "
            "Predict the label in the behavior column for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 behavior prediction with deterministic chronological split.",
    },
    {
        "id": 14,
        "text": (
            "Sort all bus rows by timestamp in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a random forest model using the acceleration features. "
            "Predict the label in the behavior column for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 behavior prediction with deterministic chronological split.",
    },
    {
        "id": 15,
        "text": (
            "Sort all bus rows by timestamp in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a 1-nearest-neighbor model using the acceleration features. "
            "Predict the label in the behavior column for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 behavior prediction with deterministic chronological split.",
    },
    {
        "id": 16,
        "text": (
            "Sort all bus rows by timestamp in ascending order. "
            "Use the first 80% of rows for training and the final 20% as the chronological holdout. "
            "Train a hist gradient boosting model using the acceleration features. "
            "Predict the label in the behavior column for the first row in the holdout set."
        ),
        "complexity": "predictive",
        "operation": "CHRONO_SPLIT+CLASSIFY",
        "stress": "Model-specific T+1 behavior prediction with deterministic chronological split.",
    },
    {
        "id": 17,
        "text": (
            "Split timestamps into 1-minute bins. For each bin, compute mean instability_score and mean accel_variance. "
            "Rank bins by mean instability_score descending, keep the top 10% of bins, then within that top decile compute "
            "the correlation between mean accel_variance and mean instability_score."
        ),
        "complexity": "extra_hard",
        "operation": "BIN+GROUPBY+RANK+THRESHOLD+SELECT+CORRELATE",
        "stress": "Compositional-depth ablation: temporal binning, dual metrics, decile selection, and correlation.",
    },
    {
        "id": 18,
        "text": (
            "Compute peak acceleration magnitude per row using the 99th-percentile x, y, and z columns. Split rows into "
            "a northern half (latitude above median) and a southern half (latitude at or below median). Within each half, "
            "compute the mean peak magnitude and the count of rows where accel_variance exceeds 0.20. Compare the two halves "
            "on both metrics and report which half is rougher by both criteria, or state disagreement."
        ),
        "complexity": "extra_hard",
        "operation": "DERIVE+MEDIAN_SPLIT+AGGREGATE+FILTER+COUNT+COMPARE",
        "stress": "Compositional-depth ablation: vector derivation, complementary partitions, dual criteria, and agreement logic.",
    },
    {
        "id": 19,
        "text": (
            "For each 5-minute time bin, compute the range (accel_stats_z_p99 minus accel_stats_z_p1) and the mean "
            "extreme_event_magnitude. Rank bins by range descending, keep the top 3 bins, then compute the behavior-label "
            "distribution across just those bins, and report the most frequent behavior label among them."
        ),
        "complexity": "extra_hard",
        "operation": "BIN+DERIVE+GROUPBY+RANK+SELECT+GROUPBY",
        "stress": "Compositional-depth ablation: derived range, top-k selection, and selected-bin label distribution.",
    },
    {
        "id": 20,
        "text": (
            "Compute per-minute mean accel_mean and mean accel_variance. Split minutes into quartiles by mean accel_variance. "
            "Within the top quartile (roughest) and bottom quartile (smoothest), compute the average instability_score. "
            "Compare the two quartile averages and report the ratio of roughest to smoothest instability_score, rounded to two decimals."
        ),
        "complexity": "extra_hard",
        "operation": "BIN+GROUPBY+QUARTILE_SPLIT+AGGREGATE+COMPARE",
        "stress": "Compositional-depth ablation: minute aggregation, quartile assignment, partition aggregates, and ratio comparison.",
    },
]

def get_queries(dataset: str) -> list[dict]:
    if dataset == DATASET_WISDM:
        return WISDM_QUERIES
    if dataset == DATASET_MIT_ECG:
        return MIT_ECG_QUERIES
    if dataset == DATASET_BUS:
        return BUS_QUERIES
    raise ValueError(f"Unsupported dataset {dataset!r}. Supported: {SUPPORTED_DATASETS}")

