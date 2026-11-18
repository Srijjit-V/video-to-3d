# ADR-0006: ECC is adopted selectively, scoped to this project, without hooks

**Date**: 2026-11-18
**Status**: accepted
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

ECC (affaan-m/ECC) ships hundreds of skills, agents, commands and hook scripts. A global install would load rules in every project and sit beside existing skills; its hooks (dev-server and pre-commit blockers) can fight local servers and git.

## Decision

We pinned commit 3f14a10 of the official repo, read the installer, dry-ran it, installed `--target claude-project --profile minimal --no-hooks` into a scratch folder, then copied 18 skills, 12 agents, 4 commands and the common/python/web rules into `.claude/`. Details: `.claude/ECC.md`.

## Alternatives Considered

### Alternative 1: Global `--target claude`
- **Pros**: What was literally asked
- **Cons**: Changes every project; mixes with existing global skills
- **Why not**: The project-scoped target gives the same files without side effects.

### Alternative 2: Full profile
- **Pros**: Everything
- **Cons**: Hundreds of files, hooks
- **Why not**: Contradicts a selective install.

## Consequences

Small, auditable `.claude/`; scanner grade A. `.claude/`, `CLAUDE.md` and `AGENTS.md` stay local because the owner's global git ignore excludes them.

### Risks

- The project copy has no install receipt, so `ecc doctor` cannot manage it; updates are manual.
