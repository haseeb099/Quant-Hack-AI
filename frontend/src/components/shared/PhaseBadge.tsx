import { Badge } from "@/components/ui/badge";
import type { DrawdownTier } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PhaseBadgeProps {
  phase: string;
  ddTier?: DrawdownTier;
  blockedSymbols?: string[];
}

/** Mirrors config/phases.yaml blocked_symbols per round (competition rules). */
const PHASE_BLOCKED_SYMBOLS: Record<string, string[]> = {
  round1: ["XRP/USD", "BAR/USD", "BTC/USD", "ETH/USD", "SOL/USD"],
  round2: ["XRP/USD", "BAR/USD"],
  round3: [],
  finals: [],
};

const tierStyles: Record<DrawdownTier, string> = {
  normal: "border-signal/40 bg-signal/10 text-signal",
  elevated: "border-border bg-muted/50 text-muted-foreground",
  warning: "border-warning/40 bg-warning/10 text-warning",
  critical: "border-destructive/40 bg-destructive/10 text-destructive",
  emergency: "border-destructive bg-destructive/20 text-destructive animate-pulse",
};

export function PhaseBadge({ phase, ddTier, blockedSymbols }: PhaseBadgeProps) {
  const blocked = blockedSymbols?.length
    ? blockedSymbols
    : PHASE_BLOCKED_SYMBOLS[phase] ?? [];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-wide">
        {phase.replace(/_/g, " ")}
      </Badge>
      {ddTier && (
        <Badge
          variant="outline"
          className={cn("text-[10px] uppercase tracking-wide", tierStyles[ddTier])}
        >
          DD {ddTier}
        </Badge>
      )}
      {blocked.length > 0 && (
        <Badge
          variant="outline"
          className="max-w-[220px] truncate text-[10px] font-normal normal-case tracking-normal text-muted-foreground"
          title={`Phase-blocked symbols (by design): ${blocked.join(", ")}`}
        >
          Blocked: {blocked.join(", ")}
        </Badge>
      )}
    </div>
  );
}
