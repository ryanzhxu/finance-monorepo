# Experiment integrity boundary

`backtesting.experiment_integrity` provides two private, adapter-driven ledgers:

- `HoldoutConsumptionRegistry` reserves a final-holdout slot before a caller loads labels or outcomes. It rejects duplicate keys, different configurations for the same slot, and any reuse of the consumed 2023–2024 `next_open_low_v2` holdout.
- `SecBatchLedger` checkpoints per-symbol SEC results, separates missing/unmapped data from systemic failures, and resumes only symbols that were not completed or resolved as missing.

The module performs no network calls, model fitting, label loading, forecast scoring, or provider retries. A caller supplies the data loader or SEC adapter after the relevant source and experiment gates are approved. Registries and manifests are local/private artifacts and must stay outside Git.
