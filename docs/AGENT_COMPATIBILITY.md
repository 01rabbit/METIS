# AI agent compatibility

METIS core commands are model- and provider-neutral. URL intake, artifact
analysis, submission, hypotheses, knowledge, and delegation plans are local CLI
commands that exchange JSON and use SQLite. They do not call a model API.

Run `./start`; it chooses the first installed CLI in this order: Codex, Claude,
Gemini, OpenCode, Aider. Select one with `./start --agent NAME` and show discovery
with `./start --list`. Extra arguments are passed unchanged to the selected CLI.

The Codex adapter is tested and enables Daybreak, multi-agent support, and
automatic approval review. Claude and Gemini receive equivalent repository
instructions through `CLAUDE.md` and `GEMINI.md`. OpenCode and Aider are launched
in the repository and can use `AGENTS.md`; their multi-agent behavior depends on
the installed version and plugins. These four CLIs were not installed in the
validation environment, so METIS does not invent provider-specific flags.

An agent without native subagents can execute each assignment returned by
`metis plan RUN_ID` sequentially. The plan, evidence schema, verifier, and
memory behavior are unchanged.
