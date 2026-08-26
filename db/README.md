# db/

SQL migration files live here, named sequentially:

    001_initial_schema.sql
    002_add_index_on_posted_at.sql
    ...

Run them manually against your Postgres database for now.
Each file is idempotent (uses IF NOT EXISTS / DO $$ guards).
