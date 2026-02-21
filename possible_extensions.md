# Possible Extensions

## 1. Host-Side Project Snapshots

### Problem

Claudito bind-mounts the project directory read-write so the user can inspect changes in real-time with their IDE. But if the agent makes destructive changes, there's no undo. A snapshot taken inside the container (e.g., a git branch) is useless — the agent could delete it.

### Approach

The `claudito` wrapper script runs on the host before Docker launches. It can write to `~/.config/claudito/snapshots/`, a path that is never mounted into the container. The agent has zero access to this location.

- **Git repos**: Use `git bundle create` to capture the full repo state in a single delta-compressed file.
- **Non-git directories**: Fall back to a tarball (`tar -czf`).

### Behavior

- **Disabled by default.** Enable with `--snapshot` flag or `"snapshot": true` in `.clauditorc`.
- Before `docker run`, create the snapshot file at `~/.config/claudito/snapshots/<dirname>-<timestamp>.bundle` (or `.tar.gz`).
- Print a one-liner after the container exits: `To restore pre-session state: claudito snapshot --restore`

### Restore

New subcommand:

```
claudito snapshot --list              # list available snapshots for current directory
claudito snapshot --restore           # restore most recent snapshot for current directory
claudito snapshot --restore <id>      # restore a specific snapshot
```

For git bundles, restore clones the bundle to a temp directory, replaces `.git`, and runs `git checkout .`. For tarballs, restore replaces the directory contents.

### Space management

Snapshots can accumulate quickly if a user runs claudito on a project hundreds of times. Mitigations:

- **Auto-prune policy**: Keep only the N most recent snapshots per project directory (default: 5). Older snapshots are deleted automatically when a new one is created.
- **`claudito snapshot --prune`**: Manual command to delete all snapshots for the current directory, or all snapshots globally with `--all`.
- **Size warning**: If total snapshot storage exceeds a threshold (e.g., 1 GB), print a warning with instructions to prune.
- **`.clauditorc` configuration**: `"snapshot_keep": 3` to override the default retention count per project.

### CLI flags

- `--snapshot` — Enable snapshot for this session
- `--no-snapshot` — Explicitly disable (useful to override `.clauditorc`)

### Implementation notes

- Roughly 10-15 lines of bash in the wrapper script for snapshot creation.
- A new `snapshot` subcommand (alongside existing `trust`/`untrust`) for list/restore/prune.
- `git bundle create --all` captures all branches and tags but not uncommitted working tree changes. To also capture uncommitted work, the wrapper could run `git stash create` first and include that ref in the bundle. This is worth considering but adds complexity.
