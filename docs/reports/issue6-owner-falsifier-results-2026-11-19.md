# Issue #6 owner/falsifier study result (2026-11-19)

## Frozen design and execution

The prospective design is in [the preregistration](issue6-owner-falsifier-preregistration-2026-11-19.md). It compares one owner with a sequential owner, fresh-context falsifier, and conditional repair on 30 new paired synthetic ordering tasks. Both arms use one active slot, the same model, 14 reserved calls, nine actions, nine stored candidates, and a 600-second run deadline. The falsifier sees public constraints and the provisional order, not a protected answer. No CTF service or official verifier was contacted.

The run completed all 60 planned arms without changing the task set or protocol after model execution began. It used Codex CLI `0.169.0`, `gpt-6.1-sol`, low reasoning effort, and the local native CLI whose SHA-256 is `739cda86e15d30a6e2b40cf8dcbbfb988aaf48b305b27065573bb8e9fd41d002`. The exact code/preregistration head before the first model call was `a10a776062b73b92a000cceebb0e896862dc240c`; its six GitHub CI jobs succeeded. The private checkpoint remains outside Git at `~/.local/state/metis/issue6-owner-falsifier-2026-11-19`. The answer-free [dataset](data/issue6-owner-falsifier-2026-11-19.json) has SHA-256 `79eb8c62e9e179ac26f56e2ad2802c51c2c2fd3564396936ad835512a89d86c2`.

## Preregistered result

| Measure | Single owner | Owner + falsifier |
| --- | ---: | ---: |
| Workflow-complete protected-oracle verification | 30/30 | 30/30 |
| Public-constraint validity after workflow completion | 30/30 | 30/30 |
| Workflow completion | 30/30 | 30/30 |
| Model calls reserved / observed | 75 / 75 | 142 / 142 |
| Mean elapsed time per arm | 21.47 s | 40.75 s |
| Usage metadata present for turns | 75 / 75 | 142 / 142 |

The paired primary difference (owner + falsifier minus single) is **0 percentage points**. The preregistered 10,000-resample paired bootstrap 95% interval is **[0, 0]**. All 30 pairs were correct in both arms, with no discordant pairs. The falsifier reported no valid public-constraint witness, so no repair wave ran. The measured-gain gate is **not met**. Both arms reached the ceiling of this task family, which makes the study uninformative about whether the conditional repair design helps on tasks where a single owner errs. The added stage consumed more calls and wall time here.

An independent read-only audit matched the 60 retained rows with the private checkpoint and frozen order, checked all 748 audit-event hash links, and reconciled all 90 completed jobs with the reserved and observed model calls. It reconstructed each task's unique public-constraint solution and matched the protected answer and retained candidate digest in all 60 arms without publishing those values. Candidate files were absent. A scoped scan of retained logical records and task artifacts found no full answer in plaintext; this does not address deleted disk blocks or provider-side storage.

These are synthetic reconstruction results, not CTF solve rates or MUNIN experience-reuse evidence. The result does not revise the earlier negative symmetric benchmark or satisfy Issue #6's measured-gain criterion. Issue #6 and dependent Issue #7 remain open. Any follow-up needs a new prospective task family with non-ceiling difficulty and the same independent correctness and matched-budget rules; changing this completed study's task set or scoring would invalidate its preregistration.
