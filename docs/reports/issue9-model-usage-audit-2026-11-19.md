# Issue #9 read-only model-usage audit increment

The per-run `metis audit` projection now reports only answer-free model usage
counts from `agent_jobs.usage`. It includes job count, jobs with missing or
invalid usage, known input/output subtotals, and a total only when every job
has valid input and output counts. Cost remains unknown. The projection reads
the same SQLite snapshot as the validated run-event chain; it never returns
raw job usage, prompts, answers, or credentials.

The focused audit suite passed (19 tests), as did Ruff, mypy for the changed
module, and `check_repo.py`. Synthetic tests cover partial usage, a second
run's excluded usage, and private-field redaction. This is monitoring data,
not an enforced token or cost budget. Issue #9 remains open for host reboot,
retention and secure credential storage, signed release evidence, and its
Issue #8 evaluation dependency.
