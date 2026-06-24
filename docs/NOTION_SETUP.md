# Notion Setup — QuantAI Sync

Notion sync is **code-complete**; you must create the workspace resources manually, then validate with the setup script.

## 1. Create integration

1. Open [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. **New integration** → name it (e.g. QuantAI)
3. Copy the secret (`secret_…` or `ntn_…`)

## 2. Create four databases

In your QuantAI workspace, create these databases. The **title property must be named `Name`**.

| Database | Required properties |
|----------|---------------------|
| **Trade Journal** | `Symbol` (text), `Direction` (select: BUY/SELL/HOLD), `Status` (text), `Confidence` (number), `Regime` (text), `Session` (text) |
| **Agent Performance** | `Agent` (text), `Win Rate`, `Avg R`, `Samples` (numbers); optional `Symbol` (text) |
| **Risk Events** | `Event Type`, `Message`, `Severity` (select), `Timestamp` (text); optional `Details` (text) |
| **Tasks** | `Status` (select or status: Not started / In progress / Done); optional `Notes` (text) |

Optional: create a page for the A–Z operator guide and note its page ID for `NOTION_AZ_PAGE_ID`.

## 3. Share with integration

For each database (and optional guide page): **⋯ → Connections → add your integration**.

## 4. Populate `.env`

```env
NOTION_API_KEY=secret_...
NOTION_TRADE_JOURNAL_DS_ID=...
NOTION_AGENT_PERF_DS_ID=...
NOTION_RISK_EVENTS_DS_ID=...
NOTION_TASKS_DS_ID=...
NOTION_AZ_PAGE_ID=...          # optional
NOTION_SYNC_ENABLED=true
```

Database IDs are the 32-character hex strings from each database URL.

## 5. Validate

```bash
python scripts/setup_notion_check.py
```

Fix any schema or access errors the script reports, then:

```bash
python scripts/sync_notion_az.py --guide-page
```

Restart the engine so live hooks (trade journal, risk events, agent performance) begin syncing.

## 6. Verify in dashboard

Overview → **NotionSyncPanel** → `GET /api/notion/status` should show configured databases and sync enabled.

See also [notion_az_operators_guide.md](notion_az_operators_guide.md) and [northflank_deploy.md](northflank_deploy.md) for deploy env vars.
