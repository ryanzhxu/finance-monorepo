from backtesting.free_price_universe import fetch_current_us_common_symbols
from tools.download_free_price_history import _sample_symbols


NASDAQ_LISTED = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\nTEST|Test Corp - Common Stock|Q|Y|N|100|N|N\nETF1|Example ETF - Common Stock|Q|N|N|100|Y|N\nWARR|Example Warrant|Q|N|N|100|N|N\nFile Creation Time: 0712202600:00|||||||\n"""

OTHER_LISTED = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nBRK.B|Berkshire Hathaway Inc. - Class B Common Stock|N|BRK.B|N|100|N|BRK.B\nBAD|Example Preferred Stock|N|BAD|N|100|N|BAD\nOTC|Example Corp - Common Stock|X|OTC|N|100|N|OTC\nFile Creation Time: 0712202600:00||||||||\n"""


def test_current_us_common_symbols_filter_non_common_and_normalize_yahoo_tickers() -> None:
    texts = iter([NASDAQ_LISTED, OTHER_LISTED])

    symbols = fetch_current_us_common_symbols(get=lambda _: next(texts))

    assert symbols == ["AAPL", "BRK-B"]


def test_seeded_symbol_sampling_is_reproducible_and_not_alphabetical_prefix() -> None:
    symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"]

    first = _sample_symbols(symbols, 3, "sample-a")

    assert first == _sample_symbols(list(reversed(symbols)), 3, "sample-a")
    assert first != sorted(symbols)[:3]
    assert first != _sample_symbols(symbols, 3, "sample-b")
