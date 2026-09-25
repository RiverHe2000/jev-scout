import { useEffect, useRef, useState, type RefObject } from "react";
import { api, messageOf } from "./api";
export function useResource<T>(path: string | null, version = 0) {
  const [state, setState] = useState<{
    path: string | null;
    data: T | null;
    error: string | null;
    loading: boolean;
  }>({ path, data: null, error: null, loading: Boolean(path) });
  useEffect(() => {
    if (!path) {
      setState({ path, data: null, error: null, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((prev) => ({
      path,
      data: prev.path === path ? prev.data : null,
      error: null,
      loading: true,
    }));
    api<T>(path, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted)
          setState({ path, data, error: null, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState((prev) => ({
            ...prev,
            error: messageOf(error),
            loading: false,
          }));
      });
    return () => controller.abort();
  }, [path, version]);
  return state.path === path
    ? state
    : { data: null, error: null, loading: Boolean(path) };
}
export function useDebounce(value: string, delay = 240) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
export function stored(key: string, fallback = "") {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
export function storeValue(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Workspace still works when browser storage is unavailable. */
  }
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(
    () => window.matchMedia?.(query).matches ?? false,
  );
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** Keep keyboard focus inside narrow-screen panels, then return it to their trigger. */
export function useOverlayFocus(
  ref: RefObject<HTMLElement | null>,
  enabled: boolean,
  onClose: () => void,
) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!enabled) return;
    const panel = ref.current;
    if (!panel) return;
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.focus();
    function keydown(event: KeyboardEvent) {
      // A native modal opened from this panel owns focus until it is dismissed.
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const controls = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex="0"]',
        ),
      ).filter((element) => element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls.at(-1);
      if (!first || !last) {
        event.preventDefault();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first || document.activeElement === panel)
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !panel.contains(document.activeElement))
      ) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, [enabled, ref]);
}
