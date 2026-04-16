import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ensure .env is loaded in this module
load_dotenv()

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")


def get_news(ticker: str):

    if not ticker:
        return []

    if not FINNHUB_API_KEY:
        print("ERROR: FINNHUB_API_KEY not found in environment")
        return []

    today = datetime.utcnow()
    week_ago = today - timedelta(days=7)

    url = "https://finnhub.io/api/v1/company-news"

    params = {
        "symbol": ticker,
        "from": week_ago.strftime("%Y-%m-%d"),
        "to": today.strftime("%Y-%m-%d"),
        "token": FINNHUB_API_KEY
    }

    try:

        response = requests.get(url, params=params)

        data = response.json()

        # Finnhub returns dict when there's an error
        if not isinstance(data, list):

            print("Finnhub returned unexpected response:")
            print(data)

            return []

        cleaned_articles = []

        for article in data:

            if (
                isinstance(article, dict)
                and "headline" in article
                and "datetime" in article
            ):
                cleaned_articles.append(article)

        return cleaned_articles[:10]

    except Exception as e:

        print("News fetch error:", e)

        return []