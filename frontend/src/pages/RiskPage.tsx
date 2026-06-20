import { useQuery } from "@tanstack/react-query";
import { RiskGauge } from "@/components/shared/RiskGauge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, DRAWDOWN_TIERS, queryKeys, RISK_CAPS } from "@/lib/api";
import { cn, formatPercent, formatTimestamp } from "@/lib/utils";

export function RiskPage() {
  const { data: risk, isLoading } = useQuery({
    queryKey: queryKeys.risk,
    queryFn: api.getRisk,
    refetchInterval: 10_000,
  });

  const margin = risk?.margin_state;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Risk</h1>
        <p className="text-sm text-muted-foreground">
          Drawdown ladder, margin/leverage gauges, and compliance
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <RiskGauge
          label="Margin Used"
          value={margin?.margin_pct ?? 0}
          cap={RISK_CAPS.margin}
        />
        <RiskGauge
          label="Leverage"
          value={margin?.leverage ?? 0}
          cap={RISK_CAPS.leverage}
          unit="×"
        />
        <RiskGauge
          label="Concentration"
          value={(margin?.concentration_pct ?? 0) * 100}
          cap={RISK_CAPS.concentration}
        />
      </div>

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
                {DRAWDOWN_TIERS.map((tier) => {
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
