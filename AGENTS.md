# ERPNext AP Closed Loop Project Memory

This repo is currently being used for the ERPNext AP Closed Loop Receipt Processing pilot.

## Canonical Project State

Read this first when resuming work:

`/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/00 - Project State.md`

Supporting notes:

- `/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/01 - Architecture Decisions.md`
- `/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/02 - Vertical Slice Plan.md`
- `/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/03 - Implementation Log.md`
- `/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/04 - Acceptance Criteria Matrix.md`
- `/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/05 - Open Questions.md`
- `/Users/brandon/Documents/Obsidian/ERPNext-PMO/AP Closed Loop Receipt Processing/06 - Claude-Codex Handoff.md`

## GitHub Epic

`https://github.com/NexeraDigital/erpnext/issues/1`

## Operating Model

- Codex owns orchestration, scoping, GitHub issue/subtask creation, Obsidian state, Claude prompts, integration review, validation, and final closure.
- Claude is the engineering executor for bounded implementation work.
- Keep Obsidian updated after meaningful milestones. GitHub is execution tracking; Obsidian is the living project memory.

## How To Open Obsidian

Open the vault:

```bash
open -a Obsidian "/Users/brandon/Documents/Obsidian/ERPNext-PMO"
```

Open the project state note directly:

```bash
open "obsidian://open?vault=ERPNext-PMO&file=AP%20Closed%20Loop%20Receipt%20Processing%2F00%20-%20Project%20State"
```

## How To Update Obsidian From Codex

Use `apply_patch` for note edits. Update these notes as work progresses:

- `03 - Implementation Log.md` after meaningful milestones.
- `04 - Acceptance Criteria Matrix.md` when ACs become implemented or validated.
- `05 - Open Questions.md` when questions are answered or new blockers appear.
- `00 - Project State.md` when the active slice, current status, or next actions change.

## How To Initiate Claude

Interactive Claude from the repo:

```bash
cd /Users/brandon/Documents/GitHub/Nexera/erpnext
claude
```

Non-interactive architecture or implementation prompt:

```bash
cd /Users/brandon/Documents/GitHub/Nexera/erpnext
claude -p --permission-mode dontAsk --effort high "PROMPT"
```

For read-only architecture review, constrain tools:

```bash
claude -p --permission-mode dontAsk --allowedTools 'Read,Grep,Glob,Bash(rg *),Bash(gh issue view *),Bash(sed *),Bash(head *),Bash(find *)' --effort high "PROMPT"
```

For implementation work, give Claude a bounded subtask, ownership boundaries, relevant AC ids, and a reminder to update no unrelated files.

