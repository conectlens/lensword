# Evidence Gaps Requiring Manual Verification

> Things the repository-audit (#269) could not confirm through static
> inspection of code, config, and GitHub metadata. Later issues that touch
> these areas (#274 desktop docs, #276 MCP docs, #282 CI enforcement) should
> either close these gaps or continue to mark the corresponding claims as
> unverified rather than asserting them as fact.

1. **Desktop installers have never been run on any real OS.** CI builds and
   unit-tests the Tauri app on Linux/macOS (and, separately, in
   `release.yml`, all three platforms on a tag push), but no `.dmg`, `.msi`,
   `.exe`, `.deb`, or `.AppImage` has ever actually been installed and
   exercised by a human. Native toast notifications are unit-tested but
   never observed on a packaged build. Requires a human (or a dedicated CI
   job with real OS runners performing an install+launch smoke test) to
   verify. Tracked separately by open issue #65.

2. **No branch-protection configuration is visible from the repository
   content.** `ci.yml`'s own comment states the `backend-postgres` job is
   not currently a required status check, while `CHANGELOG.md` (issue #164)
   describes making it required. Repository branch-protection rules are a
   GitHub settings artifact, not something visible in the checked-out repo
   — resolving this discrepancy requires checking the actual repo settings
   (Settings → Branches) or the GitHub API with sufficient permissions.

3. **No live interop test exists between the MCP server's remote HTTP
   transport and a real third-party MCP client** (Claude Desktop, Cursor,
   etc.) — it has only been exercised against its own stdio implementation
   in tests. Verifying this requires an actual session against a real MCP
   host with `REMOTE_MCP_ENABLED=true` and TLS termination configured.

4. **The browser extension has never been verified against the real Chrome
   Web Store review/packaging process** — install is "Load unpacked" only,
   with zero CI coverage. Whether the extension would pass store review, or
   even build cleanly as a packaged `.crx`, is unverified.

5. **`SECURITY.md`'s "known limitations" section has not been cross-checked
   line-by-line against every later CHANGELOG entry** (e.g., auth
   rate-limiting was added after the file's original limitations list was
   written). A full reconciliation pass was out of scope for this audit and
   should be done by whoever next edits `SECURITY.md`.

6. **`docs/memory-loop-verification.md` is missing.** `ROADMAP.md` (item 6.0)
   and, before this rewrite, `README.md` both referenced it as the evidence
   record for the graduated-acquisition-policy verification work. The file
   does not exist anywhere in the repository's history that this audit could
   find — it was either never committed or was removed without updating its
   referring links. The underlying work is still marked shipped in
   `ROADMAP.md` on the strength of the test coverage described there; only
   the standalone report is missing. If it turns up (e.g. in an old branch or
   someone's local copy), restore it at that path; otherwise the ROADMAP
   entry should eventually cite the actual test files instead of a report
   that doesn't exist.

7. **Docker-to-host Ollama networking** is documented with OS-specific
   caveats (`host.docker.internal` behavior differs by platform) but the
   audit could not independently confirm current behavior on Windows/Linux
   Docker hosts beyond what's already written in the README — this should
   be re-verified by whoever writes the Ollama use-case guide if platform
   behavior is in question.

None of these gaps block issue #269's deliverables (the audit, registry,
and migration map are complete and evidence-based as written); they are
flagged so that downstream issues do not silently assert verified status
for claims that are, in fact, still open.
