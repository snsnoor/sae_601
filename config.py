"""
config.py — Module de configuration partagé .

Centralise :
  - le mapping région -> départements (déplacé depuis Dashboard/back.py) ;
  - le mapping département -> code région INSEE (utile pour l'API DPE ADEME) ;
  - le patron d'URL geo-DVF par département/année ;
  - la lecture de la sélection (départements + années) écrite par launcher.py.

L'ETL (init_base.py), le téléchargement (download_data.py), le chargement DPE
(dpe_api.py) et le dashboard (back.py) importent tous depuis ce module afin de
partager UNE seule source de vérité.
"""

import json
from pathlib import Path

# Fichier de sélection produit par launcher.py (départements + années choisis)
SELECTION_FILE = Path(__file__).parent / "selection.json"

# Patron d'URL geo-DVF (data.gouv) : un fichier .csv.gz par département et par année.
# Ex : https://files.data.gouv.fr/geo-dvf/latest/csv/2024/departements/53.csv.gz
GEO_DVF_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/departements/{dept}.csv.gz"

# Valeurs par défaut si aucun selection.json n'est présent
DEFAULT_DEPARTEMENTS = ["53"]
DEFAULT_ANNEES = [2024, 2025]

# --- Mapping région -> départements -------------------------------------------
# (déplacé depuis Dashboard/back.py ; back.py l'importe désormais d'ici)
REGIONS_MAPPING = {
    'Toutes les régions': [],
    'Auvergne-Rhône-Alpes': ['01', '03', '07', '15', '26', '38', '42', '43', '63', '69', '73', '74'],
    'Bourgogne-Franche-Comté': ['21', '25', '39', '58', '70', '71', '89', '90'],
    'Bretagne': ['22', '29', '35', '56'],
    'Centre-Val de Loire': ['18', '28', '36', '37', '41', '45'],
    'Corse': ['2A', '2B'],
    'Grand Est': ['08', '10', '51', '52', '54', '55', '57', '67', '68', '88'],
    'Hauts-de-France': ['02', '59', '60', '62', '80'],
    'Île-de-France': ['75', '77', '78', '91', '92', '93', '94', '95'],
    'Normandie': ['14', '27', '50', '61', '76'],
    'Nouvelle-Aquitaine': ['16', '17', '19', '23', '24', '33', '40', '47', '64', '79', '86', '87'],
    'Occitanie': ['09', '11', '12', '30', '31', '32', '34', '46', '48', '65', '66', '81', '82'],
    'Pays de la Loire': ['44', '49', '53', '72', '85'],
    'Provence-Alpes-Côte d\'Azur': ['04', '05', '06', '13', '83', '84'],
}

# --- Mapping nom de région -> code région INSEE -------------------------------
# L'API DPE ADEME filtre par code_region_ban (code INSEE de la région), pas par
# le nom. On garde ce mapping pour traduire départements -> régions INSEE.
REGION_NOM_VERS_CODE_INSEE = {
    'Auvergne-Rhône-Alpes': '84',
    'Bourgogne-Franche-Comté': '27',
    'Bretagne': '53',
    'Centre-Val de Loire': '24',
    'Corse': '94',
    'Grand Est': '44',
    'Hauts-de-France': '32',
    'Île-de-France': '11',
    'Normandie': '28',
    'Nouvelle-Aquitaine': '75',
    'Occitanie': '76',
    'Pays de la Loire': '52',
    'Provence-Alpes-Côte d\'Azur': '93',
}

# Mapping inverse construit automatiquement : département -> code région INSEE
DEPT_VERS_REGION_INSEE = {}
for _nom_region, _depts in REGIONS_MAPPING.items():
    _code_insee = REGION_NOM_VERS_CODE_INSEE.get(_nom_region)
    if not _code_insee:
        continue
    for _d in _depts:
        DEPT_VERS_REGION_INSEE[_d] = _code_insee


def _normaliser_dept(dept) -> str:
    """Normalise un code département : padding à 2 chiffres, conserve la Corse (2A/2B)."""
    d = str(dept).strip().upper()
    if d in ("2A", "2B"):
        return d
    # NOTE: les codes numériques < 10 doivent être paddés ('5' -> '05')
    if d.isdigit():
        return d.zfill(2)
    return d


def _lire_selection() -> dict:
    """Lit selection.json s'il existe, sinon retourne un dict vide."""
    if SELECTION_FILE.exists():
        try:
            with open(SELECTION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # NOTE: fichier corrompu -> on retombe sur les défauts plutôt que de planter
            return {}
    return {}


def get_departements() -> list:
    """
    Renvoie la liste des codes départements à ingérer.
    Lit selection.json si présent, sinon DEFAULT_DEPARTEMENTS.
    Les codes sont normalisés (padding à 2 chiffres) ET VALIDÉS : un
    selection.json édité à la main (entrées vides, code inexistant) ne doit pas
    laisser passer un code invalide jusqu'aux URLs et aux DELETE SQL.
    """
    sel = _lire_selection()
    depts = sel.get("departements") or DEFAULT_DEPARTEMENTS

    valides = departements_valides()
    resultat = []
    for d in depts:
        # On ignore les entrées vides / blanches issues d'une édition manuelle.
        if d is None or not str(d).strip():
            continue
        code = _normaliser_dept(d)
        # On écarte (avec avertissement) tout code qui n'existe pas dans le
        # référentiel des départements connus (REGIONS_MAPPING).
        if code not in valides:
            print(f"[AVERTISSEMENT] config.get_departements : code département "
                  f"invalide ignoré → {d!r}")
            continue
        if code not in resultat:  # déduplication en conservant l'ordre
            resultat.append(code)

    # Repli sur les défauts si rien de valide ne subsiste (selection.json cassé).
    if not resultat:
        print("[AVERTISSEMENT] config.get_departements : aucun département valide "
              f"dans la sélection, repli sur les défauts {DEFAULT_DEPARTEMENTS}.")
        resultat = [_normaliser_dept(d) for d in DEFAULT_DEPARTEMENTS]
    return resultat


def get_annees() -> list:
    """
    Renvoie la liste des années à ingérer (entiers).
    Lit selection.json si présent, sinon DEFAULT_ANNEES.
    """
    sel = _lire_selection()
    annees = sel.get("annees") or DEFAULT_ANNEES
    return [int(a) for a in annees]


def get_regions_insee() -> list:
    """
    Traduit la sélection de départements en codes région INSEE uniques,
    pour le filtrage de l'API DPE ADEME (code_region_ban_eq).
    """
    codes = []
    for d in get_departements():
        code = DEPT_VERS_REGION_INSEE.get(d)
        if code and code not in codes:
            codes.append(code)
    return codes


def departements_valides() -> set:
    """Ensemble de tous les codes départements connus (toutes régions confondues)."""
    valides = set()
    for depts in REGIONS_MAPPING.values():
        valides.update(depts)
    return valides
