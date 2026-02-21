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

## 2. Network Isolation Controls

### Problem

Claudito's value proposition is sandboxing — the agent can't reach the host OS outside the project directory. But the container currently has unrestricted network access. The agent can make arbitrary HTTP requests, install packages, and in theory exfiltrate source code to any endpoint. For security-conscious users and enterprise environments, this is a significant gap in the isolation story.

### Modes

Three levels of network access, controlled via CLI flag or `.clauditorc`:

1. **`--network=full`** (current default, no change) — Unrestricted network access. The agent can reach any host.

2. **`--network=none`** — Complete network isolation. Maps directly to Docker's `--network=none`. The agent can only work with files already present in the mounted directory. No package installs, no API calls, no DNS. Useful for pure code review/refactoring tasks where the agent needs nothing from the internet.

3. **`--network=api-only`** — Allow only the traffic needed for Claude Code to function (Anthropic API endpoints) while blocking everything else. This is the most useful middle ground: the agent can think but can't reach arbitrary servers.

### Implementation approach for `api-only`

Docker's `--network=none` is trivial. The `api-only` mode is more involved. Options:

- **DNS-based filtering**: Run a lightweight DNS proxy (or use `--dns` with a restricted resolver) that only resolves allowed domains. Simple but bypassable if the agent hardcodes IPs.
- **iptables rules in entrypoint**: The entrypoint script could set up iptables rules allowing outbound traffic only to specific CIDR ranges (Anthropic API IPs). Requires `NET_ADMIN` capability, which partially undermines the security model.
- **Docker network with egress policy**: Create a custom Docker network with an outbound proxy or firewall container that whitelists traffic. More infrastructure but cleanest isolation.
- **Simplest viable approach**: Start with just `full` and `none`. These require zero additional infrastructure — `none` is a single Docker flag. The `api-only` mode can come later as a separate effort once there's demand.

### Behavior

- **Default: `full`** (preserves current behavior, no breaking change).
- The `.clauditorc` key `"network"` accepts `"full"`, `"none"`, or (eventually) `"api-only"`.
- CLI flag `--network=<mode>` overrides `.clauditorc`.
- When `none` is active, print a notice at launch: `Network access disabled. The agent cannot install packages or make HTTP requests.`

### CLI flags

- `--network=full` — Unrestricted (default)
- `--network=none` — No network access
- `--network=api-only` — (future) Anthropic API only

### Implementation notes

- `--network=none` is a one-line change to the `docker run` invocation.
- The wrapper should validate the `--network` value and error on unrecognized modes.
- `api-only` is a meaningful project on its own and should not block shipping `full`/`none`.
- Consider that `--network=none` also blocks the agent from authenticating with Anthropic if credentials aren't already cached in the config volume. The launch notice should mention this.
