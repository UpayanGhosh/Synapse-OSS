# Governance

## Current state

Synapse is currently maintained by one person — [@UpayanGhosh](https://github.com/UpayanGhosh).
All decisions on architecture, releases, and merging are made by the maintainer.
This is a known bus-factor risk; users committing personal AI to this stack
should weigh that.

## Decision making

- Roadmap shifts are decided by the maintainer.
- Trade-off discussions happen on PRs and GitHub Issues.
- Architectural decisions of any size are documented in commit messages,
  ARCHITECTURE.md, and (for high-impact ones) PRODUCT_ISSUES.md.

## Pull requests

- Welcome — please open an Issue first for non-trivial changes so we can align
  on approach before you write code.
- Standard checks (tests, lint) must pass.
- Squash-merged by default to keep `main` linear.

## Becoming a co-maintainer

The bar is sustained, review-quality contributions over **3+ months** —
specifically:
- ≥ 5 merged non-trivial PRs (bug fixes count, typo fixes don't).
- Demonstrated reviewing of others' PRs with substantive feedback.
- Familiarity with the SBS, memory, and routing subsystems.

If you meet that bar, the maintainer may invite you as a co-maintainer.
Co-maintainers share merge rights but not unilateral release authority — that
remains with the original maintainer until co-maintainer pairs converge on a
release-rotation policy.

## Releases

- Versioning: SemVer.
- The maintainer cuts releases. There is no fixed cadence.
- Release artifacts are signed via SBOM + cosign — see [SECURITY.md](SECURITY.md).

## Forking

This is OSS (license per LICENSE in the repo root). You are free to fork and run
your own instance; please don't redistribute personal-data fixtures or seeds.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Violations should be reported to
the maintainer via the channels listed in [SECURITY.md](SECURITY.md).
