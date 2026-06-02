import type { Health } from "../api/types";
import { agoLabel } from "../lib/format";

// Sticky top bar: brand, live status (driven by the API health feed), and "updated Ns ago".
export function Header({
  health,
  storeId,
  lastUpdated,
  now,
  hasError,
}: {
  health: Health | null;
  storeId: string;
  lastUpdated: number | null;
  now: number;
  hasError: boolean;
}) {
  const stale = health?.stores?.some((s) => s.stale_feed) ?? false;
  const liveClass = hasError ? "live live--down" : stale ? "live live--stale" : "live";
  const liveText = hasError ? "Reconnecting" : stale ? "Feed stale" : "Live";

  return (
    <header className="header">
      <div className="container header__inner">
        <div className="brand">
          <div className="brand__mark">S</div>
          <div>
            <div className="brand__name">ShelfSense</div>
            <div className="brand__sub">{storeId} · Brigade Bangalore</div>
          </div>
        </div>
        <div className="header__meta">
          <span className={liveClass}>
            <span className="live__dot" />
            {liveText}
          </span>
          <span className="muted">Updated {agoLabel(lastUpdated, now)}</span>
        </div>
      </div>
    </header>
  );
}
