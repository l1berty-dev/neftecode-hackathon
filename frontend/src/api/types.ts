import type {
  Decision,
  ProcessSnapshot,
  ScenarioEvaluation,
} from "./contracts.generated";
import type { components } from "./openapi.generated";

export type { Decision, ProcessSnapshot, ScenarioEvaluation };

type Transport = components["schemas"];

/** Transport shapes are generated from examples/openapi.v1.json. */
export type HealthResponse = Transport["HealthResponse"];
export type ControlDescriptor = Transport["ControlResponse"];
export type ControlsResponse = Transport["ControlsResponse"];
export type EpisodesResponse = Transport["EpisodesResponse"];
export type Episode = Transport["EpisodeResponse"];
export type SnapshotResponse = Omit<Transport["SnapshotResponse"], "snapshot"> & {
  snapshot: ProcessSnapshot;
};
export type DecisionResponse = Omit<Transport["DecisionResponse"], "decision"> & {
  decision: Decision;
};
export type StoredDecisionResponse = Omit<Transport["StoredDecisionResponse"], "decision"> & {
  decision: Decision;
};
export type DecisionSummary = Omit<Transport["DecisionSummary"], "status"> & {
  status: Decision["status"];
};
export type DecisionHistoryResponse = Omit<Transport["DecisionListResponse"], "items"> & {
  items: DecisionSummary[];
};
export type SaveDecisionResponse = Transport["SaveDecisionResponse"];
export type DecideRequest = Transport["DecisionRequest"];
export type ScenarioRequest = Transport["ScenarioRequest"];
export type ScenarioResponse = Omit<Transport["ScenarioResponse"], "evaluation"> & {
  evaluation: ScenarioEvaluation;
};
export type ModelledChainRequest = Transport["ModelledChainRequest"];
export type ModelledChainResult = Transport["ModelledChainResult"];
export type ModelledPreset = Transport["ModelledPreset"];
export type ModelledPresetsResponse = Transport["ModelledPresetsResponse"];
export type ModelledRunResponse = Transport["ModelledRunResponse"];
export type ModelledRunsResponse = Transport["ModelledRunsResponse"];

export interface Api {
  health(signal?: AbortSignal): Promise<HealthResponse>;
  controls(signal?: AbortSignal): Promise<ControlsResponse>;
  episodes(signal?: AbortSignal): Promise<EpisodesResponse>;
  currentSnapshot(signal?: AbortSignal): Promise<SnapshotResponse>;
  snapshot(id: string, signal?: AbortSignal): Promise<SnapshotResponse>;
  startReplay(episodeId: string | null, signal?: AbortSignal): Promise<SnapshotResponse>;
  advanceReplay(expectedSnapshotId: string, signal?: AbortSignal): Promise<SnapshotResponse>;
  decide(request: DecideRequest, signal?: AbortSignal): Promise<DecisionResponse>;
  evaluate(request: ScenarioRequest, signal?: AbortSignal): Promise<ScenarioResponse>;
  savedDecisions(signal?: AbortSignal): Promise<DecisionHistoryResponse>;
  decision(id: string, signal?: AbortSignal): Promise<StoredDecisionResponse>;
  saveDecision(id: string, signal?: AbortSignal): Promise<SaveDecisionResponse>;
  modelledPresets(signal?: AbortSignal): Promise<ModelledPresetsResponse>;
  createModelledRun(
    request: ModelledChainRequest,
    signal?: AbortSignal,
  ): Promise<ModelledRunResponse>;
  modelledRuns(signal?: AbortSignal): Promise<ModelledRunsResponse>;
  modelledRun(id: string, signal?: AbortSignal): Promise<ModelledRunResponse>;
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
