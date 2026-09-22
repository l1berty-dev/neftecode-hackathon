import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../examples/contract_v1.synthetic.json";
import App from "./App";
import type { ContractExample, Decision } from "./api/contracts.generated";
import { FixtureApi } from "./api/fixture";
import type { Api, DecideRequest, DecisionResponse, ProcessSnapshot } from "./api/types";
import { ApiError } from "./api/types";

const sample = fixture as unknown as ContractExample;

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("App", () => {
  it("marks fixture mode and saves by the server decision id", async () => {
    const api: Api = new FixtureApi();
    const save = vi.spyOn(api, "saveDecision");
    const user = userEvent.setup();
    render(<App api={api} fixtureMode initialMode="replay" />);

    expect(screen.getByText(/DEMO FIXTURE/)).toBeInTheDocument();
    const button = await screen.findByRole("button", { name: "Сохранить решение" });
    await user.click(button);

    await waitFor(() => expect(save).toHaveBeenCalledWith("44444444-4444-4444-8444-444444444444"));
    expect(await screen.findByRole("button", { name: "Сохранено" })).toBeDisabled();
  });

  it("shows an API failure as an error, not as a technological decision", async () => {
    const api: Api = new FixtureApi();
    vi.spyOn(api, "health").mockRejectedValue(new ApiError("Backend недоступен", 503, "UNAVAILABLE"));
    render(<App api={api} initialMode="replay" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend недоступен");
    expect(screen.queryByText("Нет допустимого варианта")).not.toBeInTheDocument();
  });

  it("starts the default real replay episode when a fresh database has no cursor", async () => {
    const api = new FixtureApi();
    vi.spyOn(api, "currentSnapshot").mockRejectedValue(
      new ApiError("Replay has not been started", 404, "not_found"),
    );
    const start = vi.spyOn(api, "startReplay").mockResolvedValue({
      snapshot: sample.snapshot,
      current_snapshot_id: sample.snapshot.snapshot_id,
    });
    render(<App api={api} initialMode="replay" />);

    await waitFor(() => expect(start).toHaveBeenCalledWith("synthetic-fixture", expect.any(AbortSignal)));
    expect(await screen.findByText("Рекомендуется изменение")).toBeInTheDocument();
  });

  it("opens saved history with its original snapshot", async () => {
    const api = new FixtureApi();
    const repeatedReason = "Повторяющееся пояснение остаётся отдельным пунктом.";
    const savedDecision: Decision = {
      ...sample.decision,
      explanation: [...sample.decision.explanation, repeatedReason, repeatedReason],
      trace: [sample.decision.trace[0], sample.decision.trace[0]],
    };
    vi.spyOn(api, "decision").mockResolvedValue({
      decision: savedDecision,
      current_snapshot_id: sample.snapshot.snapshot_id,
      stale: false,
    });
    await api.saveDecision(savedDecision.decision_id);
    const loadDecision = vi.spyOn(api, "decision");
    const loadSnapshot = vi.spyOn(api, "snapshot");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<App api={api} initialMode="replay" />);

    const historyItem = await screen.findByRole("button", {
      name: /Открыть исходный снимок/,
    });
    await user.click(historyItem);

    await waitFor(() => {
      expect(loadDecision).toHaveBeenCalledWith(sample.decision.decision_id);
      expect(loadSnapshot).toHaveBeenCalledWith(sample.snapshot.snapshot_id);
    });
    expect(screen.getAllByText(repeatedReason)).toHaveLength(2);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
  });

  it("checks one operator action without replacing the current decision", async () => {
    const api: Api = new FixtureApi();
    vi.spyOn(api, "controls").mockResolvedValue({
      constraint_version: sample.decision.constraint_version,
      controls: [
        {
          signal_id: "ht:F26",
          label: "Тестовая уставка",
          available: true,
          reason: null,
          unit: "m3/h",
          min: 200,
          max: 300,
          step: 1,
          source: "test",
        },
      ],
      review_issues: [],
    });
    const evaluation = sample.decision.preferred ?? sample.decision.baseline;
    const evaluate = vi.spyOn(api, "evaluate").mockResolvedValue({
      evaluation,
      current_snapshot_id: sample.snapshot.snapshot_id,
      stale: false,
    });
    const user = userEvent.setup();
    render(<App api={api} initialMode="replay" />);

    const originalDecision = await screen.findByText("Рекомендуется изменение");
    const input = await screen.findByRole("spinbutton", { name: /Новое значение/ });
    fireEvent.change(input, { target: { value: "251" } });
    await user.click(screen.getByRole("button", { name: "Только проверить" }));

    await waitFor(() => expect(evaluate).toHaveBeenCalledWith(
      {
        snapshot_id: sample.snapshot.snapshot_id,
        horizon_minutes: 60,
        changes: { "ht:F26": 251 },
      },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByRole("heading", { name: "Отдельная проверка действия" })).toBeInTheDocument();
    expect(originalDecision).toBeInTheDocument();
  });

  it("does not let a late response for an old snapshot overwrite a new comparison", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const newerSnapshot: ProcessSnapshot = {
      ...sample.snapshot,
      snapshot_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      as_of: "2026-01-15T09:10:00Z",
    };
    let currentCalls = 0;
    let resolveOld!: (value: DecisionResponse) => void;
    const oldRequest = new Promise<DecisionResponse>((resolve) => {
      resolveOld = resolve;
    });
    const newerDecision: Decision = {
      ...sample.decision,
      decision_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      snapshot_id: newerSnapshot.snapshot_id,
      preferred: sample.decision.preferred
        ? {
            ...sample.decision.preferred,
            snapshot_id: newerSnapshot.snapshot_id,
            action: { ...sample.decision.preferred.action, label: "Совет для нового снимка" },
          }
        : null,
      baseline: { ...sample.decision.baseline, snapshot_id: newerSnapshot.snapshot_id },
    };
    const api: Api = new FixtureApi();
    vi.spyOn(api, "controls").mockResolvedValue({
      constraint_version: sample.decision.constraint_version,
      controls: [
        {
          signal_id: "ht:F26",
          label: "Тестовая уставка",
          available: true,
          reason: null,
          unit: "m3/h",
          min: 200,
          max: 300,
          step: 1,
          source: "test",
        },
      ],
      review_issues: [],
    });
    vi.spyOn(api, "currentSnapshot").mockImplementation(async () => {
      currentCalls += 1;
      const next = currentCalls === 1 ? sample.snapshot : newerSnapshot;
      return { snapshot: next, current_snapshot_id: next.snapshot_id };
    });
    vi.spyOn(api, "decide").mockImplementation(async (request: DecideRequest) => {
      if (request.snapshot_id === newerSnapshot.snapshot_id) {
        return {
          decision: newerDecision,
          current_snapshot_id: newerSnapshot.snapshot_id,
          stale: false,
        };
      }
      if (request.operator_action) return oldRequest;
      return {
        decision: sample.decision,
        current_snapshot_id: sample.snapshot.snapshot_id,
        stale: false,
      };
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App api={api} initialMode="replay" />);

    const input = await screen.findByRole("spinbutton", { name: /Новое значение/ });
    await user.clear(input);
    await user.type(input, "251");
    await user.click(screen.getByRole("button", { name: "Сравнить варианты" }));

    await act(async () => vi.advanceTimersByTime(5000));
    const moveButton = await screen.findByRole("button", { name: "Перейти к новому снимку" });
    await user.click(moveButton);
    expect((await screen.findAllByText("Совет для нового снимка")).length).toBeGreaterThan(0);

    await act(async () => {
      resolveOld({
        decision: {
          ...sample.decision,
          preferred: sample.decision.preferred && {
            ...sample.decision.preferred,
            action: { ...sample.decision.preferred.action, label: "Устаревший совет" },
          },
        },
        current_snapshot_id: newerSnapshot.snapshot_id,
        stale: true,
      });
      await Promise.resolve();
    });
    expect(screen.queryByText("Устаревший совет")).not.toBeInTheDocument();
    expect(screen.getAllByText("Совет для нового снимка").length).toBeGreaterThan(0);
  });
});
