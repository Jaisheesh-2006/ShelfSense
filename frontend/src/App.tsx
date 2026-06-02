import { useCallback, useEffect, useState } from "react";

import { API_BASE, DEFAULT_STORE_ID, fetchDashboard, fetchStores } from "./api/client";
import type { Dashboard, StoreInfo } from "./api/types";
import { Anomalies } from "./components/Anomalies";
import { Badge } from "./components/Badge";
import { Card } from "./components/Card";
import { Funnel } from "./components/Funnel";
import { Header } from "./components/Header";
import { Heatmap } from "./components/Heatmap";
import { Ring } from "./components/Ring";
import { StatCard } from "./components/StatCard";
import { useNow, usePolling } from "./hooks/usePolling";
import { hourLabel, inr, titleize } from "./lib/format";

const POLL_MS = 4000;

function ConfidenceBadge({ confidence }: { confidence: string }) {
  return confidence === "ok" ? (
    <Badge tone="success">data: ok</Badge>
  ) : (
    <Badge tone="neutral">data: {confidence}</Badge>
  );
}

function Body({ data }: { data: Dashboard }) {
  const { metrics, funnel, heatmap, anomalies } = data;
  const entry = funnel.stages[0]?.visitors ?? 0;
  const waiting = metrics.unique_visitors === 0 && entry === 0;

  return (
    <>
      {waiting && (
        <div className="banner banner--info">
          No visitor events for this store yet — metrics populate live as the detection pipeline
          ingests events.
        </div>
      )}

      <section className="card">
        <div className="hero">
          <Ring value={metrics.conversion_rate} caption="conversion" />
          <div>
            <div className="stat__label">Store conversion · the north-star metric</div>
            <div className="row" style={{ alignItems: "baseline", marginTop: "6px" }}>
              <span className="num" style={{ fontSize: "var(--fs-xl)", fontWeight: 700 }}>
                {metrics.converted}
              </span>
              <span className="muted">of {metrics.unique_visitors} visitors converted</span>
            </div>
            <div className="row" style={{ marginTop: "10px" }}>
              <ConfidenceBadge confidence={metrics.data_confidence} />
              {metrics.abandoned > 0 && <Badge tone="neutral">{metrics.abandoned} abandoned</Badge>}
            </div>
            <p className="muted" style={{ marginTop: "12px", fontSize: "var(--fs-sm)" }}>
              Billing-queue visitors are joined to POS sales within a 5-minute window. Staff are
              excluded and each shopper is counted once (Re-ID).
            </p>
          </div>
        </div>
      </section>

      <div className="stats">
        <StatCard label="Unique Visitors" value={metrics.unique_visitors} sub="staff excluded" />
        <StatCard
          label="Transactions"
          value={metrics.pos.transaction_count}
          sub={`peak ${hourLabel(metrics.pos.peak_hour)}`}
        />
        <StatCard
          label="Revenue (GMV)"
          value={inr(metrics.pos.total_gmv)}
          sub={`avg ${inr(metrics.pos.avg_basket)}`}
        />
        <StatCard
          label="Top Brand"
          value={metrics.pos.top_brand ? titleize(metrics.pos.top_brand) : "—"}
          sub="by sales"
        />
        <StatCard
          label="Top Department"
          value={metrics.pos.top_department ? titleize(metrics.pos.top_department) : "—"}
          sub="by sales"
        />
      </div>

      <div className="panels">
        <Card
          title="Conversion Funnel"
          subtitle="session-based · no double counting"
          right={<ConfidenceBadge confidence={funnel.data_confidence} />}
        >
          <Funnel funnel={funnel} />
        </Card>
        <Card
          title="Zone Heatmap"
          subtitle="visitors × dwell, normalised 0–100"
          right={<ConfidenceBadge confidence={heatmap.data_confidence} />}
        >
          <Heatmap heatmap={heatmap} />
        </Card>
      </div>

      <Card title="Anomalies" subtitle="operational alerts — honest about data limits">
        <Anomalies report={anomalies} />
      </Card>
    </>
  );
}

export function App() {
  const [stores, setStores] = useState<StoreInfo[]>([]);
  const [storeId, setStoreId] = useState<string>(DEFAULT_STORE_ID);

  // Fetch the switcher's store list once. On failure, stay single-store (the default id still polls).
  useEffect(() => {
    const controller = new AbortController();
    fetchStores(controller.signal)
      .then((list) => {
        if (!list.length) return;
        setStores(list);
        setStoreId((prev) => (list.some((s) => s.store_id === prev) ? prev : list[0].store_id));
      })
      .catch(() => {
        /* no /stores — keep the default single store */
      });
    return () => controller.abort();
  }, []);

  // Poll only the selected store; `storeId` as resetKey restarts polling cleanly on a switch.
  const fetcher = useCallback((signal: AbortSignal) => fetchDashboard(storeId, signal), [storeId]);
  const { data, error, loading, lastUpdated } = usePolling(fetcher, POLL_MS, storeId);
  const now = useNow();

  const storeName = stores.find((s) => s.store_id === storeId)?.name;

  return (
    <div className="app">
      <Header
        health={data?.health ?? null}
        storeId={storeId}
        storeName={storeName}
        stores={stores}
        onSelectStore={setStoreId}
        lastUpdated={lastUpdated}
        now={now}
        hasError={Boolean(error)}
      />
      <main className="container main">
        {error && (
          <div className="banner banner--warn">
            Can’t reach the API at {API_BASE} — retrying. Showing the last snapshot.
          </div>
        )}
        {loading && !data && <p className="empty">Connecting to the API…</p>}
        {data && <Body data={data} />}
      </main>
      <footer className="container">
        <div className="footer">
          <span>ShelfSense · metrics computed live from CCTV events + POS — never hardcoded.</span>
          <span>
            Polling every {POLL_MS / 1000}s · {storeName ? `${storeName} (${storeId})` : storeId}
          </span>
        </div>
      </footer>
    </div>
  );
}
