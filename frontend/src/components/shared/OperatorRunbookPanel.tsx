import { useQuery } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, Circle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys, type OperatorStepStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

function StepIcon({ status }: { status: OperatorStepStatus }) {
  if (status === "pass") return <CheckCircle2 className="size-3.5 shrink-0 text-emerald-400" />;
  if (status === "fail") return <XCircle className="size-3.5 shrink-0 text-destructive" />;
  if (status === "warn") return <Circle className="size-3.5 shrink-0 text-amber-300" />;
  return <Circle className="size-3.5 shrink-0 text-muted-foreground" />;
}

function statusBadgeClass(status: OperatorStepStatus) {
  if (status === "pass") return "border-emerald-500/40 text-emerald-300";
  if (status === "fail") return "border-destructive/40 text-destructive";
  if (status === "warn") return "border-amber-500/40 text-amber-200";
  return "border-muted-foreground/40 text-muted-foreground";
}

export function OperatorRunbookPanel() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.operatorRunbook,
    queryFn: api.getOperatorRunbook,
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return <Skeleton className="h-72 w-full" />;
  }

  if (!data) return null;

  const preflight = data.preflight;

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <BookOpen className="size-4 text-primary" />
            Competition Operator Runbook
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-[10px] uppercase">
              {data.mode} · {data.phase}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "font-mono text-[10px] uppercase",
                data.launch_readiness
                  ? "border-emerald-500/40 text-emerald-300"
                  : "border-amber-500/40 text-amber-200",
              )}
            >
              {data.launch_readiness ? "Launch GO" : "Launch pending"}
            </Badge>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Preflight {preflight.passed}/{preflight.total} · updated {data.timestamp_bst}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          {data.phases.map((phase) => (
            <div key={phase.id} className="rounded-lg border border-border/50 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold">{phase.title}</h3>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {phase.summary.pass}/{phase.summary.total} pass
                </span>
              </div>
              <ul className="space-y-1.5">
                {phase.steps.map((step) => (
                  <li
                    key={step.id}
                    className="flex items-start gap-2 rounded border border-border/40 px-2 py-1.5 text-xs"
                  >
                    <StepIcon status={step.status} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{step.label}</span>
                        <Badge
                          variant="outline"
                          className={cn("text-[9px] uppercase", statusBadgeClass(step.status))}
                        >
                          {step.status}
                        </Badge>
                      </div>
                      {step.detail && (
                        <p className="mt-0.5 text-muted-foreground">{step.detail}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
