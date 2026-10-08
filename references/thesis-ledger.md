# Thesis ledger and accountability

Use an append-only thesis ledger to make prior views auditable. A report may summarize entries, but it must not overwrite the original record.

## Entry schema

| Field | Meaning |
| --- | --- |
| thesis_id | stable identifier |
| created_at | timestamp and timezone |
| cutoff | latest evidence allowed when formed |
| scope | macro, asset, market, sector, theme, product, or portfolio |
| thesis | falsifiable claim, not a topic label |
| status | active, strengthened, unchanged, weakened, invalidated, not yet testable, expired |
| horizon | observation or decision horizon |
| expected_observation | what should occur if the thesis is right |
| evidence_for | dated evidence supporting it |
| evidence_against | dated counterevidence |
| alternative | strongest competing explanation or opportunity |
| confirmation | observable condition that strengthens the view |
| invalidation | observable condition that disproves or materially weakens it |
| benchmark | comparison appropriate to the claim |
| action_relevance | none, watch, worth dedicated research, or portfolio review |
| resolved_at | resolution timestamp when applicable |
| outcome | observed result without reinterpretation |
| postmortem | data, causal, timing, implementation, or behavioral lesson |

## Writing rules

- Write the thesis before the outcome is known.
- Preserve original wording, horizon, and thresholds. Add updates as dated events.
- A favorable result does not validate a poor process; an unfavorable result does not automatically invalidate a sound probabilistic process.
- Distinguish `wrong` from `not yet testable` and `trigger never occurred`.
- Do not score vague statements such as “volatility may continue.” Rewrite them into an observable claim or leave them out.
- Use the correct benchmark and currency basis.

## Daily review

For each active entry affected by new evidence, report:

| Thesis | New evidence | Status | What changes now |
| --- | --- | --- | --- |

Carry unresolved entries forward. Do not silently replace yesterday's narrative.

The executable `ledger-review --file <ledger> --directory <sealed-run> [--append]` evaluates the original conditions against frozen new evidence. Numeric conditions specify exact identity, provider, metric, interval, basis, unit, currency, comparison/threshold and daily market calendar. `all_of`/`any_of` combine nonempty conditions with true/false/unknown logic. Old observations do not become new confirmations merely because they were downloaded again; daily observation completion is resolved in the specified venue timezone.

Unstructured text and primary-event conditions remain manual review, not false or automatically confirmed. Missing, ineligible or mismatched evidence returns unknown. Conflicting confirmation/invalidation conditions remain not yet testable; invalidated/expired views are not automatically resurrected. `--append` preserves the original thesis, cutoff, horizon, benchmark and conditions and records the later review cutoff separately.

## Weekly review

Summarize:

- confirmed or invalidated views;
- views still inside their horizon;
- missing triggers;
- recurring error types;
- whether confidence calibration was too high or too low;
- changes to research process supported by observed failures.

Avoid a single “accuracy” number when theses have different horizons and types. Separate directional result, evidence quality, timing, and decision usefulness.
