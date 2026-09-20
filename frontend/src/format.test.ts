import { describe, expect, it } from "vitest";
import { formatNumber } from "./format";

describe("formatNumber", () => {
  it("does not turn an unknown estimate into zero", () => {
    expect(formatNumber(null)).toBe("не оценено");
    expect(formatNumber(undefined)).toBe("не оценено");
  });
});
