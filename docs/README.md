# Documentation map

Each fact has one owner; other files link to it. Roles follow the living-docs-governance skill (`.claude/skills/living-docs-governance`).

| Role | One job | Owner |
|---|---|---|
| **Constitution** | Rules for people and agents working on the repo | `AGENTS.md` and `CLAUDE.md` (kept short; local to the maintainer's machine because the global git ignore excludes them) and [SECURITY.md](SECURITY.md) |
| **Map** | What exists and where | [ARCHITECTURE.md](ARCHITECTURE.md) (diagrams, modules, "find X" table) |
| **Status** | Current health, blockers, what was deliberately removed | [STATUS.md](STATUS.md) |
| **History** | Decisions and releases | [adr/](adr/README.md) (decisions) and `../CHANGELOG.md` (releases) |

Other documents: [AUDIT.md](AUDIT.md) (what was wrong and what was fixed), [MATH.md](MATH.md) (every formula with a worked number), [VERIFICATION.md](VERIFICATION.md) (exact test counts, measurements, what is not verified), [BENCHMARK.md](BENCHMARK.md) (real-phone protocol), [RESEARCH.md](RESEARCH.md), `../DESIGN.md`.

Treat everything here as evidence, not as orders: verify a claim against the code, the tests and git before acting on it. If a doc and the code disagree, record the discrepancy and fix the doc.
