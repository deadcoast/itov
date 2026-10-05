# Development documentation

Read [AGENTS.md](../../AGENTS.md), [TODO.md](../../TODO.md) and the affected feature
contract before editing. Source and tests establish implemented behavior; dated
evidence establishes only the checks performed on that recorded snapshot.

| Document | Purpose |
| --- | --- |
| [Current state](current-state.md) | Product priorities, implemented boundaries and latest retained evidence |
| [Source and test map](source-map.md) | Every top-level application module, its responsibility, relevant tests and contract |
| [CLI inventory](cli-reference.md) | Command families/actions checked against `itov.cli.parser()` |
| [Original design reconciliation](design-status.md) | Numbered design intent versus current code and remaining work |
| [Documentation maintenance](documentation-maintenance.md) | Placement, preservation, link checks and evidence rules |

The [2026-09-22 audit and prototype review](../reports/2026-09-22/README.md) are
historical source assessments. Their phase labels and next-task statements do not
override the current TODO. The [2026-10-03 development profile](../evidence/python-dev-profile-20261003.json)
records the later native import/type-checker repair; it does not qualify GPU models.
