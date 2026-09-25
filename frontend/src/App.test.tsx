import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

describe("Daily focus request boundaries", () => {
  it("uses the profile limit for Read first, while preserving the complete inbox", async () => {
    const profile = {
      id: "synthetic-profile",
      name: "Synthetic test profile",
      question: "A synthetic question for a request contract test?",
      preferences: [],
      keywords: ["synthetic"],
      exclusions: "",
      seed_papers: [],
      daily_limit: 3,
      confidence_threshold: 0.65,
      version: 1,
      archived: false,
    };
    const counts = {
      all: 12,
      read: 7,
      skim: 2,
      review: 1,
      later: 2,
      saved: 0,
      unread: 12,
    };
    const fetchMock = vi.fn(async (path: string) => {
      let body: unknown = {};
      if (path.startsWith("/api/profiles")) body = { items: [profile] };
      else if (path === "/api/settings")
        body = {
          default_mode: "baseline",
          jev_configured: false,
          llm_configured: false,
          version: "0.1.0",
        };
      else if (path === "/api/jobs") body = { items: [] };
      else if (path.startsWith("/api/stats"))
        body = { papers: 12, saved: 0, review: 1, route_counts: counts };
      else if (path.startsWith("/api/papers?"))
        body = { items: [], total: 0, counts, profile_version: 1 };
      return new Response(JSON.stringify(body));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const focusButton = await screen.findByRole("button", {
      name: /Read first 7/,
    });
    fireEvent.click(focusButton);
    await waitFor(() => {
      const request = fetchMock.mock.calls
        .map(([url]) => url)
        .find((url) => url.includes("route=read"));
      expect(request).toBeDefined();
      const query = new URL(request!, "http://localhost").searchParams;
      expect(query.get("limit")).toBe("3");
      expect(query.get("profile_id")).toBe("synthetic-profile");
    });
    expect(
      screen.getByText("DAILY FOCUS · UP TO 3 PAPERS"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /All papers 12/ }));
    await waitFor(() => {
      const requests = fetchMock.mock.calls
        .map(([url]) => url)
        .filter((url) => url.startsWith("/api/papers?"));
      const query = new URL(requests.at(-1)!, "http://localhost").searchParams;
      expect(query.get("route")).toBe("all");
      expect(query.get("limit")).toBe("30");
    });
  });
});

describe("Responsive navigation accessibility", () => {
  it("removes the closed mobile navigation from focus and the accessibility tree", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (path: string) =>
          new Response(
            JSON.stringify(
              path === "/api/settings"
                ? { default_mode: "baseline" }
                : { items: [] },
            ),
          ),
      ),
    );
    render(<App />);
    const sidebar = screen.getByLabelText("Workspace navigation");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");
    expect(sidebar).toHaveAttribute("inert");
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(sidebar).not.toHaveAttribute("aria-hidden");
    expect(sidebar).not.toHaveAttribute("inert");
    expect(
      screen.getByRole("dialog", { name: "Workspace navigation" }),
    ).toBeVisible();
    fireEvent.click(
      within(sidebar).getByRole("button", { name: "Close navigation" }),
    );
    expect(sidebar).toHaveAttribute("inert");
    await screen.findByRole("button", { name: "Create your first profile" });
  });
});
