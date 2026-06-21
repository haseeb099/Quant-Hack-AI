import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, ExternalLink, Notebook } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

function taskStatusClass(status: string) {
  const s = status.toLowerCase();
  if (s.includes("done") || s.includes("complete") || s.includes("✅")) {
    return "border-emerald-500/40 text-emerald-300";
  }
  if (s.includes("progress")) {
    return "border-primary/40 text-primary";
  }
  return "border-muted-foreground/40 text-muted-foreground";
}

export function NotionSyncPanel() {
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: queryKeys.notionStatus,
    queryFn: api.getNotionStatus,
    refetchInterval: 60_000,
  });

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: queryKeys.notionTasks,
    queryFn: () => api.getNotionTasks(20),
    enabled: Boolean(status?.enabled && status?.databases?.tasks),
    refetchInterval: 120_000,
  });

  if (statusLoading) {
    return <Skeleton className="h-56 w-full" />;
  }

  if (!status) return null;

  const dbs = status.databases;
  const stats = status.sync_stats ?? {};

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Notebook className="size-4 text-primary" />
            Notion Sync
          </CardTitle>
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] uppercase",
              status.enabled
                ? "border-emerald-500/40 text-emerald-300"
                : "border-muted-foreground/40 text-muted-foreground",
            )}
          >
            {status.enabled ? "Active" : "Off"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          {(
            [
              ["Journal", dbs.trade_journal],
              ["Agents", dbs.agent_performance],
              ["Risk", dbs.risk_events],
              ["Tasks", dbs.tasks],
            ] as const
          ).map(([label, on]) => (
            <div
              key={label}
              className="flex items-center gap-1.5 rounded border border-border/50 px-2 py-1.5"
            >
              {on ? (
                <CheckCircle2 className="size-3.5 text-emerald-400" />
              ) : (
                <Circle className="size-3.5 text-muted-foreground" />
              )}
              <span>{label}</span>
            </div>
          ))}
        </div>

        {Object.keys(stats).length > 0 && (
          <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
            {Object.entries(stats).map(([channel, val]) => {
              const bucket = val as { success?: number; failure?: number };
              return (
                <div key={channel} className="rounded border border-border/40 px-2 py-1">
                  <span className="capitalize">{channel.replace(/_/g, " ")}</span>
                  <span className="ml-1 font-mono text-foreground">
                    {bucket.success ?? 0} ok · {bucket.failure ?? 0} err
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {tasksLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : tasksData?.tasks?.length ? (
          <div>
            <div className="mb-2 text-xs text-muted-foreground">
              Command Center tasks ({tasksData.count})
            </div>
            <ul className="max-h-40 space-y-1 overflow-y-auto">
              {tasksData.tasks.map((task) => (
                <li
                  key={task.id}
                  className="flex items-center justify-between gap-2 rounded border border-border/40 px-2 py-1.5 text-xs"
                >
                  <span className="min-w-0 truncate">
                    {task.step != null && (
                      <span className="mr-1 font-mono text-muted-foreground">
                        S{task.step}
                      </span>
                    )}
                    {task.title}
                  </span>
                  <div className="flex shrink-0 items-center gap-1">
                    <Badge variant="outline" className={cn("text-[9px]", taskStatusClass(task.status))}>
                      {task.status}
                    </Badge>
                    {task.url && (
                      <a
                        href={task.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-primary hover:underline"
                        aria-label="Open in Notion"
                      >
                        <ExternalLink className="size-3" />
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            {status.enabled
              ? "No tasks loaded — configure NOTION_TASKS_DS_ID or check API permissions."
              : "Set NOTION_API_KEY and database IDs to enable sync."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
