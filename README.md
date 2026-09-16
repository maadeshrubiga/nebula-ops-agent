# Nebula Kirana Ops Agent

live deployment link: https://nebula-ops-agent.onrender.com

Run a small Indian kirana store end-to-end from Telegram — stock, billing, khata, daily close,
GST invoices, and analysis decks — driven by an agent that calls tools, not a command router.

**Telegram bot:** `@your_bot_handle_here` ← *fill in after you deploy (see "Running it" below).*

---

## 1. Harness

I built the control loop directly against the **Anthropic Messages API's native tool use**
(`agent/orchestrator.py`) rather than pulling in a framework. This *is* effectively what Claude
Agent SDK / Vercel AI SDK give you — an observe → reason → act → feed-result-back loop over
tool-calling — but writing it directly kept the harness small, dependency-free, and fully
auditable for a 5-day take-home, and it makes the "no big if/elif router" requirement obvious by
inspection: there is no branching on user intent anywhere in this codebase. All intent
resolution happens inside the model; `agent/tools_schema.py` is the only place tool names are
listed, and it's a flat dispatch table, not a decision tree.

Swapping in Claude Agent SDK proper is a small change: replace the loop body in
`orchestrator.run_turn` with an SDK session and hand it the same `skills/*.py` functions as
tools — the skill/tool layer underneath was written to be harness-agnostic on purpose.

## 2. Control loop

```
Telegram message
   -> mark update_id processed (transport-level idempotency)
   -> load this chat's rolling history from SQLite
   -> build system prompt = base instructions + live preferences + shop info from DB
   -> loop (max 8 iterations):
        call Claude with [system, tools, messages]
        if stop_reason == tool_use:
            execute each tool call against skills/*.py
            feed tool_result(s) back as the next user turn
            continue
        else: break, this is the final reply
   -> save updated history to SQLite
   -> send reply text; upload any generated files (invoice PDF / deck PPTX)
```

Multiple tool calls in one model turn are executed and fed back together, so the agent can, e.g.,
resolve an ambiguous product via `search_products`, then `add_bill_item`, then `get_bill` in a
single reasoning pass without another round-trip to the owner.

## 3. Skill / tool design

Six skill modules, each owning one part of the store's data and its rules — the model never
touches the DB directly, only through these:

| Skill | File | Responsibility |
|---|---|---|
| Inventory | `skills/inventory.py` | catalog, stock-in, stock lookups, low-stock report |
| Billing | `skills/billing.py` | draft bills, line items, GST math, oversell guard, finalize |
| Khata | `skills/khata.py` | customer credit ledger |
| Analytics | `skills/analytics.py` | daily close, date-range sales summary, stock health |
| Preferences | `skills/preferences.py` | durable owner preferences + shop info (the memory layer) |
| Documents | `skills/documents.py` | PDF invoice (reportlab), PPTX analysis deck (python-pptx) |

Tools are kept deliberately **thin and single-purpose** (`add_bill_item` does one thing;
`search_products` does one thing) so the model composes them, rather than a few "do everything"
mega-tools that would smuggle intent logic back into a monolith. `agent/tools_schema.py` is
purely wiring: JSON schema + a name→function dispatch dict, nothing else.

## 4. How each hard part is solved

1. **Grounding** — every tool that returns a fact (price, stock, GST rate, balance) reads it
   from SQLite. The system prompt explicitly forbids stating such facts without a tool result.
2. **Oversell guard** — enforced at the DB layer, not the prompt. `add_bill_item` does a soft
   check against `stock - already reserved in this draft`. The **hard** guard is in
   `finalize_bill`: a conditional update, `UPDATE products SET quantity = quantity - ? WHERE id
   = ? AND quantity >= ?`, inside a `BEGIN IMMEDIATE` transaction per item. If `rowcount == 0`
   the whole finalize transaction rolls back — no partial stock decrement, ever.
3. **GST correctness** — each SKU carries its own slab + HSN code. Per line item: taxable value
   = price × qty, CGST = SGST = slab/2 applied to taxable value, each rounded to paise; bill
   totals are the *sum of already-rounded line items* (how real POS/GST invoices avoid rounding
   disputes), shown as a full breakup on both the chat reply and the PDF invoice.
4. **Multi-turn bills** — a bill is a `draft` row + `bill_items` rows. `start_bill` /
   `add_bill_item` / `remove_bill_item` / `update_bill_item_qty` can be called across any number
   of separate Telegram messages; `products.quantity` is untouched until `finalize_bill` runs.
5. **Idempotency** — two independent layers:
   - **Transport**: `processed_telegram_updates(update_id PRIMARY KEY)` — a redelivered Telegram
     update is detected and skipped before any tool runs at all.
   - **Business logic**: `finalize_bill(bill_id, finalize_token)` — `finalize_token` is a UNIQUE
     column on `bills`. A retried finalize call with the same token returns the already-committed
     result (`idempotent_replay: true`) instead of decrementing stock again. Verified in
     `tests/test_flow.py`.
6. **Concurrency** — SQLite in WAL mode plus every stock-touching write wrapped in an explicit
   `BEGIN IMMEDIATE ... COMMIT/ROLLBACK` transaction (`db/database.transaction()`), serialized by
   SQLite's writer lock. Two bills racing on the same low-stock SKU cannot both succeed: the
   second one's conditional `UPDATE` sees the already-decremented row and fails the guard.
7. **Guardrails** — selling below `cost_price` is refused inside `add_bill_item`; settling a
   khata for a customer with no account is refused inside `khata_payment`; stock rows are never
   deleted, only adjusted via `stock_transactions` history.
8. **Real artifacts** — `generate_invoice_pdf` builds an actual GST tax-invoice table (reportlab);
   `generate_analysis_deck` builds a PPTX with real native charts (line, bar, pie via
   `python-pptx`'s chart API fed by `matplotlib`-free `CategoryChartData`) — not screenshots or
   pasted text. The orchestrator watches tool results for `file_path` and the bot layer uploads
   the actual file to Telegram.
9. **Memory across sessions** — `preferences.py` is a key/value table read fresh into the system
   prompt on *every* turn, including right after `/new`. `/new` only clears
   `conversation_state` (the chat transcript); it never touches `preferences` or `shop_info`, so
   a standing instruction like "always assume UPI unless I say cash" survives a brand-new chat,
   as required.

## 5. Data model

SQLite (`db/schema.sql`): `products`, `stock_transactions`, `bills`, `bill_items`,
`khata_customers`, `khata_transactions`, `preferences`, `shop_info`,
`processed_telegram_updates`, `conversation_state`. All durable; survives a process restart.

## 6. Running it

### Windows setup

Open Command Prompt in this folder and install the dependencies:

```bat
"C:\Users\<your-user>\AppData\Local\Programs\Python\Python311\python.exe" -m pip install -r requirements.txt
```

Create `.env` from `.env.example` and fill in your own values. Never commit `.env`:

```env
ANTHROPIC_API_KEY=your_anthropic_api_key
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_BOT_USERNAME=your_bot_username_without_@
NEBULA_MODEL=claude-sonnet-4-5
NEBULA_DB_PATH=./nebula_store.db
```

Use a real bot username for the dashboard's **Open Bot** button. The token authenticates
the local bot process; the username only creates the public Telegram chat link.

### UI mode

Double-click `run_ui.bat`. It starts the local Flask dashboard and opens:

```text
http://127.0.0.1:5000/
```

Keep the **Nebula Kirana Ops UI** command window open. In the dashboard you can add products,
receive stock, create and finalize bills, generate invoices, and create analysis decks.

### Telegram mode

Double-click `run_nebula.bat` in a second Command Prompt window. Keep it open while using the bot.
Open Telegram Web, open the bot from the dashboard's **Open Bot** button, and send `/start`.
Then send normal store requests, for example:

```text
50 packets of Maggi came in, cost ₹12
make a bill: 2kg sugar, 1 Maggi, UPI
today's sales?
```

The UI and Telegram bot use the same `nebula_store.db` file. Bills created in Telegram appear in
the dashboard's **Recent bills** section after they are created, with their source, status, and
amount. Both processes must use the same folder and `NEBULA_DB_PATH`.

### Offline tests

```bat
run_test.bat
```

Or run the test module directly:

```bash
python -m tests.test_flow
```

First run auto-creates `nebula_store.db` and seeds the demo SKUs from the brief (Aashirvaad
Atta, Tata Salt, Amul Butter, Fortune oil, Maggi, Parle-G, Surf Excel, loose sugar/rice/dal).

Deploy anywhere that can hold a long-running process (Railway, Render, a small VM, `screen`/
`systemd` on your own box) — long-polling needs no public URL/webhook.

### Sanity-testing without Telegram/API keys
```bash
python -m tests.test_flow
```
Exercises stock-in, multi-turn bill + edit, oversell guard, below-cost guard, GST math,
idempotent finalize, khata cycle, preferences, and both document generators — all against a
throwaway SQLite file, no network calls.

## 7. Known simplifications

- GST slabs seeded for demo SKUs are illustrative (matching the brief's "loose staples 0% /
  packaged staples 5% / FMCG 12–18%" model), not a certified real-world GST rate table.
- Single shop / single GSTIN assumed (no multi-store support).
- Intra-state GST only (CGST+SGST split); inter-state IGST is not modeled.

## 8. Stretch items not implemented (by design, to keep scope tight for 5 days)
Branded invoice templates, scheduled auto-sent decks, reorder-from-velocity suggestions,
expiry/FEFO batch tracking, voice-note billing, Hindi/Tamil, barcode/photo lookup, khata
reminders — the architecture (thin tools + durable preferences) is built to make each of these
an additive skill rather than a rewrite.

## 9. Publish this folder to GitHub

Create an empty repository on GitHub first. Do not add a README, `.gitignore`, or license there
because this folder already contains them. Then run these commands from the project folder:

```bat
git init
git add .
git status
git commit -m "Initial Nebula Kirana Ops agent"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repository>.git
git push -u origin main
```

Before `git add .`, confirm that `.env`, `nebula_store.db`, `outputs/*.pdf`, and
`outputs/*.pptx` are listed in `.gitignore` and are not shown as staged files. If GitHub asks
for a password, use a GitHub personal access token or configure SSH; never put API keys in the
remote URL.

For future changes:

```bat
git add .
git commit -m "Describe the change"
git push
```
