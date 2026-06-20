import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface MetricCardProps {
  title: string;
  value: ReactNode;
  subtitle?: ReactNode;
  loading?: boolean;
  className?: string;
  valueClassName?: string;
}

export function MetricCard({
  title,
  value,
  subtitle,
  loading,
  className,
  valueClassName,
}: MetricCardProps) {
  return (
    <Card className={cn("bg-panel border-border/60", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {loading ? (
          <Skeleton className="h-8 w-28" />
        ) : (
          <div className={cn("font-mono text-2xl font-semibold", valueClassName)}>
            {value}
          </div>
        )}
        {subtitle && !loading && (
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );
}
