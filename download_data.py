"""
download_data.py — Télécharge les données sources dans le dossier data/

Inclut désormais (Domain 2) le cache des fichiers geo-DVF par département/année
dans data/dvf/{year}/{dept}.csv.gz, en sautant les fichiers déjà présents.
La sélection (départements + années) provient de config (selection.json),
elle-même alimentée par launcher.py.
"""

import gzip
import io
import urllib.request
from pathlib import Path

import pandas as pd
import requests

import config

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Taille minimale plausible : en-dessous, le fichier est quasi certainement une
# page d'erreur et non une vraie donnée.
TAILLE_MIN_OCTETS = 256


def _fichier_telecharge_valide(chemin: Path) -> tuple:
    """
    Valide un fichier fraîchement téléchargé : urlretrieve NE LÈVE PAS sur un 404,
    donc un corps d'erreur HTML peut être enregistré comme `.csv.gz` puis ignoré à
    jamais par le skip-if-present. On rejette les fichiers trop petits, le HTML
    déguisé, et les `.gz` qui ne sont pas un gzip valide.
    Renvoie (ok: bool, raison: str).
    """
    try:
        taille = chemin.stat().st_size
    except OSError:
        return (False, "fichier absent après téléchargement")
    if taille < TAILLE_MIN_OCTETS:
        return (False, f"fichier trop petit ({taille} octets), probable page d'erreur")

    # Détection d'une réponse HTML (404/maintenance) renvoyée en 200.
    try:
        with open(chemin, "rb") as f:
            debut = f.read(512)
    except OSError as e:
        return (False, f"lecture impossible : {e}")
    debut_strip = debut.lstrip().lower()
    if debut_strip.startswith(b"<!doctype html") or debut_strip.startswith(b"<html"):
        return (False, "contenu HTML (probable page d'erreur 404)")

    # Pour les .gz : on vérifie l'en-tête magique puis qu'on peut décompresser un bloc.
    if chemin.suffix == ".gz":
        if debut[:2] != b"\x1f\x8b":
            return (False, "en-tête gzip invalide")
        try:
            with gzip.open(chemin, "rb") as gz:
                gz.read(1)
        except OSError as e:
            return (False, f"gzip illisible : {e}")
    return (True, "")

# DÉCISION Domain 8 (2026-06-05) : la BAN nationale (adresses-france.csv.gz) est
# SUPPRIMÉE du téléchargement. Le projet utilise geo-DVF, qui fournit déjà les
# coordonnées (lat/lng) ; le fichier BAN national (très volumineux) était chargé
# dans une table 'adresses' jamais interrogée — pur gaspillage de bande passante
# et d'espace disque. La BAN pourra être réintroduite PAR DÉPARTEMENT plus tard
# pour géocoder d'éventuelles sources dépourvues de coordonnées.

_HEADERS = {"User-Agent": "Mozilla/5.0 (sae601 ETL)"}


def _filtrer_par_departement(df, col_codgeo, departements):
    """Restreint un DataFrame INSEE aux départements sélectionnés via le préfixe du
    code commune INSEE (CODGEO). startswith gère les codes à longueur variable :
    métropole sur 2 ('53'), Corse ('2A'/'2B'), DOM sur 3 ('971'). Si la sélection est
    vide, on ne filtre pas (comportement national)."""
    if not departements:
        return df
    codes = tuple(str(d) for d in departements)
    return df[df[col_codgeo].astype(str).str.startswith(codes)].copy()


# ------------------- DPE — API ADEME (Domain 4) -------------------
# init_base.py attend un fichier data/dpe.csv (étape 6, puis jointure sur dim_adresses).
# L'API ADEME ne filtrant qu'à la maille région historiquement, on utilise ici le filtre
# SERVEUR par département (code_departement_ban_eq), bien plus léger : on ne télécharge
# que les DPE des départements sélectionnés. Colonnes alignées sur init_base (COLS_TO_KEEP).
ADEME_DPE_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
DPE_PAGE_SIZE = 10000
DPE_COLS = [
    "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe", "date_derniere_modification_dpe",
    "code_insee_ban", "code_departement_ban", "code_region_ban",
    "coordonnee_cartographique_x_ban", "coordonnee_cartographique_y_ban", "score_ban",
    "nom_commune_ban", "code_postal_ban", "adresse_brut", "nom_commune_brut", "code_postal_brut",
    "etiquette_dpe", "etiquette_ges", "conso_5_usages_ep", "conso_5_usages_par_m2_ep",
    "emission_ges_5_usages", "cout_total_5_usages", "cout_chauffage", "cout_ecs",
    "cout_refroidissement", "cout_eclairage", "cout_auxiliaires", "type_batiment",
    "typologie_logement", "surface_habitable_logement", "periode_construction",
    "indicateur_confort_ete", "nombre_niveau_logement", "zone_climatique", "classe_altitude",
    "type_energie_principale_chauffage", "type_generateur_chauffage_principal",
    "qualite_isolation_enveloppe", "qualite_isolation_murs", "qualite_isolation_menuiseries",
    "ubat_w_par_m2_k", "isolation_toiture", "conso_chauffage_ef",
]


def telecharger_dpe(departements, annees=None):
    dest = DATA_DIR / "dpe.csv"
    if dest.exists():
        print("[OK] dpe.csv déjà présent, ignoré.")
        return
    # Filtre années : comme pour le DVF, on borne les DPE sur la plage d'années
    # sélectionnée (date_etablissement_dpe entre min et max), sinon l'API ramène
    # TOUTES les années pour le département (volume inutilement élevé).
    date_gte = date_lte = None
    if annees:
        date_gte, date_lte = f"{min(annees)}-01-01", f"{max(annees)}-12-31"
        print(f"[...] Téléchargement DPE (API ADEME, dépt + années {min(annees)}-{max(annees)})...")
    else:
        print("[...] Téléchargement DPE (API ADEME, filtre département)...")
    session = requests.Session()
    select = ",".join(DPE_COLS)
    rows = []
    try:
        for dept in departements:
            params = {"code_departement_ban_eq": dept, "select": select, "size": DPE_PAGE_SIZE}
            if date_gte:
                params["date_etablissement_dpe_gte"] = date_gte
                params["date_etablissement_dpe_lte"] = date_lte
            resp = session.get(ADEME_DPE_URL, headers=_HEADERS, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            total = data.get("total", 0)
            rows.extend(data.get("results", []))
            url = data.get("next")
            while url:
                resp = session.get(url, headers=_HEADERS, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                rows.extend(data.get("results", []))
                url = data.get("next")
            print(f"[OK] DPE département {dept} : {total:,} lignes.")
        df = pd.DataFrame(rows)
        # Garde uniquement les colonnes connues (l'API ajoute parfois '_score').
        df = df[[c for c in DPE_COLS if c in df.columns]]
        df.to_csv(dest, index=False, encoding="utf-8")
        print(f"[OK] dpe.csv écrit ({len(df):,} lignes).")
    except Exception as e:
        if dest.exists():
            dest.unlink()
        print(f"[AVERTISSEMENT] DPE non téléchargé : {e}")


# ------------------- Revenu médian par commune (Domain 6, FiLoSoFi) -------------------
# Source : data.gouv "Niveau de vie médian", ressource par commune (mediane-niveau-vie_com,
# millésime 2021). On la normalise dans le format attendu par init_base (xlsx CODGEO + MED*).
REVENU_COMMUNE_URL = "https://www.data.gouv.fr/api/1/datasets/r/1187a4c9-711f-4d16-b775-a313a09627b6"


def telecharger_revenu_filosofi(departements=None):
    dest = DATA_DIR / "insee_filosofi.xlsx"
    if dest.exists():
        print("[OK] insee_filosofi.xlsx déjà présent, ignoré.")
        return
    print("[...] Téléchargement revenu médian communal (data.gouv)...")
    try:
        resp = requests.get(REVENU_COMMUNE_URL, headers=_HEADERS, timeout=120)
        resp.raise_for_status()
        df = pd.read_csv(io.BytesIO(resp.content), dtype=str)  # annee, code_com, nom_territoire, valeur
        df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce")
        df = df.dropna(subset=["code_com"]).sort_values("annee")
        df = df.drop_duplicates("code_com", keep="last")  # millésime le plus récent par commune
        out = pd.DataFrame({
            "CODGEO": df["code_com"].astype(str).str.strip().str.zfill(5),
            "MED": df["valeur"],          # init_base détecte la 1re colonne 'MED*'
            "LIBGEO": df["nom_territoire"],
        })
        out = _filtrer_par_departement(out, "CODGEO", departements)
        out.to_excel(dest, index=False)
        print(f"[OK] insee_filosofi.xlsx écrit ({len(out):,} communes).")
    except Exception as e:
        if dest.exists():
            dest.unlink()
        print(f"[AVERTISSEMENT] revenu INSEE non téléchargé : {e}")


# ------------------- Population communale (Domain 6 + TEMPS, recensement) -------------------
# Source : INSEE « fichier d'ensemble des populations », feuille 'Communes', PLUSIEURS
# millésimes (2020→2023) pour porter une dimension TEMPORELLE (la population change chaque
# année). On normalise en CSV FORMAT LONG : CODGEO, ANNEE, PMUN, LIBGEO. Le code commune
# INSEE (CODGEO) est reconstruit = 'Code département' + 'Code commune' (sur 3 chiffres).
POPULATION_URLS = {
    2020: "https://www.insee.fr/fr/statistiques/fichier/6683035/ensemble.xlsx",
    2021: "https://www.insee.fr/fr/statistiques/fichier/7739582/ensemble.xlsx",
    2022: "https://www.insee.fr/fr/statistiques/fichier/8290591/ensemble.xlsx",
    2023: "https://www.insee.fr/fr/statistiques/fichier/8680726/ensemble.xlsx",
}


def _lire_population_ensemble(content, annee):
    """Lit la feuille 'Communes' d'un fichier d'ensemble INSEE (en-tête détecté de façon
    robuste) -> DataFrame [CODGEO, ANNEE, PMUN, LIBGEO], ou None si schéma non reconnu."""
    xl = pd.ExcelFile(io.BytesIO(content))
    sheet = next((s for s in xl.sheet_names if s.strip().lower().startswith("commune")), None)
    if sheet is None:
        return None
    # L'en-tête réel est précédé de lignes de métadonnées (≈7) ; on essaie plusieurs offsets.
    for skip in (7, 6, 8, 5, 9):
        df = pd.read_excel(xl, sheet_name=sheet, skiprows=skip, dtype=str)
        low = {str(c).strip().lower(): c for c in df.columns}
        c_dep = next((low[k] for k in low if k.startswith("code départe") or k.startswith("code departe")), None)
        c_com = next((low[k] for k in low if k.startswith("code commune")), None)
        c_pop = next((low[k] for k in low if "population municipale" in k), None)
        c_nom = next((low[k] for k in low if k.startswith("nom de la commune")), None)
        if c_dep and c_com and c_pop:
            dep = df[c_dep].astype(str).str.strip()
            com = df[c_com].astype(str).str.strip().str.zfill(3)
            out = pd.DataFrame({
                "CODGEO": (dep + com).str.zfill(5),
                "ANNEE": annee,
                "PMUN": pd.to_numeric(df[c_pop], errors="coerce"),
                "LIBGEO": df[c_nom] if c_nom else None,
            })
            return out.dropna(subset=["CODGEO"])
    return None


def telecharger_population(departements=None):
    dest = DATA_DIR / "insee_population.csv"
    if dest.exists():
        print("[OK] insee_population.csv déjà présent, ignoré.")
        return
    print("[...] Téléchargement population communale (INSEE, millésimes multiples)...")
    frames = []
    for annee, url in sorted(POPULATION_URLS.items()):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=180)
            resp.raise_for_status()
            d = _lire_population_ensemble(resp.content, annee)
            if d is not None and len(d):
                frames.append(d)
                print(f"   • {annee} : {len(d):,} communes")
            else:
                print(f"   ⚠️ {annee} : feuille/colonnes non reconnues, ignoré")
        except Exception as e:
            print(f"   ⚠️ {annee} : non téléchargé ({e})")
    if not frames:
        print("[AVERTISSEMENT] population INSEE non téléchargée (aucun millésime).")
        return
    out = pd.concat(frames, ignore_index=True)
    out = _filtrer_par_departement(out, "CODGEO", departements)
    out.to_csv(dest, index=False, encoding="utf-8")
    print(f"[OK] insee_population.csv écrit ({len(out):,} lignes, {out['ANNEE'].nunique()} millésimes).")


# ------------------- BAN par département (Domain 8 — géocodage) -------------------
# Base Adresse Nationale : 1 fichier CSV.gz par département (numéro + voie + code postal +
# lon/lat). Sert à géocoder, dans init_base (étape 0), les adresses DVF dépourvues de
# coordonnées (au lieu de les jeter). Rangé PAR DÉPARTEMENT (data/ban/{dept}.csv.gz) :
# naturellement correct au changement de sélection, comme le cache geo-DVF.
BAN_URL = "https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{dept}.csv.gz"


def telecharger_ban(departements):
    base = DATA_DIR / "ban"
    base.mkdir(parents=True, exist_ok=True)
    for dept in departements:
        dest = base / f"{dept}.csv.gz"
        if dest.exists():
            print(f"[OK] ban/{dept}.csv.gz déjà présent, ignoré.")
            continue
        url = BAN_URL.format(dept=dept)
        print(f"[...] Téléchargement BAN {dept} (géocodage)...")
        try:
            urllib.request.urlretrieve(url, dest)
            ok, raison = _fichier_telecharge_valide(dest)
            if not ok:
                if dest.exists():
                    dest.unlink()
                raise ValueError(f"fichier invalide ({raison})")
            print(f"[OK] ban/{dept}.csv.gz téléchargé.")
        except Exception as e:
            if dest.exists():
                dest.unlink()
            print(f"[AVERTISSEMENT] BAN {dept} non téléchargée : {e}")


# ------------------- DPE + INSEE + BAN (Domain 4, 6, 8) -------------------
# Étapes DÉFENSIVES : un échec réseau n'arrête pas le script (init_base sait sauter
# l'absence de data/dpe.csv, insee_filosofi.xlsx, insee_population.csv, data/ban/*).
print("\n--- DPE (API ADEME) + INSEE (revenu, population) + BAN (géocodage) ---")
_departements_sel = config.get_departements()
telecharger_dpe(_departements_sel, config.get_annees())
telecharger_revenu_filosofi(_departements_sel)
telecharger_population(_departements_sel)
telecharger_ban(_departements_sel)

# ------------------- Cache geo-DVF par département × année -------------------
# On télécharge un fichier .csv.gz par couple (année, département) sélectionné,
# vers data/dvf/{year}/{dept}.csv.gz. Même logique de saut que ci-dessus :
# un 2e run ne refait aucune requête réseau pour les fichiers déjà présents.
print("\n--- Cache geo-DVF (par département × année) ---")
departements = config.get_departements()
annees = config.get_annees()
print(f"Départements : {departements} | Années : {annees}")

for annee in annees:
    for dept in departements:
        dest = DATA_DIR / "dvf" / str(annee) / f"{dept}.csv.gz"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            print(f"[OK] dvf/{annee}/{dept}.csv.gz déjà présent, ignoré.")
            continue
        url = config.GEO_DVF_URL.format(year=annee, dept=dept)
        print(f"[...] Téléchargement de dvf/{annee}/{dept}.csv.gz...")
        try:
            urllib.request.urlretrieve(url, dest)
            # urlretrieve ne lève pas sur 404 : un .csv.gz invalide (HTML, gzip
            # corrompu...) serait sauté indéfiniment par le skip-if-present. On le
            # valide et on le supprime sinon, pour pouvoir le re-télécharger.
            ok, raison = _fichier_telecharge_valide(dest)
            if not ok:
                if dest.exists():
                    dest.unlink()
                raise ValueError(f"fichier invalide ({raison})")
            print(f"[OK] dvf/{annee}/{dept}.csv.gz téléchargé.")
        except Exception as e:
            # NOTE : certaines combinaisons année/département peuvent ne pas exister
            # côté data.gouv ; on ne stoppe pas tout le téléchargement pour autant.
            if dest.exists():
                dest.unlink()  # évite de laisser un fichier partiel/invalide
            print(f"[ERREUR] dvf/{annee}/{dept}.csv.gz : {e}")

# ------------------- Polygones administratifs communaux (Domain 7) -------------------
# Domain 7 : on télécharge les contours (polygones) des communes pour pouvoir tracer
# un choroplèthe (carte choroplèthe) clé par code commune INSEE, au lieu de la carte
# de POINTS actuelle. Sauvegardé dans data/communes.geojson.
#
# NOTE (équipe — source à confirmer) : on utilise l'API geo.api.gouv.fr, qui renvoie,
# pour chaque commune, un objet GeoJSON avec les propriétés 'code' (code INSEE) et 'nom',
# ainsi que la géométrie ('contour'/'geometry') quand on demande le format geojson.
#   - Endpoint commune par département :
#       https://geo.api.gouv.fr/departements/{dept}/communes?format=geojson&geometry=contour
#   - Le 'featureidkey' Plotly correspondant est 'properties.code' (code INSEE 5 car.).
# Alternative possible : IGN Admin Express (fichiers SHP/GeoJSON nationaux plus lourds).
# On télécharge UNIQUEMENT les départements sélectionnés (config.get_departements()),
# avec repli sur le fichier national de toutes les communes si la requête par dépt échoue.
# Étape DÉFENSIVE : une erreur réseau n'arrête pas le script (l'ingestion ETL sait sauter
# l'absence de ce fichier).
print("\n--- Polygones communaux (choroplèthe, Domain 7) ---")
import json

COMMUNES_GEOJSON = DATA_DIR / "communes.geojson"
if True:  # toujours régénérer pour couvrir les nouveaux départements de selection.json
    features = []
    erreurs = 0
    for dept in departements:
        # geometry=contour -> renvoie le polygone du contour communal (et non le centre).
        url = (
            f"https://geo.api.gouv.fr/departements/{dept}/communes"
            f"?format=geojson&geometry=contour"
        )
        print(f"[...] Contours des communes du département {dept}...")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                fc = json.loads(resp.read().decode("utf-8"))
            feats = fc.get("features", []) if isinstance(fc, dict) else []
            features.extend(feats)
            print(f"[OK] département {dept} : {len(feats)} communes.")
        except Exception as e:
            erreurs += 1
            print(f"[AVERTISSEMENT] contours du département {dept} non récupérés : {e}")

    # Repli national : si AUCUN département n'a abouti, on tente le fichier global.
    if not features:
        print("[...] Repli : téléchargement national de toutes les communes...")
        url_national = (
            "https://geo.api.gouv.fr/communes"
            "?format=geojson&geometry=contour&fields=code,nom"
        )
        try:
            with urllib.request.urlopen(url_national, timeout=300) as resp:
                fc = json.loads(resp.read().decode("utf-8"))
            features = fc.get("features", []) if isinstance(fc, dict) else []
            print(f"[OK] repli national : {len(features)} communes.")
        except Exception as e:
            print(f"[AVERTISSEMENT] repli national échoué : {e}")

    if features:
        collection = {"type": "FeatureCollection", "features": features}
        with open(COMMUNES_GEOJSON, "w", encoding="utf-8") as f:
            json.dump(collection, f)
        print(f"[OK] communes.geojson écrit ({len(features)} communes).")
    else:
        print("[AVERTISSEMENT] communes.geojson non créé (aucun contour récupéré) — "
              "le choroplèthe basculera sur la carte de points.")

print("Terminé.")
