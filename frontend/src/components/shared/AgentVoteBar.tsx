import { Badge } from "@/components/ui/badge";
import type { AgentVote } from "@/lib/api";
import { agentDisplayName, cn } from "@/lib/utils";

interface AgentVoteBarProps {
  vote: AgentVote;
  compact?: boolean;
}

const voteColors: Record<string, string> = {
  buy: "bg-primary",
  sell: "bg-destructive",
  hold: "bg-muted-foreground",
  skip: "bg-secondary",
};

export function AgentVoteBar({ vote, compact }: AgentVoteBarProps) {
  const pct = Math.round(vote.confidence * 100);

  return (
    <div className={cn("flex flex-col gap-1", compact && "gap-0.5")}>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">{agentDisplayName(vote.agent)}</span>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="font-mono uppercase">
            {vote.vote}
          </Badge>
          <span className="font-mono text-muted-foreground">{pct}%</span>
        </div>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            voteColors[vote.vote] ?? "bg-muted-foreground",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {vote.reasoning && !compact && (
        <p className="text-xs text-muted-foreground line-clamp-2">
          {vote.reasoning}
        </p>
      )}
    </div>
  );
}
