import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../../examples/contract_v1.synthetic.json";
import type { ContractExample } from "../api/contracts.generated";
import { QualityChart } from "./QualityChart";

const sample = fixture as unknown as ContractExample;

describe("QualityChart", () => {
  it("renders a separate forecast point without a forecast trajectory", () => {
    render(<QualityChart snapshot={sample.snapshot} evaluation={sample.evaluation} />);
    expect(screen.getByTestId("forecast-point")).toBeInTheDocument();
    expect(screen.queryByTestId("forecast-line")).not.toBeInTheDocument();
  });

  it("does not invent a forecast when applicability is unsupported", () => {
    const evaluation = {
      ...sample.evaluation,
      quality: { ...sample.evaluation.quality, applicability: "unsupported" as const },
    };
    render(<QualityChart snapshot={sample.snapshot} evaluation={evaluation} />);
    expect(screen.queryByTestId("forecast-point")).not.toBeInTheDocument();
  });
});
