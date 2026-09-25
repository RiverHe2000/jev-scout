import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModeSelector, ProfileModal } from "./forms";
import type { Profile, Settings } from "./types";

const settings: Settings = {
  jev_configured: false,
  jev_provider: null,
  llm_configured: true,
  llm_model: "local-test-model",
  llm_provider: "local",
  available_modes: ["baseline", "llm"],
  model: "jev",
  default_mode: "llm",
  price_per_million_input: null,
  local_only: true,
  database_path_display: "local.db",
  version: "0.1.0",
};
const profile: Profile = {
  id: "profile-test",
  name: "Test research lens",
  question: "A deliberately synthetic test question?",
  preferences: [],
  keywords: ["synthetic"],
  exclusions: "",
  seed_papers: [],
  daily_limit: 10,
  confidence_threshold: 0.65,
  version: 7,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
  archived: false,
};
describe("Truthful analysis controls", () => {
  it("keeps unavailable Jev disabled while allowing a configured compatible LLM", () => {
    const onChange = vi.fn();
    render(
      <ModeSelector value="baseline" onChange={onChange} settings={settings} />,
    );
    expect(
      screen.getByRole("radio", { name: /Jev semantic decisions/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: /Keyword baseline/ }),
    ).toBeChecked();
    fireEvent.click(
      screen.getByRole("radio", { name: /Local \/ compatible LLM/ }),
    );
    expect(onChange).toHaveBeenCalledWith("llm");
    expect(onChange).not.toHaveBeenCalledWith("jev");
  });
});
describe("Versioned research profile editing", () => {
  it("submits the expected version and retains the user edits after a conflict", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Profile was changed in another window." }),
          { status: 409 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const onSave = vi.fn();
    render(
      <ProfileModal profile={profile} onSave={onSave} onClose={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText("Profile name"), {
      target: { value: "My revised question" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save research profile" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Your edits are still here",
      ),
    );
    expect(screen.getByLabelText("Profile name")).toHaveValue(
      "My revised question",
    );
    expect(
      screen.getByRole("button", { name: "Save research profile" }),
    ).toBeDisabled();
    const request = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(request.expected_version).toBe(7);
    expect(request.name).toBe("My revised question");
    expect(onSave).not.toHaveBeenCalled();
  });
});
