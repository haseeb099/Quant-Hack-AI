"""Symbol analysis — grounded verdicts with optional Doubleword narrative."""

from __future__ import annotations

from typing import Any

from src.copilot.context import CopilotContextBuilder, resolve_symbol_from_message
from src.copilot.models import AgentVoteSummary, DataCitation, SymbolAnalysisResponse
from src.copilot.provider import enhance_summary_with_llm
from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate
from src.utils.logger import instrument_span
from src.web.runtime_state import read_state


class CopilotAnalyzer:
    """Read-only analysis pipeline for copilot API."""

    def __init__(self) -> None:
        self.context_builder = CopilotContextBuilder()
        self.gate = get_pre_trade_gate()

    @instrument_span("quantai.copilot.analyze_symbol")
    def analyze_symbol(
        self,
        symbol: str,
        volume: float = 0.01,
        direction: str = "BUY",
        state: dict[str, Any] | None = None,
        use_llm: bool = True,
    ) -> SymbolAnalysisResponse:
        state = state or read_state()
        context, citations, refusal = self.context_builder.build(symbol, state)

        if refusal:
            return SymbolAnalysisResponse(
                symbol=symbol,
                verdict="REFUSE",
                confidence=0.0,
                summary=refusal,
                data_citations=citations,
                provider="template",
                refused=True,
                refusal_reason=refusal,
            )

        signals = context["agent_signals"]
        market = context["market"]
        risk = context["risk"]

        trade_check = self.gate.evaluate_from_state(
            state,
            TradeCheckRequest(
                symbol=symbol,
                direction=direction,
                volume=volume,
                price=float(market.get("mid") or 0) or None,
            ),
        )
        citations.append(DataCitation(
            source="pre_trade_gate",
            field="allowed",
            value=trade_check.allowed,
            timestamp=context["timestamp"],
        ))

        votes = [
            AgentVoteSummary(
                agent=s.agent_name,
                direction=s.direction.value,
                confidence=round(s.confidence, 3),
                reasoning=s.reasoning,
            )
            for s in signals
        ]

        actionable = [s for s in signals if s.is_actionable]
        buy_votes = sum(1 for s in actionable if s.direction.value == "BUY")
        sell_votes = sum(1 for s in actionable if s.direction.value == "SELL")

        verdict = "WAIT"
        confidence = 0.0
        if not trade_check.allowed:
            verdict = "BLOCK"
        elif not context["symbol_session_ok"]:
            verdict = "WAIT"
            confidence = 0.35
        elif buy_votes > sell_votes and buy_votes >= 2:
            verdict = "ALLOW" if direction == "BUY" else "WAIT"
            confidence = min(0.95, max(s.confidence for s in actionable if s.direction.value == "BUY"))
        elif sell_votes > buy_votes and sell_votes >= 2:
            verdict = "ALLOW" if direction == "SELL" else "WAIT"
            confidence = min(0.95, max(s.confidence for s in actionable if s.direction.value == "SELL"))
        else:
            verdict = "WAIT"
            confidence = max((s.confidence for s in signals), default=0.0) * 0.5

        risks = self._collect_risks(context, trade_check)
        strategy = {
            "regime": market.get("regime"),
            "semantic_best_agent": context["semantic"].get("best_agent"),
            "semantic_win_rate": context["semantic"].get("win_rate"),
            "preferred_session_agents": context["session_agents"],
            "last_orchestrator_decision": context.get("last_decision"),
            "consensus": {"buy": buy_votes, "sell": sell_votes, "actionable": len(actionable)},
        }

        template_summary = self._template_summary(
            symbol=symbol,
            verdict=verdict,
            context=context,
            trade_check=trade_check,
            votes=votes,
        )

        summary = template_summary
        provider = "template"
        if use_llm:
            summary, provider = enhance_summary_with_llm(context, template_summary)

        return SymbolAnalysisResponse(
            symbol=symbol,
            verdict=verdict,  # type: ignore[arg-type]
            confidence=round(confidence, 3),
            summary=summary,
            risks=risks,
            strategy=strategy,
            session={
                "name": context["session"],
                "symbol_ok": context["symbol_session_ok"],
                "preferred_instruments": context["session_preferred"],
            },
            market=market,
            agent_consensus=votes,
            trade_check=trade_check.to_dict(),
            data_citations=citations,
            provider=provider,
            refused=False,
        )

    def chat(
        self,
        message: str,
        symbol: str | None = None,
        state: dict[str, Any] | None = None,
        use_llm: bool = True,
    ) -> tuple[str, SymbolAnalysisResponse | None]:
        """Route chat message — returns (reply text, optional symbol analysis)."""
        state = state or read_state()
        resolved = resolve_symbol_from_message(message, symbol)

        if not resolved:
            account = state.get("account", {})
            risk = state.get("risk", {})
            reply = (
                f"Account equity ${float(account.get('equity', 0)):,.2f} · "
                f"drawdown tier {risk.get('dd_tier', 'normal')} · "
                f"discipline {risk.get('discipline', 100)}. "
                "Mention a symbol (e.g. XAU/USD or Gold) for full analysis."
            )
            return reply, None

        analysis = self.analyze_symbol(resolved, state=state, use_llm=use_llm)
        return analysis.summary, analysis

    @staticmethod
    def _collect_risks(context: dict[str, Any], trade_check: Any) -> list[str]:
        risks: list[str] = []
        risk = context.get("risk", {})
        if risk.get("dd_tier") not in (None, "normal"):
            risks.append(f"Drawdown tier: {risk.get('dd_tier')} ({float(risk.get('drawdown_pct', 0)):.1%})")
        if not context.get("symbol_session_ok"):
            risks.append(f"Outside preferred session window for {context['symbol']}")
        for w in trade_check.warnings:
            risks.append(w.message)
        for b in trade_check.blockers:
            risks.append(b.message)
        market = context.get("market", {})
        if market.get("tick_age_ms") and float(market["tick_age_ms"]) > 3000:
            risks.append(f"Tick age {float(market['tick_age_ms']) / 1000:.1f}s — execution risk")
        return risks

    @staticmethod
    def _template_summary(
        symbol: str,
        verdict: str,
        context: dict[str, Any],
        trade_check: Any,
        votes: list[AgentVoteSummary],
    ) -> str:
        market = context["market"]
        mid = market.get("mid")
        price_str = f"{float(mid):.5f}" if mid is not None else "unavailable"
        vote_line = ", ".join(f"{v.agent} {v.direction} ({v.confidence:.0%})" for v in votes) or "no actionable votes"

        parts = [
            f"{symbol} at {price_str} · regime {market.get('regime')} · session {context.get('session')}.",
            f"Agent consensus: {vote_line}.",
            f"Verdict: {verdict}.",
        ]
        if not trade_check.allowed and trade_check.blockers:
            parts.append(f"Blocked: {trade_check.blockers[0].message}")
        elif context.get("symbol_session_ok") is False:
            parts.append("Session filter suggests waiting for a preferred window.")
        if context.get("open_positions_on_symbol"):
            parts.append("You already have an open position on this symbol.")
        return " ".join(parts)
