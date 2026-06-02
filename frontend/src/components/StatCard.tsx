import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  sub,
  accent = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <span className={accent ? "stat__value num stat__value--accent" : "stat__value num"}>
        {value}
      </span>
      {sub !== undefined && <span className="stat__sub">{sub}</span>}
    </div>
  );
}
