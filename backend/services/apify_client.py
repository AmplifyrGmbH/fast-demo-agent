from apify_client import ApifyClient
from config import settings

ACTOR_ID = "compass~crawler-google-places"


def search_google_maps(query: str, max_results: int = 3) -> list[dict]:
    """
    Synchron — aus async-Funktionen via asyncio.to_thread aufrufen.
    """
    client = ApifyClient(settings.APIFY_API_TOKEN)
    run_input = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": max_results,
        "language": "de",
        "maxReviews": 5,
        "reviewsSort": "newest",
        "countryCode": "ch",
    }
    run = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=90)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return items
