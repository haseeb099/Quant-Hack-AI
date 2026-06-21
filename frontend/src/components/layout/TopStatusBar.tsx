import { useQuery } from "@tanstack/react-query";
import { ConnectionIndicators } from "@/components/shared/ConnectionIndicators";
import { DataSourceBadge } from "@/components/shared/DataSourceBadge";
import { TradingControlBar } from "@/components/shared/TradingControlBar";
import { PhaseBadge } from "@/components/shared/PhaseBadge";
import { Separator } from "@/components/ui/separator";
import { useCycleCountdown, useLastTickAge } from "@/hooks/useWebSocket";
import { api, queryKeys } from "@/lib/api";
import { formatCurrency, formatDuration } from "@/lib/utils";

interface TopStatusBarProps {
  wsConnected: boolean;
}

function formatTickAge(seconds: number | null) {
  if (seconds == null) return "—";
  if (seconds < 1) return `${seconds.toFixed(1)}s ago`;
  return `${Math.round(seconds)}s ago`;
}

export function TopStatusBar({ wsConnected }: TopStatusBarProps) {
  const { data: status } = useQuery({
    queryKey: queryKeys.status,
    queryFn: api.getStatus,
    refetchInterval: 15_000,
  });

  const { data: risk } = useQuery({
    queryKey: queryKeys.risk,
    queryFn: api.getRisk,
    refetchInterval: 15_000,
  });

  const { data: account } = useQuery({
    queryKey: queryKeys.account,
    queryFn: api.getAccount,
    refetchInterval: 15_000,
  });

  const countdown = useCycleCountdown(status?.next_cycle_at);
  const tickAgeSec = useLastTickAge(status?.last_tick_age_ms);

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-panel/95 backdrop-blur">
      <div className="flex h-14 items-center justify-between px-6">
        <div className="flex items-center gap-4">
          {status && (
            <PhaseBadge phase={status.phase} ddTier={risk?.dd_tier} />
          )}
          {status && <DataSourceBadge status={status} />}
          <Separator orientation="vertical" className="h-6" />
          <ConnectionIndicators
            wsConnected={wsConnected}
            status={status}
            tickAgeSec={tickAgeSec}
          />
          <Separator orientation="vertical" className="h-6" />
          <span className="text-xs text-muted-foreground">
            Mode{" "}
            <span className="font-mono uppercase text-foreground">
              {status?.mode ?? "—"}
            </span>
          </span>
        </div>

        <div className="flex items-center gap-6">
          {account && (
            <>
              <div className="hidden text-right text-xs md:block">
                <div className="text-muted-foreground">Equity</div>
                <div className="font-mono">{formatCurrency(account.equity, true)}</div>
              </div>
              <Separator orientation="vertical" className="hidden h-6 md:block" />
            </>
          )}
          <div className="text-right text-xs">
            <div className="text-muted-foreground">Last tick</div>
            <div className="font-mono">{formatTickAge(tickAgeSec)}</div>
          </div>
          <Separator orientation="vertical" className="h-6" />
          <div className="text-right text-xs">
            <div className="text-muted-foreground">Next cycle</div>
            <div className="font-mono text-primary">{formatDuration(countdown)}</div>
          </div>
        </div>
      </div>

      <div className="border-t border-border/50 px-6 py-2">
        <TradingControlBar compact />
      </div>
    </header>
  );
}
