import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { AgentVoteBar } from "@/components/shared/AgentVoteBar";
import { TradeDetailSheet } from "@/components/shared/TradeDetailSheet";
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
import { api, queryKeys, type Trade } from "@/lib/api";
import {
  formatCurrency,
  formatTimestamp,
  pnlColorClass,
} from "@/lib/utils";

export function TradesPage() {
  const [symbolFilter, setSymbolFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.trades({
      symbol: symbolFilter || undefined,
      status: statusFilter || undefined,
    }),
    queryFn: () =>
      api.getTrades({
        limit: 50,
        symbol: symbolFilter || undefined,
        status: statusFilter || undefined,
      }),
    refetchInterval: 20_000,
  });

  const trades = data?.trades ?? [];

  async function openTradeDetail(trade: Trade) {
    try {
      const full = await api.getTrade(trade.id);
      setSelectedTrade(full);
    } catch {
      setSelectedTrade(trade);
    }
    setSheetOpen(true);
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Trade Journal</h1>
        <p className="text-sm text-muted-foreground">
          Full history with agent votes and orchestrator reasoning
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Filter by symbol"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="max-w-xs"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="">All statuses</option>
          <option value="executed">Executed</option>
          <option value="simulated">Simulated</option>
          <option value="decision">Decision</option>
          <option value="error">Error</option>
        </select>
      </div>

      <Card className="bg-panel border-border/60">
        <CardHeader>
          <CardTitle>
            Trades {data ? `(${trades.length} / ${data.total})` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-48 w-full" />
          ) : trades.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No trades found
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Time</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>P&amp;L</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade) => {
                  const expanded = expandedId === trade.id;
                  return (
                    <Fragment key={trade.id}>
                      <TableRow key={trade.id}>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setExpandedId(expanded ? null : trade.id)
                            }
                          >
                            {expanded ? <ChevronDown /> : <ChevronRight />}
                          </Button>
                        </TableCell>
                        <TableCell>{formatTimestamp(trade.timestamp)}</TableCell>
                        <TableCell>{trade.symbol}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{trade.direction}</Badge>
                        </TableCell>
                        <TableCell>{trade.status}</TableCell>
                        <TableCell
                          className={
                            trade.pnl != null ? pnlColorClass(trade.pnl) : ""
                          }
                        >
                          {trade.pnl != null ? formatCurrency(trade.pnl) : "—"}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openTradeDetail(trade)}
                          >
                            Details
                          </Button>
                        </TableCell>
                      </TableRow>
                      {expanded && (
                        <TableRow key={`${trade.id}-detail`}>
                          <TableCell colSpan={7}>
                            <div className="flex flex-col gap-3 py-2 pl-8">
                              {trade.reasoning && (
                                <p className="text-sm text-muted-foreground">
                                  {trade.reasoning}
                                </p>
                              )}
                              {trade.agent_votes?.map((vote) => (
                                <AgentVoteBar
                                  key={vote.agent}
                                  vote={vote}
                                  compact
                                />
                              ))}
                              {!trade.reasoning &&
                                !trade.agent_votes?.length && (
                                  <p className="text-sm text-muted-foreground">
                                    No expanded details — open sheet for full
                                    record
                                  </p>
                                )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <TradeDetailSheet
        trade={selectedTrade}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      />
    </div>
  );
}
