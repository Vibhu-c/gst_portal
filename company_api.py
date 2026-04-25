from __future__ import annotations

import yfinance as yf

FALLBACK_COMPANY_DATA = {
    "INFY.NS": {
        "ticker": "INFY.NS",
        "company_name": "Infosys Limited",
        "sector": "Technology",
        "industry": "Information Technology Services",
        "website": "https://www.infosys.com",
        "city": "Bengaluru",
        "country": "India",
        "employee_count": 317240,
        "market_cap": 6_200_000_000_000.0,
        "current_price": 1515.0,
        "financial_year_hint": "FY 2024-25",
        "turnover": 1_570_000_000_000.0,
        "purchase_value": 328_000_000_000.0,
        "source": "Built-in public company fallback dataset",
    },
    "RELIANCE.NS": {
        "ticker": "RELIANCE.NS",
        "company_name": "Reliance Industries Limited",
        "sector": "Energy / Conglomerate",
        "industry": "Oil, Gas and Consumer Businesses",
        "website": "https://www.ril.com",
        "city": "Mumbai",
        "country": "India",
        "employee_count": 389414,
        "market_cap": 19_500_000_000_000.0,
        "current_price": 2920.0,
        "financial_year_hint": "FY 2024-25",
        "turnover": 9_000_000_000_000.0,
        "purchase_value": 6_400_000_000_000.0,
        "source": "Built-in public company fallback dataset",
    },
    "TCS.NS": {
        "ticker": "TCS.NS",
        "company_name": "Tata Consultancy Services Limited",
        "sector": "Technology",
        "industry": "IT Services and Consulting",
        "website": "https://www.tcs.com",
        "city": "Mumbai",
        "country": "India",
        "employee_count": 601546,
        "market_cap": 14_500_000_000_000.0,
        "current_price": 4025.0,
        "financial_year_hint": "FY 2024-25",
        "turnover": 2_400_000_000_000.0,
        "purchase_value": 510_000_000_000.0,
        "source": "Built-in public company fallback dataset",
    },
}


def _safe_float(value):
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def fetch_public_company_financials(ticker: str):
    """
    Uses public Yahoo Finance data (via yfinance) to fetch latest annual
    turnover (Total Revenue) and purchase proxy (Cost Of Revenue).
    """
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("Ticker symbol is required.")

    try:
        t = yf.Ticker(normalized_ticker)
        stmt = t.financials
        info = t.info or {}

        if stmt is None or stmt.empty:
            raise ValueError(
                "No financial statement data returned for this ticker. Try another listed company symbol."
            )

        cols = list(stmt.columns)
        latest_col = cols[0]
        latest_year = str(latest_col.year) if hasattr(latest_col, "year") else "Latest"

        turnover = 0.0
        purchases = 0.0

        for row_name in ["Total Revenue", "Operating Revenue", "Revenue"]:
            if row_name in stmt.index:
                turnover = _safe_float(stmt.loc[row_name, latest_col])
                if turnover:
                    break

        for row_name in ["Cost Of Revenue", "Cost of Revenue"]:
            if row_name in stmt.index:
                purchases = _safe_float(stmt.loc[row_name, latest_col])
                if purchases:
                    break

        if turnover == 0.0 and purchases == 0.0:
            raise ValueError("Could not find revenue/cost rows for this company.")

        return {
            "ticker": normalized_ticker,
            "company_name": info.get("longName") or info.get("shortName") or normalized_ticker,
            "sector": info.get("sectorDisp") or info.get("sector") or "Not available",
            "industry": info.get("industryDisp") or info.get("industry") or "Not available",
            "website": info.get("website") or "Not available",
            "city": info.get("city") or "Not available",
            "country": info.get("country") or "Not available",
            "employee_count": info.get("fullTimeEmployees") or 0,
            "market_cap": _safe_float(info.get("marketCap")),
            "current_price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
            "financial_year_hint": f"FY {latest_year}-{str(int(latest_year) + 1)[-2:]}" if latest_year.isdigit() else "Latest FY",
            "turnover": turnover,
            "purchase_value": purchases,
            "source": "Yahoo Finance (public data)",
        }
    except Exception as exc:
        if normalized_ticker in FALLBACK_COMPANY_DATA:
            fallback = FALLBACK_COMPANY_DATA[normalized_ticker].copy()
            fallback["fallback_reason"] = str(exc)
            return fallback
        raise ValueError(
            "Live public-company lookup failed. Try INFY.NS, RELIANCE.NS or TCS.NS for built-in fallback data."
        ) from exc
