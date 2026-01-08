# Notes Directory

This directory contains technical documentation and debugging notes for the Thoth project.

## Contents

### discord-dom-selectors.md

Comprehensive guide to Discord's web UI DOM structure. Includes:
- Server sidebar selectors
- Message container patterns
- Author/username extraction (Compact vs Cozy mode)
- Content, timestamp, and reaction selectors
- Known issues and debugging tips

**When to reference:** When Discord changes their UI and selectors stop working.

### message-database-schema.md

Documentation of the SQLite database schema:
- Table definitions and relationships
- Upsert behavior for idempotent syncing
- Sync modes (recent vs backfill)
- Data quality requirements
- Future considerations (FTS, embeddings)

**When to reference:** When modifying the database or writing queries.

### sync-debugging-log.md

Chronological log of debugging sessions:
- Problems encountered and their root causes
- Fixes applied with code snippets
- Performance observations

**When to reference:** When troubleshooting similar issues.

---

## Adding Notes

When debugging or making significant changes:

1. Document the problem and symptoms
2. Record investigation steps
3. Note the root cause
4. Include the fix (with before/after code)
5. Add any relevant observations

This helps future debugging and onboarding.
