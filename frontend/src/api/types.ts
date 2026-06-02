// Response shapes for the ShelfSense Intelligence API. Mirrors the FastAPI Pydantic models so the
// dashboard is typed end to end.

export interface StoreInfo {
  store_id: string;
  name: string;
}

export interface PosMetrics {
  transaction_count: number;
  total_gmv: number;
  avg_basket: number;
  top_brand: string | null;
  top_department: string | null;
  peak_hour: number | null;
}

export interface StoreMetrics {
  store_id: string;
  unique_visitors: number;
  conversion_rate: number; // fraction 0..1
  data_confidence: string; // "ok" | "low"
  converted: number;
  abandoned: number;
  abandonment_rate: number;
  avg_dwell_ms_by_zone: Record<string, number>;
  max_queue_depth: number;
  pos: PosMetrics;
}

export interface FunnelStage {
  stage: string;
  visitors: number;
  drop_off_pct: number | null;
}

export interface Funnel {
  store_id: string;
  stages: FunnelStage[];
  conversion_rate: number;
  data_confidence: string;
}

export interface HeatZone {
  zone: string;
  visits: number;
  avg_dwell_ms: number;
  score: number; // 0..100, normalised to the busiest zone
}

export interface Heatmap {
  store_id: string;
  zones: HeatZone[];
  data_confidence: string;
}

export interface Anomaly {
  type: string;
  severity: string; // "INFO" | "WARNING" | "CRITICAL"
  message: string;
  suggested_action: string;
  zone_id: string | null;
  value: number | null;
}

export interface AnomalyReport {
  store_id: string;
  evaluated_at: string;
  anomalies: Anomaly[];
}

export interface StoreHealth {
  store_id: string;
  last_event_at: string;
  lag_seconds: number | null;
  stale_feed: boolean;
}

export interface Health {
  status: string; // "ok" | "degraded"
  reference_at: string;
  strict_now: boolean;
  stores: StoreHealth[];
}

// The full snapshot the dashboard renders each poll.
export interface Dashboard {
  metrics: StoreMetrics;
  funnel: Funnel;
  heatmap: Heatmap;
  anomalies: AnomalyReport;
  health: Health;
}
