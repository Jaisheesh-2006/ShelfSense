import { pct } from "../lib/format";

// A solid-stroke SVG progress ring (no gradient). Used for the headline conversion rate.
export function Ring({ value, caption }: { value: number; caption: string }) {
  const size = 132;
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(1, value));
  const offset = circ * (1 - clamped);

  return (
    <div className="ring">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          className="ring__track"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
        />
        <circle
          className="ring__value"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeDasharray={circ}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="ring__center">
        <div>
          <div className="ring__pct num">{pct(clamped, 1)}</div>
          <div className="ring__cap">{caption}</div>
        </div>
      </div>
    </div>
  );
}
