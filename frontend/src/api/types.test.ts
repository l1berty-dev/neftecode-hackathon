import { describe, expect, it } from "vitest";
import { LatestRequestGate, requestKey } from "./types";

describe("LatestRequestGate", () => {
  it("rejects a late response even if the transport ignores abort", () => {
    const gate = new LatestRequestGate();
    const oldToken = gate.begin("snapshot-a");
    const currentToken = gate.begin("snapshot-b");

    expect(oldToken.signal.aborted).toBe(true);
    expect(gate.isCurrent(oldToken, "snapshot-a")).toBe(false);
    expect(gate.isCurrent(currentToken, "snapshot-b")).toBe(true);
  });

  it("creates the same key regardless of control insertion order", () => {
    expect(requestKey("snapshot", { "ht:P8": 340, "ht:F19": 5 })).toBe(
      requestKey("snapshot", { "ht:F19": 5, "ht:P8": 340 }),
    );
  });
});
