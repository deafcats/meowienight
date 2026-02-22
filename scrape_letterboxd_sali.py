import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

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
                
                # Extract rating from parent li element
                li = film_div.find_parent('li')
                rating = None
                rating_stars = None
                
                if li:
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
    # Scraping Sali's Letterboxd profile
    username = 'salicore'
    print(f"\n{'='*60}")
    print(f"Scraping Letterboxd profile: {username}")
    print(f"{'='*60}\n")
    
    films_data = scrape_letterboxd_films(username)
    
    if films_data:
        df = pd.DataFrame(films_data)
        df.to_csv('salicore_scraped_films.csv', index=False)
        
        print(f"\n{'='*60}")
        print(f"✅ SUCCESS: Saved {len(df)} films to salicore_scraped_films.csv")
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

