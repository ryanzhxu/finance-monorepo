# Cache-only provenance manifest

`backtesting.provenance_manifest` provides the first safe STOCK-28 slice. It inventories already-present cache files, records source/retrieval/adjustment metadata, requested and completed symbols, benchmark coverage, file hashes, and explicit certification state.

The audit is read-only with respect to data sources: it never downloads, refreshes, calls SEC/Yahoo/R2, or changes the forecast model. A cache-only rerun with the same files and retrieval timestamp produces the same manifest and report fingerprints. Verification detects both manifest tampering and cached-file mutation.

Current-listing price data must remain `point_in_time_certified=false` unless a separate source review proves historical universe, delisted-symbol, and corporate-action coverage. Manifests, reports, and raw cache files are private artifacts and must remain outside Git.
