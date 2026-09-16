-- Nebula KnowLab Supermarket Ops Agent — SQLite schema
-- All business rules (oversell guard, idempotency, khata integrity) are
-- enforced at this layer via constraints + transactional updates in skills/*.py,
-- never in the LLM prompt.

PRAGMA journal_mode = WAL;      -- allows concurrent readers while a writer commits
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    unit            TEXT NOT NULL,               -- kg, g, litre, ml, packet, dozen, piece
    is_loose        INTEGER NOT NULL DEFAULT 0,  -- 1 = sold loose by weight/volume
    hsn_code        TEXT,
    gst_rate        REAL NOT NULL DEFAULT 0,     -- overall slab e.g. 0, 5, 12, 18
    cost_price      REAL NOT NULL,
    sell_price      REAL NOT NULL,               -- MRP / selling price per unit
    quantity        REAL NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level   REAL NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS stock_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id),
    change_qty          REAL NOT NULL,           -- + stock-in, - sale/adjustment
    txn_type            TEXT NOT NULL,           -- stock_in | sale | adjustment | return
    ref_type            TEXT,                    -- bill | manual
    ref_id              INTEGER,
    cost_price_at_time  REAL,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER,
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft | finalized | cancelled
    customer_name   TEXT,
    payment_mode    TEXT,                            -- cash | upi | card | khata
    payment_ref     TEXT,
    subtotal        REAL DEFAULT 0,
    cgst_total      REAL DEFAULT 0,
    sgst_total      REAL DEFAULT 0,
    grand_total     REAL DEFAULT 0,
    finalize_token  TEXT UNIQUE,                     -- idempotency key supplied by caller
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    finalized_at    TEXT
);

CREATE TABLE IF NOT EXISTS bill_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id         INTEGER NOT NULL REFERENCES bills(id),
    product_id      INTEGER NOT NULL REFERENCES products(id),
    product_name    TEXT NOT NULL,
    qty             REAL NOT NULL,
    unit            TEXT,
    unit_price      REAL NOT NULL,
    gst_rate        REAL NOT NULL,
    taxable_value   REAL NOT NULL,
    cgst_amount     REAL NOT NULL,
    sgst_amount     REAL NOT NULL,
    line_total      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS khata_customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    phone       TEXT,
    balance     REAL NOT NULL DEFAULT 0,   -- positive = customer owes the shop
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS khata_transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id       INTEGER NOT NULL REFERENCES khata_customers(id),
    txn_type          TEXT NOT NULL,      -- credit | payment
    amount            REAL NOT NULL,
    bill_id           INTEGER,
    note              TEXT,
    idempotency_key   TEXT UNIQUE,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shop_info (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    name     TEXT,
    gstin    TEXT,
    address  TEXT,
    phone    TEXT
);

-- Telegram redelivers updates on reconnect/timeout; this makes "process an
-- update" idempotent independent of anything the LLM decides to do.
CREATE TABLE IF NOT EXISTS processed_telegram_updates (
    update_id     INTEGER PRIMARY KEY,
    processed_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Rolling per-chat message history so multi-turn bill building and context
-- survive across separate webhook/poll invocations (the process can restart).
CREATE TABLE IF NOT EXISTS conversation_state (
    chat_id       INTEGER PRIMARY KEY,
    active_bill_id INTEGER,
    history_json  TEXT,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bill_items_bill ON bill_items(bill_id);
CREATE INDEX IF NOT EXISTS idx_stock_txn_product ON stock_transactions(product_id);
CREATE INDEX IF NOT EXISTS idx_khata_txn_customer ON khata_transactions(customer_id);
