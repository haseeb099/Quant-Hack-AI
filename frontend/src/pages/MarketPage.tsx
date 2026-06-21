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

export function MarketPage() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: api.getInstruments,
    refetchInterval: 30_000,
  });

  const instruments = data?.instruments ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Market</h1>
        <p className="text-sm text-muted-foreground">
          Live bid/ask, spread, and freshness across 15 competition instruments
        </p>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 15 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
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
                    <CardTitle className="font-mono text-sm">
                      {inst.symbol}
                    </CardTitle>
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
                  <span
                    className={cn(
                      "font-mono",
                      pnlColorClass(inst.change_pct ?? 0),
                    )}
                  >
                    {inst.change_pct != null
                      ? formatPercent(inst.change_pct)
                      : "—"}
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
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
