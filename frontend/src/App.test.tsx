import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { FixtureApi } from "./api/fixture";
import { ApiError } from "./api/types";

describe("App", () => {
  it("marks fixture mode and saves by the server decision id", async () => {
    const api = new FixtureApi();
    const save = vi.spyOn(api, "saveDecision");
    const user = userEvent.setup();
    render(<App api={api} fixtureMode />);

    expect(screen.getByText(/DEMO FIXTURE/)).toBeInTheDocument();
    const button = await screen.findByRole("button", { name: "Сохранить решение" });
    await user.click(button);

    await waitFor(() => expect(save).toHaveBeenCalledWith("44444444-4444-4444-8444-444444444444"));
    expect(await screen.findByRole("button", { name: "Сохранено" })).toBeDisabled();
  });

  it("shows an API failure as an error, not as a technological decision", async () => {
    const api = new FixtureApi();
    vi.spyOn(api, "health").mockRejectedValue(new ApiError("Backend недоступен", 503, "UNAVAILABLE"));
    render(<App api={api} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend недоступен");
    expect(screen.queryByText("Нет допустимого варианта")).not.toBeInTheDocument();
  });
});
