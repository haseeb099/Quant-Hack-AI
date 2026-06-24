import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type MetricAccent = "default" | "positive" | "negative" | "warning" | "primary";

interface MetricCardProps {
  title: string;
  value: ReactNode;
  subtitle?: ReactNode;
  loading?: boolean;
  className?: string;
  valueClassName?: string;
  accent?: MetricAccent;
}

const accentStyles: Record<MetricAccent, string> = {
  default: "border-border/60",
  positive: "border-positive/30 shadow-[inset_0_1px_0_0_rgba(52,211,153,0.15)]",
  negative: "border-negative/30 shadow-[inset_0_1px_0_0_rgba(248,113,113,0.15)]",
  warning: "border-warning/30 shadow-[inset_0_1px_0_0_rgba(251,191,36,0.12)]",
  primary: "border-primary/25 shadow-[inset_0_1px_0_0_rgba(56,189,248,0.12)]",
};

export function MetricCard({
  title,
  value,
  subtitle,
  loading,
  className,
  valueClassName,
  accent = "default",
}: MetricCardProps) {
  return (
    <Card
      className={cn(
        "bg-panel transition-colors hover:border-border",
        accentStyles[accent],
        className,
      )}
    >
      <CardHeader className="pb-2">
        <CardTitle className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {loading ? (
          <Skeleton className="h-8 w-28 skeleton-shimmer" />
        ) : (
          <div className={cn("font-mono text-2xl font-semibold tabular-nums", valueClassName)}>
            {value}
          </div>
        )}
        {subtitle && !loading && (
          <div className="mt-1.5 text-xs text-muted-foreground">{subtitle}</div>
        )}
      </CardContent>
    </Card>
  );
}
