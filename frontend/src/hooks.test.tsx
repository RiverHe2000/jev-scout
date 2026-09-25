import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useResource } from "./hooks";
describe("Profile-isolated request lifecycle", () => {
  it("never shows an old profile response under a newly selected profile", async () => {
    let resolveSecond!: (value: Response) => void;
    const second = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ name: "First profile" })),
        )
        .mockReturnValueOnce(second),
    );
    const { result, rerender } = renderHook(
      ({ path }) => useResource<{ name: string }>(path),
      { initialProps: { path: "/papers?profile_id=first" } },
    );
    await waitFor(() =>
      expect(result.current.data?.name).toBe("First profile"),
    );
    rerender({ path: "/papers?profile_id=second" });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    await act(async () =>
      resolveSecond(new Response(JSON.stringify({ name: "Second profile" }))),
    );
    await waitFor(() =>
      expect(result.current.data?.name).toBe("Second profile"),
    );
  });
});
