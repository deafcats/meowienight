import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re

def scrape_letterboxd_films(username, max_pages=50):
    """
    Scrape Letterboxd films for a given username.
    
    Issues that can cause scraping to fail:
    1. Profile is private - Letterboxd returns 403 or empty results
    2. Profile doesn't exist - Returns 404
    3. Rate limiting - Too many requests too fast (solved with time.sleep)
    4. HTML structure changes - Letterboxd updates their site layout
    5. Missing User-Agent header - Some sites block requests without proper headers
    """
    films = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for page in range(1, max_pages + 1):
        url = f'https://letterboxd.com/{username}/films/page/{page}/'
        print(f'Scraping page {page}: {url}')
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            # Check for various error conditions
            if response.status_code == 404:
                print(f"❌ Profile '{username}' not found (404). Check the username.")
                break
            elif response.status_code == 403:
                print(f"❌ Access denied (403). Profile '{username}' might be private.")
                break
            elif response.status_code != 200:
                print(f"⚠️  Unexpected status code {response.status_code} on page {page}")
                break
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Letterboxd uses div elements with data-item-slug inside li elements
            film_divs = soup.find_all('div', {'data-item-slug': True})
            
            if not film_divs:
                # Check if we're on a valid page but just no films
                if page == 1:
                    print(f"⚠️  No films found on first page. Profile might be empty or private.")
                else:
                    print(f"✅ Reached end of films at page {page-1}")
                break
            
            print(f"   Found {len(film_divs)} films on page {page}")
            
            for film_div in film_divs:
                # Use data-item-name if available, otherwise derive from slug
                film_title = film_div.get('data-item-name')
                if not film_title:
                    film_title = film_div['data-item-slug'].replace('-', ' ').title()
                
                # Extract rating from parent li element - try multiple methods
                li = film_div.find_parent('li')
                rating = None
                rating_stars = None
                
                if li:
                    # Method 1: Look for span with class 'rating' and 'rated-X' class
                    rating_span = li.find('span', class_='rating')
                    if rating_span:
                        # Get the rated-X class value (X is 2-10, where 2=1 star, 10=5 stars)
                        rating_classes = rating_span.get('class', [])
                        rated_class = [c for c in rating_classes if 'rated-' in c]
                        if rated_class:
                            try:
                                rated_value = int(rated_class[0].split('-')[1])
                                rating = rated_value / 2.0  # Convert to 0.5-5.0 scale
                                rating_stars = rating_span.get_text(strip=True)
                            except (ValueError, IndexError):
                                pass
                    
                    # Method 2: If Method 1 didn't work, try finding any element with 'rated-' class
                    if rating is None:
                        rated_elements = li.find_all(class_=lambda x: x and 'rated-' in str(x))
                        for elem in rated_elements:
                            classes = elem.get('class', [])
                            for cls in classes:
                                if 'rated-' in cls:
                                    try:
                                        rated_value = int(cls.split('-')[1])
                                        rating = rated_value / 2.0
                                        # Try to get star representation from text
                                        rating_stars = elem.get_text(strip=True)
                                        if not rating_stars or len(rating_stars) == 0:
                                            # Generate star representation
                                            full_stars = int(rating)
                                            half_star = (rating % 1) >= 0.5
                                            rating_stars = '★' * full_stars + ('½' if half_star else '')
                                        break
                                    except (ValueError, IndexError):
                                        continue
                    
                    # Method 3: Look for data-rating attribute or similar
                    if rating is None:
                        # Check if the li itself has rating info
                        data_rating = li.get('data-rating') or li.get('data-rating-value')
                        if data_rating:
                            try:
                                rating = float(data_rating)
                                if rating > 5:  # If it's on 10-point scale, convert to 5
                                    rating = rating / 2.0
                            except (ValueError, TypeError):
                                pass
                    
                    # Method 4: Look for any text that looks like a rating (e.g., "4.5", "★★★★½")
                    if rating is None:
                        # Search for star symbols in the li text
                        li_text = li.get_text()
                        # Look for patterns like "★★★★" or "4.5/5" or "9/10"
                        # Try to find star count (★ = 1, ★★ = 2, etc.)
                        star_match = re.search(r'[★☆]+', li_text)
                        if star_match:
                            stars = star_match.group(0)
                            star_count = stars.count('★') + stars.count('☆')
                            if '½' in li_text or 'half' in li_text.lower():
                                rating = star_count + 0.5
                            else:
                                rating = float(star_count)
                            rating_stars = stars
                
                films.append({
                    'film_title': film_title,
                    'rating': rating,
                    'rating_stars': rating_stars
                })
            
            # Be kind to Letterboxd servers - wait between pages
            time.sleep(1.5)
            
        except requests.exceptions.Timeout:
            print(f"❌ Timeout error on page {page}")
            break
        except requests.exceptions.RequestException as e:
            print(f"❌ Request error on page {page}: {e}")
            break
        except Exception as e:
            print(f"❌ Unexpected error on page {page}: {e}")
            break
    
    return films

if __name__ == '__main__':
    # Scraping Gorg's Letterboxd profile
    username = 'dmcoutlaw'  # Gorg's actual Letterboxd username
    print(f"\n{'='*60}")
    print(f"Scraping Letterboxd profile: {username}")
    print(f"{'='*60}\n")
    
    films_data = scrape_letterboxd_films(username)
    
    if films_data:
        df = pd.DataFrame(films_data)
        df.to_csv('gorg_scraped_films.csv', index=False)
        
        print(f"\n{'='*60}")
        print(f"✅ SUCCESS: Saved {len(df)} films to gorg_scraped_films.csv")
        print(f"{'='*60}")
        
        if len(df) > 0:
            print(f"\nRating distribution:")
            print(df['rating'].value_counts().sort_index())
            print(f"\nFilms with ratings: {df['rating'].notna().sum()}")
            print(f"Films without ratings: {df['rating'].isna().sum()}")
    else:
        print(f"\n❌ No films found. Possible reasons:")
        print(f"   - Profile '{username}' doesn't exist")
        print(f"   - Profile is private")
        print(f"   - Profile has no films logged")
        print(f"   - Network/connection issues")

