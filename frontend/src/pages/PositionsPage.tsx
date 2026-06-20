import { useQuery } from "@tanstack/react-query";
import { MetricCard } from "@/components/shared/MetricCard";
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
import { api, queryKeys } from "@/lib/api";
import {
  formatCurrency,
  formatTimestamp,
  pnlColorClass,
} from "@/lib/utils";

export function PositionsPage() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.positions,
    queryFn: api.getPositions,
    refetchInterval: 10_000,
  });

  const positions = data?.positions ?? [];
  const totalPnl =
    data?.total_unrealized_pnl ??
    positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
  const totalExposure =
    data?.total_exposure ??
    positions.reduce((sum, p) => sum + Math.abs(p.size * p.entry), 0);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Positions</h1>
        <p className="text-sm text-muted-foreground">
          Open positions with SL/TP and unrealized P&amp;L
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <MetricCard
          title="Open Positions"
          loading={isLoading}
          value={positions.length}
        />
        <MetricCard
          title="Total Exposure"
          loading={isLoading}
          value={formatCurrency(totalExposure, true)}
        />
        <MetricCard
          title="Unrealized P&L"
          loading={isLoading}
          value={formatCurrency(totalPnl)}
          valueClassName={pnlColorClass(totalPnl)}
        />
      </div>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>Open Positions</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-48 w-full" />
          ) : positions.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No open positions
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>SL</TableHead>
                  <TableHead>TP</TableHead>
                  <TableHead>P&amp;L</TableHead>
                  <TableHead>Opened</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((pos) => (
                  <TableRow key={pos.id}>
                    <TableCell>{pos.symbol}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          pos.direction === "long" ? "signal" : "destructive"
                        }
                      >
                        {pos.direction.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell>{pos.size}</TableCell>
                    <TableCell>{pos.entry}</TableCell>
                    <TableCell>{pos.sl ?? "—"}</TableCell>
                    <TableCell>{pos.tp ?? "—"}</TableCell>
                    <TableCell className={pnlColorClass(pos.unrealized_pnl)}>
                      {formatCurrency(pos.unrealized_pnl)}
                    </TableCell>
                    <TableCell>{formatTimestamp(pos.opened_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
