import { Badge } from "@/components/ui/badge";
import type { CopilotVerdict } from "@/lib/copilot";
import { cn } from "@/lib/utils";

const VERDICT_STYLES: Record<
  CopilotVerdict,
  { label: string; className: string }
> = {
  ALLOW: {
    label: "Allow",
    className: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  },
  WAIT: {
    label: "Wait",
    className: "border-amber-500/40 bg-amber-500/15 text-amber-200",
  },
  BLOCK: {
    label: "Block",
    className: "border-destructive/40 bg-destructive/15 text-destructive",
  },
  REFUSE: {
    label: "Refuse",
    className: "border-orange-500/40 bg-orange-500/15 text-orange-200",
  },
};

interface CopilotVerdictBadgeProps {
  verdict: CopilotVerdict;
  confidence?: number;
  className?: string;
}

export function CopilotVerdictBadge({
  verdict,
  confidence,
  className,
}: CopilotVerdictBadgeProps) {
  const style = VERDICT_STYLES[verdict];
  return (
    <Badge
      variant="outline"
      className={cn("font-mono text-[10px] uppercase tracking-wide", style.className, className)}
    >
      {style.label}
      {confidence != null && confidence > 0 && (
        <span className="ml-1 opacity-80">{(confidence * 100).toFixed(0)}%</span>
      )}
    </Badge>
  );
}
