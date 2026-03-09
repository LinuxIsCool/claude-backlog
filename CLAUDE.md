# claude-backlog

Milestone-linked task management. Tasks connect to milestones, milestones live in ventures.

## Quick Start
- `/task <title>` — create a new task
- `/backlog` — show active tasks by priority
- `/backlog plan` — planning session: what to work on next
- `/backlog triage` — review and prioritize open tasks

## Data Location
Tasks: `~/.claude/local/backlog/task-NNN - title.md`
Config: `~/.claude/local/backlog/config.yml`

## The Five Ws
- **What** → venture (strategic container)
- **How** → task (tactical steps, acceptance criteria)
- **Why** → journal (reflections, decisions, meaning)
- **When** → milestone deadlines, task due dates, temporal grounding
- **Where** → inventory (machine, drive, venue, network)
- **Who** → co-venturers (venture), assignees (task)

## Milestone Linking
Tasks link to milestones via `milestone:` frontmatter field.
Milestones live in venture files. The milestone is the joint
between strategic intent (ventures) and tactical execution (tasks).
