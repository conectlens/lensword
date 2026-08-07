# Local development (without Docker)

Docker Compose (see the root [README](../README.md#quick-start)) is the
fastest verified path to a running instance. Run the backend and frontend
directly when you're developing on the code itself.

```bash
# Backend — defaults to SQLite, so no database server is needed
cd apps/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload

# Frontend (separate terminal)
cd apps/frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for running the test suites, lint,
and the pull request process.

## Database

The Compose stack runs **Postgres**, and the backend waits for it to pass a
health check before starting, because it runs migrations on boot. The database
port is not published to the host — nothing outside the stack needs it, and the
default `lensword`/`lensword` credentials are only safe while it is
unreachable. Override `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`
for anything that is not a throwaway local environment.

To point the backend at a database you already run, set `DATABASE_URL`:

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/lensword
```

The `+psycopg` suffix is required — without it SQLAlchemy looks for `psycopg2`,
which this project does not depend on. `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`
bound the connection pool; against a managed plan's connection cap, the number
that matters is their sum multiplied by how many backend instances you run.

Alembic manages schema changes. Run `cd apps/backend && alembic upgrade head`
before a direct local server start; the Docker backend runs this
automatically.
