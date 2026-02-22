"""Scrape Sali's (salicore) Letterboxd profile."""
from scraper import run_scrape

if __name__ == "__main__":
    run_scrape(username="salicore", output_csv="salicore_scraped_films.csv")
