import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MetricCard } from "@/components/shared/MetricCard";
import { CompetitionDayPanel } from "@/components/shared/CompetitionDayPanel";
import { DeployStatusCard } from "@/components/shared/DeployStatusCard";
import { EngineHealthPanel } from "@/components/shared/EngineHealthPanel";
import { LaunchReadinessPanel } from "@/components/shared/LaunchReadinessPanel";
import { MemoryContextCard } from "@/components/shared/MemoryContextCard";
import { NotionSyncPanel } from "@/components/shared/NotionSyncPanel";
import { OperatorRunbookPanel } from "@/components/shared/OperatorRunbookPanel";
import { TradingControlBar } from "@/components/shared/TradingControlBar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { formatCurrency, formatPercent, pnlColorClass } from "@/lib/utils";

export function OverviewPage() {
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

  const dailyPnl = account?.daily_pnl ?? 0;
  const returnPct = account?.return_pct ?? 0;

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
  const yPadding =
    equities.length > 1
      ? (maxEquity - minEquity) * 0.08
      : maxEquity * 0.01 || 1000;
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
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-sm text-muted-foreground">
          Live competition metrics and engine status
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <MetricCard
          title="Equity"
          loading={accountLoading}
          value={account ? formatCurrency(account.equity, true) : "—"}
          subtitle={`Balance ${account ? formatCurrency(account.balance, true) : "—"}`}
        />
        <MetricCard
          title="Free Margin"
          loading={accountLoading}
          value={account ? formatCurrency(account.free_margin, true) : "—"}
          subtitle={
            account
              ? `Used ${formatCurrency(account.margin, true)}`
              : undefined
          }
        />
        <MetricCard
          title="Daily P&L"
          loading={accountLoading}
          value={formatCurrency(dailyPnl)}
          valueClassName={pnlColorClass(dailyPnl)}
        />
        <MetricCard
          title="Return"
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

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="bg-panel border-border/60 lg:col-span-2">
          <CardHeader>
            <CardTitle>Equity Curve</CardTitle>
          </CardHeader>
          <CardContent className="h-72 min-h-72">
            {equityLoading ? (
              <Skeleton className="h-full w-full" />
            ) : chartData.length > 0 ? (
              <div className="h-full w-full min-h-[288px]">
                <ResponsiveContainer width="100%" height="100%" minHeight={288}>
                  <LineChart data={chartData}>
                    <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                    <XAxis dataKey="time" stroke="#94a3b8" fontSize={11} />
                    <YAxis
                      stroke="#94a3b8"
                      fontSize={11}
                      domain={yDomain}
                      tickFormatter={formatEquityTick}
                    />
                  <Tooltip
                    contentStyle={{
                      background: "#151e32",
                      border: "1px solid #334155",
                      borderRadius: 8,
                    }}
                    formatter={(value) =>
                      typeof value === "number"
                        ? [formatCurrency(value), "Equity"]
                        : ["—", "Equity"]
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="equity"
                    stroke="#22d3ee"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                No equity history yet
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
              <Skeleton className="h-10 w-24" />
            ) : (
              <div className="font-mono text-3xl font-semibold text-primary">
                {weightedTotal.toFixed(1)}
              </div>
            )}
            <div className="flex flex-col gap-3">
              {scoreBreakdown.map((item) => (
                <div key={item.label} className="flex flex-col gap-1">
                  <div className="flex justify-between text-xs">
                    <span>{item.label}</span>
                    <span className="font-mono text-muted-foreground">
                      {(item.weight * 100).toFixed(0)}% · {item.value.toFixed(0)}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${item.value}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

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
        <CompetitionDayPanel />
      </div>

      <DeployStatusCard />

      <div className="grid gap-4 md:grid-cols-2">
        <EngineHealthPanel />
        <MemoryContextCard />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="bg-panel border-border/60">
          <CardHeader>
            <CardTitle>Risk Snapshot</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {riskLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Drawdown</span>
                  <span className="font-mono">
                    {risk ? formatPercent(risk.drawdown_pct) : "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Discipline</span>
                  <span className="font-mono">
                    {risk ? `${risk.discipline}/100` : "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">DD Tier</span>
                  <Badge variant="outline" className="uppercase">
                    {risk?.dd_tier ?? "—"}
                  </Badge>
                </div>
              </>
            )}
          </CardContent>
        </Card>
        <div className="hidden md:block" />
      </div>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>Trading Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <TradingControlBar />
        </CardContent>
      </Card>
    </div>
  );
}
