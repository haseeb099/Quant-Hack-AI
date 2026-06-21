import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { MetricCard } from "@/components/shared/MetricCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, queryKeys, type Position } from "@/lib/api";
import {
  formatCurrency,
  formatTimestamp,
  pnlColorClass,
} from "@/lib/utils";

export function PositionsPage() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [modifyTarget, setModifyTarget] = useState<Position | null>(null);
  const [modifySl, setModifySl] = useState("");
  const [modifyTp, setModifyTp] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.positions,
    queryFn: api.getPositions,
    refetchInterval: 10_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.positions });
    void queryClient.invalidateQueries({ queryKey: queryKeys.account });
  };

  const closeMut = useMutation({
    mutationFn: (ticket: string) => api.closePosition(ticket),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const modifyMut = useMutation({
    mutationFn: ({ ticket, sl, tp }: { ticket: string; sl?: number; tp?: number }) =>
      api.modifyPosition(ticket, { sl, tp }),
    onSuccess: () => {
      setError(null);
      setModifyTarget(null);
      invalidate();
    },
    onError: (err: Error) => setError(err.message),
  });

  const positions = data?.positions ?? [];
  const totalPnl =
    data?.total_unrealized_pnl ??
    positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
  const totalExposure =
    data?.total_exposure ??
    positions.reduce((sum, p) => sum + Math.abs(p.size * p.entry), 0);

  function openModify(pos: Position) {
    setModifyTarget(pos);
    setModifySl(pos.sl != null ? String(pos.sl) : "");
    setModifyTp(pos.tp != null ? String(pos.tp) : "");
  }

  function confirmClose(pos: Position) {
    if (
      !window.confirm(
        `Close ${pos.direction.toUpperCase()} ${pos.size} ${pos.symbol}?`,
      )
    ) {
      return;
    }
    closeMut.mutate(pos.id);
  }

  function submitModify() {
    if (!modifyTarget) return;
    modifyMut.mutate({
      ticket: modifyTarget.id,
      sl: modifySl ? parseFloat(modifySl) : undefined,
      tp: modifyTp ? parseFloat(modifyTp) : undefined,
    });
  }

  const busy = closeMut.isPending || modifyMut.isPending;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Positions</h1>
        <p className="text-sm text-muted-foreground">
          Live open positions — close or modify SL/TP from the terminal
        </p>
      </div>

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

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
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((pos) => (
                  <TableRow key={pos.id}>
                    <TableCell className="font-medium">{pos.symbol}</TableCell>
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
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => openModify(pos)}
                        >
                          Modify
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={busy}
                          onClick={() => confirmClose(pos)}
                        >
                          Close
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Sheet open={modifyTarget != null} onOpenChange={(open) => !open && setModifyTarget(null)}>
        <SheetContent className="bg-panel border-border">
          <SheetHeader>
            <SheetTitle>Modify {modifyTarget?.symbol}</SheetTitle>
            <SheetDescription>
              Update stop loss and take profit for ticket {modifyTarget?.id}
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 flex flex-col gap-4">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Stop loss</label>
              <Input
                value={modifySl}
                onChange={(e) => setModifySl(e.target.value)}
                inputMode="decimal"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Take profit</label>
              <Input
                value={modifyTp}
                onChange={(e) => setModifyTp(e.target.value)}
                inputMode="decimal"
              />
            </div>
            <Button disabled={busy} onClick={submitModify}>
              Save changes
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
