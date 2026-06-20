import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { AgentVoteBar } from "@/components/shared/AgentVoteBar";
import type { Trade } from "@/lib/api";
import { cn, formatCurrency, formatTimestamp, pnlColorClass } from "@/lib/utils";

interface TradeDetailSheetProps {
  trade: Trade | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function TradeDetailSheet({
  trade,
  open,
  onOpenChange,
}: TradeDetailSheetProps) {
  if (!trade) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle className="font-mono">{trade.symbol}</SheetTitle>
          <SheetDescription>
            {formatTimestamp(trade.timestamp)} · Ticket {trade.id}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-4 overflow-y-auto pr-2">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{trade.direction.toUpperCase()}</Badge>
            <Badge variant="outline">{trade.status}</Badge>
            {trade.regime && <Badge variant="signal">{trade.regime}</Badge>}
            {trade.session && <Badge variant="secondary">{trade.session}</Badge>}
          </div>

          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Entry</dt>
              <dd className="font-mono">{trade.entry}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Size</dt>
              <dd className="font-mono">{trade.size}</dd>
            </div>
            {trade.exit != null && (
              <div>
                <dt className="text-muted-foreground">Exit</dt>
                <dd className="font-mono">{trade.exit}</dd>
              </div>
            )}
            {trade.pnl != null && (
              <div>
                <dt className="text-muted-foreground">P&amp;L</dt>
                <dd className={cn("font-mono", pnlColorClass(trade.pnl))}>
                  {formatCurrency(trade.pnl)}
                </dd>
              </div>
            )}
            {trade.slippage != null && (
              <div>
                <dt className="text-muted-foreground">Slippage</dt>
                <dd className="font-mono">{trade.slippage} pips</dd>
              </div>
            )}
            {trade.latency_ms != null && (
              <div>
                <dt className="text-muted-foreground">Latency</dt>
                <dd className="font-mono">{trade.latency_ms} ms</dd>
              </div>
            )}
          </dl>

          {trade.reasoning && (
            <>
              <Separator />
              <div>
                <h4 className="mb-2 text-sm font-medium">Orchestrator Reasoning</h4>
                <p className="text-sm text-muted-foreground">{trade.reasoning}</p>
              </div>
            </>
          )}

          {trade.agent_votes && trade.agent_votes.length > 0 && (
            <>
              <Separator />
              <div className="flex flex-col gap-3">
                <h4 className="text-sm font-medium">Agent Votes</h4>
                {trade.agent_votes.map((vote) => (
                  <AgentVoteBar key={vote.agent} vote={vote} />
                ))}
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
