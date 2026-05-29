"""
download_data.py — Télécharge les données sources dans le dossier data/
"""

import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FICHIERS = {
    "adresses-france.csv.gz": "https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-france.csv.gz",

}

for nom, url in FICHIERS.items():
    dest = DATA_DIR / nom
    if dest.exists():
        print(f"[OK] {nom} déjà présent, ignoré.")
        continue
    print(f"[...] Téléchargement de {nom}...")
    urllib.request.urlretrieve(url, dest)
    print(f"[OK] {nom} téléchargé.")

print("Terminé.")
