# End-to-end research workflow

Use this for a complete allocation/tactical research run rather than a single data question.

## Collect and prepare

Use an independent market universe and the named profile. Inspect actual coverage, source/session/unit conflicts and question-specific evidence. Broad quote anomalies are investigation priorities; retrieve their histories, dated fundamentals/events and counterevidence before promotion.

```powershell
python scripts\market_engine.py --db C:\runtime\market.sqlite3 scan-market
python scripts\market_engine.py --db C:\runtime\market.sqlite3 prepare-research --directory C:\runtime\research-runs\unique-run --profile allocation
python scripts\market_engine.py prepare-research --config C:\runtime\market-config.json --directory C:\runtime\research-runs\unique-configured-run --profile allocation
```

`prepare-research` writes immutable numerical inputs, measured coverage, a source-bound evidence register and an input seal. It does not load holdings. Use a unique directory; revised data or new official evidence belongs in a new run. The `tactical` profile follows the same boundary.

With `--config`, preparation uses that config's database and freezes its task-scoped health. A conflicting explicit `--db` is rejected. Without a config, the frozen health is labeled whole-database history and does not establish profile acceptance. Source recovery or sufficient row counts do not erase remaining contract, timing or evidence gaps.

For tactical preparation, configured research targets are fetched explicitly alongside the global snapshot. A global quote/indicator cap cannot remove their snapshot and minute indicators. Their generation fingerprints freeze the full minute input prefix, rather than only the latest bar. Supplier aggregate summaries include their dated normalized source records; verification independently sums buy/sell/neutral/unknown amounts and the configured large-aggregate threshold. These remain supplier classification and price/flow evidence, not proof of individual orders or institutional buying. `tactical_input_coverage` states the targets and counts actually frozen; data-health readiness alone does not establish package completeness.

Schema 2 packages also freeze compressed calculation inputs and the calculator source version. Indicator generation binds the exact ordered input prefix, including the recursive seed and series identity. Preparation checks that the current stored inputs match that generation fingerprint and recomputes the measurement before marking it eligible. Old indicators without generation lineage, revised inputs or mismatched values remain explicitly unverified.

```powershell
python scripts\market_engine.py verify-research --directory C:\runtime\research-runs\unique-run
```

This command validates every referenced input artifact and replays the frozen industry/broad-market scan and verified indicators without opening the live database. A changed calculator version is reported separately; archived source is retained for inspection and is never evaluated as arbitrary code. Input tampering, missing lineage and numerical disagreements produce a nonzero result. Reproducible arithmetic does not establish current freshness, historical publication availability or an economic thesis.

Read the frozen inputs and collect any missing primary evidence. Write independent analysis as JSON with `market_summary`, `theses`, `opportunities`, `alternatives`, and `waiting_case`. Each thesis/candidate references real `evidence_ids` from the register and includes `countercase` and `invalidation`. Candidate states are `worth dedicated research`, `watch`, or `not yet`. Follow the decision and opportunity frameworks; data sufficiency alone does not establish an investment thesis.

```powershell
python scripts\market_engine.py lock-market-view --directory C:\runtime\research-runs\unique-run --view C:\runtime\market-view-input.json
python scripts\market_engine.py load-portfolio --directory C:\runtime\research-runs\unique-run --portfolio C:\runtime\authoritative-portfolio.private.json
```

The locking interface verifies the input seal, evidence references and minimum promotion conditions. It refuses holdings fields in the independent view. Portfolio loading is unavailable before locking and rejects a changed view. The private portfolio input requires `authoritative_source` and an explicit `positions` list; its amounts are not printed by this interface.

Promoted candidates require an exact `target_identity`, `core_missing: []` and `core_evidence` mapping each required role to cited evidence IDs. Use `fundamental_driver` for fundamental improvement; `implemented_change` and `transmission_measure` for policy transmission; `valuation` and `catalyst` for valuation mean reversion; `exposure_measure` and `risk_scenario` for defensive value. These roles accept the corresponding source measurements, rather than any two populated records. Target-specific fundamental, valuation and defensive measures must match `target_identity`; a different currency or maturity cannot establish the proposed exposure. A proxy or linked product needs its own verified mapping before product selection.

An imported `exposure_measure` requires a named `measurement`, numerical `value`, `unit` and defined `window`, with direct source provenance. Its default imported quality remains unverified until source review. The structural gate checks identity and evidence kinds; the analyst still verifies policy implementation, transmission, comparable valuation, event independence and economic relevance. A populated role or a passing JSON interface alone does not prove those claims.

## Analysis responsibilities

The current Codex agent supplies interpretation and primary-source research. A second or third role of the same LLM is not an independent quantitative model or additional evidence. Test the strongest competing explanation and compare alternatives/waiting. Technical signals cannot replace opportunity-type core evidence. Unverified financial units block a valuation conclusion.

After locking, map authoritative positions through exact underlying assets, currency, product structure, costs and dealing constraints. Missing shares/current values prevent quantitative portfolio weights; preserve qualitative exposure analysis without inventing numbers. Do not rewrite market conclusions after seeing holdings.

Append the original thesis and dated reviews using `ledger-add`. Original cutoff, claim, horizon, benchmark and conditions remain immutable. A report can summarize the record but does not replace it.

## Export the sealed research record

```powershell
python scripts\market_engine.py export-report --directory C:\runtime\research-runs\unique-run --output C:\runtime\exports\unique-export
```

This writes a readable Markdown projection and a provenance manifest from the locked market view. It rechecks frozen calculations, market/input links and hashes without opening the live database or network. The projection preserves the analyst's judgments and missing fields; it does not manufacture a complete narrative from numerical inputs alone. Inspect the artifact before presenting it as a complete daily report.

After `freeze-product-dossier`, `load-portfolio` and `map-portfolio`, add `--include-portfolio` to create a separate `portfolio-appendix.private.md`. The public market report never reads private positions. The optional appendix rebuilds the mapping against its authoritative inputs and sealed products; altered mappings refuse export. Original amount fields are excluded from both artifacts. Product evidence has its own cutoff, and the appendix does not rewrite the market judgment. Use a new export directory rather than overwriting previous artifacts.

## Issuer documents

Use `fetch-fund-official` for the supported direct issuer adapter, or `fetch-fund-documents` with the reviewed source registry. A fixed document source is dated evidence, not proof that no later notice exists. The registry binds reviewed facts to SHA-256 of the actual PDF; changed bytes invalidate that review and require fresh source inspection. A fund-family document that lacks the requested share code cannot establish the share-specific contract.

Preserve fee charge bases and normal-case dealing qualifications. Fee measurements are not extra charges to subtract again from a NAV return. Limit notices require an audit for later superseding changes. A browser verification page is not a fund data response and must not be evaluated as provider JavaScript.

## Release evidence

Code/fixture tests, source samples, behavioral evaluation, continuous-session acceptance and deployment verification are separate records. The five genuine consecutive-trading-session gate applies to operational release of a recurring collector; historical replay does not pass it. It is not a prerequisite for this skill-editing delivery. Preserve the existing automation; the user's current task excludes changing or connecting the daily task.
