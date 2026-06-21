import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { formatTimestamp } from "@/lib/utils";

export function EngineHealthPanel() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.engineHealth,
    queryFn: api.getEngineHealth,
    refetchInterval: 10_000,
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;

  return (
    <Card className="bg-panel border-border/60">
      <CardHeader>
        <CardTitle className="text-base">Engine Health</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm">
        <Row label="Data source" value={data?.data_source ?? "—"} />
        <Row label="Engine" value={data?.engine_running ? "Running" : "Stopped"} />
        <Row label="MT5 bridge" value={data?.mt5_connected ? "Connected" : "Offline"} />
        <Row label="Last cycle" value={formatTimestamp(data?.last_cycle_at)} />
        <Row label="Tick age" value={data?.last_tick_age_ms != null ? `${Math.round(data.last_tick_age_ms)}ms` : "—"} />
        {data?.zmq_last_error && (
          <p className="font-mono text-xs text-destructive">{data.zmq_last_error}</p>
        )}
        {data?.state_stale && (
          <Badge variant="destructive">State snapshot is stale</Badge>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-right">{value}</span>
    </div>
  );
}
