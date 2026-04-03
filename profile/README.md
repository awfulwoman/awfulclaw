# profile/

Human-authored files that define who the agent is and how it should behave. Personal — not committed to the repo. Back up with Time Machine, rsync, or your preferred method.

## Contents

- **`PERSONALITY.md`** — Character, tone, and values. Who the agent is.
- **`PROTOCOLS.md`** — Operating rules and procedures. How the agent behaves.
- **`USER.md`** — Facts about you the agent should always know.
- **`CHECKIN.md`** — Short patrol checklist the agent runs periodically to decide whether anything warrants your attention.

## Ownership

You write and maintain these. The agent reads them on every turn; it cannot modify them. Run `scripts/setup.py` to generate starter templates.
