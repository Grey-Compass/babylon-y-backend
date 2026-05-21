from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from app.cache_service import get_cached_json, get_stale_cached_json, set_cached_json
from app.price_service import get_price

load_dotenv()

ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
EPS_WEIGHTS = [0.10, 0.15, 0.20, 0.25, 0.30]
REQUEST_TIMEOUT = 15
ALPHA_VANTAGE_CACHE_TTL_SECONDS = 60 * 60 * 6
VALUATION_CACHE_TTL_SECONDS = 60 * 15

VALUATION_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}


def get_valuation_data(ticker: str) -> Dict[str, Any]:
    ticker = (ticker or "").strip().upper()

    if not ticker:
        return {
            "ticker": ticker,
            "error": "Ticker is required.",
            "quality_grade": "D",
            "confidence_notes": ["No ticker was provided."],
        }

    if not ALPHA_VANTAGE_API_KEY:
        return {
            "ticker": ticker,
            "error": "Alpha Vantage API key is missing.",
            "quality_grade": "D",
            "confidence_notes": ["ALPHA_VANTAGE_API_KEY was not found."],
        }

    cached_result = _get_cached_payload(VALUATION_CACHE, ticker, VALUATION_CACHE_TTL_SECONDS)
    if cached_result is not None:
        return cached_result

    confidence_notes: List[str] = []

    earnings_data = fetch_alpha_vantage_earnings(ticker)
    income_data = fetch_alpha_vantage_income_statement(ticker)
    balance_data = fetch_alpha_vantage_balance_sheet(ticker)
    overview_data = fetch_alpha_vantage_overview(ticker)
    _collect_cache_notes(
        [earnings_data, income_data, balance_data, overview_data],
        confidence_notes,
    )

    eps_values = extract_annual_eps(earnings_data, confidence_notes)

    if not eps_values:
        result = {
            "ticker": ticker,
            "error": "Insufficient financial data for valuation.",
            "quality_grade": "D",
            "confidence_notes": confidence_notes + ["EPS history unavailable."],
        }
        _set_cached_payload(VALUATION_CACHE, ticker, result)
        return result

    normalized_eps = calculate_normalized_eps(eps_values, confidence_notes)
    margins = extract_operating_margins(income_data, confidence_notes)
    financial_profile = calculate_financial_profile(balance_data, confidence_notes)
    dividend_present = extract_dividend_signal(overview_data)

    factor_scores = {
        "eps_consistency": score_eps_consistency(eps_values),
        "eps_trend": score_eps_trend(eps_values, confidence_notes),
        "financial_strength": score_financial_strength(financial_profile, confidence_notes),
        "margin_stability": score_margin_stability(margins, confidence_notes),
        "dividend_stability": score_dividend_stability(dividend_present),
    }

    quality_score = calculate_quality_score(factor_scores)
    quality_grade = map_quality_grade(quality_score)
    cap_rate = map_cap_rate(quality_grade, confidence_notes)
    fair_value_range = calculate_fair_value_range(
        normalized_eps=normalized_eps,
        base_cap_rate=cap_rate,
    )
    intrinsic_value = fair_value_range["base"]

    current_price = None
    try:
        current_price = get_price(ticker)
    except Exception as exc:
        confidence_notes.append(f"Current price unavailable: {exc}")

    margin_of_safety = calculate_margin_of_safety(intrinsic_value, current_price)
    valuation_label = map_valuation_label(margin_of_safety)
    valuation_summary = build_valuation_summary(
        valuation_label=valuation_label,
        quality_grade=quality_grade,
        normalized_eps=normalized_eps,
        cap_rate=cap_rate,
        fair_value_low=fair_value_range["low"],
        fair_value_high=fair_value_range["high"],
        confidence_notes=confidence_notes,
    )

    result = {
        "ticker": ticker,
        "normalized_eps": round(normalized_eps, 2),
        "eps_years_used": len(eps_values),
        "quality_score": quality_score,
        "quality_grade": quality_grade,
        "cap_rate": round(cap_rate, 4),
        "fair_value_low": round(fair_value_range["low"], 2),
        "fair_value_base": round(fair_value_range["base"], 2),
        "fair_value_high": round(fair_value_range["high"], 2),
        "intrinsic_value": round(intrinsic_value, 2),
        "current_price": round(float(current_price), 2) if current_price is not None else None,
        "margin_of_safety": round(margin_of_safety, 2) if margin_of_safety is not None else None,
        "valuation_label": valuation_label,
        "valuation_summary": valuation_summary,
        "factor_scores": factor_scores,
        "confidence_notes": confidence_notes,
    }
    _set_cached_payload(VALUATION_CACHE, ticker, result)
    return result


def fetch_alpha_vantage_earnings(ticker: str) -> Dict[str, Any]:
    return _fetch_alpha_vantage(function="EARNINGS", ticker=ticker)


def fetch_alpha_vantage_income_statement(ticker: str) -> Dict[str, Any]:
    return _fetch_alpha_vantage(function="INCOME_STATEMENT", ticker=ticker)


def fetch_alpha_vantage_balance_sheet(ticker: str) -> Dict[str, Any]:
    return _fetch_alpha_vantage(function="BALANCE_SHEET", ticker=ticker)


def fetch_alpha_vantage_overview(ticker: str) -> Dict[str, Any]:
    return _fetch_alpha_vantage(function="OVERVIEW", ticker=ticker)


def _fetch_alpha_vantage(function: str, ticker: str) -> Dict[str, Any]:
    cache_key = f"{function}:{ticker}"
    cached_response = get_cached_json(cache_key, ALPHA_VANTAGE_CACHE_TTL_SECONDS)
    if cached_response is not None:
        return cached_response

    params = {
        "function": function,
        "symbol": ticker,
        "apikey": ALPHA_VANTAGE_API_KEY,
    }

    try:
        response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=REQUEST_TIMEOUT)
        data = response.json()
    except Exception as exc:
        stale_response = get_stale_cached_json(cache_key)
        if stale_response is not None:
            stale_response["_cache_notice"] = (
                f"Using cached {function} data because the live request failed."
            )
            return stale_response
        return {"error": f"Request failed: {exc}"}

    if isinstance(data, dict):
        note = data.get("Note") or data.get("Information") or data.get("Error Message")
        if note:
            stale_response = get_stale_cached_json(cache_key)
            if stale_response is not None:
                stale_response["_cache_notice"] = (
                    f"Using cached {function} data because Alpha Vantage returned a temporary limit."
                )
                return stale_response
            return {"error": note}

    if isinstance(data, dict):
        set_cached_json(cache_key, data)
        return data

    return {"error": "Unexpected response format."}


def extract_annual_eps(data: Dict[str, Any], confidence_notes: List[str]) -> List[float]:
    annual_earnings = data.get("annualEarnings")

    if not isinstance(annual_earnings, list):
        _append_data_error(confidence_notes, "EPS history unavailable.", data)
        return []

    annual_earnings = list(reversed(annual_earnings[:5]))
    values: List[float] = []

    for item in annual_earnings:
        eps = _safe_float(item.get("reportedEPS")) if isinstance(item, dict) else None
        if eps is not None:
            values.append(eps)

    if len(values) < 5:
        confidence_notes.append(f"Only {len(values)} years of EPS data available.")

    return values


def calculate_normalized_eps(eps_values: List[float], confidence_notes: List[str]) -> float:
    if not eps_values:
        return 0.0

    weights = EPS_WEIGHTS[-len(eps_values):]
    weight_total = sum(weights)
    normalized_weights = [weight / weight_total for weight in weights]

    if len(eps_values) < 5:
        confidence_notes.append("Normalized EPS used a reduced history window.")

    return sum(eps * weight for eps, weight in zip(eps_values, normalized_weights))


def extract_operating_margins(data: Dict[str, Any], confidence_notes: List[str]) -> List[float]:
    annual_reports = data.get("annualReports")

    if not isinstance(annual_reports, list):
        _append_data_error(confidence_notes, "Income statement history unavailable.", data)
        return []

    margins: List[float] = []

    for item in reversed(annual_reports[-5:]):
        if not isinstance(item, dict):
            continue

        revenue = _safe_float(item.get("totalRevenue"))
        operating_income = _safe_float(item.get("operatingIncome"))

        if revenue and operating_income is not None and revenue != 0:
            margins.append(operating_income / revenue)

    if len(margins) < 5:
        confidence_notes.append(f"Only {len(margins)} years of margin data available.")

    return margins


def calculate_financial_profile(data: Dict[str, Any], confidence_notes: List[str]) -> Dict[str, Optional[float]]:
    annual_reports = data.get("annualReports")

    if not isinstance(annual_reports, list) or not annual_reports:
        _append_data_error(confidence_notes, "Balance sheet history unavailable.", data)
        return {
            "debt_to_equity": None,
            "debt_to_assets": None,
            "current_ratio": None,
            "cash_to_debt": None,
        }

    latest = annual_reports[0]
    if not isinstance(latest, dict):
        confidence_notes.append("Latest balance sheet report could not be read.")
        return {
            "debt_to_equity": None,
            "debt_to_assets": None,
            "current_ratio": None,
            "cash_to_debt": None,
        }

    total_liabilities = _safe_float(latest.get("totalLiabilities"))
    total_equity = _safe_float(latest.get("totalShareholderEquity"))
    total_debt = _safe_float(latest.get("shortLongTermDebtTotal"))
    total_assets = _safe_float(latest.get("totalAssets"))
    current_assets = _safe_float(latest.get("totalCurrentAssets"))
    current_liabilities = _safe_float(latest.get("totalCurrentLiabilities"))
    cash = _safe_float(latest.get("cashAndShortTermInvestments"))

    debt_to_equity = None
    if total_liabilities is not None and total_equity not in (None, 0):
        debt_to_equity = total_liabilities / total_equity
    elif total_debt is not None and total_equity not in (None, 0):
        confidence_notes.append("Debt-to-equity used total debt fallback instead of total liabilities.")
        debt_to_equity = total_debt / total_equity

    debt_to_assets = None
    debt_numerator = total_debt if total_debt is not None else total_liabilities
    if debt_numerator is not None and total_assets not in (None, 0):
        debt_to_assets = debt_numerator / total_assets

    current_ratio = None
    if current_assets is not None and current_liabilities not in (None, 0):
        current_ratio = current_assets / current_liabilities

    cash_to_debt = None
    if cash is not None and total_debt not in (None, 0):
        cash_to_debt = cash / total_debt

    if all(metric is None for metric in (debt_to_equity, debt_to_assets, current_ratio, cash_to_debt)):
        confidence_notes.append("Financial profile could not be calculated cleanly.")

    return {
        "debt_to_equity": debt_to_equity,
        "debt_to_assets": debt_to_assets,
        "current_ratio": current_ratio,
        "cash_to_debt": cash_to_debt,
    }


def extract_dividend_signal(data: Dict[str, Any]) -> Optional[bool]:
    dividend_yield = _safe_float(data.get("DividendYield"))
    dividend_per_share = _safe_float(data.get("DividendPerShare"))

    if dividend_yield is None and dividend_per_share is None:
        return None

    return bool((dividend_yield or 0) > 0 or (dividend_per_share or 0) > 0)


def score_eps_consistency(eps_values: List[float]) -> int:
    if not eps_values:
        return 0

    positive_years = sum(1 for eps in eps_values if eps > 0)
    severe_drop = False

    for older, newer in zip(eps_values, eps_values[1:]):
        if older > 0 and newer < older * 0.5:
            severe_drop = True
            break

    if positive_years >= 4 and not severe_drop:
        return 2
    if positive_years >= 3:
        return 1
    return 0


def score_eps_trend(eps_values: List[float], confidence_notes: List[str]) -> int:
    if len(eps_values) < 3:
        confidence_notes.append("EPS trend score used limited history.")
        return 1

    older_period = eps_values[:-2] if len(eps_values) >= 4 else eps_values[:-1]
    recent_period = eps_values[-2:] if len(eps_values) >= 2 else eps_values[-1:]

    older_avg = sum(older_period) / len(older_period) if older_period else 0
    recent_avg = sum(recent_period) / len(recent_period) if recent_period else 0

    if older_avg == 0:
        if recent_avg > 0:
            return 2
        return 1

    change = (recent_avg - older_avg) / abs(older_avg)

    if change >= 0.10:
        return 2
    if change >= -0.10:
        return 1
    return 0


def score_financial_strength(
    financial_profile: Dict[str, Optional[float]],
    confidence_notes: List[str],
) -> int:
    debt_to_equity = financial_profile.get("debt_to_equity")
    debt_to_assets = financial_profile.get("debt_to_assets")
    current_ratio = financial_profile.get("current_ratio")
    cash_to_debt = financial_profile.get("cash_to_debt")

    signals: List[int] = []

    if debt_to_equity is not None:
        if debt_to_equity <= 1.0:
            signals.append(2)
        elif debt_to_equity <= 2.0:
            signals.append(1)
        else:
            signals.append(0)
    elif debt_to_assets is not None:
        if debt_to_assets <= 0.35:
            signals.append(2)
        elif debt_to_assets <= 0.60:
            signals.append(1)
        else:
            signals.append(0)

    if current_ratio is not None:
        if current_ratio >= 1.5:
            signals.append(2)
        elif current_ratio >= 1.0:
            signals.append(1)
        else:
            signals.append(0)

    if cash_to_debt is not None:
        if cash_to_debt >= 1.0:
            signals.append(2)
        elif cash_to_debt >= 0.5:
            signals.append(1)
        else:
            signals.append(0)

    if not signals:
        confidence_notes.append("Financial strength score defaulted to neutral due to missing debt data.")
        return 1

    average_signal = sum(signals) / len(signals)

    if average_signal >= 1.5:
        return 2
    if average_signal >= 0.75:
        return 1
    return 0


def score_margin_stability(margins: List[float], confidence_notes: List[str]) -> int:
    if not margins:
        confidence_notes.append("Margin stability score defaulted to neutral due to missing margin data.")
        return 1

    avg_margin = sum(margins) / len(margins)
    margin_range = max(margins) - min(margins)
    weakest_margin = min(margins)

    if avg_margin >= 0.20 and weakest_margin >= 0.10 and margin_range <= 0.18:
        return 2
    if avg_margin > 0 and weakest_margin >= 0 and margin_range <= 0.28:
        return 1
    return 0


def score_dividend_stability(dividend_present: Optional[bool]) -> int:
    if dividend_present is True:
        return 2
    if dividend_present is False:
        return 1
    return 1


def calculate_quality_score(factor_scores: Dict[str, int]) -> int:
    return sum(factor_scores.values())


def map_quality_grade(score: int) -> str:
    if score >= 9:
        return "A"
    if score >= 7:
        return "B"
    if score >= 5:
        return "C"
    return "D"


def map_cap_rate(grade: str, confidence_notes: List[str]) -> float:
    if len(confidence_notes) >= 4:
        return 0.16

    grade_map = {
        "A": 0.08,
        "B": 0.10,
        "C": 0.12,
        "D": 0.14,
    }
    return grade_map.get(grade, 0.14)


def calculate_intrinsic_value(normalized_eps: float, cap_rate: float) -> float:
    if cap_rate <= 0:
        return 0.0
    return normalized_eps / cap_rate


def calculate_fair_value_range(
    normalized_eps: float,
    base_cap_rate: float,
) -> Dict[str, float]:
    bull_cap_rate = max(0.06, base_cap_rate - 0.02)
    bear_cap_rate = min(0.18, base_cap_rate + 0.02)

    low_value = calculate_intrinsic_value(normalized_eps, bear_cap_rate)
    base_value = calculate_intrinsic_value(normalized_eps, base_cap_rate)
    high_value = calculate_intrinsic_value(normalized_eps, bull_cap_rate)

    return {
        "low": low_value,
        "base": base_value,
        "high": high_value,
    }


def calculate_margin_of_safety(intrinsic_value: float, current_price: Optional[float]) -> Optional[float]:
    if current_price is None or intrinsic_value <= 0:
        return None
    return ((intrinsic_value - current_price) / intrinsic_value) * 100


def map_valuation_label(margin_of_safety: Optional[float]) -> str:
    if margin_of_safety is None:
        return "Unavailable"
    if margin_of_safety >= 20:
        return "Attractive"
    if margin_of_safety >= 5:
        return "Modestly Attractive"
    if margin_of_safety > -15:
        return "Near Fair Value"
    return "Expensive"


def build_valuation_summary(
    valuation_label: str,
    quality_grade: str,
    normalized_eps: float,
    cap_rate: float,
    fair_value_low: float,
    fair_value_high: float,
    confidence_notes: List[str],
) -> str:
    quality_descriptions = {
        "A": "a high-quality business profile",
        "B": "a solid business profile",
        "C": "a mixed business profile",
        "D": "a weak or uncertain business profile",
    }

    valuation_descriptions = {
        "Attractive": "The current price sits below our conservative fair value range.",
        "Modestly Attractive": "The current price looks somewhat favorable relative to our fair value range.",
        "Near Fair Value": "The current price appears close to our estimated fair value range.",
        "Expensive": "The current price appears well above our conservative fair value range.",
        "Unavailable": "A full valuation view is limited right now.",
    }

    confidence_sentence = (
        "Confidence is reduced by incomplete or fallback data."
        if confidence_notes
        else "Confidence is stronger because the estimate used a clean data set."
    )

    return (
        f"{valuation_descriptions.get(valuation_label, 'Valuation data is available.')} "
        f"We estimate normalized earnings power at ${normalized_eps:.2f} per share, "
        f"supported by {quality_descriptions.get(quality_grade, 'an uncertain business profile')}. "
        f"Our current fair value range is ${fair_value_low:.2f} to ${fair_value_high:.2f}, "
        f"using a base capitalization rate of {cap_rate:.0%}. "
        f"{confidence_sentence}"
    )


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, "None", ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_data_error(confidence_notes: List[str], fallback_note: str, data: Dict[str, Any]) -> None:
    error_message = data.get("error") if isinstance(data, dict) else None
    confidence_notes.append(error_message or fallback_note)


def _collect_cache_notes(data_sets: List[Dict[str, Any]], confidence_notes: List[str]) -> None:
    for data in data_sets:
        notice = data.get("_cache_notice") if isinstance(data, dict) else None
        if notice and notice not in confidence_notes:
            confidence_notes.append(notice)


def _get_cached_payload(
    cache: Dict[str, tuple[float, Dict[str, Any]]],
    key: str,
    ttl_seconds: int,
) -> Optional[Dict[str, Any]]:
    cached_item = cache.get(key)
    if not cached_item:
        return None

    cached_at, payload = cached_item
    if time.time() - cached_at > ttl_seconds:
        return None

    return dict(payload)


def _set_cached_payload(
    cache: Dict[str, tuple[float, Dict[str, Any]]],
    key: str,
    payload: Dict[str, Any],
) -> None:
    cache[key] = (time.time(), dict(payload))
