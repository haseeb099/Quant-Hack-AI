import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import {

  Area,

  AreaChart,

  CartesianGrid,

  ResponsiveContainer,

  Tooltip,

  XAxis,

  YAxis,

} from "recharts";

import { Link } from "react-router-dom";

import { ArrowRight } from "lucide-react";

import { MetricCard } from "@/components/shared/MetricCard";

import { PageHeader } from "@/components/shared/PageHeader";

import { CompetitionDayPanel } from "@/components/shared/CompetitionDayPanel";

import { DeployStatusCard } from "@/components/shared/DeployStatusCard";

import { EngineHealthPanel } from "@/components/shared/EngineHealthPanel";

import { LaunchReadinessPanel } from "@/components/shared/LaunchReadinessPanel";

import { MemoryContextCard } from "@/components/shared/MemoryContextCard";

import { NotionSyncPanel } from "@/components/shared/NotionSyncPanel";

import { OperatorRunbookPanel } from "@/components/shared/OperatorRunbookPanel";

import { OperatorSnapshotPanel } from "@/components/shared/OperatorSnapshotPanel";

import { TradingControlBar } from "@/components/shared/TradingControlBar";

import { Badge } from "@/components/ui/badge";

import { Button } from "@/components/ui/button";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { Skeleton } from "@/components/ui/skeleton";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { api, queryKeys, resolveRiskCaps } from "@/lib/api";

import { formatCurrency, formatPercent, pnlColorClass } from "@/lib/utils";



export function OverviewPage() {

  const { data: status } = useQuery({

    queryKey: queryKeys.status,

    queryFn: api.getStatus,

    refetchInterval: 15_000,

  });



  const { data: account, isLoading: accountLoading } = useQuery({

    queryKey: queryKeys.account,

    queryFn: api.getAccount,

    refetchInterval: 15_000,

  });



  const { data: risk, isLoading: riskLoading } = useQuery({

    queryKey: queryKeys.risk,

    queryFn: api.getRisk,

    refetchInterval: 15_000,

  });



  const { data: equity, isLoading: equityLoading } = useQuery({

    queryKey: queryKeys.equityCurve,

    queryFn: api.getEquityCurve,

    refetchInterval: 30_000,

  });



  const { data: competition, isLoading: scoreLoading } = useQuery({

    queryKey: queryKeys.competitionScore,

    queryFn: api.getCompetitionScore,

    refetchInterval: 30_000,

  });



  const accountStale = Boolean(account?.account_stale);
  const dailyPnl = account?.daily_pnl ?? null;

  const returnPct = account?.return_pct ?? 0;

  const caps = resolveRiskCaps(risk);



  const scoreBreakdown = competition?.components ?? [];

  const weightedTotal = competition?.total ?? 0;



  const chartData =

    equity?.points.map((p) => ({

      time: new Date(p.t).toLocaleTimeString("en-GB", {

        hour: "2-digit",

        minute: "2-digit",

      }),

      equity: p.equity,

    })) ?? [];



  const equities = chartData.map((p) => p.equity);

  const minEquity = equities.length ? Math.min(...equities) : 0;

  const maxEquity = equities.length ? Math.max(...equities) : 0;

  const isMicro = status?.account_profile === "micro";

  const yPadding =

    equities.length > 1

      ? (maxEquity - minEquity) * 0.08

      : isMicro

        ? Math.max(maxEquity * 0.05, 0.5)

        : Math.max(maxEquity * 0.01, 100);

  const yDomain: [number, number] = [

    minEquity - yPadding,

    maxEquity + yPadding,

  ];



  const formatEquityTick = (value: number) => {

    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;

    if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;

    return `$${value.toFixed(0)}`;

  };



  return (

    <div className="flex flex-col gap-6">

      <PageHeader

        title="Overview"

        description="Live competition metrics, equity curve, and engine status at a glance."

        actions={

          <Button variant="outline" size="sm" asChild>

            <Link to="/risk">

              Risk dashboard

              <ArrowRight className="size-3.5" />

            </Link>

          </Button>

        }

      />



      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">

        <MetricCard

          title="Equity"

          accent="primary"

          loading={accountLoading}

          value={

            account && !accountStale

              ? formatCurrency(account.equity, true)

              : accountStale

                ? "Stale"

                : "—"

          }

          subtitle={

            <>

              Balance {account ? formatCurrency(account.balance, true) : "—"}

              {accountStale && (

                <Badge variant="destructive" className="ml-2 px-1 py-0 text-[9px] uppercase">

                  MT5 offline

                </Badge>

              )}

              {status?.account_profile === "micro" && (

                <Badge variant="outline" className="ml-2 px-1 py-0 text-[9px] uppercase">

                  Micro

                </Badge>

              )}

            </>

          }

        />

        <MetricCard

          title="Free Margin"

          loading={accountLoading}

          value={account ? formatCurrency(account.free_margin, true) : "—"}

          subtitle={

            account ? `Used ${formatCurrency(account.margin, true)}` : undefined

          }

        />

        <MetricCard

          title="Daily P&L"

          accent={

            dailyPnl != null && dailyPnl > 0

              ? "positive"

              : dailyPnl != null && dailyPnl < 0

                ? "negative"

                : "default"

          }

          loading={accountLoading}

          value={formatCurrency(dailyPnl)}

          valueClassName={dailyPnl != null ? pnlColorClass(dailyPnl) : undefined}

        />

        <MetricCard

          title="Return"

          accent={returnPct > 0 ? "positive" : returnPct < 0 ? "negative" : "default"}

          loading={accountLoading}

          value={formatPercent(returnPct)}

          valueClassName={pnlColorClass(returnPct)}

        />

        <MetricCard

          title="Exposure"

          loading={accountLoading}

          value={account ? formatCurrency(account.gross_exposure, true) : "—"}

        />

        <MetricCard

          title="Sharpe"

          loading={riskLoading}

          value={risk ? risk.sharpe.toFixed(2) : "—"}

        />

      </div>



      <Tabs defaultValue="performance" className="gap-6">

        <TabsList className="w-full justify-start sm:w-auto">

          <TabsTrigger value="performance">Performance</TabsTrigger>

          <TabsTrigger value="operations">Operations</TabsTrigger>

        </TabsList>



        <TabsContent value="performance" className="flex flex-col gap-4">

          <div className="grid gap-4 lg:grid-cols-3">

            <Card className="bg-panel border-border/60 lg:col-span-2">

              <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">

                <CardTitle>Equity Curve</CardTitle>

                <span className="text-xs text-muted-foreground">

                  {chartData.length} snapshots

                </span>

              </CardHeader>

              <CardContent className="h-72 min-h-72">

                {equityLoading ? (

                  <Skeleton className="h-full w-full skeleton-shimmer" />

                ) : chartData.length > 0 ? (

                  <div className="h-full w-full min-h-[288px]">

                    <ResponsiveContainer width="100%" height={288} minWidth={0}>

                      <AreaChart data={chartData}>

                        <defs>

                          <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">

                            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.35} />

                            <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />

                          </linearGradient>

                        </defs>

                        <CartesianGrid stroke="#243049" strokeDasharray="3 3" vertical={false} />

                        <XAxis dataKey="time" stroke="#8b9cb8" fontSize={11} tickLine={false} />

                        <YAxis

                          stroke="#8b9cb8"

                          fontSize={11}

                          domain={yDomain}

                          tickFormatter={formatEquityTick}

                          tickLine={false}

                          width={56}

                        />

                        <Tooltip

                          contentStyle={{

                            background: "#0f1729",

                            border: "1px solid #243049",

                            borderRadius: 8,

                            fontSize: 12,

                          }}

                          formatter={(value) =>

                            typeof value === "number"

                              ? [formatCurrency(value), "Equity"]

                              : ["—", "Equity"]

                          }

                        />

                        <Area

                          type="monotone"

                          dataKey="equity"

                          stroke="#22d3ee"

                          strokeWidth={2}

                          fill="url(#equityFill)"

                          dot={false}

                          activeDot={{ r: 4, fill: "#22d3ee" }}

                        />

                      </AreaChart>

                    </ResponsiveContainer>

                  </div>

                ) : (

                  <div className="flex h-full flex-col items-center justify-center gap-1 text-sm text-muted-foreground">

                    <span>No equity history yet</span>

                    <span className="text-xs">Snapshots appear after the first engine cycle</span>

                  </div>

                )}

              </CardContent>

            </Card>



            <Card className="bg-panel border-border/60">

              <CardHeader>

                <CardTitle>Competition Score</CardTitle>

              </CardHeader>

              <CardContent className="flex flex-col gap-4">

                {scoreLoading ? (

                  <Skeleton className="h-10 w-24 skeleton-shimmer" />

                ) : (

                  <div className="font-mono text-4xl font-semibold tabular-nums text-primary">

                    {weightedTotal.toFixed(1)}

                  </div>

                )}

                <div className="flex flex-col gap-3">

                  {scoreBreakdown.map((item) => (

                    <div key={item.label} className="flex flex-col gap-1.5">

                      <div className="flex justify-between text-xs">

                        <span>{item.label}</span>

                        <span className="font-mono text-muted-foreground">

                          {(item.weight * 100).toFixed(0)}% · {item.value.toFixed(0)}

                        </span>

                      </div>

                      <div className="h-1.5 overflow-hidden rounded-full bg-muted/80">

                        <div

                          className="h-full rounded-full bg-gradient-to-r from-primary/80 to-accent"

                          style={{ width: `${Math.min(100, item.value)}%` }}

                        />

                      </div>

                    </div>

                  ))}

                </div>

              </CardContent>

            </Card>

          </div>



          <div className="grid gap-4 md:grid-cols-2">

            <Card className="bg-panel border-border/60">

              <CardHeader className="flex-row items-center justify-between space-y-0">

                <CardTitle>Risk Snapshot</CardTitle>

                <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>

                  <Link to="/risk">Details</Link>

                </Button>

              </CardHeader>

              <CardContent className="flex flex-col gap-3">

                {riskLoading ? (

                  <Skeleton className="h-20 w-full skeleton-shimmer" />

                ) : (

                  <>

                    <RiskRow label="Drawdown" value={risk ? formatPercent(risk.drawdown_pct) : "—"} />

                    <RiskRow label="Discipline" value={risk ? `${risk.discipline}/100` : "—"} />

                    <RiskRow

                      label="DD Tier"

                      value={

                        risk?.dd_tier ? (

                          <Badge variant="outline" className="uppercase">

                            {risk.dd_tier}

                          </Badge>

                        ) : (

                          "—"

                        )

                      }

                    />

                    <RiskRow

                      label="Net directional"

                      value={

                        risk?.margin_state?.net_directional_pct != null

                          ? formatPercent(risk.margin_state.net_directional_pct)

                          : "—"

                      }

                    />

                    <RiskRow

                      label="Margin level"

                      value={

                        <span className="flex items-center gap-2">

                          {risk?.margin_state?.margin_level_pct != null

                            ? `${risk.margin_state.margin_level_pct.toFixed(0)}%`

                            : "—"}

                          {risk?.margin_state?.margin_level_pct != null &&

                            risk.margin_state.margin_level_pct <= caps.stopOut && (

                              <Badge variant="destructive" className="text-[10px]">

                                Stop-out

                              </Badge>

                            )}

                        </span>

                      }

                    />

                  </>

                )}

              </CardContent>

            </Card>



            <EngineHealthPanel />

          </div>

        </TabsContent>



        <TabsContent value="operations" className="flex flex-col gap-4">

          <div className="grid gap-4 lg:grid-cols-3">

            <div className="lg:col-span-2">

              <LaunchReadinessPanel />

            </div>

            <NotionSyncPanel />

          </div>



          <div className="grid gap-4 lg:grid-cols-3">

            <div className="lg:col-span-2">

              <OperatorRunbookPanel />

            </div>

            <div className="flex flex-col gap-4">

              <OperatorSnapshotPanel />

              <CompetitionDayPanel />

            </div>

          </div>



          <DeployStatusCard />



          <div className="grid gap-4 md:grid-cols-2">

            <MemoryContextCard />

            <Card className="bg-panel border-border/60">

              <CardHeader>

                <CardTitle>Trading Controls</CardTitle>

              </CardHeader>

              <CardContent>

                <TradingControlBar />

              </CardContent>

            </Card>

          </div>

        </TabsContent>

      </Tabs>

    </div>

  );

}



function RiskRow({

  label,

  value,

}: {

  label: string;

  value: ReactNode;

}) {

  return (

    <div className="flex items-center justify-between gap-4 text-sm">

      <span className="text-muted-foreground">{label}</span>

      <span className="font-mono text-right">{value}</span>

    </div>

  );

}


