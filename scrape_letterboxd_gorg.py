"""Scrape Gorg's (dmcoutlaw) Letterboxd profile."""
from scraper import run_scrape

if __name__ == "__main__":
    run_scrape(username="dmcoutlaw", output_csv="gorg_scraped_films.csv")
