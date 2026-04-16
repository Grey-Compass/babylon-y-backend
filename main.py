from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime

from app.news_service import get_news
from app.sentiment_service import get_sentiment

import os
import requests
import math

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

def get_price(ticker):

    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"

    print("PRICE URL:", url)

    r = requests.get(url)

    print("PRICE RESPONSE:", r.text)

    data = r.json()

    return data.get("c")

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



LAMBDA = 0.15

CACHE = {}
CACHE_TTL_SECONDS = 600

HISTORY = {}
MAX_HISTORY_POINTS = 50



@app.get("/")
def root():
    return {"message": "API is working"}



def interpret_score(score):

    if score > 0.35:
        return "strong_positive"

    elif score > 0.15:
        return "positive"

    elif score > 0.05:
        return "slightly_positive"

    elif score >= -0.05:
        return "neutral"

    elif score >= -0.15:
        return "slightly_negative"

    elif score >= -0.35:
        return "negative"

    else:
        return "strong_negative"



def confidence_level(article_count):

    if article_count >= 8:
        return "high"

    elif article_count >= 4:
        return "medium"

    else:
        return "low"



@app.get("/score")
def score(ticker: str, investor_type: str = "defensive"):

    tickers = ticker.split(",")

    results = []

    for ticker_symbol in tickers:

        ticker_symbol = ticker_symbol.strip().upper()

        cache_key = f"{ticker_symbol}_{investor_type}"

        now = datetime.utcnow().timestamp()

        if cache_key in CACHE:

            cached_time, cached_result = CACHE[cache_key]

            if now - cached_time < CACHE_TTL_SECONDS:

                results.append(cached_result)
                continue



        articles = get_news(ticker_symbol)

        sentiments = []

        trend = []

        headlines = []



        for article in articles:

            headline = article.get("headline", "")

            sentiment_score = get_sentiment(headline)

            sentiments.append(sentiment_score)

            headlines.append(headline)

            hours_old = (
                datetime.utcnow()
                - datetime.utcfromtimestamp(article["datetime"])
            ).total_seconds() / 3600

            weight = math.exp(-LAMBDA * hours_old)

            trend.append(sentiment_score * weight)



        if sentiments:

            weighted_score = sum(trend) / len(trend)

        else:

            weighted_score = 0



        # investor style adjustment

        if investor_type == "defensive":

            adjusted_score = weighted_score * 0.7

            if abs(weighted_score) > 0.35:
                adjusted_score *= 0.85


        elif investor_type == "active":

            adjusted_score = weighted_score * 1.15

            if abs(weighted_score) > 0.25:
                adjusted_score *= 1.1


        else:

            adjusted_score = weighted_score



        signal = interpret_score(adjusted_score)

        confidence = confidence_level(len(sentiments))



        # get price safely
        price = get_price(ticker_symbol)


        if price is not None:

            intrinsic_value = price * (1 + adjusted_score)

            value_gap_percent = (
                (intrinsic_value - price) / price
            ) * 100

        else:

            intrinsic_value = None

            value_gap_percent = 0



        result = {

            "ticker": ticker_symbol,

            "score": round(adjusted_score, 4),

            "raw_score": round(weighted_score, 4),

            "signal": signal,

            "confidence": confidence,

            "article_count": len(sentiments),

            "trend": [round(x, 4) for x in trend][-10:],

            "trend_direction":
                "up" if weighted_score > 0
                else "down" if weighted_score < 0
                else "flat",

            "price": round(price, 2) if price else None,

            "intrinsic_value": round(intrinsic_value, 2) if price else None,

            "value_gap_percent": round(value_gap_percent, 2),
            
            "headlines": headlines[:5],

            "insight": ""

        }



        CACHE[cache_key] = (now, result)

        results.append(result)



    return results