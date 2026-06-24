import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(
  value: number | null | undefined,
  compact = false,
): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (compact && Math.abs(value) >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(2)}M`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatTickAgeMs(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

export function formatPercent(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatPct(value: number, digits = 2): string {
  return formatPercent(value, digits);
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(iso: string | null | undefined): string {
  return formatTimestamp(iso);
}

export function formatDuration(seconds: number): string {
  if (seconds <= 0) return "due now";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

export function pnlColorClass(value: number): string {
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-muted-foreground";
}

const AGENT_LABELS: Record<string, string> = {
  trend_surfer: "TrendSurfer",
  breakout_hunter: "BreakoutHunter",
  momentum_pulse: "MomentumPulse",
  mean_reversion: "MeanReversion",
  sentiment_agent: "SentimentAgent",
};

export function agentDisplayName(agent: string): string {
  return AGENT_LABELS[agent] ?? agent.replace(/_/g, " ");
}
