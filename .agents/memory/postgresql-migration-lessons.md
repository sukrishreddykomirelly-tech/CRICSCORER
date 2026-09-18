---
name: PostgreSQL migration lessons
description: Durable constraints discovered while moving CricScorer from SQLite to PostgreSQL.
---

PostgreSQL query compatibility requires explicit grouping of every selected non-aggregate column and aggregate expressions in HAVING clauses; SQLite may accept aliases or omitted grouped columns.

**Why:** The first PostgreSQL-backed HTTP smoke test exposed queries that worked under SQLite but failed under PostgreSQL, so a successful data migration alone is not enough to prove application compatibility.

**How to apply:** After future schema or database-driver changes, exercise profile, tournament, match, and scoring routes against PostgreSQL rather than relying only on unit tests.