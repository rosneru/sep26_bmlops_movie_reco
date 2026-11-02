"""Generate synthetic CSVs for CI; does not validate recommendation quality."""

import csv
from pathlib import Path

GENRES = [
    "(no genres listed)",
    "Action",
    "Adventure",
    "Animation",
    "Children",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Film-Noir",
    "Horror",
    "IMAX",
    "Musical",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
]

# Small catalog used to train a disposable CI model.
MODEL_MOVIE_COUNT = 40

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "processed"
USER_FILE = OUTPUT / "user_matrix.csv"
MOVIE_FILE = OUTPUT / "movie_matrix.csv"


def main():
    if USER_FILE.exists() or MOVIE_FILE.exists():
        raise SystemExit("Refusing to overwrite existing inference data.")

    OUTPUT.mkdir(parents=True, exist_ok=True)

    with USER_FILE.open("x", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["userId", *GENRES])
        writer.writerow([1, *([0.5] * len(GENRES))])

    with MOVIE_FILE.open("x", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["movieId", *GENRES])
        writer.writerows(
            [movie_id, *[int((movie_id + i) % 3 == 0) for i in range(len(GENRES))]]
            for movie_id in range(1, MODEL_MOVIE_COUNT + 1)
        )

    print("Generated synthetic inference data for CI test user 1.")


if __name__ == "__main__":
    main()