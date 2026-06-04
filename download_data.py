"""
download_data.py — Télécharge les données sources dans le dossier data/

Sources gérées ici :
  - BAN (Base Adresse Nationale) — adresses France entière

Sources gérées ailleurs :
  - DVF     : chargé directement en streaming depuis l'URL dans init_base.py
  - DPE     : exécutez dpe_api.py pour charger via l'API ADEME (lent ~30min),
               ou placez manuellement un fichier data/dpe.csv pour les tests
  - SNCF / Écoles / IRIS : récupérés en live dans init_base.py via API REST
"""

import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FICHIERS = {
    "adresses-france.csv.gz": (
        "https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-france.csv.gz"
    ),
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
print()
print("Étapes suivantes :")
print("  1. DPE  : python dpe_api.py   (ou placez data/dpe.csv manuellement)")
print("  2. DB   : python init_base.py")
print("  3. App  : streamlit run dashboard/front.py")
