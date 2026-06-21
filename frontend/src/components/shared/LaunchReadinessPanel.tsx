import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Clock, Rocket, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

type CheckStatus = "pass" | "warn" | "fail" | "skip";

function StatusIcon({ status }: { status: CheckStatus }) {
  if (status === "pass") return <CheckCircle2 className="size-4 text-emerald-400" />;
  if (status === "fail") return <XCircle className="size-4 text-destructive" />;
  if (status === "warn") return <Circle className="size-4 text-amber-300" />;
  return <Circle className="size-4 text-muted-foreground" />;
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "Live";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function LaunchReadinessPanel() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.launchReadiness,
    queryFn: api.getLaunchReadiness,
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (!data) return null;

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Rocket className="size-4 text-primary" />
            Competition Launch Readiness
          </CardTitle>
          <Badge
            variant="outline"
            className={cn(
              "font-mono text-[10px] uppercase",
              data.ready
                ? "border-emerald-500/40 text-emerald-300"
                : "border-amber-500/40 text-amber-200",
            )}
          >
            {data.ready ? "GO" : "NOT READY"}
          </Badge>
        </div>
        {!data.launched && data.launch_in_seconds > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="size-3.5" />
            Round 1 launch in {formatCountdown(data.launch_in_seconds)}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="mb-3 flex gap-3 text-[11px] text-muted-foreground">
          <span className="text-emerald-400">{data.summary.pass} pass</span>
          <span className="text-amber-300">{data.summary.warn} warn</span>
          <span className="text-destructive">{data.summary.fail} fail</span>
        </div>
        <ul className="max-h-56 space-y-1.5 overflow-y-auto">
          {data.checks.map((check) => (
            <li
              key={check.code}
              className="flex items-start gap-2 rounded-md border border-border/50 px-2.5 py-2 text-xs"
            >
              <StatusIcon status={check.status} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{check.label}</span>
                  <span className="font-mono text-[10px] uppercase text-muted-foreground">
                    {check.status}
                  </span>
                </div>
                <p className="mt-0.5 text-muted-foreground">{check.message}</p>
                {check.remediation && check.status !== "pass" && (
                  <p className="mt-1 text-[10px] text-primary/90">{check.remediation}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
