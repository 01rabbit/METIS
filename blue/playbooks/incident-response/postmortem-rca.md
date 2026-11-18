# Turn an incident into tested improvements

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

The incident is stable enough to review decisions, control behavior and organizational conditions without disrupting urgent response.

## Responsibilities

An independent facilitator can reduce blame and hindsight bias. Investigators, responders, service owners and decision makers contribute facts; improvement owners accept specific follow-up work.

## Work and decision records

1. Reconstruct a sourced timeline of observations, decisions and effects. Distinguish what participants knew at the time from facts learned later.
2. Identify contributing conditions across people, process and technology. Do not label the last visible mistake as the sole root cause without a supported causal path.
3. Test counterfactual claims: specify which change would plausibly prevent or reduce a particular effect and what evidence supports that reasoning.
4. Measure detection and response intervals using defined start/end events and clock uncertainty. Avoid precision unsupported by the logs.
5. Convert findings into actions with owner, priority, due date, acceptance test and dependency. Include controls that worked, since their maintenance is also a decision.
6. Validate improvements with a tabletop, inert replay or approved retained-data check. An implemented ticket is not the same as an effective control.
7. Promote only independently written general methods through the knowledge-intake review. Keep incident narratives, evidence and identifiable operating details private.

## Completion evidence

The review separates established causes, contributing factors and unresolved hypotheses. Follow-up actions have verifiable outcomes and escalation for overdue work; blame is not an acceptance criterion.

## Tabletop check

Exercise a misleading first alert, a justified decision made with incomplete information and an improvement that merely changes documentation. Require an observable check showing how the proposed action changes future outcomes.

## Concrete observation contract

Reconstruct a causal record with event/decision ID, UTC time or uncertainty interval,
evidence locator, observation, available information at that time, decision and outcome.
Separate contributing conditions from a single asserted root cause. A later discovery
does not show that earlier responders had the same evidence or feasible options.

For metrics, name the start/stop milestone definitions, population, excluded cases and
censored or unknown intervals. Missing first-activity time cannot produce a precise
dwell-time result. Each improvement needs owner, due date, acceptance observation and
test evidence tied to the changed rule/configuration/document hash. A closed ticket is
not proof that the regression test passed or that coverage improved. Publish independently
written lessons with case identifiers, private communications and raw artifacts removed.
