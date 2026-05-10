from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from dk.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY,
    symbol TEXT,
    region TEXT,
    source TEXT,
    title TEXT,
    summary TEXT,
    url TEXT,
    published TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    sentiment REAL
);
CREATE INDEX IF NOT EXISTS idx_news_symbol_published ON news(symbol, published DESC);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published DESC);

CREATE TABLE IF NOT EXISTS earnings (
    symbol TEXT NOT NULL,
    report_date TEXT NOT NULL,
    eps_estimate REAL,
    eps_actual REAL,
    revenue_estimate REAL,
    revenue_actual REAL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, report_date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    kind TEXT,
    message TEXT,
    payload TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    seen INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT,
    pinned INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notes_symbol ON notes(symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS chart_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    symbol TEXT,
    settings_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS theme_scores (
    theme_id TEXT NOT NULL,
    snapshot_ts TEXT NOT NULL,
    aggregate_score REAL,
    avg_sentiment REAL,
    avg_price_chg_1d REAL,
    constituent_count INTEGER,
    top_contributor TEXT,
    PRIMARY KEY (theme_id, snapshot_ts)
);
CREATE INDEX IF NOT EXISTS idx_theme_ts ON theme_scores(snapshot_ts DESC);

CREATE TABLE IF NOT EXISTS trending_mentions (
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,            -- 'reddit_wsb' | 'reddit_stocks' | 'stocktwits' | 'news'
    mention_count INTEGER,
    sentiment REAL,                  -- -1..1 (where source provides it)
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, source)
);
CREATE INDEX IF NOT EXISTS idx_trending_source ON trending_mentions(source, mention_count DESC);

CREATE TABLE IF NOT EXISTS macro_context (
    symbol TEXT PRIMARY KEY,
    label TEXT,
    last_value REAL,
    chg_pct REAL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS custom_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,            -- 'price_above'|'price_below'|'rsi_above'|'rsi_below'|'sentiment_above'|'sentiment_below'
    threshold REAL NOT NULL,
    note TEXT,
    active INTEGER DEFAULT 1,
    fired_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tv_ratings (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,           -- '1h' | '1d' | '1W'
    recommendation TEXT,              -- 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL'
    buy_signals INTEGER,
    sell_signals INTEGER,
    neutral_signals INTEGER,
    rsi REAL,
    macd_hist REAL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, interval)
);

CREATE TABLE IF NOT EXISTS positions (
    broker TEXT NOT NULL,
    account_id TEXT,
    symbol TEXT NOT NULL,
    asset_type TEXT,            -- 'equity' | 'crypto' | 'option' | 'cash'
    quantity REAL,
    avg_cost REAL,
    market_price REAL,
    market_value REAL,
    unrealized_pnl REAL,
    currency TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (broker, account_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);

CREATE TABLE IF NOT EXISTS broker_status (
    broker TEXT PRIMARY KEY,
    connected INTEGER DEFAULT 0,
    last_sync TEXT,
    last_error TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    market_cap REAL,
    last_price REAL,
    mention_count INTEGER DEFAULT 0,
    discovered_via TEXT,         -- 'news_mentions' | 'sec_s1' | 'manual'
    score REAL,
    score_direction TEXT,
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(score DESC);

CREATE TABLE IF NOT EXISTS score_history (
    snapshot_ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank INTEGER,
    score REAL,
    direction TEXT,
    price_mom REAL,
    vol_mom REAL,
    news_vel REAL,
    sentiment REAL,
    earn_prox REAL,
    headline_count_24h INTEGER,
    PRIMARY KEY (snapshot_ts, symbol)
);
CREATE INDEX IF NOT EXISTS idx_score_symbol_ts ON score_history(symbol, snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS idx_score_ts ON score_history(snapshot_ts DESC);

CREATE TABLE IF NOT EXISTS macro_events (
    id TEXT PRIMARY KEY,
    event_date TEXT NOT NULL,
    region TEXT,
    category TEXT,
    title TEXT,
    importance INTEGER DEFAULT 1,
    source TEXT,
    notes TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_macro_date ON macro_events(event_date);

CREATE TABLE IF NOT EXISTS ipos (
    id TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    expected_date TEXT,
    price_range TEXT,
    shares REAL,
    exchange TEXT,
    source TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ipos_date ON ipos(expected_date);

CREATE TABLE IF NOT EXISTS crypto_prices (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    price_usd REAL,
    market_cap REAL,
    vol_24h REAL,
    change_24h_pct REAL,
    PRIMARY KEY (symbol, ts)
);
"""


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def conn():
    init_db()
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def upsert_news(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR IGNORE INTO news
               (id, symbol, region, source, title, summary, url, published)
               VALUES (:id, :symbol, :region, :source, :title, :summary, :url, :published)""",
            rows,
        )
        return c.total_changes


def upsert_prices(symbol: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO prices
               (symbol, ts, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(symbol, r["ts"], r.get("open"), r.get("high"), r.get("low"),
              r.get("close"), r.get("volume")) for r in rows],
        )
        return len(rows)


def upsert_crypto(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO crypto_prices
               (symbol, ts, price_usd, market_cap, vol_24h, change_24h_pct)
               VALUES (:symbol, :ts, :price_usd, :market_cap, :vol_24h, :change_24h_pct)""",
            rows,
        )
        return len(rows)


def upsert_earnings(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO earnings
               (symbol, report_date, eps_estimate, eps_actual, revenue_estimate, revenue_actual)
               VALUES (:symbol, :report_date, :eps_estimate, :eps_actual, :revenue_estimate, :revenue_actual)""",
            rows,
        )
        return len(rows)


def upsert_tv_ratings(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany("""
            INSERT OR REPLACE INTO tv_ratings
              (symbol, interval, recommendation, buy_signals, sell_signals,
               neutral_signals, rsi, macd_hist, fetched_at)
            VALUES (:symbol, :interval, :recommendation, :buy_signals, :sell_signals,
                    :neutral_signals, :rsi, :macd_hist, CURRENT_TIMESTAMP)
        """, rows)
    return len(rows)


def upsert_positions(broker: str, rows: list[dict]) -> int:
    """Replace all positions for a broker. Always full-replace (sync semantics)."""
    with conn() as c:
        c.execute("DELETE FROM positions WHERE broker = ?", (broker,))
        if rows:
            c.executemany("""
                INSERT INTO positions
                  (broker, account_id, symbol, asset_type, quantity, avg_cost,
                   market_price, market_value, unrealized_pnl, currency)
                VALUES
                  (:broker, :account_id, :symbol, :asset_type, :quantity, :avg_cost,
                   :market_price, :market_value, :unrealized_pnl, :currency)
            """, rows)
    return len(rows)


def set_broker_status(broker: str, connected: bool, error: str = "", note: str = "") -> None:
    with conn() as c:
        c.execute("""
            INSERT INTO broker_status (broker, connected, last_sync, last_error, note)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(broker) DO UPDATE SET
              connected=excluded.connected,
              last_sync=CURRENT_TIMESTAMP,
              last_error=excluded.last_error,
              note=excluded.note
        """, (broker, 1 if connected else 0, error, note))


def owned_symbols() -> set[str]:
    """Return the set of symbols held in any broker (uppercase, normalized)."""
    with conn() as c:
        rows = c.execute("SELECT DISTINCT UPPER(symbol) FROM positions WHERE quantity > 0").fetchall()
        return {r[0] for r in rows}


def upsert_candidates(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        # Update last_seen + new fields; preserve first_seen on existing rows.
        c.executemany("""
            INSERT INTO candidates
              (symbol, name, sector, market_cap, last_price, mention_count,
               discovered_via, score, score_direction, notes, last_seen)
            VALUES
              (:symbol, :name, :sector, :market_cap, :last_price, :mention_count,
               :discovered_via, :score, :score_direction, :notes, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol) DO UPDATE SET
              name=excluded.name, sector=excluded.sector,
              market_cap=excluded.market_cap, last_price=excluded.last_price,
              mention_count=excluded.mention_count,
              discovered_via=excluded.discovered_via,
              score=excluded.score, score_direction=excluded.score_direction,
              notes=excluded.notes, last_seen=CURRENT_TIMESTAMP
        """, rows)
    return len(rows)


def insert_score_snapshot(snapshot_ts: str, ranked: list[dict]) -> int:
    if not ranked:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO score_history
               (snapshot_ts, symbol, rank, score, direction, price_mom, vol_mom,
                news_vel, sentiment, earn_prox, headline_count_24h)
               VALUES (:snapshot_ts, :symbol, :rank, :score, :direction, :price_mom,
                       :vol_mom, :news_vel, :sentiment, :earn_prox, :headline_count_24h)""",
            [
                {**r, "snapshot_ts": snapshot_ts, "rank": i + 1}
                for i, r in enumerate(ranked)
            ],
        )
    return len(ranked)


def upsert_macro(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO macro_events
               (id, event_date, region, category, title, importance, source, notes)
               VALUES (:id, :event_date, :region, :category, :title, :importance, :source, :notes)""",
            rows,
        )
        return len(rows)


def upsert_ipos(rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO ipos
               (id, symbol, name, expected_date, price_range, shares, exchange, source)
               VALUES (:id, :symbol, :name, :expected_date, :price_range, :shares, :exchange, :source)""",
            rows,
        )
        return len(rows)


def add_alert(symbol: str, kind: str, message: str, payload: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO alerts (symbol, kind, message, payload) VALUES (?, ?, ?, ?)",
            (symbol, kind, message, payload),
        )
