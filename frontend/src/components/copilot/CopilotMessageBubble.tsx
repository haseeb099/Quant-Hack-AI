import { AlertTriangle, Bot, User } from "lucide-react";
import type { CopilotMessage } from "@/hooks/useCopilotChat";
import { CopilotCitations } from "@/components/copilot/CopilotCitations";
import { CopilotVerdictBadge } from "@/components/copilot/CopilotVerdictBadge";
import { cn } from "@/lib/utils";

interface CopilotMessageBubbleProps {
  message: CopilotMessage;
}

export function CopilotMessageBubble({ message }: CopilotMessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex gap-2",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border",
          isUser
            ? "border-primary/30 bg-primary/10 text-primary"
            : "border-accent/30 bg-accent/10 text-accent",
        )}
      >
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </div>

      <div
        className={cn(
          "min-w-0 max-w-[85%] space-y-2 rounded-lg border px-3 py-2 text-sm",
          isUser
            ? "border-primary/25 bg-primary/10"
            : "border-border/70 bg-card/80",
        )}
      >
        <p className="whitespace-pre-wrap leading-relaxed text-foreground/95">
          {message.content || (message.streaming ? "Analyzing…" : "—")}
          {message.streaming && (
            <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-accent align-middle" />
          )}
        </p>

        {!isUser && message.analysis?.verdict && (
          <div className="flex flex-wrap items-center gap-2">
            <CopilotVerdictBadge
              verdict={message.analysis.verdict}
              confidence={message.analysis.confidence}
            />
            {message.analysis.symbol && (
              <span className="font-mono text-[10px] text-muted-foreground">
                {message.analysis.symbol}
              </span>
            )}
            {message.analysis.provider && message.analysis.provider !== "template" && (
              <span className="text-[10px] text-muted-foreground">
                via {message.analysis.provider}
              </span>
            )}
          </div>
        )}

        {!isUser && message.analysis?.risks && message.analysis.risks.length > 0 && (
          <ul className="space-y-1 text-xs text-amber-200/90">
            {message.analysis.risks.slice(0, 4).map((risk) => (
              <li key={risk} className="flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                <span>{risk}</span>
              </li>
            ))}
          </ul>
        )}

        {!isUser && message.citations && message.citations.length > 0 && (
          <CopilotCitations citations={message.citations} />
        )}

        {message.error && (
          <p className="text-xs text-destructive">{message.error}</p>
        )}
      </div>
    </div>
  );
}
