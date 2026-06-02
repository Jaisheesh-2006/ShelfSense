import type {
  AnomalyReport,
  Dashboard,
  Funnel,
  Health,
  Heatmap,
  StoreInfo,
  StoreMetrics,
} from "./types";

// API base resolution, in priority order:
//  1. VITE_API_BASE (baked at build time) if provided,
//  2. otherwise the host the dashboard is served from, on port 8000 (works for localhost or a LAN
//     IP). The API enables CORS, so the browser can call it cross-port.
const ENV_BASE = import.meta.env.VITE_API_BASE as string | undefined;
export const API_BASE = (ENV_BASE && ENV_BASE.replace(/\/$/, "")) ||
  `${window.location.protocol}//${window.location.hostname}:8000`;

// Falls back to ST1008 if the /stores list can't be fetched (single-store dev).
export const DEFAULT_STORE_ID = (import.meta.env.VITE_STORE_ID as string | undefined) ?? "ST1008";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`${path} returned ${res.status}`);
  }
  return (await res.json()) as T;
}

// The stores the switcher offers. Fetched once on load.
export async function fetchStores(signal?: AbortSignal): Promise<StoreInfo[]> {
  return getJson<StoreInfo[]>(`/stores`, signal);
}

// One snapshot for a single store = all five endpoints fetched in parallel. Only the store currently
// shown is polled (App passes the selected id). If any call fails, the whole poll fails and the UI
// keeps the previous snapshot (see usePolling) rather than flashing partial data.
export async function fetchDashboard(storeId: string, signal?: AbortSignal): Promise<Dashboard> {
  const id = storeId;
  const [metrics, funnel, heatmap, anomalies, health] = await Promise.all([
    getJson<StoreMetrics>(`/stores/${id}/metrics`, signal),
    getJson<Funnel>(`/stores/${id}/funnel`, signal),
    getJson<Heatmap>(`/stores/${id}/heatmap`, signal),
    getJson<AnomalyReport>(`/stores/${id}/anomalies`, signal),
    getJson<Health>(`/health`, signal),
  ]);
  return { metrics, funnel, heatmap, anomalies, health };
}
