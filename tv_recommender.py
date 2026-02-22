import pandas as pd
import requests
import time
from collections import defaultdict

# TMDB API key
TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"

# Load both CSVs
print("Loading movie data...")
gorg_df = pd.read_csv("gorg_scraped_films.csv")
sali_df = pd.read_csv("salicore_scraped_films.csv")

print(f"Gorg has {len(gorg_df)} films")
print(f"Sali has {len(sali_df)} films")

# Create sets of watched movies (normalized titles for matching)
def normalize_title(title):
    """Normalize title for better matching"""
    if not title:
        return ""
    import re
    title = str(title).lower().strip()
    title = re.sub(r'\s*\(\d{4}\)\s*', '', title)
    title = ' '.join(title.split())
    title = re.sub(r'[^\w\s]', '', title)
    return title

gorg_watched = set(gorg_df['film_title'].apply(normalize_title))
sali_watched = set(sali_df['film_title'].apply(normalize_title))

# Cache for TMDB data
tmdb_cache = {}

def get_tv_info(title):
    """Get TV show info from TMDB API"""
    cache_key = f"tv_{title}"
    if cache_key in tmdb_cache:
        return tmdb_cache[cache_key]
    
    url = "https://api.themoviedb.org/3/search/tv"
    params = {
        "api_key": TMDB_API_KEY,
        "query": title
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data["results"]:
            tv = data["results"][0]
            tmdb_cache[cache_key] = tv
            time.sleep(0.25)
            return tv
        else:
            tmdb_cache[cache_key] = None
            return None
    except Exception as e:
        print(f"Error fetching {title}: {e}")
        tmdb_cache[cache_key] = None
        return None

def get_similar_tv(tmdb_id, limit=10):
    """Get similar TV shows from TMDB"""
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/similar"
    params = {"api_key": TMDB_API_KEY}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.25)
        return data.get("results", [])[:limit]
    except Exception as e:
        print(f"Error fetching similar TV shows for {tmdb_id}: {e}")
        return []

def get_tv_recommendations(tmdb_id, limit=10):
    """Get TMDB TV recommendations"""
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/recommendations"
    params = {"api_key": TMDB_API_KEY}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.25)
        return data.get("results", [])[:limit]
    except Exception as e:
        print(f"Error fetching TV recommendations for {tmdb_id}: {e}")
        return []

# Find movies you both liked (rating >= 4.0) - use these to find similar TV shows
print("\n" + "="*60)
print("Finding movies you both loved to recommend TV shows...")
print("="*60)

both_loved = []
for gorg_movie in gorg_df.itertuples():
    gorg_title_norm = normalize_title(gorg_movie.film_title)
    if gorg_movie.rating and gorg_movie.rating >= 4.0:
        matching = sali_df[sali_df['film_title'].apply(normalize_title) == gorg_title_norm]
        if not matching.empty:
            sali_rating = matching.iloc[0]['rating']
            if sali_rating and sali_rating >= 4.0:
                both_loved.append({
                    'title': gorg_movie.film_title,
                    'gorg_rating': gorg_movie.rating,
                    'sali_rating': sali_rating,
                    'avg_rating': (gorg_movie.rating + sali_rating) / 2
                })

both_loved.sort(key=lambda x: x['avg_rating'], reverse=True)
print(f"\nFound {len(both_loved)} movies you both loved")

# Get TV recommendations based on loved movies
print("\n" + "="*60)
print("Getting TV show recommendations from TMDB...")
print("="*60)

tv_recommendations = defaultdict(lambda: {'count': 0, 'sources': [], 'tmdb_data': None})

MIN_TMDB_RATING = 7.0  # Higher threshold for TV shows
MIN_YEAR = 2000
MAX_YEAR = 2026

# Also get popular TV shows by genre
print("\nGetting popular TV shows by genre...")
tv_genre_map = {
    'Drama': 18,
    'Thriller': 53,
    'Mystery': 9648,
    'Crime': 80,
    'Sci-Fi': 8785,
    'Horror': 27,
    'Comedy': 35
}

for genre_name, genre_id in tv_genre_map.items():
    url = f"https://api.themoviedb.org/3/discover/tv"
    params = {
        "api_key": TMDB_API_KEY,
        "with_genres": genre_id,
        "sort_by": "popularity.desc",
        "vote_average.gte": MIN_TMDB_RATING,
        "first_air_date.gte": f"{MIN_YEAR}-01-01",
        "first_air_date.lte": f"{MAX_YEAR}-12-31"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.25)
        
        for tv in data.get("results", [])[:15]:
            tv_title = tv.get('name', '')
            tv_title_norm = normalize_title(tv_title)
            
            # Check if already watched (as a movie - might be same title)
            if tv_title_norm not in gorg_watched and tv_title_norm not in sali_watched:
                tv_rating = tv.get('vote_average', 0)
                first_air_date = tv.get('first_air_date', '')
                year = int(first_air_date[:4]) if first_air_date and len(first_air_date) >= 4 else 0
                
                if tv_rating >= MIN_TMDB_RATING and MIN_YEAR <= year <= MAX_YEAR:
                    tv_recommendations[tv_title]['count'] += 1
                    tv_recommendations[tv_title]['sources'].append(f"Popular {genre_name}")
                    if not tv_recommendations[tv_title]['tmdb_data']:
                        tv_recommendations[tv_title]['tmdb_data'] = tv

    except Exception as e:
        print(f"Error fetching {genre_name} TV shows: {e}")

# Sort recommendations
sorted_tv_recs = sorted(tv_recommendations.items(), key=lambda x: (
    x[1]['count'],
    x[1]['tmdb_data'].get('vote_average', 0) if x[1]['tmdb_data'] else 0
), reverse=True)

print("\n" + "="*60)
print(f"TOP TV SHOW RECOMMENDATIONS (rating >= {MIN_TMDB_RATING}, {MIN_YEAR}-{MAX_YEAR})")
print("="*60)

tv_recommendations_list = []
for title, data in sorted_tv_recs[:30]:
    tmdb_data = data['tmdb_data']
    if tmdb_data:
        first_air_date = tmdb_data.get('first_air_date', 'N/A')
        year = first_air_date[:4] if first_air_date != 'N/A' else 'N/A'
        overview = tmdb_data.get('overview', 'No overview available')
        rating = tmdb_data.get('vote_average', 'N/A')
        poster_path = tmdb_data.get('poster_path', '')
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        
        print(f"\n📺 {title} ({year})")
        print(f"   ⭐ TMDB Rating: {rating:.1f}")
        print(f"   📝 {overview[:120]}...")
        
        tv_recommendations_list.append({
            'title': title,
            'year': year,
            'tmdb_rating': rating,
            'overview': overview,
            'recommended_because': ', '.join(data['sources'][:3]) if data['sources'] else 'Popular',
            'recommendation_count': data['count'],
            'tmdb_id': tmdb_data.get('id'),
            'poster_url': poster_url
        })

# Save TV recommendations to CSV
if tv_recommendations_list:
    tv_df = pd.DataFrame(tv_recommendations_list)
    tv_df.to_csv('tv_recommendations.csv', index=False)
    print(f"\n✅ Saved {len(tv_recommendations_list)} TV show recommendations to tv_recommendations.csv")

print("\n" + "="*60)
print("Summary")
print("="*60)
print(f"✅ Generated {len(tv_recommendations_list)} TV show recommendations")
print(f"✅ Saved to tv_recommendations.csv")

