import { useQuery } from "@tanstack/react-query";
import { AgentVoteBar } from "@/components/shared/AgentVoteBar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { agentDisplayName } from "@/lib/utils";

const AGENT_ORDER = [
  "trend_surfer",
  "breakout_hunter",
  "momentum_pulse",
  "mean_reversion",
];

export function AgentsPage() {
  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: queryKeys.agents,
    queryFn: api.getAgents,
    refetchInterval: 30_000,
  });

  const { data: lastCycle, isLoading: cycleLoading } = useQuery({
    queryKey: queryKeys.lastCycle,
    queryFn: api.getLastCycle,
    refetchInterval: 15_000,
  });

  const { data: attribution } = useQuery({
    queryKey: queryKeys.agentAttribution,
    queryFn: api.getAgentAttribution,
    refetchInterval: 60_000,
  });

  const sortedAgents = [...(agents ?? [])].sort(
    (a, b) => AGENT_ORDER.indexOf(a.agent) - AGENT_ORDER.indexOf(b.agent),
  );

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Agents</h1>
        <p className="text-sm text-muted-foreground">
          Four-agent ensemble performance and last-cycle votes
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {agentsLoading
          ? AGENT_ORDER.map((agent) => (
              <Skeleton key={agent} className="h-36" />
            ))
          : sortedAgents.map((agent) => (
              <Card key={agent.agent} className="bg-panel border-border/60">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">
                    {agentDisplayName(agent.agent)}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Win rate</span>
                    <span className="font-mono">
                      {(agent.win_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Avg R</span>
                    <span className="font-mono">{agent.avg_r.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Samples</span>
                    <span className="font-mono">{agent.samples}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
      </div>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>
            Closed Trade Attribution
            {attribution ? ` · ${attribution.total_closed_trades} trades` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {attribution?.attribution?.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {attribution.attribution.map((row) => (
                <div
                  key={row.agent}
                  className="rounded-lg border border-border/60 p-3 text-sm"
                >
                  <div className="font-medium">{row.label}</div>
                  <div className="mt-2 flex justify-between text-muted-foreground">
                    <span>Trades</span>
                    <span className="font-mono text-foreground">{row.trades}</span>
                  </div>
                  <div className="flex justify-between text-muted-foreground">
                    <span>Win rate</span>
                    <span className="font-mono text-foreground">
                      {(row.win_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="flex justify-between text-muted-foreground">
                    <span>Avg R</span>
                    <span className="font-mono text-foreground">{row.avg_r.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No closed trades in memory yet
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>
            Last Cycle Votes
            {lastCycle
              ? ` · ${lastCycle.symbols_processed} symbols`
              : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {cycleLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : lastCycle?.agent_votes?.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              {lastCycle.agent_votes.map((vote, i) => (
                <AgentVoteBar key={`${vote.agent}-${vote.symbol ?? i}`} vote={vote} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No votes from the last cycle yet
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
