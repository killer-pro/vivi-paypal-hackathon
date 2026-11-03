"""Remplit la bibliothèque musicale avec des pistes de Kevin MacLeod à licence ouverte (Internet Archive).

Usage : uv run python scripts/seed_music.py [--api http://localhost:8000] [--email …] [--password …]
Les pistes passent par `POST /api/music` (donc stockées dans MinIO) ; une piste déjà présente (même nom) est ignorée.
Licences : CC0 / domaine public, ou CC BY 4.0 (attribution à conserver, d'où le crédit dans le nom).
"""
import argparse
import os

import httpx

ARCHIVE = "https://archive.org/download"
BY, CC0, PD = "CC BY 4.0", "CC0", "domaine public"
# (identifiant archive.org, fichier, titre, licence, tags)
TRACKS = [
    ("sneaky-snitch_202610", "Sneaky Snitch.mp3", "Sneaky Snitch", PD, "mystère,fun"),
    ("local-forecast-by-kevin-macleod", "local-forecast-by-kevin-macleod.mp3", "Local Forecast", BY, "calme,lofi"),
    ("wholesome-by-kevin-macleod", "wholesome-by-kevin-macleod.mp3", "Wholesome", BY, "doux,positif"),
    ("pixelland-by-kevin-macleod", "4222-pixelland-by-kevin-macleod.mp3", "Pixelland", BY, "jeu,fun"),
    ("monkeys-spinning-monkeys", "Monkeys Spinning Monkeys.mp3", "Monkeys Spinning Monkeys", BY, "fun,comique"),
    ("modern-jazz-samba-by-kevin-macleod", "modern-jazz-samba-by-kevin-macleod.mp3", "Modern Jazz Samba", BY, "jazz,détente"),
    ("new-friendly", "New Friendly.mp3", "New Friendly", BY, "positif,doux"),
    ("radio-martini", "Radio Martini.mp3", "Radio Martini", BY, "lounge,calme"),
    ("covert-affair-by-kevin-macleod-from-filmmusic-io", "covert-affair-by-kevin-macleod-from-filmmusic-io.mp3",
     "Covert Affair", BY, "suspense,mystère"),
    ("5759blippytrancebykevinmacleod", "5759-blippy-trance-by-kevin-macleod.mp3", "Blippy Trance", BY, "énergique,électro"),
    ("hypno-this-by-kevin-macleod", "Hypnothis.mp3", "Hypnothis", CC0, "suspense,rythmé"),
    ("come-play-with-me-by-kevin-macleod", "come-play-with-me-by-kevin-macleod.mp3", "Come Play with Me", BY,
     "fun,enfantin"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", "admin@example.com"))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", "change-me"))
    args = parser.parse_args()
    with httpx.Client(base_url=f"{args.api}/api", timeout=120, follow_redirects=True) as api:
        api.post("/auth/login", json={"email": args.email.strip().lower(), "password": args.password}).raise_for_status()
        existing = {t["name"] for t in api.get("/music").json()}
        for identifier, filename, title, licence, tags in TRACKS:
            name = f"{title} — Kevin MacLeod ({licence})"
            if name in existing:
                continue
            audio = api.get(f"{ARCHIVE}/{identifier}/{filename}")
            audio.raise_for_status()
            api.post("/music", data={"name": name, "tags": tags},
                     files={"file": (filename, audio.content, "audio/mpeg")}).raise_for_status()
            print("ajoutée :", name)


if __name__ == "__main__":
    main()
