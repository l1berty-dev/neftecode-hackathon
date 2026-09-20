/* AUTO-GENERATED from examples/contract_v1.schema.json. Do not edit manually. */

export type ContractVersion = 1;
export type Synthetic = true;
export type Disclaimer = string;
export type ContractVersion1 = 1;
export type SnapshotId = string;
export type AsOf = string;
export type SnapshotMode = "replay" | "manual";
export type DatasetVersion = string;
export type Value = number | null;
export type Unit = string | null;
export type Source = string;
export type MeasuredAt = string;
export type AvailableAt = string;
export type AgeSeconds = number;
export type MeasurementQuality = "valid" | "suspect" | "missing";
export type Issues = string[];
export type SignalId = string;
export type MeasuredAt1 = string;
export type Value1 = number;
export type History = HistoryRecord[];
export type Issues1 = string[];
export type Completeness = number;
export type ActionId = string;
export type Label = string;
export type ActionOrigin = "baseline" | "system" | "operator";
export type EvaluationId = string;
export type SnapshotId1 = string;
export type HorizonMinutes = number;
export type Target = string;
export type ForecastAt = string;
export type Prediction = number | null;
export type Unit1 = string;
export type Lower = number | null;
export type Upper = number | null;
export type IntervalCoverageTarget = number | null;
export type Applicability = "supported" | "unsupported" | "insufficient_data";
export type Reasons = string[];
export type ModelVersion = string;
export type SeverityIndex = number | null;
export type Name = string;
export type Contribution = number;
export type Explanation = string;
export type Factors = ReliabilityFactor[];
export type TransitionAssessed = boolean;
export type Limitations = string[];
export type Value2 = number | null;
export type Unit2 = string | null;
export type EstimateBasis = "measured" | "predicted" | "proxy" | "unavailable";
export type Explanation1 = string;
export type Lower1 = number | null;
export type Upper1 = number | null;
export type Code = string;
export type Passed = boolean | null;
export type CheckCategory = "data" | "quality" | "reliability" | "control" | "applicability";
export type Message = string;
export type Actual = number | null;
export type Limit = number | null;
export type Unit3 = string | null;
export type Checks = CheckResult[];
export type Admissibility = "admissible" | "rejected" | "not_assessable";
export type Reasons1 = string[];
export type ModelVersion1 = string;
export type ConstraintVersion = string;
export type DecisionId = string;
export type SnapshotId2 = string;
export type HorizonMinutes1 = number;
export type DecisionStatus = "change_recommended" | "no_change" | "insufficient_data" | "no_feasible_option";
/**
 * @maxItems 2
 */
export type Alternatives = [] | [ScenarioEvaluation] | [ScenarioEvaluation, ScenarioEvaluation];
export type RejectedEvaluations = ScenarioEvaluation[];
export type Explanation2 = string[];
export type Role = string;
export type InputIds = string[];
export type OutputSummary = string;
export type CheckCodes = string[];
export type Trace = TraceEntry[];
export type DatasetVersion1 = string;
export type ModelVersion2 = string;
export type ConstraintVersion1 = string;

/**
 * Versioned wrapper used only to exchange the common synthetic fixture.
 */
export interface ContractExample {
  contract_version?: ContractVersion;
  synthetic: Synthetic;
  disclaimer: Disclaimer;
  snapshot: ProcessSnapshot;
  action: Action;
  evaluation: ScenarioEvaluation;
  decision: Decision;
}
export interface ProcessSnapshot {
  contract_version?: ContractVersion1;
  snapshot_id: SnapshotId;
  as_of: AsOf;
  mode: SnapshotMode;
  dataset_version: DatasetVersion;
  values: Values;
  history: History;
  issues?: Issues1;
  completeness: Completeness;
}
export interface Values {
  [k: string]: Measurement;
}
/**
 * One value together with its event time, availability, and quality.
 *
 * This interface was referenced by `Values`'s JSON-Schema definition
 * via the `patternProperty` "^[a-z][a-z0-9_-]*:[^\s]+$".
 */
export interface Measurement {
  value: Value;
  unit: Unit;
  source: Source;
  measured_at: MeasuredAt;
  available_at: AvailableAt;
  age_seconds: AgeSeconds;
  quality: MeasurementQuality;
  issues?: Issues;
}
/**
 * A historical observation included in a snapshot history window.
 */
export interface HistoryRecord {
  signal_id: SignalId;
  measured_at: MeasuredAt1;
  value: Value1;
}
/**
 * Alternative next action; changes are absolute current setpoints.
 */
export interface Action {
  action_id: ActionId;
  label: Label;
  origin: ActionOrigin;
  changes?: Changes;
}
export interface Changes {
  /**
   * This interface was referenced by `Changes`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_-]*:[^\s]+$".
   */
  [k: string]: number;
}
export interface ScenarioEvaluation {
  evaluation_id: EvaluationId;
  snapshot_id: SnapshotId1;
  horizon_minutes: HorizonMinutes;
  action: Action;
  quality: QualityAssessment;
  reliability: ReliabilityAssessment;
  throughput: MetricEstimate;
  cost: MetricEstimate;
  checks: Checks;
  admissibility: Admissibility;
  reasons: Reasons1;
  model_version: ModelVersion1;
  constraint_version: ConstraintVersion;
}
export interface QualityAssessment {
  target: Target;
  forecast_at: ForecastAt;
  prediction: Prediction;
  unit: Unit1;
  lower: Lower;
  upper: Upper;
  interval_coverage_target: IntervalCoverageTarget;
  applicability: Applicability;
  reasons: Reasons;
  model_version: ModelVersion;
}
export interface ReliabilityAssessment {
  severity_index: SeverityIndex;
  factors: Factors;
  transition_assessed: TransitionAssessed;
  limitations: Limitations;
}
export interface ReliabilityFactor {
  name: Name;
  contribution: Contribution;
  explanation: Explanation;
}
export interface MetricEstimate {
  value: Value2;
  unit: Unit2;
  basis: EstimateBasis;
  explanation: Explanation1;
  lower?: Lower1;
  upper?: Upper1;
}
export interface CheckResult {
  code: Code;
  passed: Passed;
  category: CheckCategory;
  message: Message;
  actual?: Actual;
  limit?: Limit;
  unit?: Unit3;
}
export interface Decision {
  decision_id: DecisionId;
  snapshot_id: SnapshotId2;
  horizon_minutes: HorizonMinutes1;
  status: DecisionStatus;
  baseline: ScenarioEvaluation;
  preferred: ScenarioEvaluation | null;
  alternatives: Alternatives;
  rejected_evaluations: RejectedEvaluations;
  explanation: Explanation2;
  trace: Trace;
  dataset_version: DatasetVersion1;
  model_version: ModelVersion2;
  constraint_version: ConstraintVersion1;
}
export interface TraceEntry {
  role: Role;
  input_ids: InputIds;
  output_summary: OutputSummary;
  check_codes?: CheckCodes;
}
