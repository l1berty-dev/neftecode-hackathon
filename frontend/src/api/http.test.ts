import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../../examples/contract_v1.synthetic.json";
import type { ContractExample } from "./contracts.generated";
import { HttpApi } from "./http";

const sample = fixture as unknown as ContractExample;

afterEach(() => vi.unstubAllGlobals());

describe("HttpApi", () => {
  it("uses the generated OpenAPI routes and request bodies", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ version: "v1", episodes: [] }))
      .mockResolvedValueOnce(
        jsonResponse({ evaluation: sample.evaluation, current_snapshot_id: sample.snapshot.snapshot_id, stale: false }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = new HttpApi("/api/v1");

    await api.episodes();
    await api.evaluate({
      snapshot_id: sample.snapshot.snapshot_id,
      horizon_minutes: 60,
      changes: { "ht:F26": 252 },
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/episodes",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/scenarios/evaluate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          snapshot_id: sample.snapshot.snapshot_id,
          horizon_minutes: 60,
          changes: { "ht:F26": 252 },
        }),
      }),
    );
  });

  it("preserves the backend error code and details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          { code: "state_conflict", message: "Replay state changed", details: { current_snapshot_id: "new" } },
          409,
        ),
      ),
    );
    const api = new HttpApi("/api/v1");

    await expect(api.advanceReplay(sample.snapshot.snapshot_id)).rejects.toEqual(
      expect.objectContaining({
        status: 409,
        code: "state_conflict",
        details: { current_snapshot_id: "new" },
      }),
    );
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
