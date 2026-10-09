from src.newupdater.tools import search_news

result = search_news.invoke(
    {
        "topic": "artificial intelligence",
        "days": 1,
        "limit": 5,
    }
)

print(result)