import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface RiskGaugeProps {
  label: string;
  value: number;
  cap: number;
  unit?: string;
  warningAt?: number;
  nearCapMessage?: string;
  className?: string;
}

export function RiskGauge({
  label,
  value,
  cap,
  unit = "%",
  warningAt,
  nearCapMessage,
  className,
}: RiskGaugeProps) {
  const pct = Math.min(100, cap > 0 ? (value / cap) * 100 : 0);
  const warnThreshold = warningAt ?? cap * 0.9;
  const nearCap = cap > 0 && value >= warnThreshold && value < cap;
  const atCap = value >= cap;
  const color = atCap
    ? "bg-destructive"
    : nearCap
      ? "bg-warning"
      : value >= cap * 0.75
        ? "bg-warning"
        : "bg-primary";

  return (
    <Card className={cn("bg-panel border-border/60", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-end justify-between gap-2">
          <span className="font-mono text-xl font-semibold tabular-nums">
            {value.toFixed(1)}
            {unit}
          </span>
          <span className="text-[11px] text-muted-foreground">
            cap {cap}
            {unit}
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted/80">
          <div
            className={cn("h-full rounded-full transition-all duration-500", color)}
            style={{ width: `${pct}%` }}
          />
        </div>
        {atCap && (
          <p className="mt-2 text-[11px] font-medium text-destructive">
            At cap — new entries in this direction may be blocked
          </p>
        )}
        {nearCap && !atCap && (
          <p className="mt-2 text-[11px] text-warning">
            {nearCapMessage ??
              `Within ${(cap - value).toFixed(1)}${unit} of cap (${pct.toFixed(0)}% utilized)`}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
