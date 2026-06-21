import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys, type MarketHealth } from "@/lib/api";
import { cn, formatPercent, pnlColorClass } from "@/lib/utils";

const categoryColors: Record<string, string> = {
  forex: "border-l-primary",
  crypto: "border-l-success",
  metals: "border-l-amber-400",
};

const healthColors: Record<MarketHealth, string> = {
  green: "bg-success",
  amber: "bg-amber-400",
  red: "bg-destructive",
};

const impactColors: Record<string, string> = {
  tier_1: "bg-destructive/20 text-destructive",
  tier_2: "bg-amber-400/20 text-amber-500",
  tier_3: "bg-muted text-muted-foreground",
};

function formatPrice(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  if (value >= 1000) return value.toFixed(2);
  if (value >= 1) return value.toFixed(4);
  return value.toFixed(5);
}

function HealthDot({ health }: { health?: MarketHealth | null }) {
  const level = health ?? "amber";
  return (
    <span
      className={cn("inline-block size-2 rounded-full", healthColors[level])}
      title={`Market health: ${level}`}
    />
  );
}

function SentimentBar({ score }: { score?: number | null }) {
  if (score == null) return <span className="text-muted-foreground">—</span>;
  const pct = ((score + 1) / 2) * 100;
  const color =
    score > 0.2 ? "bg-success" : score < -0.2 ? "bg-destructive" : "bg-muted-foreground";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-muted">
        <div className={cn("h-1.5 rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn("font-mono text-xs", pnlColorClass(score * 100))}>
        {score > 0 ? "+" : ""}
        {score.toFixed(2)}
      </span>
    </div>
  );
}

export function MarketPage() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: api.getInstruments,
    refetchInterval: 30_000,
  });

  const { data: intel, isLoading: intelLoading } = useQuery({
    queryKey: queryKeys.intelligence,
    queryFn: api.getIntelligenceSnapshot,
    refetchInterval: 60_000,
  });

  const instruments = data?.instruments ?? [];
  const events = intel?.upcoming_events ?? [];
  const macro = intel?.macro;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Market</h1>
        <p className="text-sm text-muted-foreground">
          Live prices, sentiment, economic events, and regime across 15 instruments
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="bg-panel border-border/60 lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Upcoming Economic Events</CardTitle>
          </CardHeader>
          <CardContent>
            {intelLoading ? (
              <Skeleton className="h-24" />
            ) : events.length === 0 ? (
              <p className="text-sm text-muted-foreground">No events in the next 8 hours</p>
            ) : (
              <div className="flex flex-col gap-2">
                {events.map((event) => (
                  <div
                    key={`${event.name}-${event.scheduled_at}`}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <Badge className={impactColors[event.impact] ?? impactColors.tier_3}>
                        {event.impact.replace("tier_", "T")}
                      </Badge>
                      <span>{event.name}</span>
                      <span className="text-muted-foreground">({event.currency})</span>
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">
                      {new Date(event.scheduled_at).toLocaleTimeString("en-GB", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-panel border-border/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Macro Regime</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {intelLoading ? (
              <Skeleton className="h-20" />
            ) : (
              <>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Bias</span>
                  <Badge variant="outline">{macro?.bias ?? "neutral"}</Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">USD</span>
                  <Badge variant="outline">{macro?.usd_strength ?? "neutral"}</Badge>
                </div>
                {macro?.fear_greed != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Fear & Greed</span>
                    <span className="font-mono">{macro.fear_greed}</span>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">{macro?.notes ?? "—"}</p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 15 }).map((_, i) => (
            <Skeleton key={i} className="h-52" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {instruments.map((inst) => (
            <Card
              key={inst.symbol}
              className={cn(
                "border-l-4 bg-panel border-border/60",
                categoryColors[inst.category] ?? "border-l-muted-foreground",
              )}
            >
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <HealthDot health={inst.market_health} />
                    <CardTitle className="font-mono text-sm">{inst.symbol}</CardTitle>
                  </div>
                  <Badge variant={inst.session_active ? "signal" : "secondary"}>
                    {inst.session_active ? "Active" : "Closed"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs">
                  <div>
                    <span className="text-muted-foreground">Bid </span>
                    {formatPrice(inst.bid)}
                  </div>
                  <div className="text-right">
                    <span className="text-muted-foreground">Ask </span>
                    {formatPrice(inst.ask)}
                  </div>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Spread</span>
                  <span className="font-mono">{formatPrice(inst.spread)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Change</span>
                  <span className={cn("font-mono", pnlColorClass(inst.change_pct ?? 0))}>
                    {inst.change_pct != null ? formatPercent(inst.change_pct) : "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Tick age</span>
                  <span className="font-mono">
                    {inst.tick_age_ms != null
                      ? `${(inst.tick_age_ms / 1000).toFixed(1)}s`
                      : "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Regime</span>
                  <Badge variant="outline">{inst.last_regime}</Badge>
                </div>
                <div>
                  <span className="text-muted-foreground text-xs">Sentiment</span>
                  <SentimentBar score={inst.sentiment_score} />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
