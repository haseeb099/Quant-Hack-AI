import { useQuery } from "@tanstack/react-query";
import { Brain } from "lucide-react";
import { api, queryKeys } from "@/lib/api";
import { agentDisplayName } from "@/lib/utils";

interface MemoryContextStripProps {
  symbol?: string | null;
}

export function MemoryContextStrip({ symbol }: MemoryContextStripProps) {
  const { data } = useQuery({
    queryKey: queryKeys.memoryContext(symbol ?? undefined),
    queryFn: () => api.getMemoryContext(symbol ?? undefined),
    enabled: Boolean(symbol),
    refetchInterval: 45_000,
  });

  if (!symbol || !data) return null;

  const semantic = data.semantic;
  if (!semantic?.best_agent && data.working_memory.length === 0) {
    return (
      <div className="border-b border-border/60 px-4 py-2 text-[11px] text-muted-foreground">
        <Brain className="mr-1 inline size-3" />
        Memory empty for {symbol} — analysis uses live state only.
      </div>
    );
  }

  return (
    <div className="border-b border-border/60 bg-background/30 px-4 py-2 text-[11px]">
      <Brain className="mr-1 inline size-3 text-accent" />
      {semantic?.best_agent ? (
        <>
          Semantic: <span className="text-foreground">{agentDisplayName(semantic.best_agent)}</span>
          <span className="text-muted-foreground">
            {" "}
            · n={semantic.sample_count} · {semantic.regime}
          </span>
        </>
      ) : (
        <span className="text-muted-foreground">
          {data.working_memory.length} trade(s) in working memory
        </span>
      )}
    </div>
  );
}
