# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in `wsp` or in any of the AWaC stack repositories under the `getGanemo` org, **please do not open a public issue**.

Instead, email **fernando@ganemo.co** with:

- A description of the vulnerability.
- Steps to reproduce.
- The version of `wsp` (`wsp --version`).
- Any proof-of-concept code or commands.

You will get an acknowledgment within **3 business days**.

## What we treat as a vulnerability

- Anything that lets an unrelated actor read or modify another user's local filesystem outside the workspace directory.
- Anything that exfiltrates secrets from `~/.devvault/` or environment variables to a remote endpoint.
- Anything that triggers arbitrary code execution from a hostile `workspace.yml`, `awac.yml`, or stack repo.
- Anything that bypasses the GitHub authentication required to clone private stack repos.

## What we don't treat as a vulnerability

- Failures caused by the user voluntarily granting `gh` write scope to a hostile org.
- Compromised credentials in `~/.devvault/` resulting from user-side disk access.
- Any issue that requires local root or admin already.

## Disclosure timeline

1. Day 0: report received, acknowledgment within 3 business days.
2. Day 1–14: triage + fix.
3. Day 14–30: release patched version.
4. Day 30+: public advisory + CVE if applicable. We credit reporters by name unless asked otherwise.

## Supported versions

Security fixes go to the latest minor release. We don't backport to older minors.
