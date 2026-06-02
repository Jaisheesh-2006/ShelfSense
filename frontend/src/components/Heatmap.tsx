import type { Heatmap as HeatmapData } from "../api/types";
import { seconds, titleize } from "../lib/format";

// Zone engagement: bars sized by the API's 0–100 score (visits × dwell, normalised to the busiest).
export function Heatmap({ heatmap }: { heatmap: HeatmapData }) {
  if (heatmap.zones.length === 0) {
    return <p className="empty">No zone activity yet — waiting for events…</p>;
  }

  const zones = [...heatmap.zones].sort((a, b) => b.score - a.score);

  return (
    <div className="bars">
      {zones.map((zone) => {
        const widthPct = Math.max(0, Math.min(100, zone.score));
        return (
          <div key={zone.zone}>
            <div className="bar__head">
              <span className="bar__label">{titleize(zone.zone)}</span>
              <span className="bar__meta">
                <span className="num">{zone.visits}</span> visits · {seconds(zone.avg_dwell_ms)} avg
              </span>
            </div>
            <div className="bar__track">
              <div className="bar__fill bar__fill--teal" style={{ width: `${widthPct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
