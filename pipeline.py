"""
Data pipeline — scrapes Letterboxd profiles and regenerates recommendations.

Can be run standalone (`python pipeline.py`) or called from the Flask app's
background scheduler.
"""

import os
import time
import traceback

DATA_DIR = os.environ.get("DATA_DIR", ".")


def run_pipeline(data_dir: str | None = None) -> None:
    """Execute the full scrape → recommend pipeline."""
    data_dir = data_dir or DATA_DIR
    os.makedirs(data_dir, exist_ok=True)

    print("\n" + "=" * 60)
    print("PIPELINE START")
    print("=" * 60)
    start = time.time()

    # --- Step 1: Scrape Letterboxd profiles ---
    try:
        from scraper import run_scrape

        print("\n[1/4] Scraping Gorg (dmcoutlaw)...")
        run_scrape(
            username="dmcoutlaw",
            output_csv=os.path.join(data_dir, "gorg_scraped_films.csv"),
        )

        print("\n[2/4] Scraping Sali (salicore)...")
        run_scrape(
            username="salicore",
            output_csv=os.path.join(data_dir, "salicore_scraped_films.csv"),
        )
    except Exception:
        print("❌ Scraping failed:")
        traceback.print_exc()
        return

    gorg_csv = os.path.join(data_dir, "gorg_scraped_films.csv")
    sali_csv = os.path.join(data_dir, "salicore_scraped_films.csv")
    if not (os.path.exists(gorg_csv) and os.path.exists(sali_csv)):
        print("❌ Scraped CSVs missing — skipping recommendation step.")
        return

    # --- Step 2: Generate movie recommendations ---
    try:
        import movie_recommender_improved

        print("\n[3/4] Generating movie recommendations...")
        movie_recommender_improved.run(data_dir=data_dir)
    except Exception:
        print("❌ Movie recommender failed:")
        traceback.print_exc()

    # --- Step 3: Generate TV recommendations ---
    try:
        import tv_recommender

        print("\n[4/4] Generating TV recommendations...")
        tv_recommender.run(data_dir=data_dir)
    except Exception:
        print("❌ TV recommender failed:")
        traceback.print_exc()

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE  ({elapsed:.0f}s)")
    print(f"{'=' * 60}\n")


def csvs_exist(data_dir: str | None = None) -> bool:
    """Return True if all expected CSV outputs exist."""
    data_dir = data_dir or DATA_DIR
    needed = [
        "gorg_scraped_films.csv",
        "salicore_scraped_films.csv",
        "movie_recommendations_improved.csv",
        "tv_recommendations.csv",
    ]
    return all(os.path.exists(os.path.join(data_dir, f)) for f in needed)


if __name__ == "__main__":
    run_pipeline()
