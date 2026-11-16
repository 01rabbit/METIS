# Claude Code integration for METIS

Install once from the repository root:

```sh
mkdir -p .claude && cp -R integrations/claude-code/skills integrations/claude-code/agents integrations/claude-code/commands .claude/
```

This adds the `metis` project skill, the `/ctf` command, and eight `ctf-*`
subagents. Re-run the copy after updating METIS. Then start with
`./start --agent claude`.

If Claude Code's sandbox is enabled, METIS network commands go through its
proxy automatically. Add every host the problems use to the sandbox network
allowlist (for ksnctf: `ksnctf.sweetduet.info` and the challenge server host
named in the statements). No command needs to run outside the sandbox.

Optional permissions (`.claude/settings.json`) that reduce prompts while keeping
the private state database unreadable:

```json
{
  "permissions": {
    "allow": ["Bash(.venv/bin/metis:*)", "Bash(file:*)", "Bash(strings:*)", "Bash(xxd:*)"],
    "deny": ["Read(./.metis-state/*.sqlite*)", "Bash(sqlite3:*)", "Read(./.env)", "Read(./.env.*)"]
  }
}
```

### Dynamic analysis (`metis sandbox`) inside Claude Code's sandbox

`metis sandbox` drives Docker/OrbStack through its Unix socket, which Claude
Code's sandbox blocks by default. Two options; choose one deliberately, since
either lets that command reach the container engine:

- Exclude only METIS's sandbox commands from Claude Code's sandbox (METIS then
  enforces its own container isolation: no network, read-only root, no host
  mounts, unprivileged user):

  ```json
  { "sandbox": { "excludedCommands": [".venv/bin/metis sandbox *"] } }
  ```

  Call it without pipes or redirects (`--stdin-file`, `--script`), because a
  chained command stays sandboxed.
- Or allow the engine socket with `sandbox.network.allowUnixSockets` (for
  OrbStack: `~/.orbstack/run/docker.sock`). The Claude Code docs warn that this
  grants host-level access through the Docker API to every sandboxed command.

