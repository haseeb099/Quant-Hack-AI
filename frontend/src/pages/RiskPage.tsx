import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/shared/PageHeader";
import { RiskGauge } from "@/components/shared/RiskGauge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  api,
  queryKeys,
  resolveDrawdownTiers,
  resolveRiskCaps,
  type TradeCheckResponse,
} from "@/lib/api";
import { cn, formatCurrency, formatPercent, formatTimestamp } from "@/lib/utils";

function WhatIfPreview({ check }: { check: TradeCheckResponse }) {
  if (check.allowed && check.warnings.length === 0) {
    const p = check.projected;
    return (
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
        Trade would pass risk gates.
        <div className="mt-2 grid gap-1 font-mono text-[11px] opacity-90">
          {p.projected_leverage != null && (
            <span>Projected leverage: {String(p.projected_leverage)}×</span>
          )}
          {typeof p.trade_notional === "number" && (
            <span>
              Notional: {formatCurrency(p.trade_notional, true)}
            </span>
          )}
          {p.concentration_pct != null && (
            <span>
              Concentration: {formatPercent(Number(p.concentration_pct) * 100)}
            </span>
          )}
          {p.projected_net_directional_pct != null && (
            <span>
              Net directional:{" "}
              {formatPercent(Number(p.projected_net_directional_pct) * 100)}
            </span>
          )}
          {p.dd_tier != null && <span>Drawdown tier: {String(p.dd_tier)}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs">
      {check.blockers.map((b) => (
        <div key={`${b.code}-${b.message}`} className="flex items-start gap-2 text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <div>
            <Badge variant="outline" className="mb-1 text-[10px] uppercase">
              {b.code}
            </Badge>
            <p>{b.message}</p>
          </div>
        </div>
      ))}
      {check.warnings.map((w) => (
        <div key={`${w.code}-${w.message}`} className="flex items-start gap-2 text-amber-200">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <p>{w.message}</p>
        </div>
      ))}
      {check.remediation.length > 0 && (
        <ul className="list-disc pl-5 text-muted-foreground">
          {check.remediation.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MarginLevelCard({
  marginLevel,
  stopOut,
}: {
  marginLevel: number | null | undefined;
  stopOut: number;
}) {
  const level = marginLevel ?? null;
  const warnAt = 50;
  const emergencyAt = 40;
  const color =
    level == null
      ? "text-muted-foreground"
      : level <= stopOut
        ? "text-destructive"
        : level <= emergencyAt
          ? "text-destructive"
          : level <= warnAt
            ? "text-amber-400"
            : "text-emerald-400";

  return (
    <Card className="bg-panel border-border/60">
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Margin Level
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-end justify-between gap-2">
          <span className={cn("font-mono text-xl font-semibold", color)}>
            {level != null ? `${level.toFixed(0)}%` : "—"}
          </span>
          <span className="text-xs text-muted-foreground">
            stop-out {stopOut}%
          </span>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Higher is safer. Below {warnAt}% blocks entries; below {emergencyAt}% triggers
          emergency reduce.
        </p>
      </CardContent>
    </Card>
  );
}

export function RiskPage() {
  const [symbol, setSymbol] = useState("EUR/USD");
  const [direction, setDirection] = useState<"BUY" | "SELL">("BUY");
  const [volume, setVolume] = useState("0.01");

  const parsedVolume = parseFloat(volume);
  const tradeParams = useMemo(() => {
    if (!symbol.trim() || Number.isNaN(parsedVolume) || parsedVolume <= 0) {
      return null;
    }
    return {
      symbol: symbol.trim(),
      direction,
      volume: parsedVolume,
    };
  }, [symbol, direction, parsedVolume]);

  const { data: risk, isLoading } = useQuery({
    queryKey: queryKeys.risk,
    queryFn: api.getRisk,
    refetchInterval: 10_000,
  });

  const {
    data: whatIf,
    isFetching: whatIfLoading,
    refetch: refetchWhatIf,
  } = useQuery({
    queryKey: tradeParams ? queryKeys.tradeCheck(tradeParams) : ["tradeCheck", "invalid"],
    queryFn: () => api.checkTrade(tradeParams!),
    enabled: tradeParams != null,
  });

  const margin = risk?.margin_state;
  const caps = resolveRiskCaps(risk);
  const drawdownTiers = resolveDrawdownTiers(risk);
  const recentEvents = risk?.events?.slice(-8).reverse() ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Risk"
        description="Drawdown ladder, margin and leverage gauges, net directional exposure, and compliance."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <RiskGauge
          label="Margin Used"
          value={margin?.margin_pct ?? 0}
          cap={caps.margin}
        />
        <RiskGauge
          label="Leverage"
          value={margin?.leverage ?? 0}
          cap={caps.leverage}
          unit="×"
        />
        <RiskGauge
          label="Concentration"
          value={margin?.concentration_pct ?? 0}
          cap={caps.concentration}
          warningAt={caps.concentration * 0.9}
          nearCapMessage={
            (margin?.concentration_pct ?? 0) >= caps.concentration * 0.9
              ? "Approaching 40% concentration cap — new entries may be blocked"
              : undefined
          }
        />
        <RiskGauge
          label="Net Directional"
          value={margin?.net_directional_pct ?? 0}
          cap={caps.netDirectional}
        />
        <MarginLevelCard
          marginLevel={margin?.margin_level_pct}
          stopOut={caps.stopOut}
        />
      </div>

      {margin?.action && margin.action !== "normal" && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm text-amber-200">
          Margin action: <span className="font-mono uppercase">{margin.action}</span>
        </div>
      )}

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>What-if trade projection</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            Preview how a proposed order would affect leverage, concentration, net
            directional exposure, and drawdown gates — same check used by manual orders
            and the copilot. Sizing uses executable bid/ask prices with spread buffer.
          </p>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Symbol</label>
              <Input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="EUR/USD"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Direction</label>
              <div className="flex gap-2">
                {(["BUY", "SELL"] as const).map((d) => (
                  <Button
                    key={d}
                    type="button"
                    size="sm"
                    variant={direction === d ? "default" : "outline"}
                    onClick={() => setDirection(d)}
                  >
                    {d}
                  </Button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Volume (lots)</label>
              <Input
                value={volume}
                onChange={(e) => setVolume(e.target.value)}
                inputMode="decimal"
                placeholder="0.01"
              />
            </div>
          </div>
          {tradeParams == null ? (
            <p className="text-xs text-muted-foreground">Enter a valid symbol and volume.</p>
          ) : whatIfLoading && !whatIf ? (
            <Skeleton className="h-20 w-full" />
          ) : whatIf ? (
            <WhatIfPreview check={whatIf} />
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={tradeParams == null || whatIfLoading}
            onClick={() => void refetchWhatIf()}
          >
            Refresh projection
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="bg-panel border-border/60">
          <CardHeader>
            <CardTitle>Drawdown Ladder</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <div className="flex flex-col gap-2">
                {drawdownTiers.map((tier) => {
                  const active = risk?.dd_tier === tier.tier;
                  return (
                    <div
                      key={tier.tier}
                      className={cn(
                        "flex items-center justify-between rounded-md border px-3 py-2 text-sm",
                        active
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border text-muted-foreground",
                      )}
                    >
                      <span className="uppercase">{tier.label}</span>
                      <span className="font-mono">≤ {tier.maxPct}%</span>
                    </div>
                  );
                })}
                <div className="mt-2 text-xs text-muted-foreground">
                  Current: {risk ? formatPercent(risk.drawdown_pct) : "—"} drawdown
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-panel border-border/60">
          <CardHeader>
            <CardTitle>Compliance</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">
                    Discipline score
                  </span>
                  <span className="font-mono text-lg">
                    {risk?.discipline ?? 0}/100
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Sharpe</span>
                  <span className="font-mono">{risk?.sharpe.toFixed(2) ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">
                    Net directional
                  </span>
                  <span className="font-mono">
                    {margin?.net_directional_pct != null
                      ? formatPercent(margin.net_directional_pct)
                      : "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">
                    Compliance score
                  </span>
                  <Badge variant="signal">
                    {risk?.compliance_score ?? risk?.discipline ?? 0}
                  </Badge>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>Recent Risk Events</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : recentEvents.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Message</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentEvents.map((event, i) => (
                  <TableRow key={`${event.timestamp}-${event.type}-${i}`}>
                    <TableCell>{formatTimestamp(event.timestamp)}</TableCell>
                    <TableCell>{event.type}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          event.severity === "critical" ? "destructive" : "outline"
                        }
                      >
                        {event.severity}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-sans">{event.message}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">No recent risk events</p>
          )}
        </CardContent>
      </Card>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>Violation History</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : risk?.violations?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Message</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {risk.violations.map((v, i) => (
                  <TableRow key={`${v.timestamp}-${i}`}>
                    <TableCell>{formatTimestamp(v.timestamp)}</TableCell>
                    <TableCell>{v.type}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          v.severity === "critical" ? "destructive" : "success"
                        }
                      >
                        {v.severity}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-sans">{v.message}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">No violations recorded</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
