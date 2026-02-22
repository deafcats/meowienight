"""
Movie Recommendation System
============================

Generates movie recommendations based on:
1. Movies both Gorg and Sali loved (rated 4+ stars)
2. Similar movies from TMDB API
3. Genre preferences from favourite movies
"""

import os
import re
import time
from collections import defaultdict

import pandas as pd
import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "2073a6aadc1cb24381bc90c83ace363a")

MIN_TMDB_RATING = 6.0
MIN_VOTE_COUNT = 500
MIN_YEAR = 1970
MAX_YEAR = 2026

SUPERHERO_GENRES = [28, 878, 12]
SUPERHERO_KEYWORDS = [
    "superhero", "spider-man", "batman", "superman", "iron man",
    "captain america", "avengers", "x-men", "guardians of the galaxy",
    "men in black", "marvel", "wolverine", "hulk", "thor", "ant-man",
    "black widow", "wonder woman", "flash", "aquaman", "green lantern",
    "deadpool", "venom", "doctor strange", "black panther", "shazam",
]

PRIORITY_GENRES = [9648, 18, 53]  # Mystery, Drama, Thriller

_tmdb_cache: dict = {}


def _normalize_title(title) -> str:
    if not title:
        return ""
    t = str(title).lower().strip()
    t = re.sub(r"\s*\(\d{4}\)\s*", "", t)
    t = " ".join(t.split())
    t = re.sub(r"[^\w\s]", "", t)
    return t


def _tmdb_get(url, params, cache_key=None):
    if cache_key and cache_key in _tmdb_cache:
        return _tmdb_cache[cache_key]
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        time.sleep(0.25)
        if cache_key:
            _tmdb_cache[cache_key] = data
        return data
    except Exception as exc:
        print(f"  TMDB error: {exc}")
        if cache_key:
            _tmdb_cache[cache_key] = None
        return None


def _search_movie(title, year=None):
    title_clean = str(title).strip()
    ym = re.search(r"\((\d{4})\)", title_clean)
    if ym and not year:
        year = int(ym.group(1))
        title_clean = re.sub(r"\s*\(\d{4}\)\s*", "", title_clean).strip()
    ck = f"{title_clean}_{year}" if year else title_clean
    data = _tmdb_get(
        "https://api.themoviedb.org/3/search/movie",
        {"api_key": TMDB_API_KEY, "query": title_clean, **({"year": year} if year else {})},
        cache_key=ck,
    )
    if isinstance(data, dict) and data.get("results"):
        return data["results"][0]
    return None


def _get_details(tmdb_id):
    data = _tmdb_get(
        f"https://api.themoviedb.org/3/movie/{tmdb_id}",
        {"api_key": TMDB_API_KEY},
        cache_key=f"detail_{tmdb_id}",
    )
    return data


def _get_related(tmdb_id, kind="recommendations", limit=10):
    data = _tmdb_get(
        f"https://api.themoviedb.org/3/movie/{tmdb_id}/{kind}",
        {"api_key": TMDB_API_KEY},
    )
    return (data.get("results", []) if isinstance(data, dict) else [])[:limit]


def _is_superhero(title, genre_ids):
    if any(kw in title.lower() for kw in SUPERHERO_KEYWORDS):
        return True
    action_count = sum(1 for g in genre_ids if g in SUPERHERO_GENRES)
    return action_count >= 2 and len(genre_ids) <= 4


def run(data_dir: str = ".") -> None:
    """Run the full movie recommendation pipeline, writing CSVs to *data_dir*."""
    gorg_path = os.path.join(data_dir, "gorg_scraped_films.csv")
    sali_path = os.path.join(data_dir, "salicore_scraped_films.csv")

    print("Loading movie data...")
    gorg_df = pd.read_csv(gorg_path)
    sali_df = pd.read_csv(sali_path)
    print(f"Gorg has {len(gorg_df)} films, Sali has {len(sali_df)} films")

    gorg_watched = set(gorg_df["film_title"].apply(_normalize_title))
    sali_watched = set(sali_df["film_title"].apply(_normalize_title))
    all_watched = (
        set(gorg_df["film_title"].str.lower().str.strip())
        | set(sali_df["film_title"].str.lower().str.strip())
    )
    both_watched = gorg_watched & sali_watched

    print(f"Both watched: {len(both_watched)}")

    # --- Find movies both loved ---
    both_loved = []
    for row in gorg_df.itertuples():
        if not (row.rating and row.rating >= 4.0):
            continue
        norm = _normalize_title(row.film_title)
        match = sali_df[sali_df["film_title"].apply(_normalize_title) == norm]
        if match.empty:
            continue
        sr = match.iloc[0]["rating"]
        if sr and sr >= 4.0:
            both_loved.append({
                "title": row.film_title,
                "gorg_rating": row.rating,
                "sali_rating": sr,
                "avg_rating": (row.rating + sr) / 2,
            })
    both_loved.sort(key=lambda x: x["avg_rating"], reverse=True)
    print(f"Found {len(both_loved)} movies both loved")

    # --- Generate recommendations from loved movies ---
    recommendations: dict = defaultdict(lambda: {"count": 0, "sources": [], "tmdb_data": None, "genre_ids": []})

    for loved in both_loved:
        info = _search_movie(loved["title"])
        if not (info and info.get("id")):
            continue
        tmdb_id = info["id"]
        print(f"  Processing: {loved['title']} (TMDB {tmdb_id})")

        details = _get_details(tmdb_id)
        all_suggestions = _get_related(tmdb_id, "recommendations") + _get_related(tmdb_id, "similar")

        for movie in all_suggestions:
            title = movie.get("title", "")
            title_norm = _normalize_title(title)
            rating = movie.get("vote_average", 0)
            votes = movie.get("vote_count", 0)
            rd = movie.get("release_date", "")
            year = int(rd[:4]) if rd and len(rd) >= 4 else 0
            genre_ids = movie.get("genre_ids", [])

            watched = (
                title_norm in gorg_watched
                or title_norm in sali_watched
                or title.lower().strip() in all_watched
                or title_norm == _normalize_title(loved["title"])
            )
            if not watched:
                for wt in gorg_watched | sali_watched:
                    if len(title_norm) > 8 and len(wt) > 8:
                        if title_norm in wt or wt in title_norm:
                            shorter, longer = sorted([len(title_norm), len(wt)])
                            if shorter / longer > 0.7:
                                watched = True
                                break
            if watched:
                continue

            if _is_superhero(title, genre_ids) and rating < 8.5:
                continue

            is_priority = any(g in PRIORITY_GENRES for g in genre_ids)
            threshold = 5.5 if is_priority else MIN_TMDB_RATING
            if rating < threshold or votes < MIN_VOTE_COUNT or not (MIN_YEAR <= year <= MAX_YEAR):
                continue

            weight = 3.0 if is_priority else 1.0
            recommendations[title]["count"] += weight
            recommendations[title]["sources"].append(loved["title"])
            if not recommendations[title]["tmdb_data"]:
                recommendations[title]["tmdb_data"] = movie
                recommendations[title]["genre_ids"] = genre_ids

    # --- Build CSV rows ---
    sorted_recs = sorted(
        recommendations.items(),
        key=lambda x: x[1]["count"] * 2 + (x[1]["tmdb_data"].get("vote_average", 0) if x[1]["tmdb_data"] else 0),
        reverse=True,
    )

    rows = []
    for title, data in sorted_recs[:25]:
        td = data["tmdb_data"]
        if not td:
            continue
        if _normalize_title(title) in (gorg_watched | sali_watched):
            continue
        rd = td.get("release_date", "N/A")
        pp = td.get("poster_path", "")
        rows.append({
            "title": title,
            "year": rd[:4] if rd != "N/A" else "N/A",
            "tmdb_rating": td.get("vote_average", 0),
            "overview": td.get("overview") or "No overview available",
            "recommended_because": ", ".join(data["sources"][:3]),
            "recommendation_count": data["count"],
            "tmdb_id": td.get("id"),
            "poster_url": f"https://image.tmdb.org/t/p/w500{pp}" if pp else None,
            "genre_ids": ", ".join(map(str, data.get("genre_ids", []))),
        })

    if rows:
        pd.DataFrame(rows).to_csv(os.path.join(data_dir, "movie_recommendations_improved.csv"), index=False)
        print(f"✅ Saved {len(rows)} movie recommendations")

    # --- Genre-based recommendations ---
    genre_counts: dict[str, int] = defaultdict(int)
    for loved in both_loved[:10]:
        info = _search_movie(loved["title"])
        if info and info.get("id"):
            det = _get_details(info["id"])
            if det:
                for g in det.get("genres", []):
                    genre_counts[g["name"]] += 1

    priority_names = ["Mystery", "Drama", "Thriller"]
    top_genres = [g for g in priority_names if g in genre_counts]
    for g, _ in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True):
        if g not in top_genres and len(top_genres) < 3:
            top_genres.append(g)

    genre_id_map = {
        "Drama": 18, "Thriller": 53, "Mystery": 9648, "Crime": 80,
        "Music": 10402, "Action": 28, "Comedy": 35, "Horror": 27,
        "Sci-Fi": 878, "Science Fiction": 878,
    }

    genre_rows = []
    for gname in top_genres:
        gid = genre_id_map.get(gname)
        if not gid:
            continue
        data = _tmdb_get(
            "https://api.themoviedb.org/3/discover/movie",
            {
                "api_key": TMDB_API_KEY,
                "with_genres": gid,
                "sort_by": "popularity.desc",
                "vote_average.gte": 7.0,
                "primary_release_date.gte": f"{MIN_YEAR}-01-01",
                "primary_release_date.lte": f"{MAX_YEAR}-12-31",
            },
        )
        if not data:
            continue
        limit = 20 if gname in priority_names else 10
        for movie in data.get("results", [])[:limit]:
            tn = _normalize_title(movie.get("title", ""))
            if tn in gorg_watched or tn in sali_watched:
                continue
            if _is_superhero(movie.get("title", ""), movie.get("genre_ids", [])):
                continue
            threshold = 5.5 if gname in priority_names else MIN_TMDB_RATING
            if movie.get("vote_average", 0) < threshold or movie.get("vote_count", 0) < MIN_VOTE_COUNT:
                continue
            pp = movie.get("poster_path", "")
            genre_rows.append({
                "title": movie["title"],
                "year": movie.get("release_date", "")[:4] or "N/A",
                "tmdb_rating": movie.get("vote_average"),
                "genre": gname,
                "tmdb_id": movie.get("id"),
                "poster_url": f"https://image.tmdb.org/t/p/w500{pp}" if pp else None,
                "overview": movie.get("overview") or "No overview available",
                "recommended_because": f"Popular {gname} film",
                "recommendation_count": 1,
            })

    if genre_rows:
        gdf = pd.DataFrame(genre_rows).drop_duplicates(subset=["title"]).sort_values("tmdb_rating", ascending=False)
        gdf.to_csv(os.path.join(data_dir, "genre_recommendations.csv"), index=False)
        print(f"✅ Saved {len(gdf)} genre recommendations")

    print("Movie recommendation pipeline complete.")


if __name__ == "__main__":
    run()
