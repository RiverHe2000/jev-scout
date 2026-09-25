import { describe, expect, it, vi } from "vitest";
import { abstractSegments, api, ApiError, safeExternal } from "./api";
describe("Original abstract evidence", () => {
  const abstract = "First claim. A second sentence. A final qualification.";
  it("preserves every character while highlighting only exact, selected spans", () => {
    const segments = abstractSegments(
      abstract,
      [
        { id: "s1", text: "First claim.", start: 0, end: 12 },
        { id: "s2", text: "A second sentence.", start: 13, end: 31 },
      ],
      ["s2"],
    );
    expect(segments.map((s) => s.text).join("")).toBe(abstract);
    expect(segments.filter((s) => s.highlight)).toEqual([
      { text: "A second sentence.", highlight: true, id: "s2" },
    ]);
  });
  it("does not turn invalid offsets, stale text, or hallucinated evidence into quotes", () => {
    const segments = abstractSegments(
      abstract,
      [
        { id: "wrong", text: "We proved superiority.", start: 0, end: 12 },
        { id: "negative", text: "First claim.", start: -1, end: 12 },
        { id: "outside", text: "missing", start: 100, end: 107 },
      ],
      ["wrong", "negative", "outside"],
    );
    expect(segments).toEqual([{ text: abstract, highlight: false }]);
  });
  it("keeps overlapping and duplicate references from repeating source text", () => {
    const sentence = { id: "s1", text: "First claim.", start: 0, end: 12 };
    expect(
      abstractSegments(abstract, [sentence, sentence], ["s1"])
        .map((s) => s.text)
        .join(""),
    ).toBe(abstract);
  });
});
describe("HTTP boundary", () => {
  it("surfaces API validation messages instead of raw objects", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              detail: [{ msg: "Profile changed. Reload the current version." }],
            }),
            { status: 409 },
          ),
        ),
    );
    await expect(api("/profiles/test")).rejects.toMatchObject({
      status: 409,
      message: "Profile changed. Reload the current version.",
    });
  });
  it("reports network failures with a recoverable local-server message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Network failure")),
    );
    await expect(api("/profiles")).rejects.toBeInstanceOf(ApiError);
    await expect(api("/profiles")).rejects.toThrow(
      "Cannot reach your local workspace",
    );
  });
  it("preserves abort errors so outdated responses can be safely discarded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("Aborted", "AbortError")),
    );
    await expect(api("/papers")).rejects.toMatchObject({ name: "AbortError" });
  });
  it("rejects executable schemes from metadata links", () => {
    expect(safeExternal("javascript:alert(1)")).toBe("#");
    expect(safeExternal("data:text/html,bad")).toBe("#");
    expect(safeExternal("https://arxiv.org/abs/2303.11366")).toBe(
      "https://arxiv.org/abs/2303.11366",
    );
  });
});
