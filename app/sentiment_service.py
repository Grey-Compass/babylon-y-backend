from nltk.sentiment import SentimentIntensityAnalyzer

sia = SentimentIntensityAnalyzer()


def get_sentiment(text: str) -> float:
    score = sia.polarity_scores(text)

    return score["compound"]