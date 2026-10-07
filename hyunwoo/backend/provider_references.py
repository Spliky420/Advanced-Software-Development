# Links belong to the checked reference files, not model output.
CHECKED_ON = "2026-10-02"
NETFLIX_CANCEL_URL = "https://help.netflix.com/en/node/407"
SPOTIFY_CANCEL_URL = "https://support.spotify.com/au/article/cancel-premium/"

SOURCES = {
    "HyunWoo_provider_Netflix_cancel.txt": {
        "provider": "netflix", "source_title": "Netflix cancellation and remaining access",
        "source_url": NETFLIX_CANCEL_URL,
        "topics": {"cancel", "delete", "remove", "uninstall", "app", "watch", "access", "hold"},
    },
    "HyunWoo_provider_Netflix_partner.txt": {
        "provider": "netflix", "source_title": "Netflix cancellation through a payment partner",
        "source_url": NETFLIX_CANCEL_URL,
        "topics": {"cancel", "partner", "third", "option", "missing"},
    },
    "HyunWoo_provider_Netflix_billing.txt": {
        "provider": "netflix", "source_title": "Netflix billing dates",
        "source_url": "https://help.netflix.com/en/node/54896",
        "topics": {"billing", "date", "payment", "history", "signup", "find"},
    },
    "HyunWoo_provider_Spotify_cancel.txt": {
        "provider": "spotify", "source_title": "Spotify Premium cancellation and playlists",
        "source_url": SPOTIFY_CANCEL_URL,
        "topics": {"cancel", "playlist", "music", "partner", "third", "access"},
    },
    "HyunWoo_provider_Spotify_trial.txt": {
        "provider": "spotify", "source_title": "Spotify zero-priced free trial cancellation",
        "source_url": SPOTIFY_CANCEL_URL,
        "topics": {"trial", "reactivate"},
    },
    "HyunWoo_provider_Spotify_billing.txt": {
        "provider": "spotify", "source_title": "Spotify billing dates",
        "source_url": "https://support.spotify.com/au/article/billing-date/",
        "topics": {"billing", "date", "payment", "subscribe", "find"},
    },
}

OUT_OF_SCOPE = {
    "price", "prices", "pricing", "cost", "costs", "amount", "fee", "fees",
    "discount", "discounts", "promotion", "promotions", "promo", "cheapest",
    "refund", "refunds", "password", "tariff", "student", "deal", "deals",
}


def allowed_sources(terms):
    providers = terms & {"netflix", "spotify"}
    if not providers:
        return None
    if terms & OUT_OF_SCOPE:
        return set()
    # A trial question needs the trial exception, not general cancellation.
    if "trial" in terms:
        return {source for source, info in SOURCES.items()
                if info["provider"] in providers and "trial" in info["topics"]}
    if terms & {"partner", "third", "option", "missing"}:
        return {source for source, info in SOURCES.items()
                if info["provider"] in providers and "partner" in info["topics"]}
    if terms & {"cancel", "watch", "playlist", "music", "delete", "remove", "uninstall", "app", "access", "hold"}:
        return {source for source, info in SOURCES.items()
                if info["provider"] in providers and source.endswith("_cancel.txt")}
    return {source for source, info in SOURCES.items()
            if info["provider"] in providers and terms & info["topics"]}


def citation_details(source):
    info = SOURCES.get(source)
    if info is None:
        return {}
    return {"source_title": info["source_title"], "source_url": info["source_url"],
            "checked_on": CHECKED_ON}


def reference_body(text):
    # Each provider reference is one short chunk.
    return text.split(f"Checked: {CHECKED_ON}", 1)[-1].strip()
