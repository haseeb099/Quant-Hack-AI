import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/shared/PageHeader";

import { AgentVoteBar } from "@/components/shared/AgentVoteBar";

import { AdaptationPanel } from "@/components/shared/AdaptationPanel";

import { Badge } from "@/components/ui/badge";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { Skeleton } from "@/components/ui/skeleton";

import { api, queryKeys } from "@/lib/api";

import { agentDisplayName, cn } from "@/lib/utils";



const AGENT_ORDER = [

  "trend_surfer",

  "breakout_hunter",

  "momentum_pulse",

  "mean_reversion",

  "sentiment_agent",

  "ml_signal",

];



function healthBadgeClass(status: string | undefined) {

  if (status === "GREEN") return "border-emerald-500/40 text-emerald-300";

  if (status === "YELLOW") return "border-amber-500/40 text-amber-300";

  return "border-destructive/40 text-destructive";

}



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



  const { data: health } = useQuery({

    queryKey: queryKeys.agentHealth,

    queryFn: api.getAgentHealth,

    refetchInterval: 120_000,

  });



  const { data: audit } = useQuery({

    queryKey: queryKeys.agentAudit,

    queryFn: api.getAgentAudit,

    refetchInterval: 120_000,

  });



  const { data: tunedConfig } = useQuery({

    queryKey: queryKeys.agentTunedConfig,

    queryFn: api.getAgentTunedConfig,

    refetchInterval: 120_000,

  });



  const sortedAgents = [...(agents ?? [])].sort(

    (a, b) => AGENT_ORDER.indexOf(a.agent) - AGENT_ORDER.indexOf(b.agent),

  );



  const skipSummary = (lastCycle?.decisions ?? []).reduce<Record<string, number>>(

    (acc, d) => {

      if (d.reason) {

        const key = d.reason.length > 48 ? `${d.reason.slice(0, 48)}…` : d.reason;

        acc[key] = (acc[key] ?? 0) + 1;

      }

      return acc;

    },

    {},

  );



  const plan = tunedConfig?.plan;

  const paramOverrides = plan?.parameter_overrides ?? {};

  const boostOverrides = plan?.regime_boost_overrides ?? {};



  return (

    <div className="flex flex-col gap-6">

      <PageHeader

        title="Agents"

        description="Six-agent ensemble performance, health, audit metrics, and adaptation diffs."

      />



      {health && (

        <Card className="bg-panel border-border/60">

          <CardHeader className="pb-2">

            <div className="flex items-center justify-between gap-2">

              <CardTitle className="text-sm">Agent Health</CardTitle>

              <Badge variant="outline" className={cn("text-[10px] uppercase", healthBadgeClass(health.status))}>

                {health.status}

              </Badge>

            </div>

          </CardHeader>

          <CardContent>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">

              {AGENT_ORDER.map((name) => {

                const report = health.agents?.[name];

                const active = report?.active ?? false;

                return (

                  <div key={name} className="rounded-md border border-border/50 px-2.5 py-2 text-xs">

                    <div className="flex items-center justify-between gap-2">

                      <span className="font-medium">{agentDisplayName(name)}</span>

                      <span className={active ? "text-emerald-400" : "text-muted-foreground"}>

                        {active ? "active" : "inactive"}

                      </span>

                    </div>

                    {report?.symbols_firing != null && (

                      <div className="mt-1 text-muted-foreground">

                        {report.symbols_firing}/{report.symbols_tested ?? 15} symbols firing

                      </div>

                    )}

                    {report?.issue && (

                      <div className="mt-1 text-destructive">{report.issue}</div>

                    )}

                  </div>

                );

              })}

            </div>

          </CardContent>

        </Card>

      )}



      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">

        {agentsLoading

          ? AGENT_ORDER.map((agent) => (

              <Skeleton key={agent} className="h-36" />

            ))

          : sortedAgents.map((agent) => {

              const auditMetrics = audit?.agents?.[agent.agent];

              return (

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

                        {agent.samples === 0 || agent.win_rate == null

                          ? "N/A"

                          : `${(agent.win_rate * 100).toFixed(1)}%`}

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

                    {auditMetrics?.attribution?.sample_size ? (

                      <div className="flex justify-between text-xs text-muted-foreground">

                        <span>Vote credit</span>

                        <span className="font-mono text-foreground">

                          {auditMetrics.attribution.win_rate != null

                            ? `${(auditMetrics.attribution.win_rate * 100).toFixed(0)}%`

                            : "—"}

                        </span>

                      </div>

                    ) : null}

                  </CardContent>

                </Card>

              );

            })}

      </div>



      <AdaptationPanel />



      {(Object.keys(paramOverrides).length > 0 || Object.keys(boostOverrides).length > 0) && (

        <Card className="bg-panel border-border/60">

          <CardHeader>

            <CardTitle>Adaptation Parameter Diff</CardTitle>

          </CardHeader>

          <CardContent className="grid gap-4 md:grid-cols-2">

            {Object.keys(paramOverrides).length > 0 && (

              <div>

                <div className="mb-2 text-xs font-medium text-muted-foreground">Parameter overrides</div>

                <div className="flex flex-col gap-2 text-xs">

                  {Object.entries(paramOverrides).map(([agent, params]) => (

                    <div key={agent} className="rounded border border-border/50 p-2">

                      <div className="font-medium">{agentDisplayName(agent)}</div>

                      {Object.entries(params).map(([key, delta]) => (

                        <div key={key} className="mt-1 flex justify-between font-mono">

                          <span>{key}</span>

                          <span className={delta > 0 ? "text-emerald-400" : "text-destructive"}>

                            {delta > 0 ? "+" : ""}

                            {delta}

                          </span>

                        </div>

                      ))}

                    </div>

                  ))}

                </div>

              </div>

            )}

            {Object.keys(boostOverrides).length > 0 && (

              <div>

                <div className="mb-2 text-xs font-medium text-muted-foreground">Regime boost overrides</div>

                <div className="flex flex-col gap-2 text-xs">

                  {Object.entries(boostOverrides).map(([regime, agents]) => (

                    <div key={regime} className="rounded border border-border/50 p-2">

                      <div className="font-medium capitalize">{regime}</div>

                      {Object.entries(agents).map(([agent, delta]) => (

                        <div key={agent} className="mt-1 flex justify-between font-mono">

                          <span>{agentDisplayName(agent)}</span>

                          <span className={delta > 0 ? "text-emerald-400" : "text-destructive"}>

                            {delta > 0 ? "+" : ""}

                            {delta}

                          </span>

                        </div>

                      ))}

                    </div>

                  ))}

                </div>

              </div>

            )}

            {plan?.blocked_reason && (

              <p className="text-xs text-muted-foreground md:col-span-2">

                Blocked: {plan.blocked_reason}

              </p>

            )}

          </CardContent>

        </Card>

      )}



      {audit?.recommendations?.length ? (

        <Card className="bg-panel border-border/60">

          <CardHeader>

            <CardTitle>Audit Recommendations · {audit.trade_count} trades</CardTitle>

          </CardHeader>

          <CardContent>

            <div className="flex flex-col gap-2 text-xs">

              {audit.recommendations.slice(0, 8).map((rec, i) => (

                <div key={`${rec.agent}-${rec.regime}-${i}`} className="rounded border border-border/50 p-2">

                  <div className="flex items-center justify-between gap-2">

                    <span className="font-medium">

                      {agentDisplayName(rec.agent)} · {rec.regime}

                    </span>

                    <Badge variant="outline" className="text-[10px] uppercase">

                      {rec.severity}

                    </Badge>

                  </div>

                  <div className="mt-1 text-muted-foreground">{rec.recommendation}</div>

                  <div className="mt-1 font-mono text-muted-foreground">

                    n={rec.sample_size} wr={(rec.win_rate * 100).toFixed(0)}%

                  </div>

                </div>

              ))}

            </div>

          </CardContent>

        </Card>

      ) : null}



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

              ? ` · ${lastCycle.symbols_processed}/${lastCycle.symbols_attempted} symbols`

              : ""}

          </CardTitle>

        </CardHeader>

        <CardContent className="flex flex-col gap-4">

          {Object.keys(skipSummary).length > 0 && (

            <div className="rounded-lg border border-border/60 p-3 text-xs text-muted-foreground">

              <div className="mb-2 font-medium text-foreground">Skip reasons</div>

              <div className="flex flex-col gap-1">

                {Object.entries(skipSummary)

                  .sort((a, b) => b[1] - a[1])

                  .slice(0, 6)

                  .map(([reason, count]) => (

                    <div key={reason} className="flex justify-between gap-2">

                      <span>{reason}</span>

                      <span className="font-mono text-foreground">{count}</span>

                    </div>

                  ))}

              </div>

            </div>

          )}

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


