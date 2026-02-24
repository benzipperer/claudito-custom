# Claudito (custom fork)

A shameless fork of [Micah Lee's claudito](https://github.com/micahflee/claudito) with added configuration features.

Claudito runs [Claude Code](https://docs.claude.com/claude-code) inside a Docker container so it can't touch anything outside your working directory. (Claudito = Little Claude playing in a sandbox.)

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed and running
- A [Claude Code account](https://claude.ai/) with API access
- [`jq`](https://jqlang.github.io/jq/) (required for config file support)

## Quick Start

```bash
# Install
curl -sSL https://raw.githubusercontent.com/benzipperer/claudito-custom/main/claudito \
  -o /usr/local/bin/claudito && chmod +x /usr/local/bin/claudito

# Run in your project directory
cd ~/my-project
claudito
```

The first run pulls the Docker image, walks you through auth, and starts Claude Code in your current directory.

## Usage

```bash
claudito                           # Start Claude Code in current directory
claudito --version                 # Show claudito version
claudito --help                    # Full help text
claudito --model opus              # Pass args through to Claude Code
claudito --volume /data:/data:ro   # Mount an extra volume
claudito --image my-claudito:dev   # Use a custom Docker image
```

Use `--` to separate claudito flags from Claude Code args if there's ambiguity:

```bash
claudito --volume /data:/data -- --model opus --verbose
```

## Configuration

Claudito supports three layers of configuration, merged in order (later layers override earlier ones for scalar values like `image`; array values like `volumes` and `claude_args` are concatenated):

1. **Global config** — `~/.config/claudito/config.json`
2. **Project config** — `.clauditorc` in the project root
3. **CLI flags**

Both config files use the same JSON format:

```json
{
  "image": "my-claudito:latest",
  "volumes": ["/host/path:/container/path:ro"],
  "claude_args": ["--model", "opus"]
}
```

| Key | Type | Description |
|---|---|---|
| `image` | string | Docker image to use. Project overrides global; CLI `--image` overrides global but conflicts with project. |
| `volumes` | string[] | Extra volume mounts. All layers are concatenated. |
| `claude_args` | string[] | Arguments passed to Claude Code. All layers are concatenated. |

### Global config

Place personal defaults at `~/.config/claudito/config.json` (respects `$XDG_CONFIG_HOME`). No trust prompt needed — it's your own config directory.

```json
{
  "volumes": ["/home/me/.ssh:/home/claudito/.ssh:ro"],
  "claude_args": ["--model", "opus"]
}
```

### Project config (`.clauditorc`)

Place a `.clauditorc` in your project root for project-specific settings. On first use, claudito prompts you to review and trust the file. If the file changes, you'll be prompted again.

```bash
claudito trust          # Pre-trust the .clauditorc in the current directory
claudito trust --list   # List all trusted directories
claudito untrust        # Remove trust for the current directory
```

Trust state is stored at `~/.config/claudito/trusted.json`.

### Skipping config

```bash
claudito --no-config           # Skip all config (global + project)
claudito --no-project-config   # Skip .clauditorc only, still load global
```

## Custom Images

Use `--image` or set `image` in a config file to run a custom Docker image. Custom images should be based on `micahflee/claudito`. The default image is always pulled fresh; custom images use the local copy if available.

```bash
claudito --image my-claudito:latest
```

## Authentication

Claude Code prompts for authentication on first run. Credentials persist in a Docker named volume (`claudito-home`) across container runs, separate from any host Claude Code installation.

## What's different from upstream

- **Global config** (`~/.config/claudito/config.json`) for personal defaults across all projects
- **Project config** (`.clauditorc`) with trust-on-first-use verification
- **Custom image** support (`--image` flag and config key)
- **Extra volume mounts** (`--volume` / `-V` flag and config key)
- **`--no-config` / `--no-project-config`** flags for selective config skipping
- **Three-layer config merge** (global + project + CLI) with source-annotated launch summary
