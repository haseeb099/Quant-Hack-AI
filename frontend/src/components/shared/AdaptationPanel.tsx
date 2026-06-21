import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Play, Scale } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { agentDisplayName, cn } from "@/lib/utils";

const AGENT_ORDER = [
  "trend_surfer",
  "breakout_hunter",
  "momentum_pulse",
  "mean_reversion",
];

export function AdaptationPanel() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.adaptationStatus,
    queryFn: api.getAdaptationStatus,
    refetchInterval: 30_000,
  });

  const runMutation = useMutation({
    mutationFn: () => api.runAdaptation({ confirm: true }),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.adaptationStatus });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents });
    },
    onError: (err: Error) => setError(err.message),
  });

  if (isLoading) {
    return <Skeleton className="h-48 w-full" />;
  }

  if (!data) return null;

  const plan = data.plan;
  const weights = plan?.new_weights ?? data.current_weights;
  const oldWeights = plan?.old_weights ?? data.current_weights;

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Scale className="size-4 text-accent" />
            Between-Round Adaptation
          </CardTitle>
          {plan?.promoted != null && (
            <Badge
              variant="outline"
              className={cn(
                "text-[10px] uppercase",
                plan.promoted
                  ? "border-emerald-500/40 text-emerald-300"
                  : "border-muted-foreground/40 text-muted-foreground",
              )}
            >
              {plan.promoted ? "Promoted" : "Not promoted"}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{data.reason}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          {AGENT_ORDER.map((agent) => {
            const oldW = oldWeights?.[agent] ?? 0;
            const newW = weights?.[agent] ?? oldW;
            const delta = newW - oldW;
            return (
              <div
                key={agent}
                className="flex items-center justify-between rounded-md border border-border/50 px-2.5 py-2 text-xs"
              >
                <span>{agentDisplayName(agent)}</span>
                <span className="flex items-center gap-1 font-mono">
                  {(oldW * 100).toFixed(0)}%
                  <ArrowRight className="size-3 text-muted-foreground" />
                  {(newW * 100).toFixed(0)}%
                  {Math.abs(delta) > 0.001 && (
                    <span className={delta > 0 ? "text-emerald-400" : "text-destructive"}>
                      ({delta > 0 ? "+" : ""}{(delta * 100).toFixed(1)}%)
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>

        {plan?.walk_forward && (
          <div className="grid grid-cols-3 gap-2 text-center text-[11px]">
            <div className="rounded border border-border/50 p-2">
              <div className="text-muted-foreground">OOS Sharpe</div>
              <div className="font-mono text-sm">
                {plan.walk_forward.oos_sharpe?.toFixed(3) ?? "—"}
              </div>
            </div>
            <div className="rounded border border-border/50 p-2">
              <div className="text-muted-foreground">Sharpe Δ</div>
              <div className="font-mono text-sm">
                {plan.walk_forward.sharpe_delta?.toFixed(3) ?? "—"}
              </div>
            </div>
            <div className="rounded border border-border/50 p-2">
              <div className="text-muted-foreground">Trades</div>
              <div className="font-mono text-sm">{plan.trade_count ?? "—"}</div>
            </div>
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}

        <Button
          size="sm"
          className="w-full"
          disabled={!data.can_run || runMutation.isPending}
          onClick={() => runMutation.mutate()}
        >
          <Play className="size-3.5" />
          {runMutation.isPending ? "Running adaptation…" : "Run adaptation"}
        </Button>
        <p className="text-[10px] text-muted-foreground">
          Rebuilds semantic memory, optimizes weights (±10% cap), walk-forward validates.
          Promoted weights apply on next engine restart.
        </p>
      </CardContent>
    </Card>
  );
}
