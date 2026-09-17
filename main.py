import os
from difflib import SequenceMatcher
import textstat
from diskcache import Cache
from sec_api import ExtractorApi, QueryApi

# --- SETUP ---

# SEC API clients are created lazily so importing this module never
# requires credentials; analyze_company() reports missing keys explicitly.
_query_api = None
_extractor_api = None


def _get_query_api():
    """Return a QueryApi client, creating it on first use."""
    global _query_api
    if _query_api is None:
        api_key = os.getenv("SEC_API_KEY")
        if not api_key:
            raise ValueError("SEC_API_KEY not found. Ensure it is in your .env file.")
        _query_api = QueryApi(api_key=api_key)
    return _query_api


def _get_extractor_api():
    """Return an ExtractorApi client, creating it on first use."""
    global _extractor_api
    if _extractor_api is None:
        api_key = os.getenv("SEC_API_KEY")
        if not api_key:
            raise ValueError("SEC_API_KEY not found. Ensure it is in your .env file.")
        _extractor_api = ExtractorApi(api_key=api_key)
    return _extractor_api


def _get_cache():
    """Return the disk cache, creating it on first use."""
    return Cache("cache_directory")


cache = _get_cache()


# --- HELPER & CORE ANALYSIS FUNCTIONS ---


@cache.memoize()
def load_lm_dictionary():
    """Loads the Loughran-McDonald dictionary from the local CSV file.

    Raises FileNotFoundError with the configured path when the asset is
    missing instead of silently returning empty sets.
    """
    import config

    dict_path = config.LM_DICTIONARY_PATH
    positive_words, negative_words = set(), set()
    try:
        # Relative path to the data directory
        with open(dict_path, "r") as f:
            next(f)  # Skip header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) > 7:
                    word = parts[0].lower()
                    if int(parts[7]) > 0:
                        positive_words.add(word)
                    if int(parts[6]) > 0:
                        negative_words.add(word)  # Typo corrected
        print(
            f"-> Loaded {len(positive_words)} positive and {len(negative_words)} negative words."
        )
        return positive_words, negative_words
    except FileNotFoundError as e:
        print(f"ERROR: LM dictionary not found at {dict_path}: {e}")
        raise FileNotFoundError(
            f"LM dictionary not found at {dict_path}. "
            "Set LM_DICTIONARY_PATH or run scripts/check_assets.py for setup."
        ) from e
    except (ValueError, IndexError) as e:
        print(f"ERROR processing LM Dictionary: {e}")
        return set(), set()


@cache.memoize(expire=3600)
def get_latest_10k_filings(ticker):
    """Fetches metadata for the two most recent 10-K filings for a given ticker, excluding amendments."""
    query = {
        "query": {
            "query_string": {
                "query": f'ticker:{ticker} AND formType:"10-K" AND NOT formType:"10-K/A"'
            }
        },
        "from": "0",
        "size": "2",
        "sort": [{"filedAt": {"order": "desc"}}],
    }
    print(f"Querying SEC API for {ticker} filings...")
    response = _get_query_api().get_filings(query)
    return response.get("filings", [])


@cache.memoize()
def get_risk_factors_text(filing_url):
    """Uses the Tier-1 ExtractorApi to reliably get the plain text of Item 1A."""
    print(
        f"Extracting 'Item 1A' from: {filing_url} using professional-grade Extractor API."
    )
    return _get_extractor_api().get_section(filing_url, "1A", "text")


def calculate_lm_sentiment(text, positive_words, negative_words):
    """Calculates sentiment based on word counts from the LM dictionary."""
    words = text.lower().split()
    positive_score = sum(1 for word in words if word in positive_words)
    negative_score = sum(1 for word in words if word in negative_words)
    return {"positive_count": positive_score, "negative_count": negative_score}


def analyze_company(ticker: str):
    """
    Main function to perform a full textual analysis for a given company ticker.
    """
    try:
        positive_words, negative_words = load_lm_dictionary()
    except FileNotFoundError as e:
        return {"error": str(e), "status": 500}
    if not positive_words and not negative_words:
        return {
            "error": "LM dictionary loaded empty; refusing to report zero sentiment.",
            "status": 500,
        }

    try:
        filings = get_latest_10k_filings(ticker)
    except ValueError as e:
        return {"error": str(e), "status": 500}
    if len(filings) < 2:
        return {
            "error": f"Could not retrieve two 10-K filings for {ticker}.",
            "status": 404,
        }

    latest_filing_meta = filings[0]
    prior_filing_meta = filings[1]

    try:
        latest_risk_text = get_risk_factors_text(
            latest_filing_meta["linkToFilingDetails"]
        )
        prior_risk_text = get_risk_factors_text(
            prior_filing_meta["linkToFilingDetails"]
        )
    except ValueError as e:
        return {"error": str(e), "status": 500}

    if not latest_risk_text or not prior_risk_text:
        return {
            "error": "Failed to extract risk factors from one or both filings using ExtractorApi.",
            "status": 502,
        }

    # --- Calculations ---
    similarity_score = SequenceMatcher(None, prior_risk_text, latest_risk_text).ratio()
    gunning_fog_latest = textstat.gunning_fog(latest_risk_text)
    gunning_fog_prior = textstat.gunning_fog(prior_risk_text)
    sentiment_latest = calculate_lm_sentiment(
        latest_risk_text, positive_words, negative_words
    )
    sentiment_prior = calculate_lm_sentiment(
        prior_risk_text, positive_words, negative_words
    )

    # --- Assemble Result ---
    result = {
        "ticker": ticker,
        "latest_filing": {
            "filed_at": latest_filing_meta["filedAt"],
            "link": latest_filing_meta["linkToFilingDetails"],
            "gunning_fog_score": round(gunning_fog_latest, 2),
            "sentiment": sentiment_latest,
        },
        "prior_filing": {
            "filed_at": prior_filing_meta["filedAt"],
            "link": prior_filing_meta["linkToFilingDetails"],
            "gunning_fog_score": round(gunning_fog_prior, 2),
            "sentiment": sentiment_prior,
        },
        "comparison_metrics": {
            "change_score_similarity_ratio": round(similarity_score, 4)
        },
    }
    return result
