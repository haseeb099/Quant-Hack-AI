# Sponsor Perk Setup — Step by Step

Configure all four competition participant perks for QuantAI. Run the validator after each step:

```bash
python scripts/setup_sponsor_check.py
```

Dashboard: **Overview → Launch Readiness** also checks Logfire and AI providers.

---

## Recommended routing (all four sponsors visible)

| Perk | Env var | Used by |
|------|---------|---------|
| Anthropic ($50) | `ANTHROPIC_API_KEY` + `QUANTAI_LLM_ALLOW_ANTHROPIC=true` | **MetaOrchestrator** — Claude trade decisions |
| Pydantic Logfire ($50) | `LOGFIRE_TOKEN` | **Engine + dashboard** — full cycle traces |
| Doubleword (via Gateway) | `PYDANTIC_AI_GATEWAY_API_KEY` | **Copilot** — narrative summaries |
| Northflank ($100) | deploy + `DASHBOARD_AUTH_TOKEN` | **Cloud dashboard** for judges |

**Provider chain (MetaOrchestrator):** follows `QUANTAI_LLM_PROVIDER` / `ORCHESTRATOR_LLM_PROVIDER`. With `anthropic` preference: Claude → Doubleword → Groq. With `doubleword` (default): Doubleword → Groq. On provider failure the orchestrator tries the next provider before rule-based fallback.

**Model env vars (do not mix):**
- `META_ORCHESTRATOR_MODEL=claude-sonnet-4-6` — Anthropic model id only
- `DOUBLEWORD_MODEL` / `DOUBLEWORD_MODEL_COMPLEX` — Doubleword/OpenAI-compat models
- `META_ORCHESTRATOR_COMPLEX_MODEL=true` — use `DOUBLEWORD_MODEL_COMPLEX` for orchestrator (off by default)

For competition Claude routing on the engine:

```bash
ANTHROPIC_API_KEY=sk-ant-...
QUANTAI_LLM_ALLOW_ANTHROPIC=true
QUANTAI_LLM_PROVIDER=anthropic
META_ORCHESTRATOR_MODEL=claude-sonnet-4-6
```

Use the Logfire Gateway key for Copilot only; leave `DOUBLEWORD_API_KEY` off the engine if you want Claude first.

---

## 1. Anthropic — $50 API credits

1. Open [platform.claude.com](https://platform.claude.com) and sign in (or create an account).
2. Redeem hackathon credits from the competition portal if prompted.
3. Go to **API Keys** → **Create Key**.
4. Add to `.env`:

   ```bash
   ANTHROPIC_API_KEY=sk-ant-...
   QUANTAI_LLM_ALLOW_ANTHROPIC=true
   QUANTAI_LLM_PROVIDER=anthropic
   META_ORCHESTRATOR_MODEL=claude-sonnet-4-6
   ```

5. **Remove or comment out** `Groq_API_KEY` / `GROQ_API_KEY` on the engine service if you want Claude as primary.

Model used: `claude-sonnet-4-6` (see `config/agents.yaml` `meta_orchestrator.anthropic_model`).

---

## 2. Pydantic — $50 Logfire inference credits

1. Open [pydantic.dev/hackathon](https://pydantic.dev/hackathon) and follow redemption steps for Logfire credits.
2. Create a project at [logfire.pydantic.dev](https://logfire.pydantic.dev) (choose region once — cannot change later).
3. In your Logfire project: **Settings → Write tokens** → create token.
4. Add to `.env` (engine **and** Northflank dashboard service):

   ```bash
   LOGFIRE_TOKEN=pylf_...
   ```

5. Restart the engine. You should see `Logfire observability enabled` in logs.

Traces cover: features → agents → orchestrator → risk → execution. Disable with `python main.py --no-logfire`.

---

## 3. Doubleword — via Pydantic AI Gateway (Logfire)

Doubleword access is bundled through the **Logfire Gateway**, not a separate MetaOrchestrator key.

1. After hackathon redemption, open **Logfire → Gateway** in your organization.
2. Add a credit card if on the free Personal plan (required for gateway usage; hackathon credits apply first).
3. Configure the **Doubleword** provider in Gateway settings (or use the routing group from the hackathon email).
4. Create a **Gateway API key**.
5. Add to `.env` for Copilot (local + dashboard):

   ```bash
   PYDANTIC_AI_GATEWAY_API_KEY=pylf_v...
   COPILOT_GATEWAY_MODEL=gateway/openai:gpt-4o-mini
   ```

   Adjust `COPILOT_GATEWAY_MODEL` to match your Gateway routing group (e.g. a Doubleword-backed route).

**Alternative:** If you received a direct Doubleword key:

```bash
DOUBLEWORD_API_KEY=...
```

Do **not** set this on the engine if you want Anthropic for MetaOrchestrator — Copilot will use it, but MetaOrchestrator would switch to Doubleword first.

---

## 4. Northflank — $100 platform credit

1. Create account: [app.northflank.com/i/AIENGINE](https://app.northflank.com/i/AIENGINE)
2. Complete **GPU Registration** from the competition portal if you need GPU workloads (optional for this dashboard).
3. Build images locally:

   ```bash
   cd frontend && npm run build && cd ..
   docker build -f Dockerfile.engine -t quantai-engine .
   docker build -f Dockerfile.dashboard -t quantai-dashboard .
   ```

4. Create a **shared volume**; mount `/app/logs` and `/app/data` on both services.
5. **Engine service** (internal): `ANTHROPIC_API_KEY`, `LOGFIRE_TOKEN`, `ZMQ_*`, `QUANTAI_PHASE`, Notion/intelligence vars as needed.
6. **Dashboard service** (public :8080): `LOGFIRE_TOKEN`, `DASHBOARD_AUTH_TOKEN`, `PORT=8080`
7. Configure **HTTPS ingress** to the dashboard URL for judges.

Full checklist: [northflank_deploy.md](northflank_deploy.md)

Generate a dashboard auth token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Local `.env` template

```bash
# Engine — Claude for decisions
ANTHROPIC_API_KEY=sk-ant-...
QUANTAI_LLM_ALLOW_ANTHROPIC=true
QUANTAI_LLM_PROVIDER=anthropic
META_ORCHESTRATOR_MODEL=claude-sonnet-4-6

# Observability — engine + dashboard
LOGFIRE_TOKEN=pylf_...

# Copilot — Doubleword via Logfire Gateway (do not set on engine MetaOrchestrator path)
PYDANTIC_AI_GATEWAY_API_KEY=pylf_v...
COPILOT_GATEWAY_MODEL=gateway/openai:gpt-4o-mini

# Northflank public dashboard
DASHBOARD_AUTH_TOKEN=<random-token>

# Do NOT set on engine if using Anthropic for MetaOrchestrator:
# Groq_API_KEY=
# DOUBLEWORD_API_KEY=
```

---

## Verify

```bash
python scripts/setup_sponsor_check.py
python scripts/preflight_competition.py
curl http://localhost:8080/api/competition/launch-readiness
```

See also [sponsor_integrations.md](sponsor_integrations.md) for code paths and demo script.
