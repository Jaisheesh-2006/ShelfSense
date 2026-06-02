import type { Health, StoreInfo } from "../api/types";
import { agoLabel } from "../lib/format";

// Sticky top bar: brand, a store switcher (when more than one store is available), live status
// (driven by the API health feed), and "updated Ns ago".
export function Header({
  health,
  storeId,
  storeName,
  stores,
  onSelectStore,
  lastUpdated,
  now,
  hasError,
}: {
  health: Health | null;
  storeId: string;
  storeName?: string;
  stores: StoreInfo[];
  onSelectStore: (id: string) => void;
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
            <div className="brand__sub">{storeName ? `${storeId} · ${storeName}` : storeId}</div>
          </div>
        </div>
        <div className="header__meta">
          {stores.length > 1 && (
            <label className="switcher">
              <span className="switcher__label">Store</span>
              <select
                className="switcher__select"
                value={storeId}
                onChange={(e) => onSelectStore(e.target.value)}
                aria-label="Select store"
              >
                {stores.map((s) => (
                  <option key={s.store_id} value={s.store_id}>
                    {s.name} ({s.store_id})
                  </option>
                ))}
              </select>
            </label>
          )}
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
