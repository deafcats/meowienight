# How to Update Your Movie Recommendations

## Quick Update Process

To update your movie recommendations, run these two commands:

```bash
# Scrape Gorg's Letterboxd profile
python3 scrape_letterboxd_gorg.py

# Scrape Sali's Letterboxd profile  
python3 scrape_letterboxd_sali.py

# Then regenerate recommendations
python3 movie_recommender_improved.py
```

The CSV files will automatically update, and when you refresh the website, the new recommendations will appear!

## What Gets Updated

1. **gorg_scraped_films.csv** - Gorg's watched movies and ratings
2. **salicore_scraped_films.csv** - Sali's watched movies and ratings
3. **movie_recommendations_improved.csv** - Updated recommendations based on new data
4. **genre_recommendations.csv** - Genre-based recommendations
5. **tv_recommendations.csv** - TV show recommendations (run `python3 tv_recommender.py`)

## Common Scraping Issues & Solutions

### Issue 1: Profile Not Found (404)
**Problem:** The scraper says "Profile 'username' not found"
**Solution:** 
- Check the username is spelled correctly
- Make sure the Letterboxd profile exists
- Usernames are case-sensitive

### Issue 2: Access Denied (403)
**Problem:** The scraper says "Access denied" or "Profile might be private"
**Solution:**
- The profile is set to private - you need to make it public on Letterboxd
- Go to Letterboxd Settings → Privacy → Make profile public

### Issue 3: No Films Found
**Problem:** Scraper runs but finds 0 films
**Possible Causes:**
- Profile has no films logged
- HTML structure changed (Letterboxd updated their site)
- Network/connection issues

### Issue 4: Rate Limiting
**Problem:** Scraper stops working after a few pages
**Solution:**
- The scraper already includes 1.5 second delays between requests
- If still having issues, increase the delay in the script

### Issue 5: Timeout Errors
**Problem:** "Timeout error on page X"
**Solution:**
- Check your internet connection
- Letterboxd might be slow - try again later

## Technical Details

The scrapers work by:
1. Making HTTP requests to Letterboxd profile pages
2. Parsing HTML to find film entries (using `data-item-slug` attributes)
3. Extracting film titles and ratings from the HTML structure
4. Saving to CSV files

**Why scraping can fail:**
- Letterboxd changes their HTML structure (we look for `div[data-item-slug]`)
- Profile privacy settings
- Network issues
- Rate limiting (though we have delays built in)
- Missing User-Agent header (we include a proper one)

The scrapers include error handling and will tell you exactly what went wrong!

