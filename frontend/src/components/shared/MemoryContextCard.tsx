import { useQuery } from "@tanstack/react-query";
import { Brain, Database, History } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { agentDisplayName } from "@/lib/utils";

interface MemoryContextCardProps {
  symbol?: string;
  compact?: boolean;
}

export function MemoryContextCard({ symbol, compact = false }: MemoryContextCardProps) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.memoryContext(symbol),
    queryFn: () => api.getMemoryContext(symbol),
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return <Skeleton className={compact ? "h-24 w-full" : "h-48 w-full"} />;
  }

  const semantic = data?.semantic;
  const working = data?.working_memory ?? [];
  const similar = data?.similar_setups ?? [];

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className={compact ? "pb-2" : undefined}>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Brain className="size-4 text-accent" />
          Agentic Memory
          {data && (
            <Badge variant="outline" className="ml-auto font-mono text-[10px]">
              {data.layers.episodic} episodic
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-md border border-border/60 bg-background/40 p-2">
            <div className="flex items-center gap-1 text-[10px] uppercase text-muted-foreground">
              <History className="size-3" />
              Working
            </div>
            <div className="mt-1 font-mono text-lg">
              {data?.layers.working ?? 0}
              <span className="text-xs text-muted-foreground"> / 3</span>
            </div>
          </div>
          <div className="rounded-md border border-border/60 bg-background/40 p-2">
            <div className="flex items-center gap-1 text-[10px] uppercase text-muted-foreground">
              <Database className="size-3" />
              Semantic
            </div>
            <div className="mt-1 font-mono text-lg">{data?.layers.semantic_keys ?? 0}</div>
          </div>
          <div className="rounded-md border border-border/60 bg-background/40 p-2">
            <div className="text-[10px] uppercase text-muted-foreground">Session</div>
            <div className="mt-1 font-mono text-sm capitalize">{data?.session ?? "—"}</div>
          </div>
        </div>

        {semantic?.best_agent ? (
          <div className="rounded-md border border-primary/25 bg-primary/5 px-3 py-2">
            <div className="text-xs text-muted-foreground">
              Semantic best for {semantic.symbol ?? symbol ?? "context"}
              {semantic.regime ? ` · ${semantic.regime}` : ""}
            </div>
            <div className="mt-1 font-medium">
              {agentDisplayName(semantic.best_agent)}
              <span className="ml-2 font-mono text-xs text-muted-foreground">
                n={semantic.sample_count} · score{" "}
                {(semantic.best_agent_score ?? 0).toFixed(2)}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            {semantic?.sample_count
              ? `Collecting samples (${semantic.sample_count}/${semantic.min_samples ?? 5} min for semantic ranking)`
              : "No semantic ranking yet — closed trades feed episodic → semantic layers."}
          </p>
        )}

        {!compact && working.length > 0 && (
          <div>
            <div className="mb-1 text-xs text-muted-foreground">Recent working memory</div>
            <ul className="space-y-1">
              {working.map((t) => (
                <li
                  key={t.trade_id}
                  className="flex justify-between rounded border border-border/50 px-2 py-1 font-mono text-xs"
                >
                  <span>
                    {t.symbol} {t.direction} · {agentDisplayName(t.agent)}
                  </span>
                  <span className={t.r_multiple != null && t.r_multiple > 0 ? "text-positive" : "text-negative"}>
                    R {t.r_multiple?.toFixed(2) ?? "—"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!compact && similar.length > 0 && (
          <div>
            <div className="mb-1 text-xs text-muted-foreground">Similar setups</div>
            <ul className="space-y-1">
              {similar.map((t) => (
                <li key={`sim-${t.trade_id}`} className="text-xs text-muted-foreground">
                  {t.symbol} {t.regime} · R {t.r_multiple?.toFixed(2) ?? "—"}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
