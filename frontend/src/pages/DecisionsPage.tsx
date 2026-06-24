import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Radio } from "lucide-react";
import { AgentVoteBar } from "@/components/shared/AgentVoteBar";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { RiskGauge } from "@/components/shared/RiskGauge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  api,
  queryKeys,
  resolveRiskCaps,
  type CycleDecision,
  type CycleEvent,
  type PositionMonitor,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/utils";

type FilterMode = "all" | "executed" | "skipped" | "analyzed";

function outcomeLabel(d: CycleDecision): string {
  if (d.executed) return "Executed";
  if (d.scan_stage === "event_gate") return "Event gate";
  if (d.scan_stage === "blocked") return "Blocked";
  if (d.reason === "HOLD decision") return "HOLD";
  if (d.action !== "HOLD") return "Skipped";
  return "No setup";
}

function outcomeVariant(d: CycleDecision): "signal" | "destructive" | "secondary" | "outline" {
  if (d.executed) return "signal";
  if (d.scan_stage === "event_gate") return "destructive";
  if (d.reason?.includes("need") && d.reason?.includes("agreeing")) return "outline";
  return "secondary";
}

function consensusLabel(d: CycleDecision): string {
  if (d.consensus_required == null) return "—";
  const got = d.consensus_agreeing ?? 0;
  return `${got}/${d.consensus_required}`;
}

function eventTypeLabel(type: string): string {
  switch (type) {
    case "entry":
      return "Entry";
    case "partial_close":
      return "Partial close";
    case "close":
      return "Full close";
    default:
      return type;
  }
}

export function DecisionsPage() {
  const [filter, setFilter] = useState<FilterMode>("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.lastCycle,
    queryFn: api.getLastCycle,
    refetchInterval: 10_000,
  });

  const { data: risk, isLoading: riskLoading } = useQuery({
    queryKey: queryKeys.risk,
    queryFn: api.getRisk,
    refetchInterval: 10_000,
  });

  const caps = resolveRiskCaps(risk);
  const margin = risk?.margin_state;
  const decisions = data?.decisions ?? [];
  const events = data?.cycle_events ?? [];
  const monitors = data?.position_monitor ?? [];

  const filtered = useMemo(() => {
    return decisions.filter((d) => {
      if (filter === "executed") return d.executed;
      if (filter === "skipped") return !d.executed;
      if (filter === "analyzed") return d.scan_stage === "analyzed" || d.scan_stage === "executed";
      return true;
    });
  }, [decisions, filter]);

  const executedCount = decisions.filter((d) => d.executed).length;
  const skippedCount = decisions.filter((d) => !d.executed).length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Scan log"
        description="Full per-symbol scan from the latest engine cycle — entries, skips, exits, and open-position rationale."
      />

      {isLoading ? (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : decisions.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="No scan data yet"
          description="Wait for the next engine cycle to see the full symbol scan log."
        />
      ) : (
        <>
          <Card className="bg-panel border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Activity className="h-4 w-4 text-primary" />
                Latest cycle
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">Last scan</p>
                <p className="font-mono">{formatTimestamp(data?.last_cycle_at ?? "")}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Next scan</p>
                <p className="font-mono">{formatTimestamp(data?.next_cycle_at ?? "")}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Symbols scanned</p>
                <p>
                  {data?.symbols_processed ?? 0} processed · {data?.symbols_attempted ?? 0} attempted
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Outcomes</p>
                <p>
                  <span className="text-primary">{executedCount} executed</span>
                  {" · "}
                  <span className="text-muted-foreground">{skippedCount} skipped/hold</span>
                </p>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            {riskLoading ? (
              <Skeleton className="h-28 md:col-span-2" />
            ) : risk ? (
              <>
                <RiskGauge
                  label="Net Directional (portfolio)"
                  value={margin?.net_directional_pct ?? 0}
                  cap={caps.netDirectional}
                />
                <RiskGauge
                  label="Concentration (largest position)"
                  value={margin?.concentration_pct ?? 0}
                  cap={caps.concentration}
                />
              </>
            ) : null}
          </div>

          {monitors.length > 0 && (
            <Card className="bg-panel border-border/60">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Open positions — hold / exit logic</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {monitors.map((m) => (
                  <MonitorSummary key={m.ticket} monitor={m} />
                ))}
              </CardContent>
            </Card>
          )}

          {events.length > 0 && (
            <Card className="bg-panel border-border/60">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Cycle events</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {events.map((ev: CycleEvent, i) => (
                  <div
                    key={`${ev.type}-${ev.symbol}-${i}`}
                    className="rounded-md border border-border/50 px-3 py-2 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={ev.type === "entry" ? "signal" : "outline"}>
                        {eventTypeLabel(ev.type)}
                      </Badge>
                      <span className="font-mono font-medium">{ev.symbol}</span>
                      {ev.direction && (
                        <Badge variant="outline">{ev.direction}</Badge>
                      )}
                      {ev.ticket != null && (
                        <span className="text-xs text-muted-foreground">#{ev.ticket}</span>
                      )}
                    </div>
                    {ev.reason && (
                      <p className="mt-1 text-xs text-muted-foreground">{ev.reason}</p>
                    )}
                    {ev.type === "entry" && ev.consensus_agreeing != null && (
                      <p className="mt-1 text-xs text-primary">
                        Consensus {ev.consensus_agreeing}/{ev.consensus_required} · conf{" "}
                        {((ev.confidence ?? 0) * 100).toFixed(0)}%
                        {ev.size != null ? ` · ${ev.size} lots` : ""}
                      </p>
                    )}
                    {ev.type === "partial_close" && ev.closed_volume != null && (
                      <p className="mt-1 text-xs text-warning">
                        Closed {ev.closed_volume} lots — {ev.reason}
                      </p>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <Card className="bg-panel border-border/60">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 pb-2">
              <CardTitle className="text-sm font-medium">Symbol scan log</CardTitle>
              <div className="flex flex-wrap gap-2">
                {(["all", "analyzed", "executed", "skipped"] as FilterMode[]).map((mode) => (
                  <ButtonChip
                    key={mode}
                    active={filter === mode}
                    onClick={() => setFilter(mode)}
                    label={mode}
                  />
                ))}
              </div>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Signal</TableHead>
                    <TableHead>Outcome</TableHead>
                    <TableHead>Consensus</TableHead>
                    <TableHead>Conf</TableHead>
                    <TableHead>Tier</TableHead>
                    <TableHead>Regime</TableHead>
                    <TableHead>Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((d) => (
                    <Fragment key={d.symbol}>
                      <TableRow
                        className="cursor-pointer hover:bg-muted/30"
                        onClick={() =>
                          setExpanded(expanded === d.symbol ? null : d.symbol)
                        }
                      >
                        <TableCell className="font-mono font-medium">{d.symbol}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{d.action}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={outcomeVariant(d)}>{outcomeLabel(d)}</Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {consensusLabel(d)}
                          {d.agreeing_agents && d.agreeing_agents.length > 0 && (
                            <span className="block text-muted-foreground">
                              {d.agreeing_agents.join(", ")}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {d.orchestrator_confidence != null
                            ? `${(d.orchestrator_confidence * 100).toFixed(0)}%`
                            : "—"}
                          {d.min_confidence_required != null && (
                            <span className="block text-muted-foreground">
                              min {(d.min_confidence_required * 100).toFixed(0)}%
                            </span>
                          )}
                        </TableCell>
                        <TableCell>{d.symbol_tier ?? "—"}</TableCell>
                        <TableCell className="text-xs">{d.regime ?? "—"}</TableCell>
                        <TableCell className="max-w-xs text-xs text-muted-foreground">
                          {d.event_gate ?? d.reason ?? d.orchestrator_output ?? "—"}
                        </TableCell>
                      </TableRow>
                      {expanded === d.symbol && (
                        <TableRow>
                          <TableCell colSpan={8} className="bg-muted/10">
                            <div className="flex flex-col gap-3 py-2">
                              {d.features_summary && (
                                <p className="text-sm">
                                  <span className="text-muted-foreground">Features: </span>
                                  {d.features_summary}
                                </p>
                              )}
                              {d.orchestrator_output && (
                                <p className="text-sm text-muted-foreground">
                                  {d.orchestrator_output}
                                </p>
                              )}
                              {d.agent_votes && d.agent_votes.length > 0 && (
                                <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
                                  {d.agent_votes.map((vote, i) => (
                                    <AgentVoteBar
                                      key={`${vote.agent}-${i}`}
                                      vote={vote}
                                      compact
                                    />
                                  ))}
                                </div>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function MonitorSummary({ monitor: m }: { monitor: PositionMonitor }) {
  return (
    <div className="rounded-md border border-border/50 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-medium">{m.symbol}</span>
        <Badge variant={m.r_multiple >= 0 ? "signal" : "destructive"}>
          {m.r_multiple >= 0 ? "+" : ""}
          {m.r_multiple.toFixed(2)}R
        </Badge>
        {m.would_close[0] ? (
          <span className="text-xs text-destructive">Close: {m.would_close[0]}</span>
        ) : m.keep_open[0] ? (
          <span className="text-xs text-muted-foreground">Hold: {m.keep_open[0]}</span>
        ) : null}
      </div>
      {m.watch.length > 0 && (
        <p className="mt-1 text-xs text-warning">Watch: {m.watch[0]}</p>
      )}
    </div>
  );
}

function ButtonChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs capitalize transition-colors ${
        active
          ? "bg-primary text-primary-foreground"
          : "bg-muted text-muted-foreground hover:bg-muted/80"
      }`}
    >
      {label}
    </button>
  );
}
