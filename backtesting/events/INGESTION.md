# Event ingestion boundary

`backtesting.event_ingestion` is a private, adapter-driven ingestion seam for STOCK-36. It does not call a provider itself. A caller supplies:

- an evidence loader that returns primary-source metadata and raw bytes;
- a price loader that returns a subject series, the configured benchmark series, and price-source provenance;
- a private artifact root, normally through `BACKTESTING_EVENT_ARTIFACT_DIR`.

The ingestion path writes content-addressed raw artifacts for both event evidence and price inputs, immutable provenance manifests, measured event records, and an atomic batch checkpoint. An event is added to the checkpoint only after evidence, price windows, and their provenance validate and the complete event record is written.

Missing evidence and systemic provider failures are separate statuses. Neither produces a complete event record, and both remain retryable on a later cache-only or resumed run. Raw payloads, manifests, checkpoints, and generated records must stay outside Git.

Impact metrics are deterministic:

- benchmark-relative return is subject-series return minus benchmark-series return over the event window;
- peak drawdown is measured from the pre-event closing baseline through the window;
- volatility is population standard deviation of daily subject returns, annualized with `sqrt(252)`;
- recovery is the number of common trading sessions from the trough back to the pre-event closing level.

This slice intentionally does not add network calls, bulk downloads, public API/UI routes, alerts, model training, or forecast promotion.
