import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Radio } from "lucide-react";
import { AgentVoteBar } from "@/components/shared/AgentVoteBar";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { RiskGauge } from "@/components/shared/RiskGauge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys, resolveRiskCaps, type CycleDecision } from "@/lib/api";

type SkipKind = "operational" | "data_failure" | "risk_gate" | "hold" | "other";

function skipCategory(reason: string): string {
  if (reason.startsWith("Live filter:")) return "Blocked symbol";
  if (reason.startsWith("Net directional")) return "Net directional";
  if (reason.includes("Insufficient OHLCV")) return "Data failure (OHLCV)";
  if (reason.startsWith("Session inactive")) return "Session inactive";
  if (reason.includes("Open position already exists")) return "Open position";
  if (reason.includes("Symbol cooldown")) return "Symbol cooldown";
  if (reason.includes("Concentration")) return "Concentration cap";
  if (reason === "HOLD decision") return "HOLD decision";
  return reason.split("(")[0]?.split(":")[0]?.trim() || "Other";
}

function skipKind(reason: string): SkipKind {
  if (reason === "HOLD decision") return "hold";
  if (
    reason.includes("Insufficient OHLCV") ||
    reason.includes("Market health RED")
  ) {
    return "data_failure";
  }
  if (
    reason.startsWith("Net directional") ||
    reason.includes("Concentration") ||
    reason.includes("Portfolio heat") ||
    reason.includes("Margin block")
  ) {
    return "risk_gate";
  }
  if (
    reason.includes("Open position") ||
    reason.includes("Live filter") ||
    reason.includes("blocked") ||
    reason.includes("Blocked") ||
    reason.includes("cooldown") ||
    reason.startsWith("Session inactive")
  ) {
    return "operational";
  }
  return "other";
}

const skipKindStyles: Record<SkipKind, string> = {
  operational: "border-muted bg-muted/30 text-muted-foreground",
  data_failure: "border-destructive/30 bg-destructive/10 text-destructive",
  risk_gate: "border-warning/30 bg-warning/10 text-warning",
  hold: "border-border bg-muted/20 text-muted-foreground",
  other: "border-warning/20 bg-warning/5 text-warning",
};

function closestToPass(decisions: CycleDecision[]): CycleDecision[] {
  return decisions
    .filter(
      (d) =>
        !d.executed &&
        d.action !== "HOLD" &&
        d.reason &&
        !d.reason.includes("HOLD"),
    )
    .sort((a, b) => {
      const aGate = skipCategory(a.reason ?? "");
      const bGate = skipCategory(b.reason ?? "");
      if (aGate !== bGate) return aGate.localeCompare(bGate);
      return (b.agent_votes?.length ?? 0) - (a.agent_votes?.length ?? 0);
    })
    .slice(0, 3);
}

export function DecisionsPage() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.lastCycle,
    queryFn: api.getLastCycle,
    refetchInterval: 10_000,
  });

  const { data: risk, isLoading: riskLoading } = useQuery({
    queryKey: queryKeys.risk,
    queryFn: api.getRisk,
    refetchInterval: 10_000,
  });

  const caps = resolveRiskCaps(risk);
  const margin = risk?.margin_state;

  const decisions = data?.decisions ?? [];
  const skipSummary = useMemo(() => {
    if (data?.skip_summary && Object.keys(data.skip_summary).length > 0) {
      return Object.entries(data.skip_summary).sort((a, b) => b[1] - a[1]);
    }
    const counts = new Map<string, number>();
    for (const d of decisions) {
      if (d.executed || !d.reason) continue;
      const key = skipCategory(d.reason);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [data?.skip_summary, decisions]);

  const nearMiss = useMemo(() => closestToPass(decisions), [decisions]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Decisions"
        description="Per-symbol orchestrator output from the last 15-minute cycle."
      />

      {isLoading ? (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : decisions.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="No decisions yet"
          description="Run a cycle or wait for the next 15-minute tick to see orchestrator output."
        />
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {riskLoading ? (
              <Skeleton className="h-28 md:col-span-2" />
            ) : risk ? (
              <>
                <RiskGauge
                  label="Net Directional (portfolio)"
                  value={margin?.net_directional_pct ?? 0}
                  cap={caps.netDirectional}
                />
                <RiskGauge
                  label="Concentration (largest position)"
                  value={margin?.concentration_pct ?? 0}
                  cap={caps.concentration}
                />
              </>
            ) : null}
          </div>

          {(skipSummary.length > 0 || nearMiss.length > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              {skipSummary.length > 0 && (
                <Card className="bg-panel border-border/60">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium">
                      Skip reasons (last cycle)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    {skipSummary.map(([reason, count]) => (
                      <div
                        key={reason}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="text-muted-foreground">{reason}</span>
                        <Badge variant="secondary">{count}</Badge>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}
              {nearMiss.length > 0 && (
                <Card className="bg-panel border-border/60">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium">
                      Closest to pass
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    {nearMiss.map((d) => (
                      <div key={d.symbol} className="text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono font-medium">{d.symbol}</span>
                          <Badge variant="outline">{d.action}</Badge>
                        </div>
                        <p className="mt-1 text-xs text-warning">
                          {d.reason}
                        </p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          <div className="flex flex-col gap-4">
            {decisions.map((decision) => (
              <Card
                key={decision.symbol}
                className="bg-panel border-border/60"
              >
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="font-mono">{decision.symbol}</CardTitle>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{decision.action}</Badge>
                      <Badge variant={decision.executed ? "signal" : "secondary"}>
                        {decision.executed ? "Executed" : "Skipped"}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                  {decision.features_summary && (
                    <div>
                      <h4 className="mb-1 text-xs uppercase tracking-wider text-muted-foreground">
                        Features
                      </h4>
                      <p className="text-sm">{decision.features_summary}</p>
                    </div>
                  )}
                  {decision.orchestrator_output && (
                    <div>
                      <h4 className="mb-1 text-xs uppercase tracking-wider text-muted-foreground">
                        Orchestrator
                      </h4>
                      <p className="text-sm text-muted-foreground">
                        {decision.orchestrator_output}
                      </p>
                    </div>
                  )}
                  {!decision.executed && decision.reason && (
                    <div>
                      <h4 className="mb-1 text-xs uppercase tracking-wider text-warning">
                        Skip reason
                        <Badge
                          variant="outline"
                          className={`ml-2 text-[10px] normal-case ${skipKindStyles[skipKind(decision.reason)]}`}
                        >
                          {skipKind(decision.reason).replace("_", " ")}
                        </Badge>
                      </h4>
                      <p
                        className={`rounded-md border px-3 py-2 text-sm ${skipKindStyles[skipKind(decision.reason)]}`}
                      >
                        {decision.reason}
                      </p>
                    </div>
                  )}
                  {decision.agent_votes && decision.agent_votes.length > 0 && (
                    <div className="grid gap-3 md:grid-cols-2">
                      {decision.agent_votes.map((vote, i) => (
                        <AgentVoteBar
                          key={`${vote.agent}-${i}`}
                          vote={vote}
                          compact
                        />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
