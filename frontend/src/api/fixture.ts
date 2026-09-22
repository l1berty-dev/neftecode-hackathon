import fixture from "../../../examples/contract_v1.synthetic.json";
import type { ContractExample } from "./contracts.generated";
import type { Api, DecideRequest, DecisionSummary, ScenarioRequest } from "./types";
import { ApiError } from "./types";

const sample = fixture as unknown as ContractExample;

/** Static development preview. It deliberately does not imitate backend calculations. */
export class FixtureApi implements Api {
  private saved = false;

  async health() {
    return {
      ready: true,
      model_ready: true,
      data_ready: true,
      database_ready: true,
      issues: [],
    };
  }

  async controls() {
    return {
      constraint_version: sample.decision.constraint_version,
      controls: [
        {
          signal_id: "ht:P8",
          label: "Температура ГСС на входе Р-202",
          available: false,
          reason: "В статическом fixture управляющие воздействия не рассчитываются",
          unit: "°C",
          min: null,
          max: null,
          step: null,
          source: "synthetic fixture",
        },
      ],
      review_issues: ["Статический fixture не подтверждает реальные управления"],
    };
  }

  async episodes() {
    return {
      version: "synthetic-fixture-v1",
      episodes: [
        {
          episode_id: "synthetic-fixture",
          name: "Статический synthetic fixture",
          start: sample.snapshot.as_of,
          end: sample.snapshot.as_of,
          step_minutes: 10,
          synthetic: true,
          limitations: ["Нет следующего replay-шага и расчёта новых действий."],
        },
      ],
    };
  }

  async currentSnapshot() {
    return { snapshot: sample.snapshot, current_snapshot_id: sample.snapshot.snapshot_id };
  }

  async snapshot(id: string) {
    if (id !== sample.snapshot.snapshot_id) {
      throw new ApiError("Снимок отсутствует в статическом fixture", 404, "FIXTURE_NOT_FOUND");
    }
    return this.currentSnapshot();
  }

  async startReplay() {
    return this.currentSnapshot();
  }

  async advanceReplay(): Promise<never> {
    throw new ApiError("Статический fixture не содержит следующего шага", 409, "FIXTURE_END");
  }

  async decide(request: DecideRequest) {
    if (request.snapshot_id !== sample.snapshot.snapshot_id || request.operator_action) {
      throw new ApiError(
        "Статический fixture не рассчитывает пользовательские действия",
        422,
        "FIXTURE_STATIC",
      );
    }
    return {
      decision: sample.decision,
      current_snapshot_id: sample.snapshot.snapshot_id,
      stale: false,
    };
  }

  async evaluate(_request: ScenarioRequest): Promise<never> {
    throw new ApiError(
      "Статический fixture не рассчитывает пользовательские действия",
      422,
      "FIXTURE_STATIC",
    );
  }

  async savedDecisions() {
    const items: DecisionSummary[] = this.saved
      ? [
          {
            decision_id: sample.decision.decision_id,
            snapshot_id: sample.snapshot.snapshot_id,
            created_at: sample.snapshot.as_of,
            status: sample.decision.status,
            saved: true,
          },
        ]
      : [];
    return { items };
  }

  async decision(id: string) {
    if (id !== sample.decision.decision_id) {
      throw new ApiError("Решение отсутствует в статическом fixture", 404, "FIXTURE_NOT_FOUND");
    }
    return {
      decision: sample.decision,
      current_snapshot_id: sample.snapshot.snapshot_id,
      stale: false,
    };
  }

  async saveDecision(id: string) {
    if (id !== sample.decision.decision_id) {
      throw new ApiError("Решение отсутствует в статическом fixture", 404, "FIXTURE_NOT_FOUND");
    }
    this.saved = true;
    return { decision_id: id, saved: true as const };
  }

  async modelledPresets(): Promise<never> {
    throw new ApiError("Модельные сценарии недоступны в fixture", 503, "FIXTURE_STATIC");
  }

  async createModelledRun(): Promise<never> {
    throw new ApiError("Модельные сценарии недоступны в fixture", 503, "FIXTURE_STATIC");
  }

  async modelledRuns(): Promise<never> {
    throw new ApiError("Модельные сценарии недоступны в fixture", 503, "FIXTURE_STATIC");
  }

  async modelledRun(): Promise<never> {
    throw new ApiError("Модельные сценарии недоступны в fixture", 503, "FIXTURE_STATIC");
  }
}
