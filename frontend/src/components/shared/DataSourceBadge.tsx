import { Badge } from "@/components/ui/badge";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

const STYLES: Record<string, string> = {
  live: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  simulate: "border-cyan-500/50 bg-cyan-500/10 text-cyan-300",
  demo: "border-amber-500/50 bg-amber-500/10 text-amber-300",
};

export function DataSourceBadge({ status }: { status?: StatusResponse }) {
  const source = status?.data_source ?? status?.mode ?? "demo";
  const stale = status?.state_stale;

  return (
    <div className="flex items-center gap-2">
      <Badge
        variant="outline"
        className={cn("uppercase font-mono text-[10px]", STYLES[source] ?? STYLES.demo)}
      >
        {source}
      </Badge>
      {stale && (
        <Badge variant="destructive" className="text-[10px]">
          Stale data
        </Badge>
      )}
    </div>
  );
}
