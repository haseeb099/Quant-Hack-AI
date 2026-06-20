import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface RiskGaugeProps {
  label: string;
  value: number;
  cap: number;
  unit?: string;
  warningAt?: number;
  className?: string;
}

export function RiskGauge({
  label,
  value,
  cap,
  unit = "%",
  warningAt,
  className,
}: RiskGaugeProps) {
  const pct = Math.min(100, (value / cap) * 100);
  const warnThreshold = warningAt ?? cap * 0.85;
  const color =
    value >= cap
      ? "bg-destructive"
      : value >= warnThreshold
        ? "bg-success"
        : "bg-primary";

  return (
    <Card className={cn("bg-panel border-border/60", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-end justify-between gap-2">
          <span className="font-mono text-xl font-semibold">
            {value.toFixed(1)}
            {unit}
          </span>
          <span className="text-xs text-muted-foreground">
            cap {cap}
            {unit}
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full transition-all", color)}
            style={{ width: `${pct}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
