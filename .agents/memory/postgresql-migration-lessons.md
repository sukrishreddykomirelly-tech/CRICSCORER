---
name: PostgreSQL migration lessons
description: Durable constraints discovered while moving CricScorer from SQLite to PostgreSQL.
---

PostgreSQL query compatibility requires explicit grouping of every selected non-aggregate column and aggregate expressions in HAVING clauses; SQLite may accept aliases or omitted grouped columns.

**Why:** The first PostgreSQL-backed HTTP smoke test exposed queries that worked under SQLite but failed under PostgreSQL, so a successful data migration alone is not enough to prove application compatibility.

**How to apply:** After future schema or database-driver changes, exercise profile, tournament, match, and scoring routes against PostgreSQL rather than relying only on unit tests.

When emulating SQLite `lastrowid`, never probe for a sequence on inserts into tables without an `id` column or sequence, or when the insert supplied an explicit ID. PostgreSQL errors abort the surrounding transaction even if the probe exception is caught, which can silently roll back the original insert.

**Why:** AI conversation inserts use text primary keys, and team membership uses a composite key with no `id`; unguarded sequence probes can abort these transactions and roll back otherwise valid inserts.

**How to apply:** Check that the target table has an `id` column before resolving its sequence and querying `currval()`, and skip the probe for explicit-ID inserts. Test inserts to both identity and composite-key tables against PostgreSQL.