# AI Usage Log

The final presentation requires an AI-usage reflection. Add a row whenever you use an AI tool
for something meaningful. It takes 30 seconds and saves hours in Week 14.

| Date | Who | Tool | What I asked for | What I used / changed | What I verified or fixed |
|---|---|---|---|---|---|
| 2026-10-09 | (name) | Claude | Project ideas, architecture, starter repo files | Adopted the clinic triage portal concept and repo layout | Checked service choices against the course rubric |
| 2026-10-12 | Tabarek | Claude Code | Draft the PostgreSQL schema, seed data, schema tests and CI database (issue #2) | Used schema.sql, seed.sql, docs/schema.md and the CI Postgres service | Ran schema + seed on a fresh Postgres 16 and ran pytest (duplicate slot and double booking both rejected); reviewed the constraints |
| 2026-10-12 | Tabarek | Claude Code | Implement GET /slots and POST /appointments with tests (issue #3) | Used the endpoints, Pydantic models, DB pool and tests | Ran pytest against Postgres 16 (21 passed, including concurrent double booking) and ran the server against seeded data with curl (201, then 409) |
| 2026-10-18 | Tabarek | Claude Code | Address review on #16 (cancelled and past slots, Docker) and fix the CI workflow | Used the partial unique index, slot filters, new tests and the docker compose CI job | 25 tests pass against Postgres 16; actionlint confirmed the old workflow error and that the new one is valid; Docker run checked in CI |
