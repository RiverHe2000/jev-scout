export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((v) =>
        typeof v === "object" && v !== null && "msg" in v
          ? String(v.msg)
          : "Invalid request",
      )
      .join("; ");
  return "The request could not be completed. Please try again.";
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      "Cannot reach your local workspace. Check that the server is running, then retry.",
      0,
    );
  }
  if (!response.ok) {
    let body: { detail?: unknown } = {};
    try {
      body = await response.json();
    } catch {
      /* Non-JSON proxy errors. */
    }
    throw new ApiError(errorMessage(body.detail), response.status);
  }
  return response.json() as Promise<T>;
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export function messageOf(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
export function safeExternal(value: string) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
}
export const formatDate = (date: string) => {
  const d = new Date(date);
  return Number.isNaN(d.getTime())
    ? "Unknown date"
    : d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
};
export const formatNumber = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(n);
export function abstractSegments(
  abstract: string,
  sentences: { id: string; start: number; end: number; text: string }[],
  ids: string[],
): { text: string; highlight: boolean; id?: string }[] {
  const spans = sentences
    .filter(
      (s) =>
        ids.includes(s.id) &&
        Number.isInteger(s.start) &&
        Number.isInteger(s.end) &&
        s.start >= 0 &&
        s.end > s.start &&
        s.end <= abstract.length &&
        abstract.slice(s.start, s.end) === s.text,
    )
    .sort((a, b) => a.start - b.start);
  const result: { text: string; highlight: boolean; id?: string }[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue;
    if (span.start > cursor)
      result.push({
        text: abstract.slice(cursor, span.start),
        highlight: false,
      });
    result.push({
      text: abstract.slice(span.start, span.end),
      highlight: true,
      id: span.id,
    });
    cursor = span.end;
  }
  if (cursor < abstract.length)
    result.push({ text: abstract.slice(cursor), highlight: false });
  return result;
}
