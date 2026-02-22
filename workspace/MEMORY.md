# MEMORY.md - Core Learnings & Preferences

## Communication & Language
- **"Kal" (Tomorrow):** When the User says "Kal" late at night (e.g., 1 AM - 4 AM), he usually means "Later today / After I wake up", NOT the next calendar date. Always clarify or assume the current awakening cycle.
- **Review Protocol (Verified Users):** **ENABLED.** The User has authorized direct messaging to verified contacts. No need to send drafts for review first unless specifically requested for a sensitive strategy. Maintain high EQ and personalized persona.

## System Maintenance
- **Archived Files:** The directory `_archived_memories/` is strictly off-limits. Do not read or search files inside it unless explicitly asked to retrieve a specific historical fact not found in the DB.
- **Database Backups:** Automated backups for `memory.db` are stored in `db/backups/`. A cron job runs every 12 hours (00:00, 12:00 IST) executing `db/backup_db.sh`. It keeps the last 7 backups (gzipped).