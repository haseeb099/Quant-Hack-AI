import { useQuery } from "@tanstack/react-query";
import { LiveIndicator } from "@/components/shared/LiveIndicator";
import { PhaseBadge } from "@/components/shared/PhaseBadge";
import { Separator } from "@/components/ui/separator";
import { useCycleCountdown } from "@/hooks/useWebSocket";
import { api, queryKeys } from "@/lib/api";
import { formatDuration, formatTimestamp } from "@/lib/utils";

interface TopStatusBarProps {
  wsConnected: boolean;
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

  const countdown = useCycleCountdown(status?.next_cycle_at);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-panel/95 px-6 backdrop-blur">
      <div className="flex items-center gap-4">
        {status && (
          <PhaseBadge phase={status.phase} ddTier={risk?.dd_tier} />
        )}
        <Separator orientation="vertical" className="h-6" />
        <span className="text-xs text-muted-foreground">
          Mode{" "}
          <span className="font-mono text-foreground">
            {status?.mode ?? "—"}
          </span>
        </span>
      </div>

      <div className="flex items-center gap-6">
        <div className="text-right text-xs">
          <div className="text-muted-foreground">Next cycle</div>
          <div className="font-mono text-primary">{formatDuration(countdown)}</div>
        </div>
        <Separator orientation="vertical" className="h-6" />
        <div className="text-right text-xs">
          <div className="text-muted-foreground">Last cycle</div>
          <div className="font-mono">
            {formatTimestamp(status?.last_cycle_at)}
          </div>
        </div>
        <Separator orientation="vertical" className="h-6" />
        <LiveIndicator connected={wsConnected && (status?.engine_running ?? false)} />
      </div>
    </header>
  );
}
