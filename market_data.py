"""Market data from Financial Modeling Prep (FMP): finds the latest trading day's
biggest move among real, sizeable companies.

The newsletter runs before the market opens, so "latest trading day" is the previous
session. (Called during market hours, FMP's lists reflect the session in progress.)

Free-plan notes, checked against the live API:
- Available: biggest-gainers, biggest-losers, and profile for any company.
- Only for very large companies (e.g. AAPL): quote, price history, analyst grades.
- Paid only: news, press releases, S&P 500 list, screener, batch quotes. News research
  is done by the Claude agent's web search instead.
So all per-company data comes from profile.
"""

import os
import time
from typing import Optional

import httpx

API_URL = "https://financialmodelingprep.com/stable/"

# The raw movers lists are dominated by penny stocks, tiny companies and leveraged
# ETFs. These filters keep companies big enough that readers may know them and
# that their moves usually have a real news story behind them.
MIN_PRICE = 5.0
# Minimum company size, tried in order: large, well-known companies first, and
# smaller ones only on days when no large company made the movers lists.
MARKET_CAP_TIERS = [10_000_000_000, 5_000_000_000, 2_000_000_000]
TOP_N = 5                # how many qualifying companies to return
MAX_PROFILE_LOOKUPS = 30  # caps API usage (one call per company checked)

CACHE_SECONDS = 60 * 60
_cache: dict = {}  # key -> (fetched_at, data)


class MarketDataError(RuntimeError):
    pass


def _get(endpoint: str, **params) -> list:
    """Call an FMP endpoint (cached) and return its JSON list."""
    key = endpoint + repr(sorted(params.items()))
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise MarketDataError("FMP_API_KEY is not set")
    try:
        r = httpx.get(API_URL + endpoint, params={**params, "apikey": api_key}, timeout=20)
    except httpx.HTTPError as e:
        raise MarketDataError(f"FMP request to {endpoint} failed: {e}") from e

    try:
        data = r.json()
    except ValueError:
        data = r.text
    # FMP reports a bad key, plan restrictions (402) and rate limits (429) as a
    # message instead of a list of results.
    if r.status_code != 200 or not isinstance(data, list):
        message = data.get("Error Message", data) if isinstance(data, dict) else data
        raise MarketDataError(f"FMP {endpoint} returned HTTP {r.status_code}: {str(message)[:200]}")

    _cache[key] = (time.time(), data)
    return data


def _is_common_stock(ticker: str) -> bool:
    """Exclude warrants, rights and units: Nasdaq marks them with a 5th letter
    (W, R, U, Z). Share classes like BRK-B are fine."""
    if not ticker.replace("-", "").replace(".", "").isalpha():
        return False
    return not (len(ticker) == 5 and ticker[-1] in "WRUZ")


def _year_range(profile: dict) -> tuple[Optional[float], Optional[float]]:
    """Parse profile's 52-week range, e.g. "164.27-243.37"."""
    try:
        low, high = profile.get("range", "").split("-")
        return float(low), float(high)
    except ValueError:
        return None, None


def _build_candidate(mover: dict, profile: dict) -> dict:
    change_percent = round(mover["changesPercentage"], 2)
    avg_volume = profile.get("averageVolume") or 0
    year_low, year_high = _year_range(profile)
    return {
        "ticker": mover["symbol"],
        "company_name": profile.get("companyName") or mover.get("name"),
        "exchange": mover.get("exchange"),
        "price": mover["price"],
        "previous_close": round(mover["price"] - mover["change"], 2),
        "change_amount": round(mover["change"], 2),
        "change_percent": change_percent,
        "direction": "up" if change_percent >= 0 else "down",
        "year_low": year_low,
        "year_high": year_high,
        "market_cap": profile.get("marketCap"),
        "volume": profile.get("volume"),
        "average_volume": avg_volume,
        # How unusual the day's trading was, e.g. 4.2 = four times the normal volume.
        "volume_vs_average": round(profile["volume"] / avg_volume, 1) if avg_volume else None,
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "ceo": profile.get("ceo"),
        "website": profile.get("website"),
        "logo_url": None if profile.get("defaultImage") else profile.get("image"),
        "description": profile.get("description"),
    }


def get_candidates() -> list[dict]:
    """The biggest movers (up or down) that pass the filters, biggest move first."""
    movers = _get("biggest-gainers") + _get("biggest-losers")
    movers = [m for m in movers if m["price"] >= MIN_PRICE and _is_common_stock(m["symbol"])]
    movers.sort(key=lambda m: abs(m["changesPercentage"]), reverse=True)

    # Look up every shortlisted mover (not just until TOP_N are found), since a
    # large company further down the list takes priority over smaller ones.
    qualifying = []
    for mover in movers[:MAX_PROFILE_LOOKUPS]:
        profiles = _get("profile", symbol=mover["symbol"])
        if not profiles:
            continue
        profile = profiles[0]
        if (
            (profile.get("marketCap") or 0) >= MARKET_CAP_TIERS[-1]
            and not profile.get("isEtf")
            and not profile.get("isFund")
            and profile.get("isActivelyTrading", True)
        ):
            qualifying.append(_build_candidate(mover, profile))

    for min_cap in MARKET_CAP_TIERS:
        tier = [c for c in qualifying if c["market_cap"] >= min_cap]
        if tier:
            if min_cap != MARKET_CAP_TIERS[0]:
                print(f"No movers worth ${MARKET_CAP_TIERS[0] / 1e9:.0f}B+; using ${min_cap / 1e9:.0f}B+")
            return tier[:TOP_N]
    return []


def latest_trading_day() -> str:
    """Date of the last completed trading session, e.g. "2026-10-23".
    The movers lists carry no date, so this reads the latest daily bar of a stock
    whose price history is on the free plan. That handles weekends and holidays."""
    bars = _get("historical-price-eod/light", symbol="AAPL")
    return bars[0]["date"] if bars else ""


def get_biggest_mover() -> tuple[str, Optional[dict], list[dict]]:
    """Return (trading date, biggest mover or None, all candidates)."""
    candidates = get_candidates()
    if not candidates:
        return "", None, []
    return latest_trading_day(), candidates[0], candidates


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    as_of, mover, candidates = get_biggest_mover()
    print(f"Trading day {as_of}: {len(candidates)} candidates")
    for c in candidates:
        print(f"  {c['ticker']:<6} {c['change_percent']:>+7.2f}%  ${c['market_cap'] / 1e9:>6.1f}B  "
              f"{c['volume_vs_average']}x vol  {c['company_name']}")
