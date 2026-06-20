import { cn } from "@/lib/utils";

interface LiveIndicatorProps {
  connected: boolean;
  label?: string;
}

export function LiveIndicator({ connected, label = "Live" }: LiveIndicatorProps) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span
        className={cn(
          "size-2 rounded-full",
          connected ? "bg-primary animate-pulse-live" : "bg-destructive",
        )}
        aria-hidden
      />
      <span className="font-mono uppercase tracking-wider">
        {connected ? label : "Offline"}
      </span>
    </div>
  );
}
