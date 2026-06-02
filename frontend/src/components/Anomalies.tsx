import type { AnomalyReport } from "../api/types";
import { titleize } from "../lib/format";
import { Badge, type Tone } from "./Badge";

const toneFor = (severity: string): Tone => {
  switch (severity.toUpperCase()) {
    case "CRITICAL":
      return "danger";
    case "WARNING":
      return "warning";
    default:
      return "neutral"; // INFO
  }
};

export function Anomalies({ report }: { report: AnomalyReport }) {
  if (report.anomalies.length === 0) {
    return <p className="empty">No anomalies — everything looks normal.</p>;
  }

  return (
    <div className="anoms">
      {report.anomalies.map((anomaly, i) => (
        <div className="anom" key={`${anomaly.type}-${i}`}>
          <Badge tone={toneFor(anomaly.severity)}>{anomaly.severity}</Badge>
          <div className="anom__body">
            <span className="anom__type">
              {titleize(anomaly.type)}
              {anomaly.zone_id ? ` · ${titleize(anomaly.zone_id)}` : ""}
            </span>
            <span className="anom__msg">{anomaly.message}</span>
            {anomaly.suggested_action && (
              <span className="anom__action">→ {anomaly.suggested_action}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
