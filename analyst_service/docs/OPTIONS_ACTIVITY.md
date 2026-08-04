# Options activity contract

`analyst_service.core.options_activity` is a provider-neutral contract and deterministic evaluator for options activity. It accepts a normalized snapshot containing expiry/strike, call/put, volume, open interest, implied volatility, bid/ask quality, source, retrieval time, adjustment mode, freshness, and point-in-time certification.

The evaluator can emit bounded informational context such as call or put dominance, unusual activity, and options liquidity risk. It never emits `BUY`/`SELL`, position sizing, or an order instruction. Contradictory volume/open-interest evidence, stale data, unavailable IV history, and uncertified historical data fail closed and remove the low-weight signal.

No provider adapter, live chain retrieval, existing API integration, or bulk download is included. A future adapter must implement the `OptionsActivityProvider` boundary and pass the source, licensing, cost, freshness, and point-in-time review before it is enabled.
