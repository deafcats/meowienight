from flask import Flask, render_template, jsonify, request
import pandas as pd
import os
from urllib.parse import quote_plus
import random
import requests
import json

app = Flask(__name__)

# Add custom Jinja filter for URL encoding
@app.template_filter('urlencode')
def urlencode_filter(s):
    return quote_plus(str(s))

# Add custom Jinja filter for JSON encoding
@app.template_filter('tojsonfilter')
def tojson_filter(data):
    return json.dumps(data)

# Load data
def load_data():
    """
    Load all CSV files containing movie data.
    
    This function reads:
    - Movie recommendations (from TMDB analysis)
    - Genre-based recommendations
    - TV show recommendations
    - Gorg's watched films (from Letterboxd scraping)
    - Sali's watched films (from Letterboxd scraping)
    
    Returns: Tuple of DataFrames (recommendations, genre_recs, tv_recs, gorg_films, sali_films)
    """
    # Try to load each CSV file, return empty DataFrame if file doesn't exist
    try:
        recommendations = pd.read_csv('movie_recommendations_improved.csv')
    except:
        recommendations = pd.DataFrame()
    
    try:
        genre_recs = pd.read_csv('genre_recommendations.csv')
    except:
        genre_recs = pd.DataFrame()
    
    try:
        tv_recs = pd.read_csv('tv_recommendations.csv')
    except:
        tv_recs = pd.DataFrame()
    
    try:
        gorg_films = pd.read_csv('gorg_scraped_films.csv')
        sali_films = pd.read_csv('salicore_scraped_films.csv')
    except:
        gorg_films = pd.DataFrame()
        sali_films = pd.DataFrame()
    
    return recommendations, genre_recs, tv_recs, gorg_films, sali_films

def generate_prediction_reasons(movie, user_films, user_name, calculated_percent, base_prediction, adjustment, genre_matches=None):
    """
    Generate short, clear reasons based on ACTUAL similar movies they watched.
    Only shows movies that are actually related to this movie.
    
    Args:
        movie: Dictionary with movie data
        user_films: DataFrame of user's watched films
        user_name: Name of the user
        calculated_percent: The calculated percentage
        base_prediction: Base prediction
        adjustment: Not used anymore
        genre_matches: List of actual similar movie titles found (optional)
    
    Returns: List of short reason strings (minimum 3)
    """
    reasons = []
    import re
    
    def clean_title(title):
        if not title:
            return ""
        title_str = str(title)
        title_str = re.sub(r'\s*\(\d{4}\)\s*', '', title_str).strip()
        return title_str
    
    # Use the actual matched movies (source movies or year matches)
    if genre_matches:
        # Find ratings for these matched movies
        matched_with_ratings = []
        for match_title in genre_matches:
            match_title_clean = clean_title(str(match_title))
            # Find rating in user_films
            for _, film in user_films.iterrows():
                film_title = clean_title(film.get('film_title', ''))
                if match_title_clean == film_title:
                    film_rating = film.get('rating', 0)
                    matched_with_ratings.append((match_title, film_rating))
                    break
        
        # Sort by rating
        matched_with_ratings.sort(key=lambda x: x[1], reverse=True)
        
        if matched_with_ratings:
            # Show based on their actual ratings
            liked = [t for t, r in matched_with_ratings if r >= 4.0]
            disliked = [t for t, r in matched_with_ratings if r <= 2.5]
            
            if calculated_percent >= 60 and liked:
                if len(liked) >= 3:
                    reasons.append(f"You liked {liked[0]}, {liked[1]}, {liked[2]}")
                elif len(liked) >= 2:
                    reasons.append(f"You liked {liked[0]}, {liked[1]}")
                elif len(liked) >= 1:
                    reasons.append(f"You liked {liked[0]}")
            
            if calculated_percent <= 50 and disliked:
                if len(disliked) >= 2:
                    reasons.append(f"You rated {disliked[0]}, {disliked[1]} low")
                elif len(disliked) >= 1:
                    reasons.append(f"You rated {disliked[0]} low")
            
            # Add more from matches if needed
            if len(reasons) < 3:
                used_titles = set()
                for r in reasons:
                    # Extract titles from existing reasons
                    if "You liked" in r:
                        titles = r.replace("You liked ", "").split(", ")
                        used_titles.update(titles)
                    elif "You rated" in r:
                        titles = r.replace("You rated ", "").replace(" low", "").split(", ")
                        used_titles.update(titles)
                
                for title, rating in matched_with_ratings:
                    if title in used_titles:
                        continue
                    if calculated_percent >= 60 and rating >= 4.0:
                        reasons.append(f"You liked {title}")
                    elif calculated_percent <= 50 and rating <= 2.5:
                        reasons.append(f"You rated {title} low")
                    if len(reasons) >= 3:
                        break
    
    # If no matches or not enough reasons, explain honestly
    if len(reasons) < 3:
        if calculated_percent <= 45:
            reasons.append("No similar movies in your history")
        else:
            # Use top rated movies as fallback
            loved = user_films[user_films['rating'] >= 4.0].nlargest(2, 'rating')
            if not loved.empty and len(reasons) < 3:
                titles = [clean_title(f.get('film_title', '')) for _, f in loved.iterrows()]
                if titles:
                    reasons.append(f"You liked {', '.join(titles[:2])}")
    
    # Ensure minimum 3 reasons
    while len(reasons) < 3:
        reasons.append("Based on movie rating")
    
    # Fill to 3 reasons
    while len(reasons) < 3:
        if calculated_percent <= 45:
            reasons.append("Different genre/style")
        else:
            reasons.append("Based on rating history")
    
    # Return first 3, no duplicates
    return list(dict.fromkeys(reasons))[:3]

def predict_liking_percentage(movie, gorg_films, sali_films):
    """
    Predict how much Sali and Gorg will like a movie based on their rating history.
    Also generates detailed reasoning for tooltips.
    
    Algorithm:
    1. Base prediction on TMDB rating (scale 0-10 to 0-100)
    2. Adjust based on user's average rating tendency
    3. Generate detailed reasons based on genre, year, and rating patterns
    
    Args:
        movie: Dictionary with movie data including 'tmdb_rating'
        gorg_films: DataFrame of Gorg's watched films
        sali_films: DataFrame of Sali's watched films
    
    Returns: dict with 'sali_percent', 'gorg_percent', 'sali_reasons', 'gorg_reasons'
    """
    # Accurate algorithm: Only predict high if there's actual evidence they'd like it
    movie_rating = movie.get('tmdb_rating', 0)
    movie_year = movie.get('year', 0)
    movie_genre_ids = movie.get('genre_ids', [])
    if isinstance(movie_genre_ids, str):
        movie_genre_ids = [int(g.strip()) for g in movie_genre_ids.split(',') if g.strip().isdigit()]
    
    # Genre ID to name mapping
    genre_id_to_name = {
        18: 'Drama', 53: 'Thriller', 9648: 'Mystery', 80: 'Crime', 10402: 'Music',
        28: 'Action', 35: 'Comedy', 27: 'Horror', 878: 'Science Fiction', 10749: 'Romance',
        16: 'Animation', 99: 'Documentary', 14: 'Fantasy', 36: 'History', 37: 'Western', 10752: 'War'
    }
    
    import re
    
    def normalize_title(title):
        """Normalize title for matching"""
        if not title:
            return ""
        title_str = str(title).lower().strip()
        # Remove common punctuation
        title_str = title_str.replace(',', '').replace(':', '').replace("'", '').replace('"', '')
        # Remove year in parentheses
        title_str = re.sub(r'\s*\(\d{4}\)\s*', '', title_str)
        return title_str.strip()
    
    # Check if this movie is in recommendations - if so, use the "recommended_because" movies
    recommended_because = movie.get('recommended_because', '')
    source_movies = []
    if recommended_because and isinstance(recommended_because, str):
        # Parse "Movie A, Movie B, Movie C" format
        source_movies = [s.strip() for s in recommended_because.split(',') if s.strip()]
    
    def predict_for_user(user_films, user_name):
        """Predict based on ACTUAL movies they've watched that led to this recommendation"""
        if user_films.empty or 'rating' not in user_films.columns:
            # No data = default to low-medium (40%)
            return max(35, min(45, (movie_rating / 10.0) * 100)), []
        
        import re
        
        # First: Check if they've actually watched THIS exact movie
        movie_title = str(movie.get('title', '')).strip()
        movie_title_norm = normalize_title(movie_title)
        
        for _, film in user_films.iterrows():
            film_title = str(film.get('film_title', '')).strip()
            film_title_norm = normalize_title(film_title)
            
            # Check if it's the same movie (exact match or very close)
            if movie_title_norm == film_title_norm:
                # They've watched it! Use their actual rating
                actual_rating = film.get('rating', 0)
                actual_percent = (actual_rating / 5.0) * 100
                return actual_percent, [film_title]  # Return their actual rating
        
        # Second: Use movies that led to this recommendation (from "recommended_because")
        source_matches = []
        if source_movies:
            for source_movie in source_movies:
                source_norm = normalize_title(source_movie)
                for _, film in user_films.iterrows():
                    film_title = str(film.get('film_title', '')).strip()
                    film_title_norm = normalize_title(film_title)
                    if source_norm == film_title_norm:
                        # Found one of the source movies they watched!
                        film_rating = film.get('rating', 0)
                        source_matches.append((film_rating, film_title))
                        break
        
        # Third: Find movies from similar years (within 5 years) as fallback
        year_matches = []
        if movie_year > 0:
            for _, film in user_films.iterrows():
                film_title = str(film.get('film_title', ''))
                year_match = re.search(r'\((\d{4})\)', film_title)
                if year_match:
                    film_year = int(year_match.group(1))
                    if abs(film_year - movie_year) <= 5:
                        film_rating = film.get('rating', 0)
                        year_matches.append((film_rating, film_title))
        
        # Use source movies (movies that led to this recommendation) - most accurate!
        if source_matches:
            ratings = [m[0] for m in source_matches]
            avg_source_rating = sum(ratings) / len(ratings)
            source_percent = (avg_source_rating / 5.0) * 100
            
            # Blend with TMDB rating
            tmdb_base = (movie_rating / 10.0) * 100
            prediction = (source_percent * 0.7) + (tmdb_base * 0.3)
            
            # Cap based on their ratings of source movies
            if avg_source_rating >= 4.5:
                prediction = min(85, prediction)  # They loved source movies
            elif avg_source_rating >= 4.0:
                prediction = min(75, prediction)  # They liked source movies
            elif avg_source_rating <= 2.5:
                prediction = max(25, min(45, prediction))  # They didn't like source movies
            
            matched_movies = [m[1] for m in source_matches[:3]]
            return max(25, min(85, prediction)), matched_movies
        
        # Use year matches as fallback
        if len(year_matches) >= 3:
            ratings = [m[0] for m in year_matches]
            avg_year_rating = sum(ratings) / len(ratings)
            year_percent = (avg_year_rating / 5.0) * 100
            
            # Blend with TMDB, but be more conservative
            tmdb_base = (movie_rating / 10.0) * 100
            prediction = (year_percent * 0.5) + (tmdb_base * 0.5)
            matched_movies = [m[1] for m in year_matches[:3]]
            return max(30, min(70, prediction)), matched_movies
        
        # NO matches = they probably won't like it, predict LOW
        # Without evidence, always predict low (25-40% max)
        if movie_rating >= 8.5:
            prediction = 40  # Even exceptional movies = max 40% if no match
        elif movie_rating >= 7.5:
            prediction = 38  # Very good movies = 38%
        elif movie_rating >= 7.0:
            prediction = 35  # Good movies = 35%
        elif movie_rating >= 6.0:
            prediction = 32  # Average movies = 32%
        else:
            prediction = 28  # Lower rated = 28%
        
        return max(25, min(40, prediction)), []  # Cap at 40% max if no matches
    
    gorg_percent, gorg_matches = predict_for_user(gorg_films, 'Gorg')
    sali_percent, sali_matches = predict_for_user(sali_films, 'Sali')
    
    # Generate reasons based on ACTUAL similar movies found
    gorg_reasons = generate_prediction_reasons(movie, gorg_films, 'Gorg', gorg_percent, (movie_rating / 10.0) * 100, 0, gorg_matches)
    sali_reasons = generate_prediction_reasons(movie, sali_films, 'Sali', sali_percent, (movie_rating / 10.0) * 100, 0, sali_matches)
    
    return {
        'sali_percent': round(sali_percent),
        'gorg_percent': round(gorg_percent),
        'sali_reasons': sali_reasons,
        'gorg_reasons': gorg_reasons
    }

@app.route('/')
def index():
    """
    Homepage route - displays statistics and top recommendations.
    
    Shows:
    - Total films watched by each user
    - Average ratings
    - Movies both loved (rated 4+ by both)
    - Top 6 recommendations with posters
    """
    # Load all data from CSV files
    recommendations, genre_recs, tv_recs, gorg_films, sali_films = load_data()
    
    # Calculate statistics for the homepage
    stats = {
        'gorg_total': len(gorg_films),  # Total number of films Gorg has watched
        'sali_total': len(sali_films),  # Total number of films Sali has watched
        'recommendations_count': len(recommendations) + len(tv_recs),  # Combined movie and TV recommendations
        'genre_recommendations_count': len(genre_recs),  # Number of genre-based recommendations
        # Calculate average ratings (handle empty DataFrames)
        'gorg_avg_rating': gorg_films['rating'].mean() if not gorg_films.empty and 'rating' in gorg_films.columns else 0,
        'sali_avg_rating': sali_films['rating'].mean() if not sali_films.empty and 'rating' in sali_films.columns else 0,
    }
    
    # Find movies both loved (rated 4.0 or higher by both users)
    both_loved = []
    if not gorg_films.empty and not sali_films.empty:
        # Loop through Gorg's films
        for _, gorg_movie in gorg_films.iterrows():
            # Check if Gorg rated it 4.0 or higher
            if gorg_movie.get('rating', 0) and gorg_movie['rating'] >= 4.0:
                # Find matching film in Sali's list (case-insensitive)
                gorg_title_lower = str(gorg_movie['film_title']).lower()
                matching = sali_films[sali_films['film_title'].str.lower() == gorg_title_lower]
                if not matching.empty:
                    sali_rating = matching.iloc[0].get('rating', 0)
                    # Check if Sali also rated it 4.0 or higher
                    if sali_rating and sali_rating >= 4.0:
                        both_loved.append({
                            'title': gorg_movie['film_title'],
                            'gorg_rating': gorg_movie['rating'],
                            'sali_rating': sali_rating
                        })
    
    # Store both loved count and full list (for the both_loved page)
    # Also get TMDB IDs and posters for both loved movies
    TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"
    for movie in both_loved:
        # Get TMDB ID for linking to detail page
        tmdb_id = None
        poster_url = None
        try:
            import re
            title_clean = str(movie['title']).strip()
            year_match = re.search(r'\((\d{4})\)', title_clean)
            year = int(year_match.group(1)) if year_match else None
            if year_match:
                title_clean = re.sub(r'\s*\(\d{4}\)\s*', '', title_clean).strip()
            
            url = "https://api.themoviedb.org/3/search/movie"
            params = {"api_key": TMDB_API_KEY, "query": title_clean}
            if year:
                params["year"] = year
            response = requests.get(url, params=params, timeout=3)
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    tmdb_id = data["results"][0].get("id")
                    poster_path = data["results"][0].get("poster_path", "")
                    if poster_path:
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        except:
            pass
        movie['tmdb_id'] = tmdb_id
        movie['poster_url'] = poster_url
    
    # Sort all both loved movies by average rating
    both_loved_sorted = sorted(both_loved, key=lambda x: (x['gorg_rating'] + x['sali_rating'])/2, reverse=True)
    stats['both_loved_count'] = len(both_loved_sorted)  # Total count
    # Show only 5 movies on homepage (will rotate through all)
    stats['both_loved'] = both_loved_sorted[:5]
    stats['both_loved_full'] = both_loved_sorted  # Full list for rotation and dedicated page
    
    # Get top recommended movies for front page display
    top_recommendations = []
    if not recommendations.empty:
        # Convert DataFrame to list of dictionaries
        recs_list = recommendations.to_dict('records')
        
        # Clean up any invalid records (missing titles, NaN values)
        def clean_rec(rec):
            if not isinstance(rec, dict) or 'title' not in rec or not isinstance(rec.get('title'), str):
                return None
            # Replace NaN overviews with placeholder text
            if 'overview' in rec and (not isinstance(rec['overview'], str) or pd.isna(rec['overview'])):
                rec['overview'] = 'No overview available'
            return rec
        
        recs_list = [r for r in [clean_rec(rec) for rec in recs_list] if r is not None]
        # Sort by recommendation count and rating, take top 6
        top_recommendations = sorted(recs_list, key=lambda x: (
            x.get('recommendation_count', 0),  # Primary sort: how many times recommended
            x.get('tmdb_rating', 0)  # Secondary sort: TMDB rating
        ), reverse=True)[:6]
        
        # Get IMDB and Rotten Tomatoes ratings for top recommendations
        OMDB_API_KEY = "b9a5e69d"
        for rec in top_recommendations:
            tmdb_id = rec.get('tmdb_id')
            if tmdb_id:
                try:
                    # Get IMDB ID from TMDB
                    tmdb_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                    tmdb_params = {"api_key": TMDB_API_KEY}
                    tmdb_response = requests.get(tmdb_url, params=tmdb_params, timeout=2)
                    if tmdb_response.status_code == 200:
                        tmdb_movie = tmdb_response.json()
                        imdb_id = tmdb_movie.get('imdb_id')
                        if imdb_id:
                            rec['imdb_id'] = imdb_id
                            # Get ratings from OMDB
                            omdb_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
                            omdb_response = requests.get(omdb_url, timeout=2)
                            if omdb_response.status_code == 200:
                                omdb_data = omdb_response.json()
                                if omdb_data.get('Response') == 'True':
                                    rec['imdb_rating'] = omdb_data.get('imdbRating')
                                    # Rotten Tomatoes rating
                                    ratings = omdb_data.get('Ratings', [])
                                    for rating in ratings:
                                        if rating.get('Source') == 'Rotten Tomatoes':
                                            rec['rotten_tomatoes_rating'] = rating.get('Value')
                                            break
                except:
                    pass  # If we can't get ratings, just continue
    
    return render_template('index.html', stats=stats, top_recommendations=top_recommendations)

@app.route('/both-loved')
def both_loved():
    """
    Page showing all movies both users loved (rated 4+ by both).
    Shows ALL movies - no limit.
    """
    TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"
    
    # Load data
    _, _, _, gorg_films, sali_films = load_data()
    
    # Find all movies both loved (same logic as homepage)
    both_loved_list = []
    if not gorg_films.empty and not sali_films.empty:
        for _, gorg_movie in gorg_films.iterrows():
            # Check if Gorg rated it 4.0 or higher
            if gorg_movie.get('rating', 0) and gorg_movie['rating'] >= 4.0:
                # Find matching film in Sali's list (case-insensitive)
                gorg_title_lower = str(gorg_movie['film_title']).lower()
                matching = sali_films[sali_films['film_title'].str.lower() == gorg_title_lower]
                if not matching.empty:
                    sali_rating = matching.iloc[0].get('rating', 0)
                    # Check if Sali also rated it 4.0 or higher
                    if sali_rating and sali_rating >= 4.0:
                        # Get TMDB ID and poster for the movie
                        tmdb_id = None
                        poster_url = None
                        try:
                            import re
                            title_clean = str(gorg_movie['film_title']).strip()
                            year_match = re.search(r'\((\d{4})\)', title_clean)
                            year = int(year_match.group(1)) if year_match else None
                            if year_match:
                                title_clean = re.sub(r'\s*\(\d{4}\)\s*', '', title_clean).strip()
                            
                            url = "https://api.themoviedb.org/3/search/movie"
                            params = {"api_key": TMDB_API_KEY, "query": title_clean}
                            if year:
                                params["year"] = year
                            response = requests.get(url, params=params, timeout=5)
                            if response.status_code == 200:
                                data = response.json()
                                if data.get("results"):
                                    tmdb_id = data["results"][0].get("id")
                                    poster_path = data["results"][0].get("poster_path", "")
                                    if poster_path:
                                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                        except:
                            pass  # If we can't find TMDB ID, just leave it as None
                        
                        both_loved_list.append({
                            'title': gorg_movie['film_title'],
                            'gorg_rating': gorg_movie['rating'],
                            'sali_rating': sali_rating,
                            'avg_rating': (gorg_movie['rating'] + sali_rating) / 2,
                            'tmdb_id': tmdb_id,
                            'poster_url': poster_url
                        })
    
    # Sort by average rating (highest first) - NO LIMIT, show ALL movies
    both_loved_list = sorted(both_loved_list, key=lambda x: x['avg_rating'], reverse=True)
    
    return render_template('both_loved.html', both_loved=both_loved_list)

@app.route('/recommendations')
def recommendations():
    """
    Recommendations page route - displays all movie and TV recommendations.
    
    Loads recommendations from CSV files, cleans the data, and displays them
    sorted by recommendation count and rating.
    """
    # Load data (we don't need gorg/sali films for this page, so use _)
    recommendations, genre_recs, tv_recs, _, _ = load_data()
    
    # Convert DataFrames to list of dictionaries for easier template handling
    recs_list = recommendations.to_dict('records') if not recommendations.empty else []
    genre_list = genre_recs.to_dict('records') if not genre_recs.empty else []
    tv_list = tv_recs.to_dict('records') if not tv_recs.empty else []

    # Superhero keywords to filter out
    SUPERHERO_KEYWORDS = ['spider-man', 'batman', 'superman', 'iron man', 'captain america', 'avengers', 'x-men', 'guardians of the galaxy', 'men in black', 'marvel', 'dc', 'comic', 'comics', 'superheroes', 'wolverine', 'hulk', 'thor', 'ant-man', 'black widow', 'wonder woman', 'flash', 'aquaman', 'green lantern', 'deadpool', 'venom', 'doctor strange', 'black panther', 'shazam']
    
    # Clean up records: remove invalid entries and fix NaN values
    def clean_rec(rec):
        # Check if record is valid (must be dict with string title)
        if not isinstance(rec, dict) or 'title' not in rec or not isinstance(rec.get('title'), str):
            return None
        
        # EXCLUDE superhero movies entirely
        title_lower = str(rec.get('title', '')).lower()
        if any(keyword in title_lower for keyword in SUPERHERO_KEYWORDS):
            return None  # Skip superhero movies
        
        # Convert NaN/float overview to placeholder text
        if 'overview' in rec and (not isinstance(rec['overview'], str) or pd.isna(rec['overview'])):
            rec['overview'] = 'No overview available'
        # Ensure poster_url exists
        if 'poster_url' not in rec or pd.isna(rec.get('poster_url')):
            rec['poster_url'] = None
        # Add recommendation_count if missing (for genre recommendations)
        if 'recommendation_count' not in rec:
            rec['recommendation_count'] = 1
        return rec
    
    # Apply cleaning function to all recommendation lists
    recs_list = [r for r in [clean_rec(rec) for rec in recs_list] if r is not None]
    genre_list = [r for r in [clean_rec(rec) for rec in genre_list] if r is not None]
    tv_list = [r for r in [clean_rec(rec) for rec in tv_list] if r is not None]
    
    # Combine main recommendations with genre recommendations
    # Genre recommendations get lower priority but are still included
    for genre_rec in genre_list:
        # Check if it's already in main recommendations
        genre_title = genre_rec.get('title', '').lower()
        if not any(r.get('title', '').lower() == genre_title for r in recs_list):
            recs_list.append(genre_rec)
    
    # Ensure all recommendation_count values are numeric (not strings)
    for rec in recs_list:
        if 'recommendation_count' in rec:
            try:
                rec['recommendation_count'] = float(rec['recommendation_count'])
            except (ValueError, TypeError):
                rec['recommendation_count'] = 1.0
        else:
            rec['recommendation_count'] = 1.0
        # Ensure tmdb_rating is also numeric
        if 'tmdb_rating' in rec:
            try:
                rec['tmdb_rating'] = float(rec['tmdb_rating'])
            except (ValueError, TypeError):
                rec['tmdb_rating'] = 0.0
        else:
            rec['tmdb_rating'] = 0.0
    
    # Sort movies by recommendation count (primary) and rating (secondary)
    # Movies recommended by multiple loved movies are ranked higher
    recs_list = sorted(recs_list, key=lambda x: (
        x.get('recommendation_count', 0),  # Primary: how many times recommended (higher = better)
        x.get('tmdb_rating', 0)  # Secondary: TMDB rating (higher = better)
    ), reverse=True)
    
    # Sort TV shows the same way
    tv_list = sorted(tv_list, key=lambda x: (
        x.get('recommendation_count', 0),
        x.get('tmdb_rating', 0)
    ), reverse=True)
    
    # Add prediction percentages to initial recommendations
    # Load user films for predictions
    _, _, _, gorg_films, sali_films = load_data()
    
    # Add predictions to movies
    for rec in recs_list:
        predictions = predict_liking_percentage(rec, gorg_films, sali_films)
        rec['sali_percent'] = predictions['sali_percent']
        rec['gorg_percent'] = predictions['gorg_percent']
        rec['sali_reasons'] = predictions.get('sali_reasons', ['Based on your rating history'])
        rec['gorg_reasons'] = predictions.get('gorg_reasons', ['Based on your rating history'])
    
    # Add predictions to TV shows
    for tv in tv_list:
        predictions = predict_liking_percentage(tv, gorg_films, sali_films)
        tv['sali_percent'] = predictions['sali_percent']
        tv['gorg_percent'] = predictions['gorg_percent']
        tv['sali_reasons'] = predictions.get('sali_reasons', ['Based on your rating history'])
        tv['gorg_reasons'] = predictions.get('gorg_reasons', ['Based on your rating history'])
    
    return render_template('recommendations.html', 
                         recommendations=recs_list,
                         tv_recommendations=tv_list,
                         genre_recommendations=genre_list)

@app.route('/api/recommendations')
def api_recommendations():
    """
    API endpoint for recommendations with filtering and predictions.
    
    Supports filtering by:
    - Decade (1950s-2020s)
    - Content type (movies, TV, or all)
    - Sort options (rating, year, title, etc.)
    - Surprise Us feature (picks one random movie)
    
    Returns JSON with:
    - surprise_movie: Single random movie (if surprise=true)
    - recommendations: List of filtered and sorted recommendations
    - Each recommendation includes prediction percentages for Sali and Gorg
    """
    # Load all data including user films (needed for predictions)
    recommendations, genre_recs, tv_recs, gorg_films, sali_films = load_data()
    
    # Get filter parameters from URL query string
    decade = request.args.get('decade', '')  # Filter by decade (e.g., "1990")
    sort_by = request.args.get('sort_by', 'recommendation_count')  # How to sort results
    surprise = request.args.get('surprise', 'false') == 'true'  # "Surprise Us" feature
    content_type = request.args.get('type', 'all')  # 'movies', 'tv', or 'all'
    genre_filter = request.args.get('genre', '')  # Filter by genre (e.g., "Drama", "Thriller")
    
    # Combine movies and TV shows based on content_type filter
    # Also include genre recommendations for movies
    if content_type == 'all':
        # Show both movies and TV shows
        recs_list = recommendations.to_dict('records') if not recommendations.empty else []
        genre_list = genre_recs.to_dict('records') if not genre_recs.empty else []
        tv_list = tv_recs.to_dict('records') if not tv_recs.empty else []
        # Combine all recommendations
        recs_list = recs_list + genre_list + tv_list
    elif content_type == 'movies':
        # Only movies (include genre recommendations)
        recs_list = recommendations.to_dict('records') if not recommendations.empty else []
        genre_list = genre_recs.to_dict('records') if not genre_recs.empty else []
        # Combine main and genre recommendations
        for genre_rec in genre_list:
            genre_title = genre_rec.get('title', '').lower()
            if not any(r.get('title', '').lower() == genre_title for r in recs_list):
                recs_list.append(genre_rec)
    elif content_type == 'tv':
        # Only TV shows
        recs_list = tv_recs.to_dict('records') if not tv_recs.empty else []
    else:
        recs_list = []

    # Superhero keywords to filter out
    SUPERHERO_KEYWORDS = ['spider-man', 'batman', 'superman', 'iron man', 'captain america', 'avengers', 'x-men', 'guardians of the galaxy', 'men in black', 'marvel', 'dc', 'comic', 'comics', 'superheroes', 'wolverine', 'hulk', 'thor', 'ant-man', 'black widow', 'wonder woman', 'flash', 'aquaman', 'green lantern', 'deadpool', 'venom', 'doctor strange', 'black panther', 'shazam']
    
    # Clean up records: remove invalid entries and fix NaN values
    def clean_rec(rec):
        # Check if record is valid dictionary with string title
        if not isinstance(rec, dict) or 'title' not in rec or not isinstance(rec.get('title'), str):
            return None
        
        # EXCLUDE superhero movies entirely
        title_lower = str(rec.get('title', '')).lower()
        if any(keyword in title_lower for keyword in SUPERHERO_KEYWORDS):
            return None  # Skip superhero movies
        
        # Replace NaN overviews with placeholder
        if 'overview' in rec and (not isinstance(rec['overview'], str) or pd.isna(rec['overview'])):
            rec['overview'] = 'No overview available'
        # Ensure poster_url exists
        if 'poster_url' not in rec or pd.isna(rec.get('poster_url')):
            rec['poster_url'] = None
        # Add recommendation_count if missing (for genre recommendations)
        if 'recommendation_count' not in rec:
            rec['recommendation_count'] = 1
        # Add recommended_because if missing
        if 'recommended_because' not in rec:
            rec['recommended_because'] = rec.get('genre', 'Your rating history')
        return rec
    
    recs_list = [r for r in [clean_rec(rec) for rec in recs_list] if r is not None]
    
    # Ensure all recommendation_count values are numeric (not strings) for proper sorting
    for rec in recs_list:
        if 'recommendation_count' in rec:
            try:
                rec['recommendation_count'] = float(rec['recommendation_count'])
            except (ValueError, TypeError):
                rec['recommendation_count'] = 1.0
        else:
            rec['recommendation_count'] = 1.0
        # Ensure tmdb_rating is also numeric
        if 'tmdb_rating' in rec:
            try:
                rec['tmdb_rating'] = float(rec['tmdb_rating'])
            except (ValueError, TypeError):
                rec['tmdb_rating'] = 0.0
        else:
            rec['tmdb_rating'] = 0.0
    
    # Apply filters (decade and genre)
    filtered = []
    TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"
    
    # Genre ID to name mapping
    genre_id_to_name = {
        18: 'Drama', 53: 'Thriller', 9648: 'Mystery', 80: 'Crime', 10402: 'Music',
        28: 'Action', 35: 'Comedy', 27: 'Horror', 878: 'Science Fiction', 10749: 'Romance',
        16: 'Animation', 99: 'Documentary', 14: 'Fantasy', 36: 'History', 10402: 'Music',
        9648: 'Mystery', 10752: 'War', 37: 'Western'
    }
    
    for rec in recs_list:
        # Extract year from movie data (handle different formats)
        year = int(rec.get('year', 0)) if rec.get('year') and str(rec.get('year')).isdigit() else 0
        
        # Filter by decade if specified (e.g., 1990 filters 1990-1999)
        if decade:
            decade_start = int(decade)
            if not (decade_start <= year < decade_start + 10):
                continue  # Skip this movie if it's not in the selected decade
        
        # Filter by genre if specified
        if genre_filter:
            rec_genre = rec.get('genre', '').lower()  # For genre recommendations
            if not rec_genre or rec_genre != genre_filter.lower():
                # For main recommendations, check genre_ids
                genre_ids_str = rec.get('genre_ids', '')
                if genre_ids_str:
                    try:
                        genre_ids = [int(g.strip()) for g in str(genre_ids_str).split(',') if g.strip().isdigit()]
                        genre_names = [genre_id_to_name.get(gid, '') for gid in genre_ids]
                        if genre_filter.lower() not in [g.lower() for g in genre_names if g]:
                            continue  # Skip if genre doesn't match
                    except:
                        continue
                else:
                    continue  # Skip if no genre info
        
        filtered.append(rec)
    
    # Surprise Us feature: pick ONE random movie to display on top
    # Prioritize movies recommended from movies you've watched (not just genre-based)
    surprise_movie = None
    if surprise and filtered:
        # Filter to only movies recommended from your watched movies (not genre recommendations)
        # Genre recommendations have "Popular [Genre] film" in recommended_because
        watched_based_recs = [
            r for r in filtered 
            if r.get('recommended_because') and 'Popular' not in str(r.get('recommended_because', ''))
        ]
        
        # If we have movies based on your watched films, use those; otherwise fall back to all
        if watched_based_recs:
            # Pick from movies with higher recommendation counts (more specific to your taste)
            # Sort by recommendation count and pick from top 10 most recommended
            watched_based_recs.sort(key=lambda x: float(x.get('recommendation_count', 0)), reverse=True)
            top_watched = watched_based_recs[:10]  # Top 10 most recommended from your watched movies
            surprise_movie = random.choice(top_watched)
        else:
            # Fallback: if no watched-based recommendations, use any movie
            surprise_movie = random.choice(filtered)
        
        # Remove it from the main list so it doesn't appear twice
        filtered = [r for r in filtered if r.get('tmdb_id') != surprise_movie.get('tmdb_id')]
    
    # Sort the filtered recommendations based on sort_by parameter
    if sort_by == 'rating':
        # Sort by TMDB rating (highest first)
        filtered.sort(key=lambda x: x.get('tmdb_rating', 0), reverse=True)
    elif sort_by == 'year':
        # Sort by year (newest first)
        filtered.sort(key=lambda x: int(x.get('year', 0)) if str(x.get('year', 0)).isdigit() else 0, reverse=True)
    elif sort_by == 'year_oldest':
        # Sort by year (oldest first)
        filtered.sort(key=lambda x: int(x.get('year', 0)) if str(x.get('year', 0)).isdigit() else 0)
    elif sort_by == 'title':
        # Sort alphabetically by title
        filtered.sort(key=lambda x: x.get('title', '').lower())
    elif sort_by == 'rec_count':
        # Sort by recommendation count
        filtered.sort(key=lambda x: float(x.get('recommendation_count', 0)), reverse=True)
    else:  # Default: sort by recommendation_count (primary) + rating (secondary)
        # Sort by recommendation count first (highest first), then by rating
        # This ensures movies recommended multiple times appear first
        filtered.sort(key=lambda x: (
            float(x.get('recommendation_count', 0)),  # Primary: how many times recommended (higher = better)
            float(x.get('tmdb_rating', 0))  # Secondary: TMDB rating (higher = better)
        ), reverse=True)
    
    # Add prediction percentages to each movie
    # This tells us how much Sali and Gorg are predicted to like each movie
    # NOTE: IMDB/RT ratings are fetched only for the first 10 movies to keep loading fast
    # More ratings can be loaded client-side if needed
    OMDB_API_KEY = "b9a5e69d"
    ratings_fetched = 0
    max_ratings_to_fetch = 10  # Reduced to 10 for faster loading
    
    for rec in filtered:
        predictions = predict_liking_percentage(rec, gorg_films, sali_films)
        rec['sali_percent'] = predictions['sali_percent']
        rec['gorg_percent'] = predictions['gorg_percent']
        rec['sali_reasons'] = predictions.get('sali_reasons', ['Based on your rating history'])
        rec['gorg_reasons'] = predictions.get('gorg_reasons', ['Based on your rating history'])
        # Make sure recommended_because is included for tooltips
        if 'recommended_because' not in rec:
            rec['recommended_because'] = 'Our rating history'
        
        # Fetch IMDB and Rotten Tomatoes ratings (limit to first 10 to keep it fast)
        if ratings_fetched < max_ratings_to_fetch:
            tmdb_id = rec.get('tmdb_id')
            if tmdb_id:
                try:
                    # Get IMDB ID from TMDB (shorter timeout for speed)
                    tmdb_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                    tmdb_params = {"api_key": TMDB_API_KEY}
                    tmdb_response = requests.get(tmdb_url, params=tmdb_params, timeout=1)
                    if tmdb_response.status_code == 200:
                        tmdb_movie = tmdb_response.json()
                        imdb_id = tmdb_movie.get('imdb_id')
                        if imdb_id:
                            rec['imdb_id'] = imdb_id
                            # Get ratings from OMDB (shorter timeout)
                            omdb_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
                            omdb_response = requests.get(omdb_url, timeout=1)
                            if omdb_response.status_code == 200:
                                omdb_data = omdb_response.json()
                                if omdb_data.get('Response') == 'True':
                                    rec['imdb_rating'] = omdb_data.get('imdbRating')
                                    # Rotten Tomatoes rating
                                    ratings = omdb_data.get('Ratings', [])
                                    for rating in ratings:
                                        if rating.get('Source') == 'Rotten Tomatoes':
                                            rec['rotten_tomatoes_rating'] = rating.get('Value')
                                            break
                            ratings_fetched += 1
                except:
                    pass  # If we can't get ratings, just continue
    
    # Add prediction and IMDB/RT ratings to surprise movie if it exists
    if surprise_movie:
        predictions = predict_liking_percentage(surprise_movie, gorg_films, sali_films)
        surprise_movie['sali_percent'] = predictions['sali_percent']
        surprise_movie['gorg_percent'] = predictions['gorg_percent']
        surprise_movie['sali_reasons'] = predictions.get('sali_reasons', ['Based on your rating history'])
        surprise_movie['gorg_reasons'] = predictions.get('gorg_reasons', ['Based on your rating history'])
        
        # Fetch IMDB and Rotten Tomatoes ratings for surprise movie (faster timeouts)
        tmdb_id = surprise_movie.get('tmdb_id')
        if tmdb_id:
            try:
                # Get IMDB ID from TMDB (shorter timeout)
                tmdb_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                tmdb_params = {"api_key": TMDB_API_KEY}
                tmdb_response = requests.get(tmdb_url, params=tmdb_params, timeout=1)
                if tmdb_response.status_code == 200:
                    tmdb_movie = tmdb_response.json()
                    imdb_id = tmdb_movie.get('imdb_id')
                    if imdb_id:
                        surprise_movie['imdb_id'] = imdb_id
                        # Get ratings from OMDB (shorter timeout)
                        omdb_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
                        omdb_response = requests.get(omdb_url, timeout=1)
                        if omdb_response.status_code == 200:
                            omdb_data = omdb_response.json()
                            if omdb_data.get('Response') == 'True':
                                surprise_movie['imdb_rating'] = omdb_data.get('imdbRating')
                                # Rotten Tomatoes rating
                                ratings = omdb_data.get('Ratings', [])
                                for rating in ratings:
                                    if rating.get('Source') == 'Rotten Tomatoes':
                                        surprise_movie['rotten_tomatoes_rating'] = rating.get('Value')
                                        break
            except:
                pass  # If we can't get ratings, just continue
    
    # Return JSON with surprise movie (if any) and filtered recommendations
    return jsonify({
        'surprise_movie': surprise_movie,
        'recommendations': filtered
    })

@app.route('/api/search')
def api_search():
    """
    API endpoint for searching movies via TMDB.
    
    Query parameters:
    - query: Search query string (required)
    - limit: Maximum number of results (default: 20)
    
    Returns JSON with:
    - results: List of search results with prediction percentages, IMDB/RT ratings, etc.
    """
    query = request.args.get('query', '').strip()
    limit = int(request.args.get('limit', 20))
    
    if not query:
        return jsonify({'results': [], 'error': 'Query parameter is required'})
    
    TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"
    OMDB_API_KEY = "b9a5e69d"
    
    # Load user films for predictions
    _, _, _, gorg_films, sali_films = load_data()
    
    # Search TMDB for movies
    search_url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
        "page": 1
    }
    
    results = []
    try:
        response = requests.get(search_url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            movies = data.get('results', [])[:limit]  # Limit results
            
            for movie in movies:
                tmdb_id = movie.get('id')
                title = movie.get('title', '')
                year = movie.get('release_date', '')[:4] if movie.get('release_date') else ''
                overview = movie.get('overview', '')
                tmdb_rating = movie.get('vote_average', 0)
                poster_path = movie.get('poster_path', '')
                genre_ids = movie.get('genre_ids', [])
                
                # Build movie dict similar to recommendation format
                movie_dict = {
                    'tmdb_id': tmdb_id,
                    'title': title,
                    'year': int(year) if year.isdigit() else 0,
                    'overview': overview if overview else 'No overview available',
                    'tmdb_rating': float(tmdb_rating) if tmdb_rating else 0.0,
                    'poster_url': f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
                    'genre_ids': genre_ids,
                    'recommendation_count': 0,  # Search results don't have recommendation count
                    'recommended_because': 'Your rating history'  # Search results use rating history for predictions
                }
                
                # Calculate prediction percentages
                predictions = predict_liking_percentage(movie_dict, gorg_films, sali_films)
                movie_dict['sali_percent'] = predictions['sali_percent']
                movie_dict['gorg_percent'] = predictions['gorg_percent']
                movie_dict['sali_reasons'] = predictions.get('sali_reasons', ['Based on your rating history'])
                movie_dict['gorg_reasons'] = predictions.get('gorg_reasons', ['Based on your rating history'])
                
                # Get IMDB ID and ratings (faster timeouts for search)
                try:
                    tmdb_detail_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                    tmdb_detail_params = {"api_key": TMDB_API_KEY}
                    tmdb_detail_response = requests.get(tmdb_detail_url, params=tmdb_detail_params, timeout=2)
                    if tmdb_detail_response.status_code == 200:
                        tmdb_detail = tmdb_detail_response.json()
                        imdb_id = tmdb_detail.get('imdb_id')
                        if imdb_id:
                            movie_dict['imdb_id'] = imdb_id
                            # Get ratings from OMDB
                            omdb_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
                            omdb_response = requests.get(omdb_url, timeout=2)
                            if omdb_response.status_code == 200:
                                omdb_data = omdb_response.json()
                                if omdb_data.get('Response') == 'True':
                                    movie_dict['imdb_rating'] = omdb_data.get('imdbRating')
                                    # Rotten Tomatoes rating
                                    ratings = omdb_data.get('Ratings', [])
                                    for rating in ratings:
                                        if rating.get('Source') == 'Rotten Tomatoes':
                                            movie_dict['rotten_tomatoes_rating'] = rating.get('Value')
                                            break
                except:
                    pass  # If we can't get ratings, just continue
                
                results.append(movie_dict)
    
    except Exception as e:
        return jsonify({'results': [], 'error': str(e)})
    
    return jsonify({'results': results})

@app.route('/api/genres')
def get_genres():
    """Get list of available genres from recommendations"""
    recommendations, _, _, _, _ = load_data()
    
    genres = set()
    if not recommendations.empty and 'genre_ids' in recommendations.columns:
        for genre_str in recommendations['genre_ids'].dropna():
            if isinstance(genre_str, str):
                # genre_ids might be comma-separated string
                genre_list = [g.strip() for g in genre_str.split(',')]
                genres.update(genre_list)
    
    return jsonify(sorted(list(genres)))

@app.route('/movie/<int:tmdb_id>')
def movie_detail(tmdb_id):
    """
    Movie detail page route - shows full information about a specific movie.
    
    Fetches data from:
    - TMDB API (movie details, cast, similar movies)
    - Wikipedia API (summary and link)
    
    Displays:
    - Movie poster, title, rating
    - Overview and Wikipedia summary
    - Budget and revenue
    - Cast members (top 10) with clickable links
    - Similar movies (6 recommendations)
    """
    TMDB_API_KEY = "2073a6aadc1cb24381bc90c83ace363a"
    
    # Fetch movie details from TMDB API
    # append_to_response gets credits (cast/crew) and similar movies in one request
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    params = {"api_key": TMDB_API_KEY, "append_to_response": "credits,similar"}
    
    try:
        # Make API request with 10 second timeout
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  # Raise error if status code is not 200
        movie = response.json()
    except Exception as e:
        return f"Error loading movie: {e}", 404
    
    # Try to get Wikipedia summary for additional context
    wikipedia_url = None
    wikipedia_summary = None
    try:
        # Wikipedia REST API for page summaries
        wiki_search_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(movie['title'])}"
        wiki_response = requests.get(wiki_search_url, timeout=5)
        if wiki_response.status_code == 200:
            wiki_data = wiki_response.json()
            # Extract Wikipedia page URL and summary text
            wikipedia_url = wiki_data.get('content_urls', {}).get('desktop', {}).get('page', '')
            wikipedia_summary = wiki_data.get('extract', '')
    except:
        # If Wikipedia lookup fails, just continue without it
        pass
    
    # Format budget and revenue as currency
    budget = movie.get('budget', 0)
    revenue = movie.get('revenue', 0)
    
    def format_currency(amount):
        """Format number as currency string (e.g., $1,000,000)"""
        if amount == 0:
            return "Not available"
        return f"${amount:,.0f}"
    
    # Try to get Wikipedia additional details (filming locations, production time, camera info)
    filming_locations = []
    production_time = None
    camera_info = None
    random_fact = None
    
    try:
        # Try to get full Wikipedia page for more details
        full_wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=false&explaintext=true&titles={quote_plus(movie['title'])}&format=json"
        full_wiki_response = requests.get(full_wiki_url, timeout=5)
        if full_wiki_response.status_code == 200:
            full_wiki_data = full_wiki_response.json()
            pages = full_wiki_data.get('query', {}).get('pages', {})
            if pages:
                page_content = list(pages.values())[0].get('extract', '')
                # Extract filming locations (look for "filmed in" or "shot in")
                import re
                location_matches = re.findall(r'(?:filmed|shot|produced)\s+(?:in|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', page_content, re.IGNORECASE)
                if location_matches:
                    filming_locations = list(set(location_matches[:5]))  # Get up to 5 unique locations
                
                # Extract production time (look for "production began" or "filming took")
                time_match = re.search(r'(?:production|filming)\s+(?:began|started|took|lasted)\s+([^\.]+)', page_content, re.IGNORECASE)
                if time_match:
                    production_time = time_match.group(1).strip()
                
                # Extract camera info
                camera_match = re.search(r'(?:shot|filmed)\s+(?:on|with|using)\s+([^\.]+)', page_content, re.IGNORECASE)
                if camera_match:
                    camera_info = camera_match.group(1).strip()
    except:
        pass
    
    # Get IMDB rating from OMDB API
    imdb_rating = None
    imdb_id = None
    rotten_tomatoes_rating = None
    
    try:
        # First get IMDB ID from TMDB
        imdb_id = movie.get('imdb_id')
        if imdb_id:
            # Use OMDB API to get IMDB and Rotten Tomatoes ratings
            OMDB_API_KEY = "b9a5e69d"  # Free tier API key
            omdb_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}"
            omdb_response = requests.get(omdb_url, timeout=5)
            if omdb_response.status_code == 200:
                omdb_data = omdb_response.json()
                if omdb_data.get('Response') == 'True':
                    imdb_rating = omdb_data.get('imdbRating')
                    # Rotten Tomatoes rating is in Ratings array
                    ratings = omdb_data.get('Ratings', [])
                    for rating in ratings:
                        if rating.get('Source') == 'Rotten Tomatoes':
                            rotten_tomatoes_rating = rating.get('Value')
                            break
    except:
        pass
    
    # Get production details from TMDB
    production_companies = [comp.get('name', '') for comp in movie.get('production_companies', [])]
    production_countries = [country.get('name', '') for country in movie.get('production_countries', [])]
    release_date = movie.get('release_date', '')
    year_shot = release_date[:4] if release_date else 'N/A'
    
    # Generate a random fact (using available data)
    import random
    facts = []
    if production_companies:
        facts.append(f"Produced by {production_companies[0]}")
    if production_countries:
        facts.append(f"Filmed in {', '.join(production_countries[:2])}")
    if movie.get('runtime'):
        facts.append(f"Runtime: {movie.get('runtime')} minutes")
    if movie.get('vote_count', 0) > 0:
        facts.append(f"Rated by {movie.get('vote_count'):,} people on TMDB")
    if movie.get('original_language'):
        facts.append(f"Original language: {movie.get('original_language', '').upper()}")
    
    random_fact = random.choice(facts) if facts else "A critically acclaimed film"
    
    # Get top 10 cast members (actors/actresses)
    cast = movie.get('credits', {}).get('cast', [])[:10] if movie.get('credits') else []
    
    # Get 6 similar movies for recommendations
    similar = movie.get('similar', {}).get('results', [])[:6] if movie.get('similar') else []
    
    # Calculate prediction percentages for this movie
    _, _, _, gorg_films, sali_films = load_data()
    
    # Build movie dict for prediction function
    movie_for_prediction = {
        'tmdb_rating': movie.get('vote_average', 0),
        'year': int(movie.get('release_date', '')[:4]) if movie.get('release_date') and len(movie.get('release_date', '')) >= 4 else 0,
        'genre_ids': [g.get('id') for g in movie.get('genres', [])],
        'title': movie.get('title', '')
    }
    
    predictions = predict_liking_percentage(movie_for_prediction, gorg_films, sali_films)
    
    return render_template('movie_detail.html',
                         movie=movie,
                         cast=cast,
                         similar=similar,
                         budget=format_currency(budget),
                         revenue=format_currency(revenue),
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
                         sali_percent=predictions.get('sali_percent'),
                         gorg_percent=predictions.get('gorg_percent'),
                         sali_reasons=predictions.get('sali_reasons', []),
                         gorg_reasons=predictions.get('gorg_reasons', []))

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5001, threaded=True)



