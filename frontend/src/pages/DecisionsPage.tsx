import { useQuery } from "@tanstack/react-query";
import { AgentVoteBar } from "@/components/shared/AgentVoteBar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";

export function DecisionsPage() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.lastCycle,
    queryFn: api.getLastCycle,
    refetchInterval: 10_000,
  });

  const decisions = data?.decisions ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Decisions</h1>
        <p className="text-sm text-muted-foreground">
          Live feed of per-symbol orchestrator decisions from the last cycle
        </p>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : decisions.length === 0 ? (
        <Card className="bg-panel border-border/60">
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No decisions from the last cycle yet
          </CardContent>
        </Card>
      ) : (
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
                  <p className="text-sm text-success">Skip reason: {decision.reason}</p>
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
      )}
    </div>
  );
}
