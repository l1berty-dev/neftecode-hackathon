import type {
  Decision,
  ProcessSnapshot,
  ScenarioEvaluation,
} from "./contracts.generated";

export type { Decision, ProcessSnapshot, ScenarioEvaluation };

/** Transport boundary kept aligned with the published examples/openapi.v1.json. */
export interface HealthResponse {
  ready: boolean;
  model_ready: boolean;
  data_ready: boolean;
  database_ready: boolean;
}

export interface ControlDescriptor {
  signal_id: string;
  label: string;
  available: boolean;
  reason: string | null;
  unit: string | null;
  min: number | null;
  max: number | null;
  step: number | null;
  source: string;
}

export interface ControlsResponse {
  constraint_version: string;
  controls: ControlDescriptor[];
}

export interface SnapshotResponse {
  snapshot: ProcessSnapshot;
  current_snapshot_id: string;
}

export interface DecisionResponse {
  decision: Decision;
  current_snapshot_id: string;
  stale: boolean;
}

export interface DecisionSummary {
  decision_id: string;
  snapshot_id: string;
  created_at: string;
  status: Decision["status"];
  saved: boolean;
}

export interface DecisionHistoryResponse {
  items: DecisionSummary[];
}

export interface SaveDecisionResponse {
  decision_id: string;
  saved: boolean;
}

export interface DecideRequest {
  snapshot_id: string;
  horizon_minutes: number;
  operator_action: null | {
    label: string;
    changes: Record<string, number>;
  };
}

export interface Api {
  health(signal?: AbortSignal): Promise<HealthResponse>;
  controls(signal?: AbortSignal): Promise<ControlsResponse>;
  currentSnapshot(signal?: AbortSignal): Promise<SnapshotResponse>;
  snapshot(id: string, signal?: AbortSignal): Promise<SnapshotResponse>;
  startReplay(episodeId: string | null, signal?: AbortSignal): Promise<SnapshotResponse>;
  advanceReplay(expectedSnapshotId: string, signal?: AbortSignal): Promise<SnapshotResponse>;
  decide(request: DecideRequest, signal?: AbortSignal): Promise<DecisionResponse>;
  savedDecisions(signal?: AbortSignal): Promise<DecisionHistoryResponse>;
  decision(id: string, signal?: AbortSignal): Promise<DecisionResponse>;
  saveDecision(id: string, signal?: AbortSignal): Promise<SaveDecisionResponse>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestToken {
  generation: number;
  key: string;
  signal: AbortSignal;
}

/** Abort and a generation key are both required: abort alone cannot prevent late commits. */
export class LatestRequestGate {
  private generation = 0;
  private controller: AbortController | null = null;

  begin(key: string): RequestToken {
    this.controller?.abort();
    this.controller = new AbortController();
    this.generation += 1;
    return { generation: this.generation, key, signal: this.controller.signal };
  }

  isCurrent(token: RequestToken, key: string): boolean {
    return token.generation === this.generation && token.key === key && !token.signal.aborted;
  }

  cancel(): void {
    this.controller?.abort();
    this.generation += 1;
  }
}

export function requestKey(snapshotId: string, changes: Record<string, number>): string {
  const normalized = Object.entries(changes).sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify([snapshotId, 60, normalized]);
}

export function allEvaluations(decision: Decision): ScenarioEvaluation[] {
  const candidates = [
    decision.baseline,
    decision.preferred,
    ...decision.alternatives,
    ...decision.rejected_evaluations,
  ].filter((value): value is ScenarioEvaluation => value !== null);
  return [...new Map(candidates.map((value) => [value.evaluation_id, value])).values()];
}
