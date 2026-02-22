# Scraping Issues - What Was Wrong & How It's Fixed

## What Was Wrong with the Original Scrapers

The original scrapers (`main.py/scrape_letterboxd.py` and `main.py/scrape_letterboxd_solicore.py`) had several potential issues:

### 1. **Limited Error Handling**
- **Problem**: If a profile was private or didn't exist, the scraper would just stop without clear error messages
- **Fix**: Added comprehensive error checking for:
  - 404 errors (profile not found)
  - 403 errors (private profile)
  - Timeout errors
  - Network issues

### 2. **Insufficient User-Agent Header**
- **Problem**: Some websites block requests without proper browser headers
- **Fix**: Added a full User-Agent string that mimics a real browser:
  ```python
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36...'
  ```

### 3. **No Timeout Protection**
- **Problem**: If Letterboxd was slow, the script would hang indefinitely
- **Fix**: Added 10-second timeout to all requests

### 4. **Poor Error Messages**
- **Problem**: When scraping failed, you didn't know why
- **Fix**: Added detailed error messages explaining:
  - Profile doesn't exist
  - Profile is private
  - Network issues
  - Empty profiles

### 5. **Inconsistent File Naming**
- **Problem**: One scraper saved to `bf_scraped_films.csv`, the other to `salicore_scraped_films.csv`
- **Fix**: Created unified scrapers:
  - `scrape_letterboxd_gorg.py` → `gorg_scraped_films.csv`
  - `scrape_letterboxd_sali.py` → `salicore_scraped_films.csv`

## How Scraping Works

1. **Makes HTTP requests** to Letterboxd profile pages (`/username/films/page/1/`, `/page/2/`, etc.)
2. **Parses HTML** using BeautifulSoup to find film entries
3. **Extracts data** from HTML attributes:
   - `data-item-name` or `data-item-slug` for film titles
   - `span.rating` with class `rated-X` for ratings (X = 2-10, where 10 = 5 stars)
4. **Saves to CSV** with columns: `film_title`, `rating`, `rating_stars`

## Common Failure Reasons

### Profile is Private
- **Symptom**: Gets 403 error or finds 0 films
- **Solution**: Make the Letterboxd profile public in settings

### Profile Doesn't Exist
- **Symptom**: Gets 404 error
- **Solution**: Check the username spelling (case-sensitive)

### HTML Structure Changed
- **Symptom**: Finds 0 films even though profile has films
- **Solution**: Letterboxd updated their site - need to update the scraper to match new HTML structure

### Rate Limiting
- **Symptom**: Works for a few pages then stops
- **Solution**: Already handled with 1.5 second delays between requests

## How to Update Recommendations

### Step 1: Scrape Both Profiles
```bash
python3 scrape_letterboxd_gorg.py
python3 scrape_letterboxd_sali.py
```

This updates:
- `gorg_scraped_films.csv`
- `salicore_scraped_films.csv`

### Step 2: Regenerate Recommendations
```bash
python3 movie_recommender_improved.py
```

This updates:
- `movie_recommendations_improved.csv`
- `genre_recommendations.csv`

### Step 3: (Optional) Regenerate TV Recommendations
```bash
python3 tv_recommender.py
```

This updates:
- `tv_recommendations.csv`

### Step 4: Refresh Website
The Flask app automatically reads the CSV files, so just refresh your browser!

## Automatic Updates

The website reads CSV files on every page load, so:
1. Run the scrapers → CSV files update
2. Refresh browser → New recommendations appear automatically!

No need to restart the Flask server.

