import os

import requests
from dotenv import load_dotenv

from app.config import FINNHUB_API_KEY as CONFIG_FINNHUB_API_KEY

load_dotenv()

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY") or CONFIG_FINNHUB_API_KEY


def get_price(ticker: str):
    if not FINNHUB_API_KEY:
        raise ValueError("FINNHUB_API_KEY is missing.")

    url = "https://finnhub.io/api/v1/quote"

    params = {
        "symbol": ticker,
        "token": FINNHUB_API_KEY
    }

    response = requests.get(url, params=params)

    data = response.json()

    if "c" not in data:
        raise ValueError(data)

    return data["c"]


def get_fundamentals(ticker: str):

    url = "https://finnhub.io/api/v1/stock/metric"

    params = {
        "symbol": ticker,
        "metric": "all",
        "token": FINNHUB_API_KEY
    }

    response = requests.get(url, params=params)

    data = response.json()

    metrics = data.get("metric", {})

    eps = metrics.get("epsTTM")
    pe = metrics.get("peTTM")

    return {
        "eps": eps,
        "pe": pe
    }
