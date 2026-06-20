import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

const categoryColors: Record<string, string> = {
  forex: "border-l-primary",
  crypto: "border-l-success",
  metals: "border-l-amber-400",
};

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
          15 competition instruments — session and regime status
        </p>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 15 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
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
                <div className="flex items-center justify-between">
                  <CardTitle className="font-mono text-sm">{inst.symbol}</CardTitle>
                  <Badge variant={inst.session_active ? "signal" : "secondary"}>
                    {inst.session_active ? "Active" : "Closed"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Category</span>
                  <span className="capitalize">{inst.category}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Bias</span>
                  <span className="capitalize">{inst.bias}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Allocation</span>
                  <span className="font-mono">
                    {(inst.allocation * 100).toFixed(0)}%
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
