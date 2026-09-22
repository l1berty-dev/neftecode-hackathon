import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Api, ModelledChainRequest, ModelledChainResult, ModelledPreset } from "../api/types";
import { ModelledDashboard } from "./ModelledDashboard";

const request = {
  preset_id: "stable_k5",
  avt_inputs: {},
  feed: {
    straight_run_sulfur_mass_pct: 0.28,
    t95_c: 350,
    cetane_number: 49,
    age_minutes: 0,
  },
  controls: { p8: 0.1569, t11: 362.88, f19: 212.04 },
  operator_controls: null,
  specification: {
    profile: "k5_summer",
    sulfur_max_mg_kg: 10,
    t95_max_c: 360,
    cetane_min: 51,
  },
  tanks: [{
    component_id: "clean",
    name: "Чистый компонент",
    available_tonnes: 1000,
    sulfur_mg_kg: 6,
    t95_c: 350,
    cetane_number: 52,
    relative_cost: 1.08,
  }],
  additive_ppm: 0,
  horizon_minutes: 180,
} as ModelledChainRequest;

const preset = {
  preset_id: "stable_k5",
  name: "Стабильный К5",
  description: "Тестовый сценарий",
  expected_status: "no_change",
  request,
} as ModelledPreset;

function resultFor(payload: ModelledChainRequest) {
  return {
    run_id: "11111111-1111-4111-8111-111111111111",
    created_at: "2026-09-22T12:00:00Z",
    status: "no_change",
    request: payload,
    avt: { t90_c: null, t50_c: null, t95_c: null, cloud_point_c: null, cfpp_c: null, reasons: [] },
    baseline: null,
    preferred: null,
    alternatives: [],
    blend: null,
    hard_checks: [],
    recommendation: ["Расчёт выполнен для текущих параметров."],
    assumptions: [],
    trace: [],
    model_version: "test-model",
    constraint_version: "test-constraints",
  } as ModelledChainResult;
}

describe("ModelledDashboard", () => {
  it("hides a stale result and offers recalculation next to edited inputs", async () => {
    const createModelledRun = vi.fn(async (payload: ModelledChainRequest) => ({
      result: resultFor(structuredClone(payload)),
    }));
    const api = {
      modelledPresets: vi.fn(async () => ({ items: [preset] })),
      modelledRuns: vi.fn(async () => ({ items: [] })),
      modelledRun: vi.fn(),
      createModelledRun,
    } as unknown as Api;
    const user = userEvent.setup();
    render(<ModelledDashboard api={api} />);

    await user.click(await screen.findByRole("button", { name: "Рассчитать цепочку" }));
    expect(await screen.findByText("Расчёт выполнен для текущих параметров.")).toBeInTheDocument();

    const sulfur = screen.getByRole("spinbutton", { name: "Сера прямогонного ДТ, % масс." });
    await user.clear(sulfur);
    await user.type(sulfur, "0.4");

    expect(screen.queryByText("Расчёт выполнен для текущих параметров.")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Предыдущий результат скрыт");

    await user.click(screen.getByRole("button", { name: "Рассчитать изменённую цепочку" }));
    await waitFor(() => expect(createModelledRun).toHaveBeenLastCalledWith(
      expect.objectContaining({
        feed: expect.objectContaining({ straight_run_sulfur_mass_pct: 0.4 }),
      }),
    ));
    expect(await screen.findByText("Расчёт выполнен для текущих параметров.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows only the latest run for each scenario", async () => {
    const api = {
      modelledPresets: vi.fn(async () => ({ items: [preset] })),
      modelledRuns: vi.fn(async () => ({
        items: [
          { run_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", status: "no_change", preset_id: "stable_k5" },
          { run_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", status: "no_feasible_option", preset_id: "stable_k5" },
          { run_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", status: "change_recommended", preset_id: "feed_sulfur_rise" },
        ],
      })),
      modelledRun: vi.fn(),
      createModelledRun: vi.fn(),
    } as unknown as Api;
    render(<ModelledDashboard api={api} />);

    expect(await screen.findByRole("heading", { name: "Operator Assistant" })).toBeInTheDocument();
    expect(screen.queryByText("Советчик, не управление")).not.toBeInTheDocument();
    expect(screen.queryByText(/Эффекты управлений экспериментальные/)).not.toBeInTheDocument();
    expect(screen.getAllByText("stable_k5")).toHaveLength(1);
    expect(screen.getByText("feed_sulfur_rise")).toBeInTheDocument();
    expect(screen.getByText("Решение требует взгляда специалиста перед изменениями характеристик")).toBeInTheDocument();
  });
});
