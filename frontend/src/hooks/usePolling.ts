import { useCallback, useEffect, useRef, useState } from "react";

export interface PollState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  lastUpdated: number | null;
}

// Polls `fetcher` every `intervalMs`. Keeps the last good `data` on error (so a transient blip
// doesn't blank the dashboard) while surfacing `error` for a non-blocking banner. Aborts the
// in-flight request on unmount/interval to avoid setState-after-unmount.
//
// `resetKey` (e.g. the selected store id) restarts polling when it changes: the old store's
// in-flight request is aborted and its interval cleared, the view resets to loading, and only the
// new store is polled. So exactly one store — the one on screen — is ever being fetched.
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  resetKey?: unknown,
): PollState<T> {
  const [state, setState] = useState<PollState<T>>({
    data: null,
    error: null,
    loading: true,
    lastUpdated: null,
  });

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const tick = useCallback(async (signal: AbortSignal) => {
    try {
      const data = await fetcherRef.current(signal);
      if (signal.aborted) return;
      setState({ data, error: null, loading: false, lastUpdated: Date.now() });
    } catch (err) {
      if (signal.aborted || (err as Error).name === "AbortError") return;
      setState((prev) => ({ ...prev, error: (err as Error).message, loading: false }));
    }
  }, []);

  useEffect(() => {
    // Reset so we never show the previous store's numbers under the new store's header.
    setState({ data: null, error: null, loading: true, lastUpdated: null });
    const controller = new AbortController();
    void tick(controller.signal);
    const id = window.setInterval(() => void tick(controller.signal), intervalMs);
    return () => {
      controller.abort();
      window.clearInterval(id);
    };
  }, [tick, intervalMs, resetKey]);

  return state;
}

// A 1Hz clock so "updated Ns ago" stays current between polls.
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}
