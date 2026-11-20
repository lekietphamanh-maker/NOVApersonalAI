# Nova's news desk (daily news intelligence)

Every morning Nova collects the news, has an AI read each article, and keeps it in a searchable database, so its
answers to "what happened today?" come from articles it can cite (title, publisher, date, link), not from memory.

```
06:00 (or Nova's first minute after it, if the PC was off)
  collect ── GNews (key) · GDELT DOC 2.0 (no key) · publishers' RSS feeds · your news sites via Google News RSS
  normalize ── one canonical link per story (tracking parameters dropped), clean text, publisher
  dedupe ──── same link, or same headline from the same publisher within 3 days
  dates ───── source date kept apart from collection date; future, undated and >72 h old articles skipped
  categorize ─ the provider's category, else the article's words (world, politics, business, finance, technology,
               ai, science, health, entertainment, sports, environment, education, general)
  analyze ─── the AI on this PC (Ollama, structured JSON): summary, category, key facts, people/companies/
              organizations, place, importance 1–10, impact, sentiment, and each claim marked confirmed /
              allegation / analysis / speculation. Checked before saving: facts and names not in the article are dropped
  save ────── SQLite (news.sqlite3 in Nova's data folder), full-text search (FTS5), related stories linked
  briefing ── the top stories per topic, with sources
  log ─────── each run's counts, providers and problems (BRIEF → News desk, `python -m news_intel log`)
```

A provider that fails is noted and the run goes on; articles the AI couldn't read yet stay searchable and are read on
the next run (up to three tries). API keys never appear in logs or errors.

## Set up

1. **BRIEF → News desk → Turn on.** It runs at 06:00 every day; **Collect now** runs it at once.
2. Optional: a free **GNews** key from [gnews.io](https://gnews.io) (100 requests a day; one run uses 14) → paste it
   under News desk → **Save key**. Without it, GDELT and the news sites' feeds still work.
3. Ask Nova: "What happened in the world today?", "Biggest tech news this week?", "What happened in the economy over
   the last seven days?", "Latest on Nvidia?", "Compare today's news with last month", "Why does this matter?".
   Both brains (this PC, Claude, Ollama Cloud) use the same database through the `news` tool.

## Without Nova open (Windows Task Scheduler)

```powershell
schtasks /Create /SC DAILY /ST 06:00 /TN "Nova news desk" /TR "\"C:\Nova\Nova.exe\" --news-run"
```

From source: `python -m news_intel run` (also `search <words> --days 7 --category technology`, `brief`, `log`).
Settings for the command line come from environment variables or a `.env` file; see `.env.example`.

## Code

| Module | Job |
|---|---|
| `news_intel/collectors/` | `gnews.py`, `gdelt.py`, `rss.py`: one per provider; `http.py`: timeouts, retries with back-off (429/5xx/timeouts), pacing (GDELT: one request per 5 s), key redaction |
| `news_intel/normalize.py` | canonical links, headline fingerprints, date parsing and checks, categories |
| `news_intel/analysis.py` | the AI read (JSON schema) and its validation; any model with `analyze(article) -> dict` fits |
| `news_intel/store.py` | SQLite with numbered migrations (`PRAGMA user_version`), FTS5 search, runs |
| `news_intel/pipeline.py` | one run, in order, with a report |
| `news_intel/scheduler.py` | when the daily run is due |
| `news_intel/assistant.py` | what Nova's brains get: cited articles, marked as freshly retrieved |

**Postgres / Supabase later:** `migrations/postgres/001_news.sql` creates the same tables with `pgvector` embeddings
and a `tsvector` for keyword search. A `store` with the same methods on Postgres is the only code to add.

## Tested

- Unit tests (`tests/test_news_intel.py`): link normalizing, duplicates, dates, each provider's format, retries and
  key hiding, GDELT pacing and its plain-text errors, GNews stopping on a used-up key, the database and its search,
  the AI answer checks (invented facts and names dropped), a whole run with a provider failing, the AI being away,
  and the cited answers.
- End to end on the real HTTP stack (httpx2, feedparser, SQLite, the Ollama analyzer) against local stand-ins for the
  providers: two runs, duplicates and failures handled as above.
- Live providers: GitHub's Windows build machine checks GDELT and two publisher feeds on every build (and GNews when the
  `GNEWS_API_KEY` repository secret is set). That step reports problems without holding up a release.

## Next, when needed

Embeddings and semantic search (Ollama `nomic-embed-text` → `embedding` column), story clustering and breaking-news
detection over `related_ids`, source reliability per publisher, personal topics, and a morning notification or email.
