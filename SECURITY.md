# Security Policy

## Supported versions

LensWord does not yet have tagged releases; security fixes are applied to the
`main` branch. Once versioned releases exist, this section will be updated to
list which lines still receive fixes.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, use GitHub's private vulnerability reporting for this repository:

1. Go to the repository's **Security** tab.
2. Select **Report a vulnerability** under "Advisories" (or use the direct
   link: `https://github.com/conectlens/lensword/security/advisories/new`).
3. Include as much detail as you can: affected component (frontend/backend),
   steps to reproduce, potential impact, and any suggested remediation.

If private reporting is not enabled on the repository, open a regular issue
that only says a security report is pending and asks a maintainer to enable
private reporting or provide an alternative contact — do not include
exploit details in the public issue itself.

We will acknowledge new reports as soon as possible and aim to provide a
timeline for a fix once the report is triaged.

## Scope and known limitations

Some behaviors are intentional trade-offs for this project's current stage
rather than vulnerabilities — see "Known gaps" in the [README](README.md):

- Access tokens are long-lived (7 days) with no refresh-token rotation.
- There is no rate limiting on authentication endpoints.
- The default `SECRET_KEY` and `docker-compose.yml` defaults are for local
  development only; they **must** be overridden before any non-local
  deployment (see the "Running it" section of the README).

If you believe one of these design trade-offs has a concrete exploitable
impact beyond what's described above, please still report it — context that
changes the risk assessment is useful.
