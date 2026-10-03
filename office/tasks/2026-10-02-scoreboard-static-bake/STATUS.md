# Status

| phase | verdict | time | note |
|---|---|---|---|
| 25 | aligned | 2026-10-02 21:46 | scoreboard_stats, within-beach in _score, p_exceed_persistence (+backfill from beach_day — PM note: uses today-vintage labels, so the persistence baseline has slight hindsight; that only makes it a harder bar), CIs, 28-day rule; 815/0 |
| 50 | aligned | 2026-10-02 21:50 | --with-tides → tides.parquet (18 stations, ~95 h, carry-over on failure, atomic), workflow flag; 821/0. PM fix: removed 3 NOAA stations with no hourly predictions (9410665, 9415118 none; 9413745 hilo-only) — pre-existing: API tides route failed for beaches nearest them; neighbours now serve them, test added |
| 75 | corrected | 2026-10-02 21:55 | detail files OK (850, validate ad hoc). Worker flagged: top-level beaches.json/parent_beaches.json are web flat shape, not BeachSummary — contract amended to api/ prefix; vendored station list still has the 3 dead stations (66 null tides) |
| 100 | aligned | 2026-10-02 22:08 | PM: api/ rework verified; real-snapshot parity 850/850; PM fixed live API 500 on null-value observation (Julia Pfeiffer Burns) + regression test (fails without fix); 857/0, ruff clean. PR #47 |
