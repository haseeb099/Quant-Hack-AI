# MT5 Integration & Pre-Competition Testing

QuantAI uses **two MT5 interfaces**:

| Interface | Purpose | Used by |
|-----------|---------|---------|
| **MT5 MCP server** | Cursor AI can inspect account, symbols, and market data during development | Cursor agent (`.cursor/mcp.json`) |
| **ZeroMQ bridge** | Live trade execution during competition rounds | `python main.py --mode live` |

Both require the MetaTrader 5 terminal to be running on Windows with **Algorithmic Trading** enabled (Tools → Options → Expert Advisors).

---

## 1. One-time setup

### Install dependencies

```bash
pip install -r requirements.txt
pip install metatrader5-mcp MetaTrader5
```

### Configure credentials

```bash
cp .env.example .env
```

Fill in your competition account:

```env
MT5_LOGIN=your_account_number
MT5_PASSWORD=your_password
MT5_SERVER=YourCompetitionServer
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

### ZeroMQ bridge (live trading)

1. Install [mql-zmq](https://github.com/dingmaotu/mql-zmq) in MT5 — **MT5 build 5100+ requires the [Furious-Production-LTD fork](https://github.com/Furious-Production-LTD/mql-zmq)** (original repo fails with `char[]`/`uchar[]` errors)
2. Compile `mql5/DWX_ZeroMQ_Server.mq5`
3. Start it as an **MQL5 Service** (Navigator → Services → Start)
4. Confirm ports **32768–32770** are listening

### Cursor MCP server (development)

Project config lives in `.cursor/mcp.json`. It launches `scripts/run_mt5_mcp.py`, which reads credentials from `.env`.

**Important:** The MCP config uses an absolute `python.exe` path and project `cwd` so Cursor can find Python even when it overrides `PATH`. If MCP fails to start on your machine, update those paths in `.cursor/mcp.json` to match your Python install and project folder.

After editing `.env` or MCP config:

1. Open **Cursor Settings → MCP**
2. Enable **metatrader5**
3. Reload the window if the server does not connect

In chat you can ask the agent to use MT5 MCP tools, for example:

- "Get my MT5 account balance and equity"
- "List open positions"
- "Fetch the last 50 M15 bars for BTCUSD"

---

## 2. Pre-competition test checklist

Run before Round 1 launch (21 Jun 22:00 BST):

```bash
# Full checklist: MT5 Python API + ZeroMQ bridge
python scripts/test_mt5_connection.py

# ZeroMQ only (if MCP credentials not set yet)
python scripts/test_mt5_connection.py --zmq-only

# Include one offline decision cycle (no real orders)
python scripts/test_mt5_connection.py --with-cycle
```

### Expected results

| Check | What it validates |
|-------|-------------------|
| MT5 initialize + login | Terminal running, credentials correct |
| 15/15 competition symbols | All instruments visible in MarketWatch |
| Historical bars | Data feed working for feature engine |
| ZeroMQ ACCOUNT | Live bridge connected |
| ZeroMQ DATA | OHLCV pipeline for agents |
| Simulation cycle | Full Python stack without MT5 orders |

### Unit tests (no MT5 required)

```bash
pytest tests/ -v
```

---

## 3. Dry-run before live competition

Use this sequence the evening before launch:

| Time (BST) | Action |
|------------|--------|
| Anytime | `pytest tests/ -v` |
| Anytime | `python scripts/test_mt5_connection.py --with-cycle` |
| ~21:30 | Start MT5, start ZeroMQ Service, re-run connection test |
| ~21:45 | `python main.py --mode single-cycle --phase round1` (one live cycle, minimal risk) |
| 22:00 | `python main.py --mode live --phase round1` |

**Single-cycle live mode** runs one 15-minute decision loop against the real account — useful to confirm orders can reach MT5 without leaving the engine running overnight.

---

## 4. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| MCP server shows error in Cursor | `PATH` override in `.cursor/mcp.json` hides Python | Use full `python.exe` path and add Python to `PATH` in MCP config (see section 1) |
| MCP server won't start | Missing `.env` credentials | Fill `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` |
| `initialize() failed` | MT5 not running | Launch terminal, enable Algorithmic Trading |
| ZeroMQ not connected | Service not started | Start `DWX_ZeroMQ_Server` as Service |
| Symbols missing | Not in MarketWatch | Right-click MarketWatch → Show All, or run test script |
| Port conflict | Another process on 32768–32770 | `netstat -ano \| findstr 32768` and stop conflicting process |

---

## 5. Security notes

- Never commit `.env` or hardcode passwords in MCP config
- Test with the **competition account only** — no multi-account logic is permitted
- MCP tools can read account data; live trading during competition uses the ZeroMQ bridge only
