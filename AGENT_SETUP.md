# AGENT_SETUP (retired)

The original design synced job discovery through a Supabase `jobs` table. That was replaced by a local, per-profile
SQLite database and the `brain/` package. For setup and daily use, see [README.md](README.md). For how the project was
built and how to resume work, see [plan.md](plan.md).

The `integration/` folder (Supabase sync scripts) is unused and can be deleted once you confirm you do not need it.
