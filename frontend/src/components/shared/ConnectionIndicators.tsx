import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { api, queryKeys, type StatusResponse } from "@/lib/api";

interface ConnectionIndicatorsProps {
  wsConnected: boolean;
  status?: StatusResponse;
  tickAgeSec?: number | null;
}

type SkipBucket = "operational" | "data_failure" | "other";

function classifySkipCategory(reason: string): SkipBucket {
  if (
    reason.includes("Insufficient OHLCV") ||
    reason.includes("Market health RED") ||
    reason.includes("data unavailable")
  ) {
    return "data_failure";
  }
  if (
    reason.includes("Open position") ||
    reason.includes("Live filter") ||
    reason.includes("blocked") ||
    reason.includes("Blocked") ||
    reason === "HOLD decision" ||
    reason.startsWith("Net directional") ||
    reason.includes("Symbol cooldown") ||
    reason.startsWith("Session inactive")
  ) {
    return "operational";
  }
  return "other";
}

function Dot({
  ok,
  label,
  shortLabel,
  detail,
}: {
  ok: boolean;
  label: string;
  shortLabel?: string;
  detail?: string;
}) {
  const title = detail ? `${label}: ${detail}` : label;
  return (
    <div className="flex shrink-0 items-center gap-1.5" title={title}>
      <span
        className={cn(
          "size-2 rounded-full",
          ok ? "bg-primary" : "bg-destructive",
        )}
        aria-hidden
      />
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground xl:hidden">
        {shortLabel ?? label}
      </span>
      <span className="hidden text-[10px] uppercase tracking-wide text-muted-foreground xl:inline">
        {label}
      </span>
    </div>
  );
}

export function ConnectionIndicators({
  wsConnected,
  status,
  tickAgeSec,
}: ConnectionIndicatorsProps) {
  const isLive = status?.mode === "live";
  const engineOk = status?.engine_running === true;
  const mt5Ok = !isLive || status?.mt5_connected === true;

  const { data: lastCycle } = useQuery({
    queryKey: queryKeys.lastCycle,
    queryFn: api.getLastCycle,
    enabled: isLive,
    refetchInterval: 30_000,
  });

  const skipBuckets = { operational: 0, data_failure: 0, other: 0 };
  for (const decision of lastCycle?.decisions ?? []) {
    if (decision.executed || !decision.reason) continue;
    const bucket = classifySkipCategory(decision.reason);
    skipBuckets[bucket] += 1;
  }

  const tickStale = tickAgeSec != null && tickAgeSec > 5;
  const dataOk = !isLive || (!tickStale && skipBuckets.data_failure === 0);
  const dataDetail = tickStale
    ? `Ticks ${tickAgeSec?.toFixed(0)}s stale`
    : skipBuckets.data_failure > 0
      ? `${skipBuckets.data_failure} symbol(s) — OHLCV/data failure`
      : skipBuckets.operational > 0
        ? `${skipBuckets.operational} skipped (position/blocked/HOLD — expected)`
        : "Tick stream fresh";

  const stateOk = status?.state_stale !== true;

  return (
    <div className="flex shrink-0 items-center gap-2 xl:gap-3">
      <Dot ok={wsConnected} label="WS" />
      <Dot ok={engineOk} label="Engine" shortLabel="Eng" />
      {isLive && <Dot ok={mt5Ok} label="MT5" />}
      {isLive && <Dot ok={dataOk} label="Data" detail={dataDetail} />}
      <Dot ok={stateOk} label="State" shortLabel="St" />
      {status?.engine_paused && (
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
          Paused
        </span>
      )}
      {status?.cycle_in_progress && (
        <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
          Cycle
        </span>
      )}
      {isLive && skipBuckets.operational > 0 && !tickStale && (
        <span
          className="hidden rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground lg:inline"
          title="Skips from open positions, phase blocks, HOLD, or risk gates — not data failures"
        >
          {skipBuckets.operational} expected skip
          {skipBuckets.operational === 1 ? "" : "s"}
        </span>
      )}
    </div>
  );
}
