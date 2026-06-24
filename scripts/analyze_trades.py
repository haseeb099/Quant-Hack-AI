"""Quick trade journal analysis."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    closed: list[dict] = []
    opens: list[dict] = []
    for line in Path("logs/trades.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        st = r.get("status")
        if st == "closed":
            closed.append(r)
        elif st == "ok":
            opens.append(r)

    by_ticket: dict[int, dict] = {}
    for r in closed:
        t = r.get("ticket") or (r.get("extra") or {}).get("ticket")
        if t is None:
            continue
        ticket = int(t)
        prev = by_ticket.get(ticket)
        ep = float(r.get("entry_price") or (r.get("extra") or {}).get("entry_price") or 0)
        if prev is None or (ep > 0 and float(prev.get("entry_price") or 0) <= 0):
            by_ticket[ticket] = r

    pnls = [float(r.get("pnl") or (r.get("extra") or {}).get("pnl") or 0) for r in by_ticket.values()]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    print(f"Closed trades (deduped): {len(by_ticket)}")
    print(f"Wins: {len(wins)} sum {sum(wins):.2f}")
    print(f"Losses: {len(losses)} sum {sum(losses):.2f}")
    print(f"Net PnL: {sum(pnls):.2f}")
    print()
    for r in sorted(by_ticket.values(), key=lambda x: x.get("timestamp", "")):
        ts = str(r.get("timestamp", ""))[:19]
        print(
            f"{ts} ticket={r.get('ticket')} {r.get('symbol')} {r.get('direction')} "
            f"pnl={r.get('pnl')} entry={r.get('entry_price')}"
        )
    print()
    print(f"Recent opens: {len(opens)}")
    for r in opens[-8:]:
        ts = str(r.get("timestamp", ""))[:19]
        print(
            f"{ts} {r.get('symbol')} {r.get('direction')} size={r.get('size')} "
            f"ticket={r.get('ticket')}"
        )


if __name__ == "__main__":
    main()
