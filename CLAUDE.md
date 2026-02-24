# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claudito is a Docker container that runs Claude Code in a sandboxed environment. This is a fork of [micahflee/claudito](https://github.com/micahflee/claudito) with added configuration features. The project consists of:

- **Dockerfile**: Multi-architecture Ubuntu 24.04 image with development tooling
- **entrypoint.sh**: Minimal entrypoint that `exec`s Claude Code with passed arguments
- **claudito script**: Bash wrapper that manages config loading, trust verification, image pulling, and Docker invocation
- **GitHub Actions workflows**: Automated builds on push, PRs, and daily cron

## Key Architecture

### Docker Image Structure

The Dockerfile builds a minimal development environment with:
- Python 3 runtime with pip and virtualenv
- Node.js LTS with npm and yarn (required for Claude Code)
- Database clients: PostgreSQL, MySQL, SQLite, Redis (clients only, no servers)
- Build tools: build-essential, git, and common C/C++ libraries (libssl-dev, libffi-dev)
- Claude Code installed as the `claudito` user (enables auto-updates without sudo)

**Security model**: The container runs as unprivileged user `claudito` (UID 1000) with sudo access. The wrapper script applies security restrictions via Docker flags (`--cap-drop=ALL` with selective `--cap-add`).

### Volume Mounts

The `claudito` script always mounts:
1. **Working directory**: `$(pwd)` → `/src` in container (read-write bind mount)
2. **Home directory**: Docker named volume `claudito-home` → `/home/claudito` (persists auth, config, and state)

Additional volumes can be added via `--volume` flag, `.clauditorc`, or global config.

### Three-Layer Configuration

The script loads configuration from three sources, merged in order:

1. **Global config** — `${XDG_CONFIG_HOME:-~/.config}/claudito/config.json`
2. **Project config** — `.clauditorc` in the working directory
3. **CLI flags** — `--image`, `--volume`, and any remaining args passed to Claude Code

**Merge rules:**
- `image`: scalar, later layers win (project over global, CLI over global). CLI `--image` conflicts with project `image` (error).
- `volumes`: concatenated (global + project + CLI)
- `claude_args`: concatenated (global + project + CLI)

**Trust model**: Global config requires no trust prompt (user's own config dir). Project `.clauditorc` uses trust-on-first-use: the script hashes the file and prompts the user to approve it. If the file changes, the user is prompted again. Trust state is stored at `~/.config/claudito/trusted.json`.

**Key variables in the script:**
- `GLOBAL_*` — values from global config
- `PROJECT_*` — values from `.clauditorc`
- `CLI_*` — values from command-line flags
- `ALL_VOLUMES`, `ALL_CLAUDE_ARGS` — final merged arrays passed to `docker run`
- `IMAGE_SOURCE` — tracks where the image came from (`default`, `global`, `project`, `cli`)

### Image Pull Strategy

- Default image (`micahflee/claudito:*`): always pulled to get latest version
- Custom images: use local copy if available, pull only if not found locally

## Common Commands

### Build Docker Image Locally
```bash
docker build -t micahflee/claudito:latest .
```

### Test the Container
```bash
./claudito
./claudito --help
./claudito --version
./claudito --no-config --help   # Skip all config files
```

### GitHub Actions

**`docker-build-pr.yml`** — Builds multi-arch image on PRs (no push, no secrets required).

**`docker-build.yml`** — Builds and pushes to Docker Hub on push to `main`, daily cron (2 AM UTC), version tags, and manual dispatch. Required secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

## Development Guidelines

### Dockerfile Modifications

**Layer ordering for caching** (least to most frequently changing):
1. System packages and core tools
2. Python and Node.js runtimes
3. Claude Code (changes frequently, hence daily rebuilds)
4. System upgrades (final layer before user creation)

### Updating the claudito Script

The script uses `exec` to replace itself with the Docker process, ensuring signals pass through correctly. Any changes should preserve:
- Security options (`--cap-drop=ALL` with selective `--cap-add`)
- The three-layer config merge order (global → project → CLI)
- Trust verification for `.clauditorc` (never auto-trust project configs)
- The `IMAGE_SOURCE` tracking for correct `--image` conflict detection

### Testing Multi-Architecture Builds

```bash
docker buildx create --use
docker buildx build --platform linux/amd64,linux/arm64 -t test .
```

## Important Files

- `Dockerfile` — Image definition with all development tools
- `entrypoint.sh` — Container entrypoint (execs `claude` with args)
- `claudito` — Wrapper script: config loading, trust, image pull, Docker invocation
- `.github/workflows/docker-build-pr.yml` — CI for PR validation (build only)
- `.github/workflows/docker-build.yml` — CI/CD for Docker Hub (build and push)
- `README.md` — User-facing documentation

## Notes

- Claude Code is installed as the `claudito` user (not root) to enable auto-updates without permission errors
- npm is configured with a user-local prefix (`~/.npm-global`) for the claudito user
- The daily cron build ensures users get the latest `@anthropic-ai/claude-code` even without code changes
- Container runs as non-root user for security but has passwordless sudo for installing additional tools
