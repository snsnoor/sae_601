#!/usr/bin/env python
"""
run.py — Orchestrateur du pipeline SAE 601.

Enchaîne automatiquement les 4 étapes du projet pour que l'utilisateur n'ait
qu'UNE seule commande à lancer (après l'installation des dépendances) :

    1. Sélection des départements / années   (launcher.py)
    2. Téléchargement des données sources     (download_data.py)
    3. Construction de la base DuckDB          (init_base.py)
    4. Lancement du dashboard Streamlit        (Dashboard/front.py)

Prérequis (une seule fois) :
    pip install -r requirements.txt

Exemples :
    python run.py                                  # réutilise selection.json (ou défauts) et tout lancer
    python run.py --departements 53 --annees 2024,2025
    python run.py --region Bretagne
    python run.py --skip-download                  # ne re-télécharge pas (réutilise data/)
    python run.py --skip-etl                       # ne reconstruit pas la base
    python run.py --no-dashboard                   # prépare tout sans ouvrir le dashboard
    python run.py --rebuild                         # force la reconstruction de la base
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable  # le même interpréteur (venv) que celui qui lance run.py
DB_PATH = ROOT / "info_appart.duckdb"


def run_step(titre, cmd):
    """Exécute une étape ; stoppe tout le pipeline si elle échoue."""
    print(f"\n{'=' * 70}\n▶  {titre}\n{'=' * 70}", flush=True)
    code = subprocess.run(cmd, cwd=ROOT).returncode
    if code != 0:
        print(f"\n✖  Étape « {titre} » échouée (code {code}). Pipeline interrompu.")
        sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="Pipeline complet SAE 601 (sélection → ETL → dashboard).")
    ap.add_argument("--departements", help="Liste de départements ex. 53,35 — ou 'all' pour toute la France")
    ap.add_argument("--region", help="Nom de région, ex. Bretagne (alternative à --departements)")
    ap.add_argument("--annees", help="Liste d'années, ex. 2024,2025")
    ap.add_argument("--skip-download", action="store_true", help="Ne pas (re)télécharger les données")
    ap.add_argument("--skip-etl", action="store_true", help="Ne pas reconstruire la base DuckDB")
    ap.add_argument("--rebuild", action="store_true", help="Supprimer la base avant de la reconstruire")
    ap.add_argument("--no-dashboard", action="store_true", help="Tout préparer sans lancer Streamlit")
    ap.add_argument("--port", default="8501", help="Port du dashboard Streamlit (défaut 8501)")
    args = ap.parse_args()

    # --- 1. Sélection (uniquement si l'utilisateur fournit des arguments de sélection) ---
    # Sans argument, on réutilise selection.json existant (ou les défauts de config.py).
    launcher_args = []
    if args.departements:
        launcher_args += ["--departements", args.departements]
    if args.region:
        launcher_args += ["--region", args.region]
    if args.annees:
        launcher_args += ["--annees", args.annees]
    if launcher_args:
        run_step("1/4  Sélection (launcher.py)", [PY, "launcher.py", *launcher_args])
        # La sélection a changé : on invalide les fichiers dérivés qui dépendent du
        # département/année et sont stockés en fichier UNIQUE (donc non versionnés par
        # la sélection, contrairement au DVF rangé en data/dvf/{annee}/{dept}.csv.gz).
        # Sans ça, le skip-if-present de download_data réutiliserait des données d'une
        # ancienne sélection.
        for nom in ("dpe.csv", "insee_filosofi.xlsx", "insee_population.csv", "communes.geojson"):
            f = ROOT / "data" / nom
            if f.exists():
                f.unlink()
                print(f"🗑  Fichier dérivé invalidé (sélection modifiée) : data/{nom}")
    else:
        print("ℹ  Aucune sélection fournie : réutilisation de selection.json (ou défauts).")

    # --- 2. Téléchargement des données ---
    if args.skip_download:
        print("⏭  Téléchargement ignoré (--skip-download).")
    else:
        run_step("2/4  Téléchargement des données (download_data.py)", [PY, "download_data.py"])

    # --- 3. Construction de la base ---
    if args.rebuild and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"🗑  Base supprimée pour reconstruction : {DB_PATH.name}")
    if args.skip_etl:
        print("⏭  Construction de la base ignorée (--skip-etl).")
    else:
        run_step("3/4  Construction de la base DuckDB (init_base.py)", [PY, "init_base.py"])

    # --- 4. Dashboard ---
    if args.no_dashboard:
        print("\n✅  Pipeline préparé. Lancez le dashboard avec :")
        print(f"    {PY} -m streamlit run Dashboard/front.py")
        return
    print(f"\n{'=' * 70}\n▶  4/4  Dashboard Streamlit → http://localhost:{args.port}\n{'=' * 70}", flush=True)
    # subprocess.run bloquant : le serveur tourne jusqu'à Ctrl-C.
    subprocess.run(
        [PY, "-m", "streamlit", "run", "Dashboard/front.py", "--server.port", str(args.port)],
        cwd=ROOT,
    )


if __name__ == "__main__":
    main()
