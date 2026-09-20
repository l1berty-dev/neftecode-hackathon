import type {
  Api,
  ControlsResponse,
  DecideRequest,
  DecisionHistoryResponse,
  DecisionResponse,
  HealthResponse,
  SaveDecisionResponse,
  SnapshotResponse,
} from "./types";
import { ApiError } from "./types";

interface ErrorEnvelope {
  code?: string;
  message?: string;
  details?: unknown;
}

export class HttpApi implements Api {
  constructor(private readonly baseUrl: string) {}

  private async request<T>(
    path: string,
    init: RequestInit = {},
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
    if (!response.ok) {
      let payload: ErrorEnvelope = {};
      try {
        payload = (await response.json()) as ErrorEnvelope;
      } catch {
        // A non-JSON proxy failure is still an API error, never a process refusal.
      }
      throw new ApiError(
        payload.message ?? `API вернул HTTP ${response.status}`,
        response.status,
        payload.code ?? "HTTP_ERROR",
        payload.details,
      );
    }
    return (await response.json()) as T;
  }

  health(signal?: AbortSignal) {
    return this.request<HealthResponse>("/health", {}, signal);
  }

  controls(signal?: AbortSignal) {
    return this.request<ControlsResponse>("/controls", {}, signal);
  }

  currentSnapshot(signal?: AbortSignal) {
    return this.request<SnapshotResponse>("/snapshots/current", {}, signal);
  }

  snapshot(id: string, signal?: AbortSignal) {
    return this.request<SnapshotResponse>(`/snapshots/${encodeURIComponent(id)}`, {}, signal);
  }

  startReplay(episodeId: string | null, signal?: AbortSignal) {
    return this.request<SnapshotResponse>(
      "/replay/start",
      { method: "POST", body: JSON.stringify({ episode_id: episodeId }) },
      signal,
    );
  }

  advanceReplay(expectedSnapshotId: string, signal?: AbortSignal) {
    return this.request<SnapshotResponse>(
      "/replay/advance",
      { method: "POST", body: JSON.stringify({ expected_snapshot_id: expectedSnapshotId }) },
      signal,
    );
  }

  decide(request: DecideRequest, signal?: AbortSignal) {
    return this.request<DecisionResponse>(
      "/decisions",
      { method: "POST", body: JSON.stringify(request) },
      signal,
    );
  }

  savedDecisions(signal?: AbortSignal) {
    return this.request<DecisionHistoryResponse>("/decisions?saved_only=true&limit=20", {}, signal);
  }

  decision(id: string, signal?: AbortSignal) {
    return this.request<DecisionResponse>(`/decisions/${encodeURIComponent(id)}`, {}, signal);
  }

  saveDecision(id: string, signal?: AbortSignal) {
    return this.request<SaveDecisionResponse>(
      `/decisions/${encodeURIComponent(id)}/save`,
      { method: "POST" },
      signal,
    );
  }
}
