import type { ReactNode } from "react";

// A titled surface with an optional subtitle and right-aligned slot (e.g. a confidence badge).
export function Card({
  title,
  subtitle,
  right,
  children,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <div className="card__head">
        <div>
          <h2 className="card__title">{title}</h2>
          {subtitle && <p className="card__subtitle">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}
