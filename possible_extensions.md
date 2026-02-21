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

## 3. Resource Limits

### Problem

The container currently runs with no CPU, memory, or time constraints. A runaway agent — or simply a large `npm install` / compilation — can consume all host resources, freeze the machine, or fill the disk. This is especially relevant when the agent has full autonomy (dangerously-skip-permissions) and may kick off expensive operations without user intervention.

### Limits to expose

Three categories, all mapping directly to existing Docker flags:

1. **Memory**: `--memory` flag, passed through to Docker's `--memory`. Caps the container's RAM usage. When exceeded, the OOM killer terminates the process rather than swapping the host to death.

2. **CPU**: `--cpus` flag, passed through to Docker's `--cpus`. Limits how many CPU cores the container can use. Prevents the agent from saturating all cores during builds or tests.

3. **Timeout**: `--timeout` flag, implemented in the wrapper script. Kills the container after N minutes. Useful for unattended runs, CI pipelines, or just a safety net against sessions that run indefinitely.

### Behavior

- **All disabled by default** (preserves current behavior).
- Configurable via CLI flags or `.clauditorc` keys (`"memory"`, `"cpus"`, `"timeout"`).
- CLI flags override `.clauditorc` values.
- When limits are active, print them at launch so the user knows what constraints are in effect.

### CLI flags

- `--memory=<limit>` — Container memory limit (e.g., `4g`, `512m`). Passed directly to `docker run --memory`.
- `--cpus=<count>` — CPU core limit (e.g., `2`, `0.5`). Passed directly to `docker run --cpus`.
- `--timeout=<minutes>` — Kill the container after this many minutes.

### `.clauditorc` example

```json
{
  "memory": "4g",
  "cpus": 2,
  "timeout": 60
}
```

### Timeout implementation

The timeout cannot be a Docker flag — Docker doesn't have a native run timeout. Two approaches:

- **Background timer in the wrapper**: After `docker run`, the wrapper's PID is replaced via `exec`. Instead, the wrapper could spawn `docker run` as a child process, start a background timer with `timeout` or a subshell (`sleep N && docker kill`), and wait. This changes the current `exec docker run` pattern but is straightforward.
- **Entrypoint-based timer**: The entrypoint script starts a background `sleep` and then execs Claude. When the sleep expires, it sends SIGTERM. Simpler to implement but the timer runs inside the container where the agent could theoretically kill it.

The wrapper-based approach is more robust since the timer runs on the host, outside the agent's reach.

### Implementation notes

- `--memory` and `--cpus` are each a single argument appended to the `docker run` invocation. Minimal code change.
- The wrapper should validate formats (e.g., memory must match Docker's syntax like `512m`, `2g`; cpus must be a positive number).
- Timeout is the most complex piece due to replacing the `exec` pattern. Consider implementing memory/cpu first and timeout as a follow-up.
- When a timeout kills the container, print a clear message: `Session terminated after N minutes (--timeout).`

## 4. Environment Variable and File Passthrough

### Problem

There's no mechanism to inject environment variables or configuration files into the container. Users frequently need API keys, database URLs, language-specific config files (`.Renviron`, `.env`), or feature flags available inside the container. Currently, the only workaround is mounting files manually with `--volume`, which requires knowing the correct container path.

### Two distinct needs

This feature actually covers two different things that look similar but behave differently:

1. **Environment variables in the container** — Real env vars visible to every process. Useful for API keys, config values, and anything the agent or its subprocesses might need. Docker supports this natively via `-e KEY=VALUE` and `--env-file`.

2. **Configuration files mounted at specific paths** — Some tools read their own config files from specific locations (e.g., R reads `~/.Renviron`, Python reads `.env` via dotenv, Node reads `.npmrc`). These need to exist as files inside the container, not just as env vars.

### Example: `.Renviron`

`.Renviron` illustrates the ambiguity. It's a file with `KEY=VALUE` lines that R reads at startup. A user could want either:

- **Mount the file** so R specifically reads it: `--volume ~/.Renviron:/home/claudito/.Renviron:ro`. Only R sees these values.
- **Parse it as env vars** so every process sees them: `--env-file .Renviron`. Docker's `--env-file` format is compatible with `.Renviron` (both use `KEY=VALUE` with `#` comments). But now the values are exposed to all processes, not just R.

The right choice depends on the user's intent, and claudito shouldn't assume.

### Possible CLI surface

```bash
# Pass individual env vars
claudito --env API_KEY=sk-123 --env DEBUG=true

# Pass an env file (Docker --env-file format: KEY=VALUE lines, # comments)
claudito --env-file .env

# Forward specific host env vars into the container
claudito --forward-env API_KEY,DATABASE_URL
```

File mounting is already handled by `--volume` but the UX is rough for common cases. A shorthand could help but risks scope creep (see open questions below).

### `.clauditorc` support

```json
{
  "env": {
    "DEBUG": "true",
    "NODE_ENV": "development"
  },
  "env_file": ".env"
}
```

### Open questions

1. **`--env-file` vs file mounting**: Should claudito offer both, or just `--env-file` (real env vars) and let `--volume` handle file mounting? Adding a file-mount shorthand (e.g., `--config ~/.Renviron`) introduces questions about target paths, naming conventions, and scope creep.

2. **Trust implications**: If `.clauditorc` specifies `"env_file": ".env"`, that file gets loaded automatically when the user trusts the config. This could be a vector for leaking secrets — a malicious `.clauditorc` committed to a shared repo could silently inject env vars from a file the user didn't intend to expose. Should `env_file` be excluded from `.clauditorc` and only allowed via CLI? Or should the trust prompt explicitly list which env file will be loaded?

3. **`--forward-env` ergonomics**: Forwarding host env vars is convenient but blurs the isolation boundary. Should it require explicit opt-in per variable (safer), or support wildcards like `--forward-env "AWS_*"` (more convenient, riskier)?

4. **Overlap with `--volume`**: Mounting `.Renviron` at `/home/claudito/.Renviron:ro` already works today. Is the friction high enough to justify a dedicated feature, or is better documentation of the `--volume` approach sufficient?

### Implementation notes

- `--env` and `--env-file` map directly to Docker's `-e` and `--env-file` flags. Minimal wrapper code.
- `--forward-env` would read the named variables from the host environment and pass them via `-e`.
- The trust system already displays config summaries when prompting. If `env_file` is allowed in `.clauditorc`, the trust prompt should show the file path and ideally the variable names (not values) it contains.
- Start with `--env` and `--env-file` CLI flags only. Defer `.clauditorc` integration until the trust implications are resolved.

## 5. Pre-Launch Setup Commands

### Problem

Most real projects require setup before the agent can be productive — `npm install`, `pip install -r requirements.txt`, `bundle install`, `apt install golang-go`, etc. Currently the user has two options, both with friction:

1. **Build a custom Docker image** with the dependencies baked in. Works but requires maintaining a Dockerfile per project and rebuilding when dependencies change.
2. **Let the agent do it** on every session. Wastes time and API tokens as the agent rediscovers and reinstalls the same dependencies each run.

Neither is great for the common case: a project with a `package.json` or `requirements.txt` that just needs a one-liner before the agent starts.

### Approach

Allow setup commands to run inside the container after it starts but before Claude launches. The entrypoint script would execute these commands sequentially, and only start Claude if they all succeed.

### `.clauditorc` support

```json
{
  "setup": [
    "npm install",
    "pip install -r requirements.txt"
  ]
}
```

The setup commands run as the `claudito` user inside the container, with access to the mounted source directory at `/src`. They have sudo available for system-level installs like `sudo apt install -y golang-go`.

### CLI support

```bash
# One-off setup command
claudito --setup "npm install"

# Multiple setup commands
claudito --setup "sudo apt install -y golang-go" --setup "go mod download"
```

CLI `--setup` commands run after `.clauditorc` setup commands (if both are present).

### Behavior

- Setup commands run sequentially in order.
- If any setup command fails (non-zero exit), claudito prints the error and aborts — it does not launch Claude. This prevents the agent from starting in a broken environment.
- Setup output is printed to the terminal so the user can see progress (dependency installs can be slow).
- Setup runs every time the container starts. Since the container is ephemeral, there's no caching between sessions — `npm install` runs fresh each time.

### Caching consideration

The "runs every time" behavior is the main downside. For large projects, `npm install` can take minutes. Possible mitigations:

- **Volume-mount the cache directory**: Mount `node_modules`, `.venv`, or other dependency directories as named Docker volumes so they persist across sessions. This could be a `.clauditorc` pattern: combine `"volumes"` with `"setup"` so the install is fast on repeat runs.
- **Layer caching via custom image**: For teams, the recommended path for heavy setup is still a custom image. Setup commands are for lightweight, per-project needs.
- **Conditional setup**: A future refinement could skip setup if a marker file exists (e.g., `node_modules/.claudito-setup-done`), but this adds complexity and staleness risks.

### Trust implications

Setup commands in `.clauditorc` are covered by the existing trust system — the user must trust the config before it takes effect, and the trust prompt already shows a config summary. The summary should include the setup commands so the user sees exactly what will run.

A malicious `.clauditorc` could include destructive setup commands (`rm -rf /src/*`), but this is no worse than the agent itself having write access. The trust prompt is the gate.

### Implementation notes

- The entrypoint script (`entrypoint.sh`) would need to accept and execute setup commands before `exec claude "$@"`. This could be done via an environment variable (e.g., `CLAUDITO_SETUP`) that the wrapper sets, containing the commands as a newline-delimited string or a JSON array.
- Alternatively, mount a setup script file into the container and have the entrypoint source it.
- The wrapper already constructs the `docker run` invocation, so injecting `-e CLAUDITO_SETUP=...` is straightforward.
- Keep setup output visible (don't redirect to /dev/null) — users need to see install failures.
