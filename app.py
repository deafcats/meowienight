import json
import os
import random
import re
import threading
from functools import lru_cache
from urllib.parse import quote_plus

import pandas as pd
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "2073a6aadc1cb24381bc90c83ace363a")
OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "b9a5e69d")
DATA_DIR = os.environ.get("DATA_DIR", ".")

SUPERHERO_KEYWORDS = {
    "spider-man", "batman", "superman", "iron man", "captain america",
    "avengers", "x-men", "guardians of the galaxy", "men in black",
    "marvel", "wolverine", "hulk", "thor", "ant-man", "black widow",
    "wonder woman", "flash", "aquaman", "green lantern", "deadpool",
    "venom", "doctor strange", "black panther", "shazam",
}

GENRE_ID_TO_NAME = {
    18: "Drama", 53: "Thriller", 9648: "Mystery", 80: "Crime",
    10402: "Music", 28: "Action", 35: "Comedy", 27: "Horror",
    878: "Science Fiction", 10749: "Romance", 16: "Animation",
    99: "Documentary", 14: "Fantasy", 36: "History", 37: "Western",
    10752: "War",
}

# ---------------------------------------------------------------------------
# Jinja filters
# ---------------------------------------------------------------------------

@app.template_filter("urlencode")
def urlencode_filter(s):
    return quote_plus(str(s))


@app.template_filter("tojsonfilter")
def tojson_filter(data):
    return json.dumps(data)

# ---------------------------------------------------------------------------
# Data loading (cached so CSVs are only read once per process)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_csv(path: str) -> pd.DataFrame:
    """Read a single CSV, returning an empty DataFrame on any error."""
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_data():
    """Return (recommendations, genre_recs, tv_recs, gorg_films, sali_films)."""
    d = DATA_DIR
    return (
        _load_csv(os.path.join(d, "movie_recommendations_improved.csv")),
        _load_csv(os.path.join(d, "genre_recommendations.csv")),
        _load_csv(os.path.join(d, "tv_recommendations.csv")),
        _load_csv(os.path.join(d, "gorg_scraped_films.csv")),
        _load_csv(os.path.join(d, "salicore_scraped_films.csv")),
    )


def invalidate_cache():
    """Call this after regenerating CSVs to force a fresh load."""
    _load_csv.cache_clear()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_title(title) -> str:
    return re.sub(r"\s*\(\d{4}\)\s*", "", str(title or "")).strip()


def _normalize_title(title) -> str:
    t = _clean_title(title).lower()
    return re.sub(r"[,:'\"]+", "", t).strip()


def _is_superhero(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in SUPERHERO_KEYWORDS)


def clean_rec(rec: dict) -> dict | None:
    """Validate and normalise a single recommendation dict. Returns None to discard."""
    if not isinstance(rec, dict):
        return None
    title = rec.get("title")
    if not isinstance(title, str):
        return None
    if _is_superhero(title):
        return None

    overview = rec.get("overview")
    if not isinstance(overview, str) or (isinstance(overview, float) and pd.isna(overview)):
        rec["overview"] = "No overview available"
    else:
        try:
            if pd.isna(overview):
                rec["overview"] = "No overview available"
        except (TypeError, ValueError):
            pass

    poster = rec.get("poster_url")
    try:
        rec["poster_url"] = None if (poster is None or pd.isna(poster)) else poster
    except (TypeError, ValueError):
        pass

    if "recommendation_count" not in rec:
        rec["recommendation_count"] = 1
    if "recommended_because" not in rec:
        rec["recommended_because"] = rec.get("genre", "Your rating history")

    try:
        rec["recommendation_count"] = float(rec["recommendation_count"])
    except (ValueError, TypeError):
        rec["recommendation_count"] = 1.0

    try:
        rec["tmdb_rating"] = float(rec.get("tmdb_rating", 0) or 0)
    except (ValueError, TypeError):
        rec["tmdb_rating"] = 0.0

    return rec


def _clean_list(records: list[dict]) -> list[dict]:
    return [r for r in (clean_rec(rec) for rec in records) if r is not None]


def _sort_recs(recs: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "rating":
        return sorted(recs, key=lambda x: x.get("tmdb_rating", 0), reverse=True)
    if sort_by == "year":
        return sorted(recs, key=lambda x: int(x.get("year", 0)) if str(x.get("year", 0)).isdigit() else 0, reverse=True)
    if sort_by == "year_oldest":
        return sorted(recs, key=lambda x: int(x.get("year", 0)) if str(x.get("year", 0)).isdigit() else 0)
    if sort_by == "title":
        return sorted(recs, key=lambda x: x.get("title", "").lower())
    # Default: recommendation_count + tmdb_rating
    return sorted(recs, key=lambda x: (x.get("recommendation_count", 0), x.get("tmdb_rating", 0)), reverse=True)


def _merge_genre_recs(main: list[dict], genre: list[dict]) -> list[dict]:
    """Append genre recs that are not already in main."""
    seen = {r.get("title", "").lower() for r in main}
    for rec in genre:
        if rec.get("title", "").lower() not in seen:
            main.append(rec)
            seen.add(rec.get("title", "").lower())
    return main


def _fetch_omdb_ratings(rec: dict) -> None:
    """Enrich *rec* in-place with imdb_id, imdb_rating, rotten_tomatoes_rating."""
    tmdb_id = rec.get("tmdb_id")
    if not tmdb_id:
        return
    try:
        r = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY},
            timeout=2,
        )
        if r.status_code != 200:
            return
        imdb_id = r.json().get("imdb_id")
        if not imdb_id:
            return
        rec["imdb_id"] = imdb_id
        omdb = requests.get(
            f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}",
            timeout=2,
        )
        if omdb.status_code == 200:
            data = omdb.json()
            if data.get("Response") == "True":
                rec["imdb_rating"] = data.get("imdbRating")
                for rating in data.get("Ratings", []):
                    if rating.get("Source") == "Rotten Tomatoes":
                        rec["rotten_tomatoes_rating"] = rating.get("Value")
                        break
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Prediction engine
# ---------------------------------------------------------------------------

def generate_prediction_reasons(movie, user_films, calculated_percent, genre_matches=None):
    reasons = []

    def clean(t):
        return _clean_title(t)

    if genre_matches:
        matched_with_ratings = []
        for match_title in genre_matches:
            match_norm = _normalize_title(match_title)
            for _, film in user_films.iterrows():
                if _normalize_title(film.get("film_title", "")) == match_norm:
                    matched_with_ratings.append((match_title, film.get("rating", 0)))
                    break
        matched_with_ratings.sort(key=lambda x: x[1], reverse=True)

        if matched_with_ratings:
            liked = [t for t, r in matched_with_ratings if r >= 4.0]
            disliked = [t for t, r in matched_with_ratings if r <= 2.5]

            if calculated_percent >= 60 and liked:
                reasons.append(f"You liked {', '.join(liked[:3])}")
            if calculated_percent <= 50 and disliked:
                reasons.append(f"You rated {', '.join(disliked[:2])} low")

            if len(reasons) < 3:
                used = set()
                for r in reasons:
                    used.update(r.replace("You liked ", "").replace("You rated ", "").replace(" low", "").split(", "))
                for title, rating in matched_with_ratings:
                    if title in used:
                        continue
                    if calculated_percent >= 60 and rating >= 4.0:
                        reasons.append(f"You liked {title}")
                    elif calculated_percent <= 50 and rating <= 2.5:
                        reasons.append(f"You rated {title} low")
                    if len(reasons) >= 3:
                        break

    if len(reasons) < 3:
        if calculated_percent <= 45:
            reasons.append("No similar movies in your history")
        else:
            loved = user_films[user_films["rating"] >= 4.0].nlargest(2, "rating")
            if not loved.empty:
                titles = [_clean_title(f.get("film_title", "")) for _, f in loved.iterrows()]
                reasons.append(f"You liked {', '.join(titles[:2])}")

    while len(reasons) < 3:
        reasons.append("Based on movie rating")

    return list(dict.fromkeys(reasons))[:3]


def predict_liking_percentage(movie, gorg_films, sali_films):
    movie_rating = movie.get("tmdb_rating", 0)
    movie_year = movie.get("year", 0)

    genre_ids = movie.get("genre_ids", [])
    if isinstance(genre_ids, str):
        genre_ids = [int(g.strip()) for g in genre_ids.split(",") if g.strip().isdigit()]

    source_movies = []
    recommended_because = movie.get("recommended_because", "")
    if isinstance(recommended_because, str):
        source_movies = [s.strip() for s in recommended_because.split(",") if s.strip()]

    def predict_for_user(user_films):
        if user_films.empty or "rating" not in user_films.columns:
            return max(35, min(45, (movie_rating / 10.0) * 100)), []

        movie_norm = _normalize_title(movie.get("title", ""))
        for _, film in user_films.iterrows():
            if _normalize_title(film.get("film_title", "")) == movie_norm:
                actual = film.get("rating", 0)
                return (actual / 5.0) * 100, [film.get("film_title", "")]

        source_matches = []
        for src in source_movies:
            src_norm = _normalize_title(src)
            for _, film in user_films.iterrows():
                if _normalize_title(film.get("film_title", "")) == src_norm:
                    source_matches.append((film.get("rating", 0), film.get("film_title", "")))
                    break

        year_matches = []
        if movie_year > 0:
            for _, film in user_films.iterrows():
                ym = re.search(r"\((\d{4})\)", str(film.get("film_title", "")))
                if ym and abs(int(ym.group(1)) - movie_year) <= 5:
                    year_matches.append((film.get("rating", 0), film.get("film_title", "")))

        if source_matches:
            ratings = [m[0] for m in source_matches]
            avg = sum(ratings) / len(ratings)
            tmdb_base = (movie_rating / 10.0) * 100
            pred = (avg / 5.0) * 100 * 0.7 + tmdb_base * 0.3
            if avg >= 4.5:
                pred = min(85, pred)
            elif avg >= 4.0:
                pred = min(75, pred)
            elif avg <= 2.5:
                pred = max(25, min(45, pred))
            return max(25, min(85, pred)), [m[1] for m in source_matches[:3]]

        if len(year_matches) >= 3:
            avg = sum(m[0] for m in year_matches) / len(year_matches)
            tmdb_base = (movie_rating / 10.0) * 100
            pred = (avg / 5.0) * 100 * 0.5 + tmdb_base * 0.5
            return max(30, min(70, pred)), [m[1] for m in year_matches[:3]]

        # No evidence — predict conservatively
        if movie_rating >= 8.5:
            pred = 40
        elif movie_rating >= 7.5:
            pred = 38
        elif movie_rating >= 7.0:
            pred = 35
        elif movie_rating >= 6.0:
            pred = 32
        else:
            pred = 28
        return max(25, min(40, pred)), []

    gorg_pct, gorg_matches = predict_for_user(gorg_films)
    sali_pct, sali_matches = predict_for_user(sali_films)

    return {
        "sali_percent": round(sali_pct),
        "gorg_percent": round(gorg_pct),
        "sali_reasons": generate_prediction_reasons(movie, sali_films, sali_pct, sali_matches),
        "gorg_reasons": generate_prediction_reasons(movie, gorg_films, gorg_pct, gorg_matches),
    }


def _add_predictions(recs, gorg_films, sali_films):
    for rec in recs:
        p = predict_liking_percentage(rec, gorg_films, sali_films)
        rec.update({
            "sali_percent": p["sali_percent"],
            "gorg_percent": p["gorg_percent"],
            "sali_reasons": p["sali_reasons"],
            "gorg_reasons": p["gorg_reasons"],
        })

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    recommendations, genre_recs, tv_recs, gorg_films, sali_films = load_data()

    stats = {
        "gorg_total": len(gorg_films),
        "sali_total": len(sali_films),
        "recommendations_count": len(recommendations) + len(tv_recs),
        "genre_recommendations_count": len(genre_recs),
        "gorg_avg_rating": gorg_films["rating"].mean() if not gorg_films.empty and "rating" in gorg_films.columns else 0,
        "sali_avg_rating": sali_films["rating"].mean() if not sali_films.empty and "rating" in sali_films.columns else 0,
    }

    both_loved = _find_both_loved(gorg_films, sali_films, fetch_tmdb=True)
    both_loved_sorted = sorted(both_loved, key=lambda x: (x["gorg_rating"] + x["sali_rating"]) / 2, reverse=True)

    stats["both_loved_count"] = len(both_loved_sorted)
    stats["both_loved"] = both_loved_sorted[:5]
    stats["both_loved_full"] = both_loved_sorted

    top_recommendations = []
    if not recommendations.empty:
        recs_list = _clean_list(recommendations.to_dict("records"))
        top_recommendations = _sort_recs(recs_list, "recommendation_count")[:6]
        for rec in top_recommendations:
            _fetch_omdb_ratings(rec)

    return render_template("index.html", stats=stats, top_recommendations=top_recommendations)


@app.route("/both-loved")
def both_loved():
    _, _, _, gorg_films, sali_films = load_data()
    both_loved_list = _find_both_loved(gorg_films, sali_films, fetch_tmdb=True, include_avg=True)
    both_loved_list = sorted(both_loved_list, key=lambda x: x.get("avg_rating", 0), reverse=True)
    return render_template("both_loved.html", both_loved=both_loved_list)


@app.route("/recommendations")
def recommendations():
    recs_df, genre_df, tv_df, gorg_films, sali_films = load_data()

    recs_list = _clean_list(recs_df.to_dict("records") if not recs_df.empty else [])
    genre_list = _clean_list(genre_df.to_dict("records") if not genre_df.empty else [])
    tv_list = _clean_list(tv_df.to_dict("records") if not tv_df.empty else [])

    recs_list = _merge_genre_recs(recs_list, genre_list)
    recs_list = _sort_recs(recs_list, "recommendation_count")
    tv_list = _sort_recs(tv_list, "recommendation_count")

    _add_predictions(recs_list, gorg_films, sali_films)
    _add_predictions(tv_list, gorg_films, sali_films)

    return render_template(
        "recommendations.html",
        recommendations=recs_list,
        tv_recommendations=tv_list,
        genre_recommendations=genre_list,
    )


@app.route("/api/recommendations")
def api_recommendations():
    recs_df, genre_df, tv_df, gorg_films, sali_films = load_data()

    decade = request.args.get("decade", "")
    sort_by = request.args.get("sort_by", "recommendation_count")
    surprise = request.args.get("surprise", "false") == "true"
    content_type = request.args.get("type", "all")
    genre_filter = request.args.get("genre", "")

    if content_type == "tv":
        recs_list = _clean_list(tv_df.to_dict("records") if not tv_df.empty else [])
    elif content_type == "movies":
        main = _clean_list(recs_df.to_dict("records") if not recs_df.empty else [])
        genre = _clean_list(genre_df.to_dict("records") if not genre_df.empty else [])
        recs_list = _merge_genre_recs(main, genre)
    else:  # all
        main = _clean_list(recs_df.to_dict("records") if not recs_df.empty else [])
        genre = _clean_list(genre_df.to_dict("records") if not genre_df.empty else [])
        tv = _clean_list(tv_df.to_dict("records") if not tv_df.empty else [])
        recs_list = main + genre + tv

    # Apply filters
    filtered = []
    for rec in recs_list:
        year = int(rec.get("year", 0)) if str(rec.get("year", 0)).isdigit() else 0
        if decade:
            decade_start = int(decade)
            if not (decade_start <= year < decade_start + 10):
                continue
        if genre_filter:
            rec_genre = rec.get("genre", "").lower()
            if rec_genre == genre_filter.lower():
                filtered.append(rec)
                continue
            genre_ids_str = rec.get("genre_ids", "")
            if genre_ids_str:
                try:
                    gids = [int(g.strip()) for g in str(genre_ids_str).split(",") if g.strip().isdigit()]
                    names = [GENRE_ID_TO_NAME.get(g, "") for g in gids]
                    if genre_filter.lower() in [n.lower() for n in names if n]:
                        filtered.append(rec)
                except Exception:
                    pass
            continue
        filtered.append(rec)

    # Surprise Us
    surprise_movie = None
    if surprise and filtered:
        watched_based = [
            r for r in filtered
            if "Popular" not in str(r.get("recommended_because", ""))
        ]
        pool = watched_based or filtered
        pool_sorted = sorted(pool, key=lambda x: float(x.get("recommendation_count", 0)), reverse=True)
        surprise_movie = random.choice(pool_sorted[:10])
        filtered = [r for r in filtered if r.get("tmdb_id") != surprise_movie.get("tmdb_id")]

    filtered = _sort_recs(filtered, sort_by)
    _add_predictions(filtered, gorg_films, sali_films)

    # Fetch OMDB ratings for first 10
    for rec in filtered[:10]:
        _fetch_omdb_ratings(rec)

    if surprise_movie:
        p = predict_liking_percentage(surprise_movie, gorg_films, sali_films)
        surprise_movie.update({
            "sali_percent": p["sali_percent"],
            "gorg_percent": p["gorg_percent"],
            "sali_reasons": p["sali_reasons"],
            "gorg_reasons": p["gorg_reasons"],
        })
        _fetch_omdb_ratings(surprise_movie)

    return jsonify({"surprise_movie": surprise_movie, "recommendations": filtered})


@app.route("/api/search")
def api_search():
    query = request.args.get("query", "").strip()
    limit = int(request.args.get("limit", 20))

    if not query:
        return jsonify({"results": [], "error": "Query parameter is required"})

    _, _, _, gorg_films, sali_films = load_data()

    try:
        resp = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_API_KEY, "query": query, "page": 1},
            timeout=5,
        )
        resp.raise_for_status()
        movies = resp.json().get("results", [])[:limit]
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})

    results = []
    for movie in movies:
        year_raw = movie.get("release_date", "")[:4]
        movie_dict = {
            "tmdb_id": movie.get("id"),
            "title": movie.get("title", ""),
            "year": int(year_raw) if year_raw.isdigit() else 0,
            "overview": movie.get("overview") or "No overview available",
            "tmdb_rating": float(movie.get("vote_average") or 0),
            "poster_url": (
                f"https://image.tmdb.org/t/p/w500{movie['poster_path']}"
                if movie.get("poster_path") else None
            ),
            "genre_ids": movie.get("genre_ids", []),
            "recommendation_count": 0,
            "recommended_because": "Your rating history",
        }
        p = predict_liking_percentage(movie_dict, gorg_films, sali_films)
        movie_dict.update({
            "sali_percent": p["sali_percent"],
            "gorg_percent": p["gorg_percent"],
            "sali_reasons": p["sali_reasons"],
            "gorg_reasons": p["gorg_reasons"],
        })
        _fetch_omdb_ratings(movie_dict)
        results.append(movie_dict)

    return jsonify({"results": results})


@app.route("/api/genres")
def get_genres():
    recommendations, _, _, _, _ = load_data()
    genres: set[str] = set()
    if not recommendations.empty and "genre_ids" in recommendations.columns:
        for genre_str in recommendations["genre_ids"].dropna():
            if isinstance(genre_str, str):
                genres.update(g.strip() for g in genre_str.split(","))
    return jsonify(sorted(genres))


@app.route("/movie/<int:tmdb_id>")
def movie_detail(tmdb_id):
    try:
        resp = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY, "append_to_response": "credits,similar"},
            timeout=10,
        )
        resp.raise_for_status()
        movie = resp.json()
    except Exception as e:
        return f"Error loading movie: {e}", 404

    # Wikipedia summary
    wikipedia_url = wikipedia_summary = None
    try:
        wiki = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(movie['title'])}",
            timeout=5,
        )
        if wiki.status_code == 200:
            wd = wiki.json()
            wikipedia_url = wd.get("content_urls", {}).get("desktop", {}).get("page", "")
            wikipedia_summary = wd.get("extract", "")
    except Exception:
        pass

    # Wikipedia details (filming locations etc.)
    filming_locations, production_time, camera_info = [], None, None
    try:
        full_wiki = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "prop": "extracts", "exintro": False,
                "explaintext": True, "titles": movie["title"], "format": "json",
            },
            timeout=5,
        )
        if full_wiki.status_code == 200:
            pages = full_wiki.json().get("query", {}).get("pages", {})
            content = list(pages.values())[0].get("extract", "") if pages else ""
            loc_matches = re.findall(
                r"(?:filmed|shot|produced)\s+(?:in|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
                content, re.IGNORECASE,
            )
            filming_locations = list(set(loc_matches[:5]))
            tm = re.search(r"(?:production|filming)\s+(?:began|started|took|lasted)\s+([^\.]+)", content, re.IGNORECASE)
            production_time = tm.group(1).strip() if tm else None
            cm = re.search(r"(?:shot|filmed)\s+(?:on|with|using)\s+([^\.]+)", content, re.IGNORECASE)
            camera_info = cm.group(1).strip() if cm else None
    except Exception:
        pass

    # OMDB ratings
    imdb_rating = rotten_tomatoes_rating = imdb_id = None
    imdb_id = movie.get("imdb_id")
    if imdb_id:
        try:
            omdb = requests.get(
                f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}",
                timeout=5,
            )
            if omdb.status_code == 200:
                od = omdb.json()
                if od.get("Response") == "True":
                    imdb_rating = od.get("imdbRating")
                    for r in od.get("Ratings", []):
                        if r.get("Source") == "Rotten Tomatoes":
                            rotten_tomatoes_rating = r.get("Value")
                            break
        except Exception:
            pass

    def format_currency(amount):
        return f"${amount:,.0f}" if amount else "Not available"

    production_companies = [c.get("name", "") for c in movie.get("production_companies", [])]
    production_countries = [c.get("name", "") for c in movie.get("production_countries", [])]
    release_date = movie.get("release_date", "")
    year_shot = release_date[:4] if release_date else "N/A"

    facts = []
    if production_companies:
        facts.append(f"Produced by {production_companies[0]}")
    if production_countries:
        facts.append(f"Filmed in {', '.join(production_countries[:2])}")
    if movie.get("runtime"):
        facts.append(f"Runtime: {movie['runtime']} minutes")
    if movie.get("vote_count", 0) > 0:
        facts.append(f"Rated by {movie['vote_count']:,} people on TMDB")
    if movie.get("original_language"):
        facts.append(f"Original language: {movie['original_language'].upper()}")
    random_fact = random.choice(facts) if facts else "A critically acclaimed film"

    cast = movie.get("credits", {}).get("cast", [])[:10]
    similar = movie.get("similar", {}).get("results", [])[:6]

    _, _, _, gorg_films, sali_films = load_data()
    movie_for_prediction = {
        "tmdb_rating": movie.get("vote_average", 0),
        "year": int(release_date[:4]) if release_date and len(release_date) >= 4 else 0,
        "genre_ids": [g.get("id") for g in movie.get("genres", [])],
        "title": movie.get("title", ""),
    }
    predictions = predict_liking_percentage(movie_for_prediction, gorg_films, sali_films)

    return render_template(
        "movie_detail.html",
        movie=movie,
        cast=cast,
        similar=similar,
        budget=format_currency(movie.get("budget", 0)),
        revenue=format_currency(movie.get("revenue", 0)),
        wikipedia_url=wikipedia_url,
        wikipedia_summary=wikipedia_summary,
        imdb_rating=imdb_rating,
        imdb_id=imdb_id,
        rotten_tomatoes_rating=rotten_tomatoes_rating,
        production_companies=production_companies,
        production_countries=production_countries,
        year_shot=year_shot,
        filming_locations=filming_locations,
        production_time=production_time,
        camera_info=camera_info,
        random_fact=random_fact,
        sali_percent=predictions.get("sali_percent"),
        gorg_percent=predictions.get("gorg_percent"),
        sali_reasons=predictions.get("sali_reasons", []),
        gorg_reasons=predictions.get("gorg_reasons", []),
    )


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _find_both_loved(gorg_films, sali_films, fetch_tmdb=False, include_avg=False):
    result = []
    if gorg_films.empty or sali_films.empty:
        return result

    for _, gm in gorg_films.iterrows():
        if not (gm.get("rating") and gm["rating"] >= 4.0):
            continue
        lower = str(gm["film_title"]).lower()
        match = sali_films[sali_films["film_title"].str.lower() == lower]
        if match.empty:
            continue
        sali_rating = match.iloc[0].get("rating", 0)
        if not (sali_rating and sali_rating >= 4.0):
            continue

        entry = {
            "title": gm["film_title"],
            "gorg_rating": gm["rating"],
            "sali_rating": sali_rating,
            "tmdb_id": None,
            "poster_url": None,
        }
        if include_avg:
            entry["avg_rating"] = (gm["rating"] + sali_rating) / 2

        if fetch_tmdb:
            try:
                title_clean = str(gm["film_title"]).strip()
                ym = re.search(r"\((\d{4})\)", title_clean)
                year = int(ym.group(1)) if ym else None
                if ym:
                    title_clean = re.sub(r"\s*\(\d{4}\)\s*", "", title_clean).strip()
                params = {"api_key": TMDB_API_KEY, "query": title_clean}
                if year:
                    params["year"] = year
                r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=3)
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    if results:
                        entry["tmdb_id"] = results[0].get("id")
                        pp = results[0].get("poster_path", "")
                        if pp:
                            entry["poster_url"] = f"https://image.tmdb.org/t/p/w500{pp}"
            except Exception:
                pass

        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Background pipeline scheduler
# ---------------------------------------------------------------------------

_pipeline_lock = threading.Lock()


def _run_pipeline_and_reload():
    """Run the full data pipeline then invalidate the CSV cache."""
    if not _pipeline_lock.acquire(blocking=False):
        print("Pipeline already running — skipping.")
        return
    try:
        from pipeline import run_pipeline
        run_pipeline(data_dir=DATA_DIR)
        invalidate_cache()
        print("CSV cache invalidated — fresh data will be served.")
    finally:
        _pipeline_lock.release()


def _start_scheduler():
    """Boot the APScheduler: run immediately if no data, then twice weekly."""
    from pipeline import csvs_exist

    scheduler = BackgroundScheduler(daemon=True)

    # Twice weekly — Monday and Thursday at 04:00 UTC
    scheduler.add_job(
        _run_pipeline_and_reload,
        "cron",
        day_of_week="mon,thu",
        hour=4,
        minute=0,
        id="pipeline_scheduled",
        replace_existing=True,
    )
    scheduler.start()

    # If CSVs don't exist yet, kick off an immediate run in a thread
    if not csvs_exist(DATA_DIR):
        print("No data found — running pipeline now...")
        threading.Thread(target=_run_pipeline_and_reload, daemon=True).start()
    else:
        print("Existing data found — loading from cache.")


# Start the scheduler when the module is imported by gunicorn / flask run.
# Guard against double-start in debug reloader.
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
    _start_scheduler()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
