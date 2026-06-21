import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, Play, Timer, XCircle } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys, type VerificationCheck } from "@/lib/api";
import { cn } from "@/lib/utils";

function CheckRow({ check }: { check: VerificationCheck }) {
  const Icon = check.passed ? CheckCircle2 : XCircle;
  return (
    <li className="flex items-start gap-2 rounded border border-border/50 px-2.5 py-2 text-xs">
      <Icon className={cn("size-3.5 shrink-0", check.passed ? "text-emerald-400" : "text-destructive")} />
      <div className="min-w-0 flex-1">
        <div className="font-medium">{check.label}</div>
        {check.detail && <p className="mt-0.5 text-muted-foreground">{check.detail}</p>}
      </div>
    </li>
  );
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "Live";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function CompetitionDayPanel() {
  const queryClient = useQueryClient();
  const [fullSuite, setFullSuite] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.operatorVerification,
    queryFn: api.getOperatorVerification,
    refetchInterval: 60_000,
  });

  const runMutation = useMutation({
    mutationFn: () => api.runOperatorVerification({ confirm: true, quick: !fullSuite }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.operatorVerification });
      queryClient.invalidateQueries({ queryKey: queryKeys.operatorRunbook });
    },
  });

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (!data) return null;

  const session = data.session;
  const checks = data.checks ?? [];

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Timer className="size-4 text-primary" />
            Competition Day Automation
          </CardTitle>
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] uppercase",
              data.ready
                ? "border-emerald-500/40 text-emerald-300"
                : data.has_run
                  ? "border-amber-500/40 text-amber-200"
                  : "border-muted-foreground/40 text-muted-foreground",
            )}
          >
            {data.has_run ? (data.ready ? "Verified" : "Issues") : "Not run"}
          </Badge>
        </div>
        {session && (
          <p className="text-xs text-muted-foreground">
            {session.label}
            {!session.launched && session.seconds_to_launch > 0 && (
              <span className="ml-2 font-mono">
                · launch in {formatCountdown(session.seconds_to_launch)}
              </span>
            )}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" />
            ) : (
              <Play className="mr-1.5 size-3.5" />
            )}
            Run verification
          </Button>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={fullSuite}
              onChange={(e) => setFullSuite(e.target.checked)}
              className="rounded border-border"
            />
            Full pytest suite
          </label>
        </div>

        {runMutation.isError && (
          <p className="text-xs text-destructive">
            {(runMutation.error as Error).message}
          </p>
        )}

        {data.last_run_at && (
          <p className="text-[11px] text-muted-foreground">
            Last run {data.last_mode ?? "quick"} · {data.passed}/{data.total} pass ·{" "}
            {new Date(data.last_run_at).toLocaleString()}
          </p>
        )}

        {checks.length > 0 ? (
          <ul className="space-y-1.5">
            {checks.map((check) => (
              <CheckRow key={check.code} check={check} />
            ))}
          </ul>
        ) : (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Circle className="size-3.5" />
            No verification run yet — click Run verification before competition launch.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
