---
name: PostgreSQL migration lessons
description: Durable constraints discovered while moving CricScorer from SQLite to PostgreSQL.
---

PostgreSQL query compatibility requires explicit grouping of every selected non-aggregate column and aggregate expressions in HAVING clauses; SQLite may accept aliases or omitted grouped columns.

**Why:** The first PostgreSQL-backed HTTP smoke test exposed queries that worked under SQLite but failed under PostgreSQL, so a successful data migration alone is not enough to prove application compatibility.

**How to apply:** After future schema or database-driver changes, exercise profile, tournament, match, and scoring routes against PostgreSQL rather than relying only on unit tests.

When emulating SQLite `lastrowid`, never probe `lastval()` for inserts into tables without an ID sequence or when the insert supplied an explicit ID. PostgreSQL errors abort the surrounding transaction even if the probe exception is caught, which can silently roll back the original insert.

**Why:** AI conversation inserts use text primary keys; an unconditional `lastval()` probe aborted their transactions, leaving messages without their parent conversation.

**How to apply:** Resolve the inserted table's ID sequence before querying `currval()`, and skip the probe for explicit-ID inserts. Exercise both ID-less and identity inserts against PostgreSQL.