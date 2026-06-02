// Small display formatters shared across the dashboard.

export const pct = (fraction: number, digits = 1): string =>
  `${(fraction * 100).toFixed(digits)}%`;

export const inr = (amount: number): string => `₹${Math.round(amount).toLocaleString("en-IN")}`;

export const seconds = (ms: number): string => `${(ms / 1000).toFixed(1)}s`;

export const titleize = (s: string): string =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// "3s ago" style label for the last successful poll.
export const agoLabel = (ts: number | null, now: number): string => {
  if (!ts) return "—";
  const d = Math.max(0, Math.round((now - ts) / 1000));
  return d <= 1 ? "just now" : `${d}s ago`;
};

export const hourLabel = (hour: number | null): string => {
  if (hour === null || hour === undefined) return "—";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${h12}${hour < 12 ? "am" : "pm"}`;
};
