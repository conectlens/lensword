# Verification actually run

- **Backend: 96/96 tests passing** (`cd apps/backend && .venv/bin/pytest`) — SM-2
  scheduler edge cases, badge thresholds, full auth/group/word/room/review/
  mnemonic/settings/admin flows, cross-user permission checks, cascade deletes.
  Also boot-tested with a real `uvicorn` process and `curl`, not just
  `TestClient`.
- **Frontend: lints clean** (`eslint`), **type-checks and builds clean**
  (`tsc -b && vite build`), **16/16 unit tests passing** (`vitest run`).
- **Ollama suggestions checked live** against a real daemon running
  `llama3.2`, via `uvicorn` + `curl` rather than mocks. All three documented
  states were observed end to end: `ok` with generated text, `disabled` with
  no AI settings present, and `unavailable` with the provider pointed at a
  port nothing is listening on. See
  [docs/local-ai-ollama.md](local-ai-ollama.md).
- **The Ollama walkthrough was followed literally from a clean shell**
  — fresh virtualenv, `pip install`, `.env`, boot, first suggestion — and
  took well under a minute, comfortably inside the 10-minute target.
  Installing Ollama and running `ollama pull llama3.2` are excluded from that
  figure: the model download is several GB and dominated entirely by your
  connection. The MnemoLab suggestion UI itself is covered by unit tests; it
  has not been click-tested in a browser.
- **The web app's Docker Compose quick start has been click-tested end to
  end**: register, complete onboarding, create a group, add words with
  translations and mnemonics, run a forced-recall review session, create a
  Mind Palace room, and place a word on its canvas. The screenshots in the
  root README were captured from that session, not staged.
- Three real bugs were caught and fixed by the test suite along the way: an
  SM-2 interval that could overflow on long correct streaks, a naive/aware
  datetime mismatch against SQLite, and a SQLAlchemy identity-map staleness bug
  where placements/attempts added mid-request didn't show up in the response.

# Known gaps

- Alembic manages schema changes. Run `cd apps/backend && alembic upgrade head`
  before a direct local server start; the Docker backend runs this automatically.
- No refresh-token rotation — a single 7-day access token. Fine for an MVP, not
  for a production launch.
- Blog/About marketing pages from the templates aren't built — the landing page
  is real; a full blog would need a content backend, which felt out of scope for
  the app itself.
- MnemoLab image generation is intentionally not implemented — that needs
  real credentials and an infrastructure decision for you to make, not
  something to fake. AI *mnemonic* suggestions are implemented and opt-in via
  Ollama.
- Scheduled notification delivery **is** implemented: a durable job dispatches
  due reminders, claims each occurrence so two instances cannot deliver it
  twice, and writes a desktop notification the shell polls for. What is still
  missing is *transport* — push and email have no provider and only write to
  the log, and no desktop toast has been observed on a real machine. So a
  reminder fires and is recorded; whether anyone sees it depends on where they
  are running the app.
- Ollama suggestions have been verified with the backend run directly on the
  host. Reaching a host-installed Ollama daemon from inside the Docker
  containers has not been tested, and `http://localhost:11434` will not resolve
  to the host from within a container — see
  [docs/local-ai-ollama.md](local-ai-ollama.md).

See [docs/internal/repo-audit.md](internal/repo-audit.md) and
[docs/internal/evidence-gaps.md](internal/evidence-gaps.md) for a broader,
per-surface evidence review beyond this page's backend/frontend/AI scope.
