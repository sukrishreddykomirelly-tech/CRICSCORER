---
name: CricScorer Firestore direction
description: User's chosen database target and safe cutover expectations.
---

Use Cloud Firestore as CricScorer's target application database. Keep PostgreSQL and its records intact until the complete app data-access conversion, Firebase credentials, and migration validation are complete. The user plans to add Firebase credentials later.

**Why:** The user explicitly chose Firestore after discussing its free quotas and requested a database change.

**How to apply:** Do not delete or abandon PostgreSQL during preparation. Migrate and validate existing records before switching all app reads and writes to Firestore.
