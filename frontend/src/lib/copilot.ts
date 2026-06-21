import { getApiAuthHeaders } from "@/lib/api";

export type CopilotVerdict = "ALLOW" | "WAIT" | "BLOCK" | "REFUSE";

export interface DataCitation {
  source: string;
  field: string;
  value: unknown;
  timestamp?: string | null;
}

export interface CopilotAnalysis {
  symbol: string;
  verdict: CopilotVerdict;
  confidence: number;
  summary: string;
  risks: string[];
  strategy: Record<string, unknown>;
  session: Record<string, unknown>;
  market: Record<string, unknown>;
  agent_consensus: Array<{
    agent: string;
    direction: string;
    confidence: number;
    reasoning: string;
  }>;
  trade_check: Record<string, unknown>;
  data_citations: DataCitation[];
  provider: string;
  refused: boolean;
  refusal_reason?: string | null;
}

export type CopilotSSEEvent =
  | { type: "start"; message: string }
  | { type: "citations"; data_citations: DataCitation[] }
  | { type: "text"; content: string }
  | { type: "refusal"; reason?: string; summary: string }
  | {
      type: "analysis";
      verdict: CopilotVerdict;
      confidence: number;
      risks: string[];
      trade_check: Record<string, unknown>;
      provider: string;
    }
  | { type: "done"; analysis: CopilotAnalysis | null }
  | { type: "error"; message: string };

export interface CopilotChatRequest {
  message: string;
  symbol?: string | null;
}

function parseSSELine(line: string): CopilotSSEEvent | null {
  if (!line.startsWith("data: ")) return null;
  try {
    return JSON.parse(line.slice(6)) as CopilotSSEEvent;
  } catch {
    return null;
  }
}

export async function streamCopilotChat(
  request: CopilotChatRequest,
  onEvent: (event: CopilotSSEEvent) => void,
  options?: { signal?: AbortSignal },
): Promise<CopilotAnalysis | null> {
  const res = await fetch("/api/copilot/chat", {
    method: "POST",
    headers: getApiAuthHeaders(),
    body: JSON.stringify({
      message: request.message,
      symbol: request.symbol ?? undefined,
    }),
    signal: options?.signal,
  });

  if (!res.ok) {
    let detail = `Copilot request failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    onEvent({ type: "error", message: detail });
    throw new Error(detail);
  }

  if (!res.body) {
    throw new Error("Copilot stream unavailable");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalAnalysis: CopilotAnalysis | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const event = parseSSELine(trimmed);
      if (!event) continue;
      onEvent(event);
      if (event.type === "done") {
        finalAnalysis = event.analysis;
      }
    }
  }

  return finalAnalysis;
}

export async function analyzeSymbol(params: {
  symbol: string;
  direction?: "BUY" | "SELL";
  volume?: number;
  useLlm?: boolean;
}): Promise<CopilotAnalysis> {
  const search = new URLSearchParams({
    symbol: params.symbol,
    direction: params.direction ?? "BUY",
    volume: String(params.volume ?? 0.01),
    use_llm: String(params.useLlm ?? true),
  });
  const res = await fetch(`/api/copilot/analyze-symbol?${search.toString()}`, {
    method: "POST",
    headers: getApiAuthHeaders(),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Analyze failed (${res.status})`);
  }
  return res.json() as Promise<CopilotAnalysis>;
}
