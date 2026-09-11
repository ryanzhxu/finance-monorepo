PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS decision_history (
    market_date TEXT NOT NULL,
    recorded_at_et TEXT NOT NULL,
    ticker TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'ETF')),
    horizon TEXT NOT NULL CHECK (horizon IN ('short', 'mid', 'long')),
    data_status TEXT NOT NULL CHECK (data_status IN ('available', 'partial', 'unavailable')),
    action TEXT,
    confidence REAL,
    price_state TEXT,
    current_price REAL,
    opportunity_low REAL,
    opportunity_high REAL,
    reduce_low REAL,
    reduce_high REAL,
    invalidation REAL,
    landscape_quality REAL,
    direction REAL,
    confirmation REAL,
    risk REAL,
    exhaustion REAL,
    market_regime TEXT,
    market_context_json TEXT,
    technical_features_json TEXT,
    supporting_reasons_json TEXT,
    limiting_reasons_json TEXT,
    primary_classification TEXT,
    lifecycle TEXT,
    company_traits_json TEXT,
    applied_profile_modifiers_json TEXT,
    leveraged INTEGER,
    etf_direction TEXT CHECK (etf_direction IN ('long', 'inverse') OR etf_direction IS NULL),
    underlying TEXT,
    etf_modifiers_json TEXT,
    material_change_json TEXT,
    PRIMARY KEY (market_date, ticker, horizon)
);

CREATE INDEX IF NOT EXISTS idx_decision_history_ticker_date
    ON decision_history (ticker, market_date);

CREATE TABLE IF NOT EXISTS eod_runs (
    market_date TEXT PRIMARY KEY,
    started_at_et TEXT NOT NULL,
    completed_at_et TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'skipped', 'failed')),
    ticker_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    unavailable_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    database_size_mb REAL
);
