# Database migrations

`0001_initial.sql` is the production PostgreSQL/pgvector reference schema. The local MVP uses
file repositories so it can run without a database. Production adapters should preserve the
repository interfaces and execute migrations through Alembic, Flyway or the platform's normal
migration system.
