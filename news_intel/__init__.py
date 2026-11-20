"""Nova's news desk: a daily news intelligence pipeline and the searchable news database behind Nova's answers.

    collect (GNews, GDELT, RSS) → normalize → remove duplicates → check dates → categorize
    → analyze with an LLM (structured JSON, validated) → save (SQLite) → daily briefing → run log

Each part is its own module so a news source, the database or the model can be replaced: `collectors/` (one per
provider), `normalize`, `analysis` (the LLM), `store` (SQLite now; Postgres/Supabase with pgvector later, see
migrations/postgres), `pipeline`, `scheduler` and `assistant` (what Nova asks the database). Run it by itself with
`python -m news_intel run`, or let Nova run it every day at 06:00.
"""
