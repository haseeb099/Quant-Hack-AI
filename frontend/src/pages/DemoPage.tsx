import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Circle,
  ExternalLink,
  PlayCircle,
  Trophy,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  queryKeys,
  type DemoWalkthroughStep,
  type TechnologyPrizeCheck,
  type WalkthroughStepStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function StatusIcon({ status }: { status: WalkthroughStepStatus | TechnologyPrizeCheck["status"] }) {
  if (status === "pass") return <CheckCircle2 className="size-4 text-emerald-400" />;
  if (status === "fail") return <XCircle className="size-4 text-destructive" />;
  if (status === "warn") return <Circle className="size-4 text-amber-300" />;
  return <Circle className="size-4 text-muted-foreground" />;
}

function statusBadgeClass(status: string) {
  if (status === "pass") return "border-emerald-500/40 text-emerald-300";
  if (status === "fail") return "border-destructive/40 text-destructive";
  if (status === "warn") return "border-amber-500/40 text-amber-200";
  return "border-muted-foreground/40 text-muted-foreground";
}

function WalkthroughStepCard({ step }: { step: DemoWalkthroughStep }) {
  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-xs text-primary">
              {step.order}
            </span>
            <div>
              <CardTitle className="text-sm">{step.title}</CardTitle>
              <p className="mt-1 text-[11px] text-muted-foreground">{step.duration_sec}s segment</p>
            </div>
          </div>
          <Badge variant="outline" className={cn("text-[9px] uppercase", statusBadgeClass(step.status))}>
            {step.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <blockquote className="border-l-2 border-primary/40 pl-3 text-xs italic text-muted-foreground">
          {step.narration}
        </blockquote>
        <p className="text-xs text-muted-foreground">{step.detail}</p>
        <div className="flex flex-wrap gap-2">
          {step.dashboard_route && (
            <Link
              to={step.dashboard_route}
              className="inline-flex items-center gap-1 rounded border border-border/60 px-2 py-1 text-[11px] text-primary hover:bg-muted/50"
            >
              <PlayCircle className="size-3" />
              Open {step.dashboard_route}
            </Link>
          )}
          {step.command && (
            <code className="rounded bg-muted/50 px-2 py-1 font-mono text-[10px] text-muted-foreground">
              {step.command}
            </code>
          )}
          {step.doc_path && step.doc_available && (
            <span className="text-[10px] text-muted-foreground">📄 {step.doc_path}</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function PrizeCheckRow({ check }: { check: TechnologyPrizeCheck }) {
  return (
    <li className="flex items-start gap-2 rounded border border-border/50 px-3 py-2 text-xs">
      <StatusIcon status={check.status} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="font-medium">{check.label}</span>
            <span className="ml-2 text-[10px] uppercase text-muted-foreground">{check.sponsor}</span>
          </div>
          <Badge variant="outline" className={cn("text-[9px] uppercase", statusBadgeClass(check.status))}>
            {check.status}
          </Badge>
        </div>
        <p className="mt-0.5 text-muted-foreground">{check.message}</p>
        {check.file_path && (
          <p className="mt-1 font-mono text-[10px] text-primary/80">{check.file_path}</p>
        )}
        {check.remediation && check.status !== "pass" && (
          <p className="mt-1 text-[10px] text-amber-200/90">{check.remediation}</p>
        )}
      </div>
    </li>
  );
}

export function DemoPage() {
  const { data: walkthrough, isLoading: walkLoading } = useQuery({
    queryKey: queryKeys.demoWalkthrough,
    queryFn: api.getDemoWalkthrough,
  });

  const { data: prize, isLoading: prizeLoading } = useQuery({
    queryKey: queryKeys.technologyPrize,
    queryFn: api.getTechnologyPrizeChecklist,
    refetchInterval: 60_000,
  });

  if (walkLoading || prizeLoading) {
    return <Skeleton className="h-96 w-full" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <Trophy className="size-5 text-primary" />
            Technology Prize Demo
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            5-minute judge walkthrough · sponsor integration checklist
          </p>
        </div>
        {walkthrough && (
          <Badge
            variant="outline"
            className={cn(
              "font-mono text-[10px] uppercase",
              walkthrough.summary.ready
                ? "border-emerald-500/40 text-emerald-300"
                : "border-amber-500/40 text-amber-200",
            )}
          >
            Demo {walkthrough.summary.pass}/{walkthrough.summary.total} ready
          </Badge>
        )}
      </div>

      <Tabs defaultValue="walkthrough">
        <TabsList>
          <TabsTrigger value="walkthrough">Walkthrough</TabsTrigger>
          <TabsTrigger value="prize">Technology Prize</TabsTrigger>
        </TabsList>

        <TabsContent value="walkthrough" className="space-y-4">
          {walkthrough && (
            <>
              <Card className="border-primary/20 bg-primary/5">
                <CardContent className="py-4 text-sm">
                  <p className="font-medium">{walkthrough.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {walkthrough.audience} · {walkthrough.duration_label} total
                  </p>
                  <p className="mt-3 text-xs italic text-muted-foreground">
                    &ldquo;{walkthrough.closing_line}&rdquo;
                  </p>
                  <a
                    href="https://github.com/haseeb099/Quant-Hack-AI"
                    target="_blank"
                    rel="noreferrer"
                    className="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    GitHub repository
                    <ExternalLink className="size-3" />
                  </a>
                </CardContent>
              </Card>
              <div className="grid gap-4 lg:grid-cols-2">
                {walkthrough.steps.map((step) => (
                  <WalkthroughStepCard key={step.id} step={step} />
                ))}
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="prize" className="space-y-4">
          {prize && (
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm">Sponsor Integration Checklist</CardTitle>
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] uppercase",
                      prize.ready
                        ? "border-emerald-500/40 text-emerald-300"
                        : "border-amber-500/40 text-amber-200",
                    )}
                  >
                    {prize.ready ? "Prize ready" : "Review items"}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {prize.notion_doc} ·{" "}
                  <span className="text-emerald-400">{prize.summary.pass} pass</span>
                  {" · "}
                  <span className="text-amber-300">{prize.summary.warn} warn</span>
                  {" · "}
                  <span className="text-destructive">{prize.summary.fail} fail</span>
                </p>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {prize.checks.map((check) => (
                    <PrizeCheckRow key={check.code} check={check} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
