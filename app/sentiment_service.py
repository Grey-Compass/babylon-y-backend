import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

def get_sia():
    try:
        return SentimentIntensityAnalyzer()
    except LookupError:
        nltk.download("vader_lexicon")
        return SentimentIntensityAnalyzer()

sia = get_sia()

def get_sentiment(text: str) -> float:
    if not text:
        return 0.0
    score = sia.polarity_scores(text)
    return score["compound"]