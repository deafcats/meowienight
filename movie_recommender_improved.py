"""
Movie Recommendation System
============================

This script generates movie recommendations based on:
1. Movies both Gorg and Sali loved (rated 4+ stars)
2. Similar movies from TMDB API
3. Genre preferences from favorite movies

The script:
- Loads watched films from CSV files (scraped from Letterboxd)
- Finds movies both users loved
- Gets TMDB recommendations for those movies
- Filters out already-watched movies
- Saves recommendations to CSV for the Flask website
"""

import pandas as pd  # For working with CSV data
import requests  # For making API calls to TMDB
import time  # For rate limiting API requests
from collections import defaultdict  # For counting recommendations

# TMDB API key - used to fetch movie data
TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"

# Load both users' watched films from CSV files
# These files are created by the scraping scripts (scrape_letterboxd_gorg.py and scrape_letterboxd_sali.py)
print("Loading movie data...")
gorg_df = pd.read_csv("gorg_scraped_films.csv")  # Gorg's watched films and ratings
sali_df = pd.read_csv("salicore_scraped_films.csv")  # Sali's watched films and ratings

print(f"Gorg has {len(gorg_df)} films")
print(f"Sali has {len(sali_df)} films")

# Create sets of watched movies (normalized titles for matching)
def normalize_title(title):
    """
    Normalize movie title for better matching.
    
    This function removes variations that might prevent matching:
    - Years in parentheses: "The Matrix (1999)" -> "the matrix"
    - Extra spaces
    - Punctuation differences
    - Case differences
    
    Example: "The Matrix (1999)" and "the matrix" both become "the matrix"
    """
    if not title:
        return ""
    import re  # Regular expressions for pattern matching
    title = str(title).lower().strip()  # Convert to lowercase and remove spaces
    # Remove year patterns like (2014) or (2001) - these can cause mismatches
    title = re.sub(r'\s*\(\d{4}\)\s*', '', title)
    # Remove extra whitespace (multiple spaces become one)
    title = ' '.join(title.split())
    # Remove common punctuation that might differ between sources
    title = re.sub(r'[^\w\s]', '', title)
    return title

# Create normalized sets for efficient matching
# This allows us to quickly check if a movie has been watched
gorg_watched = set(gorg_df['film_title'].apply(normalize_title))  # Set of Gorg's watched movies (normalized)
sali_watched = set(sali_df['film_title'].apply(normalize_title))  # Set of Sali's watched movies (normalized)
both_watched = gorg_watched & sali_watched  # Movies both have watched (set intersection)

# Also create a set of all watched titles (original format) for fuzzy matching
# This helps catch variations in title formatting
all_watched_titles = set(gorg_df['film_title'].str.lower().str.strip()) | set(sali_df['film_title'].str.lower().str.strip())

print(f"\nMovies you've both watched: {len(both_watched)}")
print(f"Movies only Gorg watched: {len(gorg_watched - sali_watched)}")
print(f"Movies only Sali watched: {len(sali_watched - gorg_watched)}")

# Cache for TMDB data - stores API responses to avoid duplicate requests
# Key: movie title, Value: movie data from TMDB
tmdb_cache = {}

def get_movie_info(title, year=None):
    """
    Get movie info from TMDB API with caching.
    
    This function searches TMDB for a movie by title and returns the first result.
    Uses caching to avoid making the same API call twice.
    
    Args:
        title: Movie title to search for (may include year in parentheses like "The Martian (2015)")
        year: Optional year to narrow down search
    
    Returns:
        Dictionary with movie data from TMDB, or None if not found
    """
    # Extract year from title if it's in parentheses (e.g., "The Martian (2015)")
    import re
    title_clean = str(title).strip()
    year_match = re.search(r'\((\d{4})\)', title_clean)
    if year_match and not year:
        year = int(year_match.group(1))
        # Remove year from title for cleaner search
        title_clean = re.sub(r'\s*\(\d{4}\)\s*', '', title_clean).strip()
    
    # Create cache key from title and year (if provided)
    cache_key = f"{title_clean}_{year}" if year else title_clean
    # Check if we already fetched this movie
    if cache_key in tmdb_cache:
        return tmdb_cache[cache_key]
    
    # TMDB search endpoint
    url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": TMDB_API_KEY,  # API key for authentication
        "query": title_clean  # Movie title to search (without year)
    }
    # Add year to search if provided (helps find the right movie)
    if year:
        params["year"] = year
    
    try:
        # Make API request
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raise error if request failed
        data = response.json()
        
        # Check if we got results
        if data["results"]:
            movie = data["results"][0]  # Take the first (most relevant) result
            tmdb_cache[cache_key] = movie  # Store in cache
            time.sleep(0.25)  # Rate limiting - be nice to TMDB API
            return movie
        else:
            # No results found
            tmdb_cache[cache_key] = None
            return None
    except Exception as e:
        print(f"Error fetching {title}: {e}")
        tmdb_cache[cache_key] = None
        return None

def get_similar_movies(tmdb_id, limit=10):
    """
    Get similar movies from TMDB based on a movie's TMDB ID.
    
    TMDB's "similar" endpoint finds movies with similar themes, genres, etc.
    
    Args:
        tmdb_id: The TMDB ID of the source movie
        limit: Maximum number of similar movies to return
    
    Returns:
        List of similar movie dictionaries
    """
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/similar"
    params = {"api_key": TMDB_API_KEY}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.25)  # Rate limiting - wait 0.25 seconds between requests
        return data.get("results", [])[:limit]  # Return up to 'limit' results
    except Exception as e:
        print(f"Error fetching similar movies for {tmdb_id}: {e}")
        return []

def get_movie_details(tmdb_id):
    """
    Get full movie details from TMDB including genres, budget, revenue, etc.
    
    This is more detailed than get_movie_info() and includes:
    - Genres
    - Budget and revenue
    - Production companies
    - Full cast and crew
    
    Args:
        tmdb_id: The TMDB ID of the movie
    
    Returns:
        Dictionary with full movie details, or None if error
    """
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    params = {"api_key": TMDB_API_KEY}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.25)  # Rate limiting
        return data
    except Exception as e:
        print(f"Error fetching details for {tmdb_id}: {e}")
        return None

def get_recommendations(tmdb_id, limit=10):
    """
    Get TMDB recommendations for a movie (often better than similar movies).
    
    TMDB's recommendation algorithm is usually better than "similar" because
    it uses more sophisticated matching (user ratings, viewing patterns, etc.)
    
    Args:
        tmdb_id: The TMDB ID of the source movie
        limit: Maximum number of recommendations to return
    
    Returns:
        List of recommended movie dictionaries
    """
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/recommendations"
    params = {"api_key": TMDB_API_KEY}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.25)  # Rate limiting
        return data.get("results", [])[:limit]
    except Exception as e:
        print(f"Error fetching recommendations for {tmdb_id}: {e}")
        return []

# Find movies you both liked (rating >= 4.0)
# These are the "seed" movies we'll use to find recommendations
print("\n" + "="*60)
print("Finding movies you both loved (rating >= 4.0)...")
print("="*60)

both_loved = []
# Loop through Gorg's films
for gorg_movie in gorg_df.itertuples():
    # Normalize title for matching (handles case/punctuation differences)
    gorg_title_norm = normalize_title(gorg_movie.film_title)
    # Only consider movies Gorg rated 4.0 or higher (out of 5.0)
    if gorg_movie.rating and gorg_movie.rating >= 4.0:
        # Check if Sali also watched this movie
        matching = sali_df[sali_df['film_title'].apply(normalize_title) == gorg_title_norm]
        if not matching.empty:
            sali_rating = matching.iloc[0]['rating']
            # Check if Sali also rated it 4.0 or higher
            if sali_rating and sali_rating >= 4.0:
                # Both loved it! Add to our list
                both_loved.append({
                    'title': gorg_movie.film_title,
                    'gorg_rating': gorg_movie.rating,
                    'sali_rating': sali_rating,
                    'avg_rating': (gorg_movie.rating + sali_rating) / 2  # Average of both ratings
                })

both_loved.sort(key=lambda x: x['avg_rating'], reverse=True)
print(f"\nFound {len(both_loved)} movies you both loved:")
for movie in both_loved[:10]:
    print(f"  {movie['title']} - Gorg: {movie['gorg_rating']:.1f}, Sali: {movie['sali_rating']:.1f}, Avg: {movie['avg_rating']:.1f}")

# Get TMDB info for both loved movies and find similar ones
# This is the main recommendation logic
print("\n" + "="*60)
print("Getting recommendations from TMDB...")
print("="*60)

# Dictionary to store recommendations
# Key: movie title, Value: dict with count (how many times recommended), sources (which movies led to this), etc.
recommendations = defaultdict(lambda: {'count': 0, 'sources': [], 'tmdb_data': None, 'genres': []})

# Configuration - adjust these to change what gets recommended
MIN_TMDB_RATING = 6.0  # Minimum TMDB rating (out of 10) - only recommend well-rated movies
MIN_VOTE_COUNT = 500  # Minimum number of votes on TMDB - ensures movies are well-known
MIN_YEAR = 1970  # Don't recommend movies older than this year
MAX_YEAR = 2026  # Don't recommend movies newer than this year

# Genres to deprioritize (superhero/action blockbusters)
SUPERHERO_GENRES = [28, 878, 12]  # Action, Science Fiction, Adventure (common in superhero movies)
SUPERHERO_KEYWORDS = ['superhero', 'spider-man', 'batman', 'superman', 'iron man', 'captain america', 'avengers', 'x-men', 'guardians of the galaxy', 'men in black', 'marvel', 'dc', 'comic', 'comics', 'superheroes', 'wolverine', 'hulk', 'thor', 'ant-man', 'black widow', 'wonder woman', 'flash', 'aquaman', 'green lantern', 'deadpool', 'venom', 'doctor strange', 'black panther', 'shazam']

# Genres to prioritize (mystery, drama, thriller)
PRIORITY_GENRES = [9648, 18, 53]  # Mystery (9648), Drama (18), Thriller (53)

# Process ALL loved movies to get better recommendations
# Using all movies gives us a more diverse set of recommendations
# that better matches your actual taste
for loved_movie in both_loved:
    print(f"\nProcessing: {loved_movie['title']}")
    # Get TMDB info for this loved movie
    tmdb_info = get_movie_info(loved_movie['title'])
    
    if tmdb_info and tmdb_info.get('id'):
        tmdb_id = tmdb_info['id']
        print(f"  ✓ Found in TMDB (ID: {tmdb_id})")
        
        # Get both recommendations and similar movies from TMDB
        # We use both because they can give different results
        recs = get_recommendations(tmdb_id, limit=10)  # TMDB's recommendation algorithm
        similar = get_similar_movies(tmdb_id, limit=10)  # Similar movies by genre/theme
        all_suggestions = recs + similar  # Combine both lists
        
        # Debug: show how many suggestions we got
        print(f"  Found {len(recs)} recommendations and {len(similar)} similar movies ({len(all_suggestions)} total)")
        
        # Count how many pass filters
        passed = 0
        for movie in all_suggestions:
            similar_title_norm = normalize_title(movie.get('title', ''))
            tmdb_rating = movie.get('vote_average', 0)
            vote_count = movie.get('vote_count', 0)
            release_date = movie.get('release_date', '')
            year = int(release_date[:4]) if release_date and len(release_date) >= 4 else 0
            already_watched = similar_title_norm in gorg_watched or similar_title_norm in sali_watched
            
            if (not already_watched and tmdb_rating >= MIN_TMDB_RATING and vote_count >= MIN_VOTE_COUNT and MIN_YEAR <= year <= MAX_YEAR):
                passed += 1
        
        print(f"  → {passed} movies passed filters (not watched, rating >= {MIN_TMDB_RATING}, votes >= {MIN_VOTE_COUNT}, year {MIN_YEAR}-{MAX_YEAR})")
        
        # Get genres from the source movie (for later genre-based recommendations)
        details = get_movie_details(tmdb_id)
        source_genres = [g['name'] for g in details.get('genres', [])] if details else []
        
        # Process all suggestions from this loved movie
        for movie in all_suggestions:
            similar_title = movie.get('title', '')
            similar_title_norm = normalize_title(similar_title)
            
            # Filter criteria
            tmdb_rating = movie.get('vote_average', 0)
            vote_count = movie.get('vote_count', 0)  # Number of votes on TMDB
            release_date = movie.get('release_date', '')
            year = int(release_date[:4]) if release_date and len(release_date) >= 4 else 0
            
            # Check if already watched - use set lookup for efficiency
            already_watched = similar_title_norm in gorg_watched or similar_title_norm in sali_watched
            
            # Also check original title format (case-insensitive)
            if not already_watched:
                similar_title_lower = similar_title.lower().strip()
                already_watched = similar_title_lower in all_watched_titles
            
            # Check if the source movie itself is being recommended (shouldn't happen but just in case)
            if not already_watched:
                source_title_norm = normalize_title(loved_movie['title'])
                if similar_title_norm == source_title_norm:
                    already_watched = True
            
            # Additional fuzzy matching - check if normalized title is very similar to watched titles
            if not already_watched:
                for watched_title in gorg_watched | sali_watched:
                    # Check if titles are very similar (one contains the other or vice versa)
                    # Only match if both are substantial (not just common words)
                    if len(similar_title_norm) > 8 and len(watched_title) > 8:
                        # Check if one is a substring of the other (but not too short)
                        if (similar_title_norm in watched_title or watched_title in similar_title_norm):
                            # Calculate similarity ratio
                            shorter = min(len(similar_title_norm), len(watched_title))
                            longer = max(len(similar_title_norm), len(watched_title))
                            if shorter / longer > 0.7:  # 70% similarity threshold
                                already_watched = True
                                break
            
            # Check if this is a superhero/action blockbuster (to exclude or heavily deprioritize)
            is_superhero = False
            movie_genres = movie.get('genre_ids', [])
            title_lower = similar_title.lower()
            
            # Check if it's primarily a superhero/action movie
            # If it has action/sci-fi/adventure and few other genres, likely superhero
            action_sci_fi_count = sum(1 for g in movie_genres if g in SUPERHERO_GENRES)
            if action_sci_fi_count >= 2 and len(movie_genres) <= 4:
                # If it's mostly action/sci-fi/adventure with few other genres, likely superhero
                is_superhero = True
            if any(keyword in title_lower for keyword in SUPERHERO_KEYWORDS):
                is_superhero = True
            
            # Check if it's a priority genre (mystery, drama, thriller)
            is_priority = any(genre in PRIORITY_GENRES for genre in movie_genres)
            
            # EXCLUDE superhero movies entirely unless they're exceptional (8.5+ rating)
            # This is much more aggressive filtering
            if is_superhero and tmdb_rating < 8.5:
                continue  # Skip this movie entirely
            
            # Only add to recommendations if:
            # 1. Not already watched
            # 2. TMDB rating meets minimum threshold (lower for priority genres)
            # 3. Year is within our range
            if is_priority:
                rating_threshold = 5.5  # Lower threshold for mystery/drama/thriller
            else:
                rating_threshold = MIN_TMDB_RATING
            
            if (not already_watched and
                tmdb_rating >= rating_threshold and
                vote_count >= MIN_VOTE_COUNT and
                MIN_YEAR <= year <= MAX_YEAR):
                
                # Increment count (how many times this movie was recommended)
                # Give much more weight to priority genres
                if is_priority:
                    weight = 3.0  # Triple weight for mystery/drama/thriller
                else:
                    weight = 1.0
                
                recommendations[similar_title]['count'] += weight
                # Track which movie(s) led to this recommendation
                recommendations[similar_title]['sources'].append(loved_movie['title'])
                # Store TMDB data (only once, on first recommendation)
                if not recommendations[similar_title]['tmdb_data']:
                    recommendations[similar_title]['tmdb_data'] = movie
                    # genre_ids are just integers, we'll get genre names from details later if needed
                    recommendations[similar_title]['genre_ids'] = movie.get('genre_ids', [])

# Sort recommendations by number of sources and TMDB rating
# Movies recommended by multiple loved movies are ranked higher
def score_recommendation(rec_data):
    """
    Score recommendations: more sources = better, higher rating = better
    
    This scoring function prioritizes:
    1. Movies recommended by multiple loved movies (count * 2)
    2. Movies with higher TMDB ratings
    
    Returns a combined score for sorting
    """
    source_score = rec_data['count'] * 2  # Each source adds 2 points
    rating_score = rec_data['tmdb_data'].get('vote_average', 0) if rec_data['tmdb_data'] else 0
    return source_score + rating_score  # Combined score

# Sort all recommendations by score (highest first)
sorted_recs = sorted(recommendations.items(), key=lambda x: score_recommendation(x[1]), reverse=True)

print("\n" + "="*60)
print(f"TOP RECOMMENDATIONS (filtered: rating >= {MIN_TMDB_RATING}, {MIN_YEAR}-{MAX_YEAR})")
print("="*60)

# Build final recommendations list for CSV export
recommendations_list = []
for title, data in sorted_recs[:25]:  # Top 25 recommendations
    tmdb_data = data['tmdb_data']
    if tmdb_data:
        # Final check: make sure this movie isn't in watched lists
        # This is a double-check in case our earlier filtering missed something
        title_norm = normalize_title(title)
        
        # Check if already watched (with improved matching)
        already_watched = False
        for watched_title in gorg_watched | sali_watched:
            if title_norm == normalize_title(watched_title):
                already_watched = True
                print(f"⚠️  Skipping {title} - already watched")
                break
        
        # Skip if already watched
        if already_watched:
            continue
        
        # Extract movie details for CSV
        release_date = tmdb_data.get('release_date', 'N/A')
        year = release_date[:4] if release_date != 'N/A' else 'N/A'  # Extract year from date
        overview = tmdb_data.get('overview', 'No overview available')
        rating = tmdb_data.get('vote_average', 'N/A')  # TMDB rating (0-10)
        poster_path = tmdb_data.get('poster_path', '')
        # Build full poster URL if poster exists
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        
        # Print recommendation to console
        print(f"\n🎬 {title} ({year})")
        print(f"   ⭐ TMDB Rating: {rating:.1f} | Recommended by {data['count']} source(s)")
        print(f"   📚 Based on: {', '.join(data['sources'][:3])}")  # Show up to 3 source movies
        print(f"   📝 {overview[:120]}...")  # Truncate overview to 120 chars
        
        # Add to recommendations list for CSV export
        recommendations_list.append({
            'title': title,
            'year': year,
            'tmdb_rating': rating,
            'overview': overview,
            'recommended_because': ', '.join(data['sources'][:3]),  # Which movies led to this recommendation
            'recommendation_count': data['count'],  # How many times it was recommended
            'tmdb_id': tmdb_data.get('id'),  # TMDB ID for linking/details
            'poster_url': poster_url,  # Poster image URL
            'genre_ids': ', '.join(map(str, data.get('genre_ids', [])))  # Genre IDs as comma-separated string
        })

# Save recommendations to CSV
# This CSV file is used by the Flask website to display recommendations
if recommendations_list:
    rec_df = pd.DataFrame(recommendations_list)  # Convert list to pandas DataFrame
    rec_df.to_csv('movie_recommendations_improved.csv', index=False)  # Save to CSV (no row numbers)
    print(f"\n✅ Saved {len(recommendations_list)} recommendations to movie_recommendations_improved.csv")

# Also find movies based on genres you both like
# This is a secondary recommendation strategy: find popular movies in your favorite genres
print("\n" + "="*60)
print("Analyzing genre preferences...")
print("="*60)

# Get genres for movies you both loved
# Count how many times each genre appears in your favorite movies
genre_counts = defaultdict(int)
for loved_movie in both_loved[:10]:  # Check top 10 loved movies
    tmdb_info = get_movie_info(loved_movie['title'])
    if tmdb_info and tmdb_info.get('id'):
        details = get_movie_details(tmdb_info['id'])
        if details and details.get('genres'):
            # Count each genre
            for genre in details['genres']:
                genre_counts[genre['name']] += 1

# Display top genres
print("\nTop genres from movies you both loved:")
for genre, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:8]:
    print(f"  {genre}: {count}")

# Find movies neither has seen from high-rated films in favorite genres
# This finds popular, well-rated movies in your top genres
# Prioritize Mystery, Drama, Thriller over other genres
print("\n" + "="*60)
print("Finding popular movies in your favorite genres...")
print("="*60)

# Prioritize mystery, drama, thriller genres
priority_genre_names = ['Mystery', 'Drama', 'Thriller']
top_genres = []
# First add priority genres if they exist
for genre_name in priority_genre_names:
    if genre_name in genre_counts:
        top_genres.append(genre_name)
# Then add other top genres (up to 3 total)
for genre, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True):
    if genre not in top_genres and len(top_genres) < 3:
        top_genres.append(genre)

if not top_genres:
    # Fallback: use top 3 genres
    top_genres = [g for g, _ in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:3]]

print(f"Searching for movies in: {', '.join(top_genres)}")

# Get popular movies by genre using TMDB's discover endpoint
genre_recommendations = []
for genre_name in top_genres:
    # Map genre name to TMDB genre ID (simplified - you'd want a full mapping for all genres)
    # TMDB uses numeric IDs for genres, not names
    genre_id_map = {
        'Drama': 18,
        'Thriller': 53,
        'Mystery': 9648,
        'Crime': 80,
        'Music': 10402,
        'Action': 28,
        'Comedy': 35,
        'Horror': 27,
        'Sci-Fi': 878,
        'Science Fiction': 878
    }
    
    genre_id = genre_id_map.get(genre_name)
    if genre_id:
        # TMDB discover endpoint - finds movies matching criteria
        url = f"https://api.themoviedb.org/3/discover/movie"
        params = {
            "api_key": TMDB_API_KEY,
            "with_genres": genre_id,  # Filter by genre
            "sort_by": "popularity.desc",  # Sort by popularity (most popular first)
            "vote_average.gte": 7.0,  # Minimum rating 7.0/10
            "primary_release_date.gte": f"{MIN_YEAR}-01-01",  # Not older than MIN_YEAR
            "primary_release_date.lte": f"{MAX_YEAR}-12-31"  # Not newer than MAX_YEAR
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            time.sleep(0.25)  # Rate limiting
            
            # Process up to 20 movies from this genre (more for priority genres)
            limit = 20 if genre_name in priority_genre_names else 10
            for movie in data.get("results", [])[:limit]:
                title_norm = normalize_title(movie.get('title', ''))
                title_lower = movie.get('title', '').lower()
                
                # Check if it's a superhero movie and exclude it
                movie_genres = movie.get('genre_ids', [])
                action_sci_fi_count = sum(1 for g in movie_genres if g in SUPERHERO_GENRES)
                is_superhero = (action_sci_fi_count >= 2 and len(movie_genres) <= 4) or any(kw in title_lower for kw in SUPERHERO_KEYWORDS)
                
                # Skip superhero movies entirely
                if is_superhero:
                    continue
                
                # Lower rating threshold for mystery/drama/thriller
                rating_threshold = 5.5 if genre_name in priority_genre_names else MIN_TMDB_RATING
                # Only add if neither has watched it, meets rating threshold, and has enough votes
                if (title_norm not in gorg_watched and 
                    title_norm not in sali_watched and
                    movie.get('vote_average', 0) >= rating_threshold and
                    movie.get('vote_count', 0) >= MIN_VOTE_COUNT):
                    poster_path = movie.get('poster_path', '')
                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                    genre_recommendations.append({
                        'title': movie.get('title'),
                        'year': movie.get('release_date', '')[:4] if movie.get('release_date') else 'N/A',
                        'tmdb_rating': movie.get('vote_average'),
                        'genre': genre_name,
                        'tmdb_id': movie.get('id'),
                        'poster_url': poster_url,
                        'overview': movie.get('overview', 'No overview available'),
                        'recommended_because': f'Popular {genre_name} film',
                        'recommendation_count': 1  # Genre recommendations have count of 1
                    })
        except Exception as e:
            print(f"Error fetching {genre_name} movies: {e}")

# Save genre-based recommendations to CSV
if genre_recommendations:
    genre_df = pd.DataFrame(genre_recommendations)  # Convert to DataFrame
    genre_df = genre_df.drop_duplicates(subset=['title'])  # Remove duplicates
    genre_df = genre_df.sort_values('tmdb_rating', ascending=False)  # Sort by rating (highest first)
    genre_df.to_csv('genre_recommendations.csv', index=False)  # Save to CSV
    print(f"\n✅ Found {len(genre_df)} additional recommendations by genre")
    print(f"✅ Saved to genre_recommendations.csv")

# Print final summary
print("\n" + "="*60)
print("Summary")
print("="*60)
print(f"✅ Analyzed {len(gorg_watched)} + {len(sali_watched)} watched movies")
print(f"✅ Found {len(both_loved)} movies you both loved")
print(f"✅ Generated {len(recommendations_list)} recommendations from similar movies")
if genre_recommendations:
    print(f"✅ Generated {len(genre_df)} recommendations by genre")
print(f"✅ Saved to movie_recommendations_improved.csv")

