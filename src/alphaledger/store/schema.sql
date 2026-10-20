-- alphaledger schema v1
-- Everything is append-only except the counters on `trial`: an evaluation that is
-- re-run must be visible as a re-run, never as a new hypothesis.

CREATE TABLE IF NOT EXISTS panel (
    id            INTEGER PRIMARY KEY,
    panel_fp      TEXT NOT NULL UNIQUE,      -- sha256(universe|dates|symbols)[:16]
    start_date    TEXT,
    end_date      TEXT,
    n_dates       INTEGER,
    n_symbols     INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trial (
    id            INTEGER PRIMARY KEY,
    fp            TEXT NOT NULL,             -- "v1:<hex32>", sign-invariant value fingerprint
    fp_expr       TEXT,                      -- "e1:<hex16>", diagnostic only
    panel_id      INTEGER NOT NULL REFERENCES panel(id),
    horizon       INTEGER NOT NULL,
    orientation   INTEGER NOT NULL,          -- +1 / -1
    label         TEXT,
    expr_text     TEXT,
    family_tag    TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    n_evals       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (fp, panel_id, horizon)           -- the idempotency key
);

CREATE INDEX IF NOT EXISTS idx_trial_family ON trial(panel_id, horizon);
CREATE INDEX IF NOT EXISTS idx_trial_expr ON trial(fp_expr);

CREATE TABLE IF NOT EXISTS trial_eval (
    id             INTEGER PRIMARY KEY,
    trial_id       INTEGER NOT NULL REFERENCES trial(id) ON DELETE CASCADE,
    ts             TEXT NOT NULL,
    session_id     TEXT,
    data_fp        TEXT,
    n_dates        INTEGER,
    n_stocks_med   INTEGER,
    ic_mean        REAL,
    ic_std         REAL,
    ic_ir          REAL,
    t_iid          REAL,
    t_nw           REAL,
    nw_lag         INTEGER,
    p_single       REAL,
    skew           REAL,
    kurt           REAL,
    leak_flag      TEXT,
    insufficient   INTEGER NOT NULL DEFAULT 0,
    engine_version TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_trial ON trial_eval(trial_id);

CREATE TABLE IF NOT EXISTS ic_series (
    eval_id        INTEGER PRIMARY KEY REFERENCES trial_eval(id) ON DELETE CASCADE,
    n              INTEGER NOT NULL,
    values_blob    BLOB NOT NULL             -- float32, NaN allowed
);

CREATE TABLE IF NOT EXISTS gate_run (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    trial_id       INTEGER REFERENCES trial(id),
    panel_id       INTEGER,
    horizon        INTEGER,
    method         TEXT,
    n_family       INTEGER,
    alpha          REAL,
    bar_sigma      REAL,
    bar_q95        REAL,
    p_family       REAL,
    verdict        TEXT,
    reason_code    TEXT,
    scope_narrowed INTEGER NOT NULL DEFAULT 0,
    params_json    TEXT,
    result_json    TEXT,
    engine_version TEXT
);

CREATE TABLE IF NOT EXISTS oos_region (
    id         INTEGER PRIMARY KEY,
    panel_id   INTEGER NOT NULL REFERENCES panel(id),
    name       TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_lock (
    id          INTEGER PRIMARY KEY,
    region_id   INTEGER NOT NULL REFERENCES oos_region(id),
    consumed_at TEXT,
    consumed_by TEXT,
    trial_id    INTEGER REFERENCES trial(id),
    note        TEXT
);

CREATE TABLE IF NOT EXISTS event (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL,                   -- sign_flip | reeval | near_duplicate | nondeterministic | lock_denied
    trial_id INTEGER REFERENCES trial(id),
    detail  TEXT
);
