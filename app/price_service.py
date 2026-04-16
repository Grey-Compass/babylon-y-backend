import requests
from app.config import FINNHUB_API_KEY


def get_price(ticker: str):

    url = "https://finnhub.io/api/v1/quote"

    params = {
        "symbol": ticker,
        "token": FINNHUB_API_KEY
    }

    response = requests.get(url, params=params)

    data = response.json()

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