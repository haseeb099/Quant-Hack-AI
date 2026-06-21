import { useQuery } from "@tanstack/react-query";
import { Cloud, Container, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, queryKeys } from "@/lib/api";
import { cn } from "@/lib/utils";

export function DeployStatusCard() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.northflankDeploy,
    queryFn: api.getNorthflankDeploy,
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return <Skeleton className="h-56 w-full" />;
  }

  if (!data) return null;

  const envEntries = Object.entries(data.env_configured);

  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Cloud className="size-4 text-primary" />
            Northflank Deploy
          </CardTitle>
          <Badge variant="outline" className="text-[10px] uppercase">
            {data.platform}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="space-y-2">
          {data.services.map((svc) => (
            <div
              key={svc.name}
              className="flex items-start justify-between gap-2 rounded border border-border/50 px-2.5 py-2 text-xs"
            >
              <div className="flex items-start gap-2">
                <Container className="mt-0.5 size-3.5 text-muted-foreground" />
                <div>
                  <div className="font-medium">{svc.name}</div>
                  <div className="text-muted-foreground">{svc.dockerfile}</div>
                  {svc.public && (
                    <div className="text-[10px] text-muted-foreground">port {svc.port}</div>
                  )}
                </div>
              </div>
              <Badge
                variant="outline"
                className={cn(
                  "text-[9px] uppercase",
                  svc.ready
                    ? "border-emerald-500/40 text-emerald-300"
                    : "border-amber-500/40 text-amber-200",
                )}
              >
                {svc.ready ? "ready" : "build"}
              </Badge>
            </div>
          ))}
        </div>

        <div>
          <div className="mb-2 text-xs text-muted-foreground">Environment secrets</div>
          <div className="grid grid-cols-2 gap-1.5">
            {envEntries.map(([key, on]) => (
              <div
                key={key}
                className="flex items-center justify-between rounded border border-border/40 px-2 py-1 text-[10px]"
              >
                <span className="truncate font-mono">{key}</span>
                <span className={on ? "text-emerald-400" : "text-muted-foreground"}>
                  {on ? "set" : "—"}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Terminal className="size-3" />
            Smoke commands
          </div>
          <ul className="space-y-1 font-mono text-[10px] text-muted-foreground">
            {data.smoke_commands.map((cmd) => (
              <li key={cmd} className="truncate rounded bg-muted/40 px-2 py-1">
                {cmd}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}
