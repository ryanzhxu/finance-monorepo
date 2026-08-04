# Event context decision boundary

`analyst_service.core.event_context` is a deterministic, read-only context layer. It accepts an observation snapshot and verified `MarketShockEvent` records, then returns bounded risk flags, source evidence, numeric context features, and explicit unknowns.

The layer fails closed when observations are stale/missing or event provenance is not verified. It never produces a direction, score, price level, position size, or order instruction. A caller may display its result beside an analysis response without changing the existing recommendation contract.

The current policy emits only these bounded flags:

- `macro_event_window`
- `liquidity_stress`
- `gap_risk`
- `export_controls_risk`
- `sector_exposure`
- `stale_data`

Thresholds are passed through `ContextPolicy` so tests and future configuration can version them without embedding provider behavior in the decision layer.
