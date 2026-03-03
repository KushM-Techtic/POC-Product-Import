"""Use AI to find brand website URL from Excel data (e.g. brand name). Known-brands fallback + OpenAI."""
import os
import re
import logging

log = logging.getLogger("app.services.ai_website_finder")

# Known brand name (normalized) -> official product catalog. Tuffy Security Products = tuffyproducts.com (not tuffy.com).
KNOWN_BRANDS: dict[str, str] = {
    "tuffy security": "https://tuffyproducts.com",
    "tuffy": "https://tuffyproducts.com",
}


def _normalize_brand(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _extract_url_from_text(text: str) -> str | None:
    if not text or "unknown" in text.lower():
        return None
    # Find first https?:// and take the URL (stop at space, newline, or common trailing chars)
    m = re.search(r"(https?://[^\s\]\)\"\']+)", text, re.IGNORECASE)
    if not m:
        return None
    url = m.group(1).strip(".,;)\"'")
    if url.startswith("http"):
        return url
    return None


def find_brand_website(brand_name: str) -> str | None:
    """Return official product website URL. Tries known-brands map first, then OpenAI if OPENAI_API_KEY set."""
    brand = (brand_name or "").strip()
    if not brand:
        return None
    key = _normalize_brand(brand)
    if key in KNOWN_BRANDS:
        log.info("Known brand match | brand=%s -> %s", brand, KNOWN_BRANDS[key])
        return KNOWN_BRANDS[key]
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f'What is the official company or product website URL for the brand "{brand}"? '
                    'Reply with ONLY the URL, nothing else (e.g. https://www.example.com). If you do not know, reply exactly: unknown'
                ),
            }],
            max_tokens=150,
        )
        text = (r.choices[0].message.content or "").strip()
        url = _extract_url_from_text(text)
        if url:
            log.info("AI found website | brand=%s -> %s", brand, url)
            return url
        log.warning("AI returned no URL for brand=%s | response=%s", brand, text[:80])
    except Exception as e:
        log.warning("AI website finder failed for brand=%s | %s", brand, e)
    return None
