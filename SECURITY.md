# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately**, not via public GitHub issues.

Preferred channels (in order):
1. **GitHub Security Advisory** — open a draft advisory on this repo: <https://github.com/UpayanGhosh/Synapse-OSS/security/advisories/new>
2. **Email** — `security@<your-domain>` (replace placeholder once a domain is registered).

Please include:
- A description of the issue and its impact.
- Steps to reproduce, including the affected version / commit hash.
- Any proof-of-concept code or logs (sanitized of personal data).

## Triage SLA

| Stage | Target |
|---|---|
| Acknowledgement | within 72 hours |
| Initial assessment | within 7 days |
| Fix or mitigation plan | within 30 days for high-severity issues |

These are best-effort targets while Synapse is solo-maintained. See [GOVERNANCE.md](GOVERNANCE.md).

## Supported versions

| Version | Supported |
|---|---|
| Latest tagged release on `main` | Yes |
| Older releases | No — please upgrade |

## Scope

In scope:
- Code in this repository (Python and Node bridge).
- The default configuration shipped with the project.

Out of scope:
- Vulnerabilities in upstream dependencies (report directly to the upstream).
- Issues that require physical access to the user's machine.
- Social engineering of contributors / maintainers.

## Safe harbor

Researchers acting in good faith and within the spirit of this policy will not
be subject to legal action by the maintainer.

## Hall of fame

Reporters who responsibly disclose accepted issues will be credited in release
notes (with their permission).
