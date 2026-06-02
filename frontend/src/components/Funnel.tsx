import type { Funnel as FunnelData } from "../api/types";
import { titleize } from "../lib/format";

// Horizontal funnel: each stage's bar is sized relative to the entry stage; drop-off is annotated.
export function Funnel({ funnel }: { funnel: FunnelData }) {
  const entry = funnel.stages[0]?.visitors ?? 0;
  const base = Math.max(entry, 1);

  if (entry === 0) {
    return <p className="empty">No visitors yet — waiting for events…</p>;
  }

  return (
    <div className="bars">
      {funnel.stages.map((stage) => {
        const widthPct = (stage.visitors / base) * 100;
        return (
          <div key={stage.stage}>
            <div className="bar__head">
              <span className="bar__label">{titleize(stage.stage)}</span>
              <span className="bar__meta">
                <span className="bar__value num">{stage.visitors}</span>
                {stage.drop_off_pct !== null && stage.drop_off_pct > 0 && (
                  <span className="faint"> · −{stage.drop_off_pct.toFixed(0)}%</span>
                )}
              </span>
            </div>
            <div className="bar__track">
              <div className="bar__fill bar__fill--primary" style={{ width: `${widthPct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
