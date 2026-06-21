import { ChevronDown, Database } from "lucide-react";
import { useState } from "react";
import type { DataCitation } from "@/lib/copilot";
import { cn } from "@/lib/utils";

function formatCitationValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

interface CopilotCitationsProps {
  citations: DataCitation[];
  className?: string;
}

export function CopilotCitations({ citations, className }: CopilotCitationsProps) {
  const [open, setOpen] = useState(false);
  if (!citations.length) return null;

  return (
    <div className={cn("rounded-md border border-border/60 bg-background/50", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left text-[11px] text-muted-foreground hover:text-foreground"
      >
        <span className="inline-flex items-center gap-1.5">
          <Database className="size-3.5" />
          {citations.length} grounded source{citations.length === 1 ? "" : "s"}
        </span>
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="max-h-40 space-y-1 overflow-y-auto border-t border-border/50 px-2.5 py-2">
          {citations.map((c) => (
            <li
              key={`${c.source}-${c.field}-${String(c.value)}`}
              className="font-mono text-[10px] leading-relaxed text-muted-foreground"
            >
              <span className="text-primary">{c.source}</span>
              <span className="text-foreground/70"> · {c.field}</span>
              <span className="block truncate text-foreground/90">
                {formatCitationValue(c.value)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
