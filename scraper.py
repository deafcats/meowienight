"""
Shared Letterboxd scraper module.

Handles 403/rate-limit errors with:
- Realistic browser headers + Accept/Referer fields
- requests.Session for cookie persistence
- Exponential back-off on non-200 responses
"""

import time
import random
import re

import requests
from bs4 import BeautifulSoup
import pandas as pd


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def _parse_rating(li) -> tuple[float | None, str | None]:
    """Extract numeric rating and star string from a <li> element."""
    if li is None:
        return None, None

    # Method 1 – span.rating with rated-X class
    rating_span = li.find("span", class_="rating")
    if rating_span:
        rated_class = [c for c in rating_span.get("class", []) if "rated-" in c]
        if rated_class:
            try:
                rated_value = int(rated_class[0].split("-")[1])
                rating = rated_value / 2.0
                return rating, rating_span.get_text(strip=True)
            except (ValueError, IndexError):
                pass

    # Method 2 – any element with a rated-X class
    for elem in li.find_all(class_=lambda x: x and "rated-" in str(x)):
        for cls in elem.get("class", []):
            if "rated-" in cls:
                try:
                    rated_value = int(cls.split("-")[1])
                    rating = rated_value / 2.0
                    stars = elem.get_text(strip=True)
                    if not stars:
                        full = int(rating)
                        half = (rating % 1) >= 0.5
                        stars = "★" * full + ("½" if half else "")
                    return rating, stars
                except (ValueError, IndexError):
                    continue

    # Method 3 – data-rating attribute on the li
    for attr in ("data-rating", "data-rating-value"):
        raw = li.get(attr)
        if raw:
            try:
                r = float(raw)
                return (r / 2.0 if r > 5 else r), None
            except (ValueError, TypeError):
                pass

    # Method 4 – star symbols in text
    li_text = li.get_text()
    star_match = re.search(r"[★☆]+", li_text)
    if star_match:
        stars = star_match.group(0)
        count = stars.count("★") + stars.count("☆")
        if "½" in li_text or "half" in li_text.lower():
            return count + 0.5, stars
        return float(count), stars

    return None, None


def scrape_letterboxd_films(username: str, max_pages: int = 50) -> list[dict]:
    """
    Scrape Letterboxd film diary for *username*.

    Returns a list of dicts with keys: film_title, rating, rating_stars.
    """
    films: list[dict] = []
    session = requests.Session()
    session.headers.update(_HEADERS)

    # Warm-up: visit the profile root so Letterboxd sets session cookies
    try:
        warmup = session.get(
            f"https://letterboxd.com/{username}/",
            timeout=10,
        )
        if warmup.status_code == 403:
            print(f"❌ Profile '{username}' is private or blocked (403 on warm-up).")
            return films
        time.sleep(random.uniform(1.5, 2.5))
    except requests.exceptions.RequestException as exc:
        print(f"⚠️  Warm-up request failed: {exc}")

    for page in range(1, max_pages + 1):
        url = f"https://letterboxd.com/{username}/films/page/{page}/"
        print(f"Scraping page {page}: {url}")

        # Referer header makes requests look more like normal browsing
        session.headers["Referer"] = (
            f"https://letterboxd.com/{username}/films/page/{page - 1}/"
            if page > 1
            else f"https://letterboxd.com/{username}/"
        )

        for attempt in range(3):
            try:
                response = session.get(url, timeout=15)
                break
            except requests.exceptions.RequestException as exc:
                wait = 2 ** attempt
                print(f"   ⚠️  Request error (attempt {attempt + 1}): {exc} — retrying in {wait}s")
                time.sleep(wait)
        else:
            print(f"❌ Failed after 3 attempts on page {page}. Stopping.")
            break

        if response.status_code == 404:
            print(f"❌ Profile '{username}' not found (404).")
            break
        elif response.status_code == 403:
            print(f"❌ Access denied (403) on page {page}. Profile may be private.")
            break
        elif response.status_code == 429:
            wait = int(response.headers.get("Retry-After", 30))
            print(f"⏳ Rate limited — waiting {wait}s before continuing.")
            time.sleep(wait)
            continue
        elif response.status_code != 200:
            print(f"⚠️  Unexpected status {response.status_code} on page {page}. Stopping.")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        film_divs = soup.find_all("div", {"data-item-slug": True})

        if not film_divs:
            if page == 1:
                print("⚠️  No films on first page — profile may be empty or private.")
            else:
                print(f"✅ Finished at page {page - 1} ({len(films)} films total).")
            break

        print(f"   Found {len(film_divs)} films on page {page}")

        for film_div in film_divs:
            title = film_div.get("data-item-name") or (
                film_div["data-item-slug"].replace("-", " ").title()
            )
            rating, rating_stars = _parse_rating(film_div.find_parent("li"))
            films.append({"film_title": title, "rating": rating, "rating_stars": rating_stars})

        # Polite delay — randomise to avoid fingerprinting
        time.sleep(random.uniform(1.5, 3.0))

    return films


def run_scrape(username: str, output_csv: str, max_pages: int = 50) -> None:
    """Scrape *username* and save results to *output_csv*."""
    print(f"\n{'=' * 60}")
    print(f"Scraping Letterboxd profile: {username}")
    print(f"{'=' * 60}\n")

    films = scrape_letterboxd_films(username, max_pages=max_pages)

    if not films:
        print(f"\n❌ No films found for '{username}'.")
        print("   Possible causes: private profile, wrong username, or network issues.")
        return

    df = pd.DataFrame(films)
    df.to_csv(output_csv, index=False)

    print(f"\n{'=' * 60}")
    print(f"✅ Saved {len(df)} films to {output_csv}")
    print(f"{'=' * 60}")
    print(f"Films with ratings : {df['rating'].notna().sum()}")
    print(f"Films without ratings: {df['rating'].isna().sum()}")
    if not df["rating"].dropna().empty:
        print("\nRating distribution:")
        print(df["rating"].value_counts().sort_index())
