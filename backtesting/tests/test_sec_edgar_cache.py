from backtesting.sec_edgar_cache import companyfacts_cache_path, read_cached_json, ticker_mapping_cache_path, write_cached_json


def test_sec_cache_round_trip_uses_stable_companyfacts_path(tmp_path) -> None:
    path = companyfacts_cache_path(tmp_path, "0000320193")
    payload = {"cik": "0000320193", "facts": {"us-gaap": {}}}

    write_cached_json(path, payload)

    assert read_cached_json(path) == payload
    assert path.name == "0000320193.json"
    assert ticker_mapping_cache_path(tmp_path).name == "company_tickers.json"
