import { cn } from "@/lib/utils";
import type { StatusResponse } from "@/lib/api";

interface ConnectionIndicatorsProps {
  wsConnected: boolean;
  status?: StatusResponse;
  tickAgeSec?: number | null;
}

function Dot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5" title={label}>
      <span
        className={cn(
          "size-2 rounded-full",
          ok ? "bg-primary" : "bg-destructive",
        )}
        aria-hidden
      />
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
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
  const dataOk =
    !isLive ||
    tickAgeSec == null ||
    tickAgeSec <= 5;

  return (
    <div className="flex items-center gap-3">
      <Dot ok={wsConnected} label="WS" />
      <Dot ok={engineOk} label="Engine" />
      {isLive && <Dot ok={mt5Ok} label="MT5" />}
      {isLive && <Dot ok={dataOk} label="Data" />}
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
    </div>
  );
}
