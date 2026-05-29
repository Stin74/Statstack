CREATE TABLE IF NOT EXISTS scores (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  date       TEXT    NOT NULL,   -- e.g. "2026-05-29"
  sport      TEXT    NOT NULL,   -- "mlb" | "nfl"
  difficulty TEXT    NOT NULL,   -- "normal" | "hard"
  score      INTEGER NOT NULL,   -- lower is better
  created_at TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scores_lookup
  ON scores (date, sport, difficulty);
