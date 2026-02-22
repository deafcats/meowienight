# Movie Recommendation System 🎬

A personalized movie recommendation system based on Letterboxd histories for Sali and Gorg!

## Features

- **Scraping**: Scrape Letterboxd profiles to get watched films and ratings
- **Recommendations**: Generate movie recommendations using TMDB API
- **Web Interface**: Beautiful Flask website to browse recommendations
- **Filtering**: Filter recommendations by rating, year, and sort options

## Setup

1. **Install dependencies:**
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Scrape your Letterboxd profiles:**
   ```bash
   # Scrape Gorg's profile
   python3 scrape_letterboxd_gorg.py
   
   # Scrape Sali's profile
   python3 scrape_letterboxd_sali.py
   ```

3. **Generate recommendations:**
   ```bash
   python3 movie_recommender_improved.py
   ```

4. **Run the Flask website:**
   ```bash
`   python3 app.py`
   ```

5. **Open in browser:**
   Navigate to `http://localhost:5000`

## Files

- `app.py` - Flask web application
- `movie_recommender_improved.py` - Recommendation engine
- `scrape_letterboxd_gorg.py` - Scraper for Gorg's profile
- `scrape_letterboxd_sali.py` - Scraper for Sali's profile
- `templates/` - HTML templates
- `static/css/` - CSS styles

## CSV Files

- `gorg_scraped_films.csv` - Gorg's watched films
- `salicore_scraped_films.csv` - Sali's watched films
- `movie_recommendations_improved.csv` - Generated recommendations
- `genre_recommendations.csv` - Genre-based recommendations

## API Key

Make sure your TMDB API key is set in `movie_recommender_improved.py`:
```python
TMDB_API_KEY = "your-api-key-here"
```

Enjoy finding your next favorite movie! 🍿

