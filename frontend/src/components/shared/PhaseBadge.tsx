import { Badge } from "@/components/ui/badge";
import type { DrawdownTier } from "@/lib/api";

interface PhaseBadgeProps {
  phase: string;
  ddTier?: DrawdownTier;
}

const tierVariants: Record<
  DrawdownTier,
  "default" | "secondary" | "success" | "destructive" | "signal"
> = {
  normal: "signal",
  elevated: "secondary",
  warning: "success",
  critical: "destructive",
  emergency: "destructive",
};

export function PhaseBadge({ phase, ddTier }: PhaseBadgeProps) {
  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" className="font-mono uppercase">
        {phase}
      </Badge>
      {ddTier && (
        <Badge variant={tierVariants[ddTier]} className="uppercase">
          DD {ddTier}
        </Badge>
      )}
    </div>
  );
}
