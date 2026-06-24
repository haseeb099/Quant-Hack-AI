import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCw, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys, type OperatorSnapshotStatus } from "@/lib/api";
import { cn, formatTimestamp } from "@/lib/utils";

function statusBadgeClass(status: OperatorSnapshotStatus | string | undefined) {
  if (status === "GREEN") return "border-emerald-500/40 text-emerald-300";
  if (status === "YELLOW") return "border-amber-500/40 text-amber-200";
  if (status === "RED") return "border-destructive/40 text-destructive";
  return "border-muted-foreground/40 text-muted-foreground";
}

export function OperatorSnapshotPanel() {
  const queryClient = useQueryClient();
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: queryKeys.operatorSnapshot,
    queryFn: api.getOperatorSnapshot,
    refetchInterval: 30_000,
  });

  const trigger = useMutation({
    mutationFn: () => api.triggerOperatorWatchdog({ confirm: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.operatorSnapshot });
      queryClient.invalidateQueries({ queryKey: queryKeys.operatorSnapshotHistory });
    },
  });

  if (isLoading) {
    return <Skeleton className="h-56 w-full" />;
  }

  const snapshot = data?.snapshot;
  if (!data?.available || !snapshot) {
    return (
      <Card className="border-border/60 bg-panel">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="size-4 text-primary" />
            Operator Watchdog
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>No snapshot yet. Run the watchdog daemon or trigger a one-off cycle.</p>
          <Button
            size="sm"
            variant="outline"
            disabled={trigger.isPending}
            onClick={() => trigger.mutate()}
          >
            Run watchdog cycle
          </Button>
        </CardContent>
      </Card>
    );
  }

  const summary = snapshot.summary ?? {};
  const failedRecon = (snapshot.reconciliation?.issues ?? []).filter((i) => !i.passed);
  const failedRisk = (snapshot.risk_compliance?.issues ?? []).filter((i) => !i.passed);

  return (
    <Card className="border-border/60 bg-panel">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="size-4 text-primary" />
            Operator Watchdog
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={cn("font-mono text-[10px] uppercase", statusBadgeClass(snapshot.status))}
            >
              {snapshot.status}
            </Badge>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2"
              disabled={isFetching || trigger.isPending}
              onClick={() => {
                void refetch();
              }}
            >
              <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} />
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Always-on monitoring · updated {formatTimestamp(snapshot.timestamp)} · MT5{" "}
          {String(summary.mt5_position_count ?? "—")} / engine{" "}
          {String(summary.engine_position_count ?? "—")}
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid gap-2 sm:grid-cols-3">
          <Metric label="Reconciliation" value={snapshot.reconciliation?.status ?? "—"} />
          <Metric label="Risk compliance" value={snapshot.risk_compliance?.status ?? "—"} />
          <Metric
            label="MT5 checks"
            value={snapshot.mt5_checks?.ready ? "ready" : "issues"}
          />
        </div>

        {(failedRecon.length > 0 || failedRisk.length > 0) && (
          <ul className="space-y-1 rounded-md border border-border/50 p-2 text-xs">
            {[...failedRecon, ...failedRisk].slice(0, 5).map((issue) => (
              <li key={issue.code} className="text-muted-foreground">
                <span className="font-mono text-foreground">{issue.code}</span>
                {" · "}
                {issue.detail}
              </li>
            ))}
          </ul>
        )}

        {snapshot.mt5_log?.error_count ? (
          <p className="text-xs text-destructive">
            {snapshot.mt5_log.error_count} DWX log errors in last 24h
          </p>
        ) : null}

        <Button
          size="sm"
          variant="outline"
          disabled={trigger.isPending}
          onClick={() => trigger.mutate()}
        >
          {trigger.isPending ? "Running…" : "Run watchdog cycle"}
        </Button>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/50 px-2 py-1.5">
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}
