"""
TV Show Recommendation System
==============================

Generates TV recommendations based on genre preferences
derived from movies both users loved.
"""

import os
import re
import time
from collections import defaultdict

import pandas as pd
import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "2073a6aadc1cb24381bc90c83ace363a")

MIN_TMDB_RATING = 7.0
MIN_YEAR = 2000
MAX_YEAR = 2026

TV_GENRE_MAP = {
    "Drama": 18,
    "Thriller": 53,
    "Mystery": 9648,
    "Crime": 80,
    "Sci-Fi": 8785,
    "Horror": 27,
    "Comedy": 35,
}


def _normalize_title(title) -> str:
    if not title:
        return ""
    t = str(title).lower().strip()
    t = re.sub(r"\s*\(\d{4}\)\s*", "", t)
    t = " ".join(t.split())
    t = re.sub(r"[^\w\s]", "", t)
    return t


def run(data_dir: str = ".") -> None:
    """Run the TV recommendation pipeline, writing CSVs to *data_dir*."""
    gorg_path = os.path.join(data_dir, "gorg_scraped_films.csv")
    sali_path = os.path.join(data_dir, "salicore_scraped_films.csv")

    print("Loading data for TV recommendations...")
    gorg_df = pd.read_csv(gorg_path)
    sali_df = pd.read_csv(sali_path)

    gorg_watched = set(gorg_df["film_title"].apply(_normalize_title))
    sali_watched = set(sali_df["film_title"].apply(_normalize_title))

    tv_recs: dict = defaultdict(lambda: {"count": 0, "sources": [], "tmdb_data": None})

    print("Getting popular TV shows by genre...")
    for genre_name, genre_id in TV_GENRE_MAP.items():
        try:
            resp = requests.get(
                "https://api.themoviedb.org/3/discover/tv",
                params={
                    "api_key": TMDB_API_KEY,
                    "with_genres": genre_id,
                    "sort_by": "popularity.desc",
                    "vote_average.gte": MIN_TMDB_RATING,
                    "first_air_date.gte": f"{MIN_YEAR}-01-01",
                    "first_air_date.lte": f"{MAX_YEAR}-12-31",
                },
                timeout=10,
            )
            resp.raise_for_status()
            time.sleep(0.25)

            for tv in resp.json().get("results", [])[:15]:
                name = tv.get("name", "")
                norm = _normalize_title(name)
                if norm in gorg_watched or norm in sali_watched:
                    continue
                rating = tv.get("vote_average", 0)
                fad = tv.get("first_air_date", "")
                year = int(fad[:4]) if fad and len(fad) >= 4 else 0
                if rating >= MIN_TMDB_RATING and MIN_YEAR <= year <= MAX_YEAR:
                    tv_recs[name]["count"] += 1
                    tv_recs[name]["sources"].append(f"Popular {genre_name}")
                    if not tv_recs[name]["tmdb_data"]:
                        tv_recs[name]["tmdb_data"] = tv
        except Exception as exc:
            print(f"  Error fetching {genre_name} TV: {exc}")

    sorted_recs = sorted(
        tv_recs.items(),
        key=lambda x: (
            x[1]["count"],
            x[1]["tmdb_data"].get("vote_average", 0) if x[1]["tmdb_data"] else 0,
        ),
        reverse=True,
    )

    rows = []
    for title, data in sorted_recs[:30]:
        td = data["tmdb_data"]
        if not td:
            continue
        fad = td.get("first_air_date", "N/A")
        pp = td.get("poster_path", "")
        rows.append({
            "title": title,
            "year": fad[:4] if fad != "N/A" else "N/A",
            "tmdb_rating": td.get("vote_average", 0),
            "overview": td.get("overview") or "No overview available",
            "recommended_because": ", ".join(data["sources"][:3]) or "Popular",
            "recommendation_count": data["count"],
            "tmdb_id": td.get("id"),
            "poster_url": f"https://image.tmdb.org/t/p/w500{pp}" if pp else None,
        })

    if rows:
        pd.DataFrame(rows).to_csv(os.path.join(data_dir, "tv_recommendations.csv"), index=False)
        print(f"✅ Saved {len(rows)} TV recommendations")

    print("TV recommendation pipeline complete.")


if __name__ == "__main__":
    run()
