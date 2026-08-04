# Watchlist alert contract

`shared.alerts` is a dry-run, evidence-first alert contract. It compares two read-only `WatchlistState` snapshots and emits state-change alerts with prior/current state, freshness, evidence, uncertainty, a deduplication key, and a suppression window.

The in-memory `AlertLedger` demonstrates deduplication, mute, acknowledge, and dismiss behavior. It is intentionally not a database, scheduler, email sender, push sender, or provider client. Those concerns can be added as separate adapters after the contract is accepted.

Alert state contains no direction, order, position-size, or execution field. Alert reasons explain a changed context; they do not instruct a trade.
