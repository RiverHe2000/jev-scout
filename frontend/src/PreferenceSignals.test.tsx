import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PreferenceSignals from "./PreferenceSignals";

describe("Provider-specific preference evidence", () => {
  it("renders LLM categorical answers without percentages or probability bars", () => {
    const { container } = render(
      <PreferenceSignals
        decision={{
          mode: "llm",
          preference_scores: [
            { id: "a", label: "First preference", value: 1 },
            { id: "b", label: "Second preference", value: 0 },
            { id: "c", label: "Third preference", value: null },
          ],
        }}
      />,
    );
    expect(screen.getByText("Supported")).toBeInTheDocument();
    expect(screen.getByText("Not established")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("CATEGORICAL ANSWERS")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(container.querySelector(".signal-track")).toBeNull();
  });
  it("retains Jev's numeric output as an explicitly labeled model signal", () => {
    const { container } = render(
      <PreferenceSignals
        decision={{
          mode: "jev",
          preference_scores: [
            { id: "a", label: "First preference", value: 0.73 },
          ],
        }}
      />,
    );
    expect(screen.getByText("JEV MODEL SIGNALS")).toBeInTheDocument();
    expect(screen.getByText("73%")).toHaveAttribute(
      "title",
      "Model affirmative probability, not calibrated correctness.",
    );
    expect(container.querySelector(".signal-track > span")).toHaveStyle({
      width: "73%",
    });
  });
  it("shows unassessed baseline preferences as unknown without a zero-probability bar", () => {
    const { container } = render(
      <PreferenceSignals
        decision={{
          mode: "baseline",
          preference_scores: [
            { id: "a", label: "First preference", value: null },
          ],
        }}
      />,
    );
    expect(screen.getByText("NOT EVALUATED")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(container.querySelector(".signal-track")).toBeNull();
  });
});
