"""
back.py — Requêtes DuckDB pour le dashboard.
Basé sur le modèle structuré (backf.py) avec intégration de la cartographie 
et des filtres régionaux.
"""

import sys
import numpy as np
import duckdb
import pandas as pd
from pathlib import Path

# Import de la config partagée (config.py est à la racine du projet, un niveau au-dessus)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import REGIONS_MAPPING  # noqa: E402  (mapping région -> départements partagé)

# Chemin vers la base de données (nom canonique unifié, produit par init_base.py).
# NOTE : ancré sur la racine du projet (un niveau au-dessus de Dashboard/) via
# Path(__file__) et NON sur le CWD, sinon lancer depuis Dashboard/ ouvrirait une
# 2e base vide (mode démo silencieux). cf. revue de code [LOW] « Chemin DB relatif ».
DB_PATH = Path(__file__).resolve().parent.parent / 'info_appart.duckdb'

# --- 1. MAPPING ET FILTRES ---
# REGIONS_MAPPING est désormais importé depuis config.py (plus de duplication).

def get_regions():
    """Renvoie la liste des régions pour le menu déroulant."""
    return list(REGIONS_MAPPING.keys())

def get_communes_dispo() -> list:
    """Renvoie ['Toutes les communes'] + liste triée des communes présentes dans la base."""
    try:
        con = _con()
        try:
            rows = con.execute("""
                SELECT DISTINCT v.nom_commune
                FROM fact_dvf f
                JOIN dim_adresses v ON f.id_adresse = v.id_adresse
                WHERE v.nom_commune IS NOT NULL
                ORDER BY v.nom_commune
            """).fetchall()
        finally:
            con.close()
        return ["Toutes les communes"] + [r[0] for r in rows]
    except Exception:
        return ["Toutes les communes"]

def _get_dept_filter(region, alias="f"):
    """Construit la condition SQL IN (...) pour filtrer par départements.

    NOTE (sécurité) : les codes département proviennent EXCLUSIVEMENT de la constante
    de confiance REGIONS_MAPPING (config.py), jamais d'une saisie utilisateur libre ;
    aucune injection SQL n'est donc possible ici. Comme cette fonction renvoie un
    FRAGMENT de chaîne (et non une requête exécutable avec une liste de params), on ne
    peut pas y placer de placeholders ? : c'est l'appelant qui exécute. L'alias est lui
    aussi un paramètre interne fixe ('f', 'p', …), jamais fourni par l'utilisateur.
    """
    if region and region != 'Toutes les régions':
        depts = REGIONS_MAPPING.get(region, [])
        depts_str = ", ".join([f"'{d}'" for d in depts])
        return f" AND {alias}.code_departement IN ({depts_str}) "
    return ""

# --- 2. CONNEXION À LA BASE ---

def _con():
    """Ouvre une connexion en lecture seule à DuckDB."""
    return duckdb.connect(str(DB_PATH), read_only=True)

def db_ready() -> bool:
    """Retourne True si la base existe et contient fact_dvf."""
    try:
        con = _con()
        try:
            tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        finally:
            con.close()  # ferme même si execute lève (pas de fuite de connexion)
        return "fact_dvf" in tables
    except Exception:
        return False

# --- 3. FONCTIONS POUR LE FRONT-END (VUE GLOBALE ET CARTE) ---

def get_donnees_globales():
    return "Voici un aperçu de l'état du marché immobilier français."

def get_modele_estimation():
    return "L'algorithme d'estimation et son formulaire arriveront ici."

def get_kpis(region=None) -> dict:
    """
    Récupère à la fois les statistiques globales ET les classements (Tops 5).
    Intègre les filtres régionaux et se concentre sur les Maisons/Appartements.
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        # 1. Statistiques globales (pour st.metric futurs ou actuels)
        row = con.execute(f"""
            SELECT
                COUNT(*)                                                      AS nb_transactions,
                COUNT(DISTINCT v.nom_commune)                                 AS nb_communes,
                MEDIAN(f.prix_m2) AS prix_m2_median,
                MEDIAN(f.surface_reelle_bati)                                AS surface_mediane
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.valeur_fonciere > 0
              AND f.surface_reelle_bati > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              {dept_filter}
        """).fetchone()

        # 2. Requête de base pour les Tops (min. et max. 10 ventes)
        query_base_tops = f"""
            SELECT
                v.nom_commune,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) as nb_ventes
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.valeur_fonciere > 0
              AND f.surface_reelle_bati > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              {dept_filter}
            GROUP BY v.nom_commune
            HAVING nb_ventes >= 10
        """

        # 3. Récupération des DataFrames
        df_top_cheres = con.execute(f"{query_base_tops} ORDER BY prix_m2_median DESC LIMIT 5").df()
        df_top_moins_cheres = con.execute(f"{query_base_tops} ORDER BY prix_m2_median ASC LIMIT 5").df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)

    # Nettoyage textuel
    if not df_top_cheres.empty:
        df_top_cheres['nom_commune'] = df_top_cheres['nom_commune'].astype(str).str.title()
    if not df_top_moins_cheres.empty:
        df_top_moins_cheres['nom_commune'] = df_top_moins_cheres['nom_commune'].astype(str).str.title()

    return {
        "nb_transactions": int(row[0] or 0),
        "nb_communes":     int(row[1] or 0),
        "prix_m2_median":  round(float(row[2]), 0) if row[2] else 0,
        "surface_mediane": round(float(row[3]), 0) if row[3] else 0,
        "top_cheres": df_top_cheres,
        "top_moins_cheres": df_top_moins_cheres
    }


def get_variation_prix(region=None) -> dict:
    """Variation du prix médian /m² entre 2024 et 2025."""
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        row = con.execute(f"""
            WITH par_annee AS (
                SELECT
                    YEAR(CAST(f.date_mutation AS DATE)) AS annee,
                    MEDIAN(f.prix_m2) AS prix_m2
                FROM fact_dvf f
                JOIN dim_adresses v ON f.id_adresse = v.id_adresse
                WHERE f.prix_m2 IS NOT NULL
                  AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
                  {dept_filter}
                GROUP BY annee
            )
            SELECT
                p2024.prix_m2 AS prix_2024,
                p2025.prix_m2 AS prix_2025,
                CASE WHEN p2024.prix_m2 > 0
                     THEN ROUND((p2025.prix_m2 - p2024.prix_m2) / p2024.prix_m2 * 100, 1)
                     ELSE NULL END AS variation
            FROM (SELECT prix_m2 FROM par_annee WHERE annee = 2024) p2024
            CROSS JOIN (SELECT prix_m2 FROM par_annee WHERE annee = 2025) p2025
        """).fetchone()
        con.close()
        if row is None:
            return {"variation": None}
        return {"variation": float(row[2]) if row[2] is not None else None}
    except Exception:
        con.close()
        return {"variation": None}


def get_top_communes_par_type(n: int = 12, region=None) -> pd.DataFrame:
    """Top N communes par volume de ventes, avec prix médian par type."""
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                v.nom_commune,
                COUNT(*) AS nb_transactions,
                ROUND(MEDIAN(f.prix_m2), 0) AS prix_tous,
                ROUND(MEDIAN(CASE WHEN f.type_local = 'Appartement' THEN f.prix_m2 END), 0) AS prix_appart,
                ROUND(MEDIAN(CASE WHEN f.type_local = 'Maison' THEN f.prix_m2 END), 0) AS prix_maison
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.prix_m2 IS NOT NULL
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              {dept_filter}
            GROUP BY v.nom_commune
            ORDER BY nb_transactions DESC
            LIMIT {n}
        """).df()
        con.close()
        return df
    except Exception:
        con.close()
        return pd.DataFrame()


def get_prix_median_par_commune(region=None, type_local=None, annee=None) -> pd.DataFrame:
    """
    Domain 7 : prix médian €/m² agrégé PAR code commune INSEE (clé du choroplèthe).

    Auparavant, l'agrégation se faisait par NOM de commune (v.nom_commune) avec une
    moyenne des lat/lon pour une carte de POINTS. On regroupe désormais par
    v.code_commune (la clé INSEE qui correspond aux polygones de dim_communes_geo)
    et on conserve un nom d'affichage via ANY_VALUE(v.nom_commune). Le centroïde
    (lat/lon moyens) est CONSERVÉ pour le repli sur la carte de points si les
    polygones sont absents.

    Filtres optionnels (Domain 7) :
      - type_local : 'Maison' ou 'Appartement' (None/'Tous' -> les deux),
      - annee      : année de transaction (None -> toutes les années ingérées),
    pour rendre le choroplèthe filtrable comme demandé dans le brief.

    Colonnes renvoyées : code_commune, nom_commune, prix_m2_median, volume_ventes,
    latitude, longitude.
    """
    dept_filter = _get_dept_filter(region, "f")

    # Filtre type de bien : par défaut Maison + Appartement (cohérent avec le reste).
    if type_local and type_local != "Tous":
        type_filter = " AND f.type_local = ? "
        type_params = [type_local]
    else:
        type_filter = " AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé') "
        type_params = []

    # Filtre année : la colonne 'annee' (INTEGER) existe sur fact_dvf (Domain 2).
    if annee:
        annee_filter = " AND f.annee = ? "
        annee_params = [int(annee)]
    else:
        annee_filter = ""
        annee_params = []

    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                v.code_commune,
                ANY_VALUE(v.nom_commune) AS nom_commune,
                MEDIAN(f.prix_m2) AS prix_m2_median,
                COUNT(f.id_mutation) AS volume_ventes,
                AVG(NULLIF(v.lat, 0)) AS latitude,
                AVG(NULLIF(v.lon, 0)) AS longitude
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.valeur_fonciere > 0
              AND f.surface_reelle_bati > 0
              AND v.code_commune IS NOT NULL
              {type_filter}
              {annee_filter}
              {dept_filter}
            GROUP BY v.code_commune
            HAVING prix_m2_median IS NOT NULL
               AND latitude IS NOT NULL
               AND longitude IS NOT NULL
        """, type_params + annee_params).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)

    if not df.empty:
        df['nom_commune'] = df['nom_commune'].astype(str).str.title()

    return df


def get_annees_disponibles(region=None) -> list:
    """
    Domain 7 : liste triée des années de transaction présentes dans fact_dvf
    (pour alimenter le sélecteur d'année du choroplèthe). Tolère une base absente.
    """
    dept_filter = _get_dept_filter(region, "f")
    try:
        con = _con()
        try:
            rows = con.execute(f"""
                SELECT DISTINCT f.annee
                FROM fact_dvf f
                WHERE f.annee IS NOT NULL
                  {dept_filter}
                ORDER BY f.annee
            """).fetchall()
        finally:
            con.close()  # ferme même si execute lève (pas de fuite de connexion)
        return [int(r[0]) for r in rows]
    except Exception:
        return []


def get_communes_geojson(region=None) -> dict:
    """
    Domain 7 : renvoie les polygones communaux sous forme de dict GeoJSON
    (FeatureCollection) pour px.choropleth_map.

    Lit la table dim_communes_geo (colonne geom_geojson = géométrie GeoJSON brute,
    clé 'code' = code_commune INSEE pour le featureidkey 'properties.code').
    Si la table est absente/vide (polygones non ingérés), renvoie un dict VIDE
    (FeatureCollection sans features) afin que le front bascule sur la carte de points.

    Le filtre régional limite le GeoJSON aux départements de la région pour alléger
    le rendu (on filtre sur les 2 premiers caractères du code commune INSEE).
    """
    import json

    if not _table_existe("dim_communes_geo"):
        return {"type": "FeatureCollection", "features": []}

    # Filtre départemental appliqué au préfixe du code commune INSEE (2 premiers car.).
    # Paramétrage réel : on génère autant de placeholders ? que de départements et on
    # passe les valeurs via une liste de params bornés (au lieu d'une interpolation
    # f-string). cf. revue de code [LOW] « Interpolation f-string des départements ».
    dept_clause = ""
    dept_params: list = []
    if region and region != 'Toutes les régions':
        depts = REGIONS_MAPPING.get(region, [])
        if depts:
            placeholders = ", ".join(["?"] * len(depts))
            dept_clause = f" WHERE SUBSTR(code_commune, 1, 2) IN ({placeholders}) "
            dept_params = list(depts)

    try:
        con = _con()
        try:
            rows = con.execute(f"""
                SELECT code_commune, nom_commune, geom_geojson
                FROM dim_communes_geo
                {dept_clause}
            """, dept_params).fetchall()
        finally:
            con.close()  # ferme même si execute lève (pas de fuite de connexion)
    except Exception:
        return {"type": "FeatureCollection", "features": []}

    features = []
    for code, nom, geom_str in rows:
        if not geom_str:
            continue
        try:
            geometry = json.loads(geom_str)
        except (json.JSONDecodeError, TypeError):
            continue
        features.append({
            "type": "Feature",
            # 'code' = clé INSEE attendue par featureidkey="properties.code".
            "properties": {"code": code, "nom": nom},
            "geometry": geometry,
        })

    return {"type": "FeatureCollection", "features": features}

# --- 4. FONCTIONS AVANCÉES (POUR FUTURS GRAPHIQUES) ---

def get_prix_par_mois(region=None) -> pd.DataFrame:
    """Évolution mensuelle des prix pour des graphiques temporels (Line chart)."""
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                STRFTIME(CAST(date_mutation AS DATE), '%Y-%m') AS mois,
                ROUND(MEDIAN(valeur_fonciere / NULLIF(surface_reelle_bati, 0)), 0) AS prix_m2_median,
                COUNT(*) AS nb_transactions
            FROM fact_dvf f
            WHERE f.surface_reelle_bati > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              {dept_filter}
            GROUP BY mois
            ORDER BY mois
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df

def get_prix_vs_proximite(region=None, limit: int = 2000) -> pd.DataFrame:
    """Échantillon pour scatter plots (prix vs distance gare/école)."""
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                ROUND(f.prix_m2, 0) AS prix_m2,
                ROUND(v.distance_gare_metres  / 1000.0, 3) AS dist_gare_km,
                ROUND(v.distance_ecole_metres / 1000.0, 3) AS dist_ecole_km,
                f.type_local,
                f.surface_reelle_bati
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.surface_reelle_bati > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              AND v.distance_gare_metres  IS NOT NULL
              AND v.distance_ecole_metres IS NOT NULL
              AND f.prix_m2 BETWEEN 500 AND 30000
              {dept_filter}
            USING SAMPLE {limit}
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df

# --- 5. FONCTIONS DPE (Domain 4 — prime énergétique) ---

def get_prix_par_dpe(region=None) -> pd.DataFrame:
    """
    Domain 4 : prix médian €/m² et nombre de ventes regroupés par étiquette DPE (A-G)
    et par type de bien (Maison/Appartement).

    On joint fact_dvf -> dim_adresses (qui porte désormais etiquette_dpe issue du
    rapprochement spatial DPE) et on ne garde que les ventes dont l'adresse a une
    étiquette DPE valide A-G. Utilise le filtre départemental partagé (_get_dept_filter).
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                v.etiquette_dpe,
                f.type_local,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) AS nb_ventes
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.surface_reelle_bati > 0
              AND f.valeur_fonciere > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              AND v.etiquette_dpe IN ('A', 'B', 'C', 'D', 'E', 'F', 'G')
              {dept_filter}
            GROUP BY v.etiquette_dpe, f.type_local
            ORDER BY v.etiquette_dpe, f.type_local
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df


def get_dpe_premium_temporel(region=None) -> pd.DataFrame:
    """
    Domain 4 : prix médian €/m² par étiquette DPE × période (mois) pour tester si la
    sensibilité du marché à la performance énergétique augmente dans le temps
    (la "prime énergétique" se creuse-t-elle entre A/B et F/G au fil des mois ?).

    Renvoie une ligne par (mois, étiquette) avec prix médian et nb de ventes.
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                STRFTIME(CAST(f.date_mutation AS DATE), '%Y-%m') AS mois,
                v.etiquette_dpe,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) AS nb_ventes
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.surface_reelle_bati > 0
              AND f.valeur_fonciere > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              AND v.etiquette_dpe IN ('A', 'B', 'C', 'D', 'E', 'F', 'G')
              {dept_filter}
            GROUP BY mois, v.etiquette_dpe
            ORDER BY mois, v.etiquette_dpe
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df


# --- 5bis. DOMAIN 5 : BRUIT AÉROPORTUAIRE (PEB) ---

# NOTE (Domain 5) : la couverture PEB est volontairement très partielle (seuls quelques
# aéroports disposent d'un Plan d'Exposition au Bruit ingéré). La plupart des régions
# n'ont donc AUCUNE vente "en zone". Les fonctions ci-dessous renvoient systématiquement
# une ligne "Hors zone" (NULL -> 'Hors zone') et un compteur nb_ventes ; c'est au front
# d'appliquer un seuil minimal et d'afficher un message si la couverture est insuffisante.

def get_noise_discount_by_zone(region=None) -> pd.DataFrame:
    """
    Domain 5 : prix médian €/m² et nombre de ventes regroupés par zone de bruit
    aéroportuaire PEB (zone_peb : A/B/C/D, NULL -> 'Hors zone') et par type de bien
    (Maison/Appartement).

    Permet de mesurer la décote RÉELLE liée au bruit aéroportuaire (remplace les
    multiplicateurs simulés 0.80/0.85/0.92/0.98). Utilise le filtre départemental
    partagé (_get_dept_filter).
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                COALESCE(v.zone_peb, 'Hors zone') AS zone_peb,
                f.type_local,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) AS nb_ventes
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.surface_reelle_bati > 0
              AND f.valeur_fonciere > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              {dept_filter}
            GROUP BY COALESCE(v.zone_peb, 'Hors zone'), f.type_local
            ORDER BY zone_peb, f.type_local
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df


def get_noise_discount_by_airport(region=None) -> pd.DataFrame:
    """
    Domain 5 : prix médian €/m² et nombre de ventes regroupés par aéroport (code_oaci)
    et par zone PEB (zone_peb). On ne garde que les ventes effectivement situées dans
    une zone PEB (code_oaci NON NULL), puisqu'une ventilation "par aéroport" n'a de sens
    que pour les biens réellement exposés.

    Utilise le filtre départemental partagé (_get_dept_filter).
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                v.code_oaci,
                COALESCE(v.zone_peb, 'Hors zone') AS zone_peb,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) AS nb_ventes
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.surface_reelle_bati > 0
              AND f.valeur_fonciere > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              AND v.code_oaci IS NOT NULL
              {dept_filter}
            GROUP BY v.code_oaci, COALESCE(v.zone_peb, 'Hors zone')
            ORDER BY v.code_oaci, zone_peb
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df


# --- 5ter. DOMAIN 6 : DONNÉES SOCIO-ÉCONOMIQUES INSEE & OPPORTUNITY FINDER ---

def _table_existe(nom_table: str) -> bool:
    """Indique si une table existe dans la base (tolère son absence sans planter)."""
    try:
        con = _con()
        try:
            tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        finally:
            con.close()  # ferme même si execute lève (pas de fuite de connexion)
        return nom_table in tables
    except Exception:
        return False


def get_socio_eco_par_commune(region=None) -> pd.DataFrame:
    """
    Domain 6 : joint fact_dvf -> dim_adresses -> dim_commune sur code_commune et expose,
    par commune, le prix médian €/m² (DVF) AUX CÔTÉS du revenu médian et de la population
    (INSEE/FiLoSoFi).

    Tolère l'absence de dim_commune : si la table n'existe pas (fichiers INSEE non
    fournis), revenu_median/population sont renvoyés à NULL (le reste fonctionne).
    Filtré aux communes avec au moins 5 ventes pour une médiane fiable.
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    # On rend la jointure dim_commune optionnelle selon sa présence dans la base.
    if _table_existe("dim_commune"):
        join_commune = "LEFT JOIN dim_commune c ON v.code_commune = c.code_commune"
        cols_commune = "ANY_VALUE(c.revenu_median) AS revenu_median, ANY_VALUE(c.population) AS population"
    else:
        join_commune = ""
        cols_commune = "CAST(NULL AS DOUBLE) AS revenu_median, CAST(NULL AS DOUBLE) AS population"

    try:
        df = con.execute(f"""
            SELECT
                v.code_commune,
                ANY_VALUE(v.nom_commune) AS nom_commune,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) AS nb_ventes,
                {cols_commune}
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            {join_commune}
            WHERE f.surface_reelle_bati > 0
              AND f.valeur_fonciere > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              AND v.code_commune IS NOT NULL
              {dept_filter}
            GROUP BY v.code_commune
            HAVING nb_ventes >= 5
            ORDER BY prix_m2_median DESC
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df


def get_population_temporelle(region=None) -> pd.DataFrame:
    """
    Domain TEMPS : évolution de la population communale par millésime, agrégée au niveau
    de la sélection (région -> départements). S'appuie sur la dimension temporelle
    dim_commune_temporel (grain code_commune × annee).

    Renvoie [annee, population_totale, nb_communes, revenu_median_moyen] trié par année.
    Tolère l'absence de la table (renvoie un DataFrame vide).
    """
    if not _table_existe("dim_commune_temporel"):
        return pd.DataFrame(columns=["annee", "population_totale", "nb_communes", "revenu_median_moyen"])
    # Filtre départemental appliqué au préfixe (2 car.) du code commune INSEE.
    where = ""
    if region and region != "Toutes les régions":
        depts = REGIONS_MAPPING.get(region, [])
        if depts:
            placeholders = ", ".join(f"'{d}'" for d in depts)
            where = f"WHERE SUBSTR(code_commune, 1, 2) IN ({placeholders})"
    con = _con()
    try:
        df = con.execute(f"""
            SELECT
                annee,
                SUM(population)                 AS population_totale,
                COUNT(DISTINCT code_commune)    AS nb_communes,
                ROUND(AVG(revenu_median), 0)    AS revenu_median_moyen
            FROM dim_commune_temporel
            {where}
            GROUP BY annee
            ORDER BY annee
        """).df()
    finally:
        con.close()
    return df


def _minmax(serie: pd.Series) -> pd.Series:
    """Normalisation min-max sur [0, 1] ; renvoie 0.5 partout si la série est constante/vide."""
    s = pd.to_numeric(serie, errors="coerce")
    mini, maxi = s.min(), s.max()
    if pd.isna(mini) or pd.isna(maxi) or maxi == mini:
        return pd.Series(0.5, index=serie.index)
    return (s - mini) / (maxi - mini)


def get_opportunity_finder(commune=None) -> pd.DataFrame:
    """
    Domain 6 : score composite "opportunité d'achat" par commune.

    On combine jusqu'à QUATRE sous-scores, chacun normalisé min-max sur [0, 1]
    (1 = favorable à l'acheteur). Les pondérations NOMINALES traduisent un profil
    "acheteur cherchant de la valeur" :

      - score_prix    (poids nominal 0.35) : prix €/m² SOUS la moyenne (inverse du prix
                                       normalisé). Une commune moins chère est plus opportune.
      - score_revenu  (poids nominal 0.25) : revenu médian AU-DESSUS de la moyenne (revenu
                                       normalisé). Pouvoir d'achat local élevé = marché plus solide.
      - score_energie (poids nominal 0.25) : part de logements bien notés au DPE (étiquettes
                                       A/B/C), via le rapprochement DPE de dim_adresses. Bon parc
                                       = moins de travaux énergétiques à prévoir.
      - score_bruit   (poids nominal 0.15) : faible exposition au bruit aéroportuaire = inverse
                                       de la part de ventes en zone PEB (A/B/C/D). Moins = mieux.

    CORRECTION DU BIAIS (revue de code [MED]) — PONDÉRATION ADAPTATIVE :
    Auparavant, lorsque le revenu (dim_commune absente), le DPE ou le PEB étaient absents
    ou peu couverts, le sous-score correspondant retombait à 0.5 CONSTANT pour toutes les
    communes (cf. _minmax sur série dégénérée). Comme une constante ajoute le même décalage
    à toutes les lignes, elle n'apporte AUCUN signal de classement : le score "4 facteurs"
    se réduisait alors de fait au seul prix. On corrige ainsi :

      1) un facteur est jugé DÉGÉNÉRÉ s'il n'a aucune variance réelle (toutes ses valeurs
         sources sont NULL/constantes -> _minmax renvoie 0.5 partout) ;
      2) le POIDS d'un facteur dégénéré est MIS À 0, et l'ensemble des poids restants est
         RE-NORMALISÉ pour sommer à 1 (la pondération porte donc seulement sur les facteurs
         qui portent vraiment du signal) ;
      3) la colonne du facteur dégénéré reste PRÉSENTE mais vaut NULL (NaN) pour signaler au
         front qu'elle n'a pas contribué — le SET de colonnes renvoyé est inchangé.

    Filtré aux communes avec nb_ventes >= 10 (médianes/parts fiables). Renvoie un
    DataFrame trié par score_opportunite décroissant, AVEC les sous-scores détaillés.
    """
    commune_filter = (
        f" AND v.nom_commune = '{commune.replace(chr(39), chr(39)*2)}' "
        if commune and commune != "Toutes les communes"
        else ""
    )
    con = _con()

    if _table_existe("dim_commune"):
        join_commune = "LEFT JOIN dim_commune c ON v.code_commune = c.code_commune"
        col_revenu = "ANY_VALUE(c.revenu_median) AS revenu_median"
    else:
        join_commune = ""
        col_revenu = "CAST(NULL AS DOUBLE) AS revenu_median"

    try:
        df = con.execute(f"""
            SELECT
                v.code_commune,
                ANY_VALUE(v.nom_commune) AS nom_commune,
                CAST(MEDIAN(f.prix_m2) AS INTEGER) AS prix_m2_median,
                COUNT(f.id_mutation) AS nb_ventes,
                {col_revenu},
                -- Part de logements bien notés (DPE A/B/C) parmi ceux dotés d'une étiquette.
                AVG(CASE WHEN v.etiquette_dpe IN ('A','B','C') THEN 1.0
                         WHEN v.etiquette_dpe IN ('D','E','F','G') THEN 0.0
                         ELSE NULL END) AS part_dpe_bon,
                -- Part de ventes situées en zone de bruit aéroportuaire PEB (exposition).
                -- NULL si AUCUNE vente n'a d'info PEB (zone_peb toujours NULL) -> facteur absent.
                AVG(CASE WHEN v.zone_peb IS NULL THEN NULL
                         WHEN v.zone_peb IN ('A','B','C','D') THEN 1.0
                         ELSE 0.0 END) AS part_bruit
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            {join_commune}
            WHERE f.surface_reelle_bati > 0
              AND f.valeur_fonciere > 0
              AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
              AND v.code_commune IS NOT NULL
              {commune_filter}
            GROUP BY v.code_commune
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)

    if df.empty:
        # On renvoie un DataFrame avec les bonnes colonnes pour un front robuste.
        return pd.DataFrame(columns=[
            "code_commune", "nom_commune", "prix_m2_median", "nb_ventes",
            "revenu_median", "part_dpe_bon", "part_bruit",
            "score_prix", "score_revenu", "score_energie", "score_bruit",
            "score_opportunite"
        ])

    # --- Sous-scores normalisés (1 = favorable acheteur) ---
    # _a_du_signal : True si la série source a une variance réelle (>=2 valeurs non-NULL
    # distinctes). Sinon le facteur est "dégénéré" : il ne classe rien et son poids = 0.
    def _a_du_signal(serie: pd.Series) -> bool:
        s = pd.to_numeric(serie, errors="coerce").dropna()
        return s.nunique() >= 2

    signal_prix = _a_du_signal(df["prix_m2_median"])
    signal_revenu = _a_du_signal(df["revenu_median"])
    signal_energie = _a_du_signal(df["part_dpe_bon"])
    signal_bruit = _a_du_signal(df["part_bruit"])

    # Score = NULL (NaN) pour un facteur dégénéré (colonne conservée mais non contributive).
    nan_col = pd.Series(np.nan, index=df.index, dtype="float64")
    df["score_prix"] = (1 - _minmax(df["prix_m2_median"])) if signal_prix else nan_col.copy()
    df["score_revenu"] = _minmax(df["revenu_median"]) if signal_revenu else nan_col.copy()
    df["score_energie"] = _minmax(df["part_dpe_bon"]) if signal_energie else nan_col.copy()
    # Moins de bruit = mieux (inverse de la part exposée).
    df["score_bruit"] = (1 - _minmax(df["part_bruit"])) if signal_bruit else nan_col.copy()

    # --- Pondération adaptative : on annule le poids des facteurs dégénérés puis on
    #     re-normalise les poids restants pour qu'ils somment à 1. ---
    POIDS_NOMINAUX = {"score_prix": 0.35, "score_revenu": 0.25, "score_energie": 0.25, "score_bruit": 0.15}
    signaux = {
        "score_prix": signal_prix,
        "score_revenu": signal_revenu,
        "score_energie": signal_energie,
        "score_bruit": signal_bruit,
    }
    poids_actifs = {k: w for k, w in POIDS_NOMINAUX.items() if signaux[k]}
    total = sum(poids_actifs.values())

    if total > 0:
        poids = {k: w / total for k, w in poids_actifs.items()}  # re-normalisation à somme 1
        df["score_opportunite"] = sum(df[k] * p for k, p in poids.items())
    else:
        # Cas extrême : aucun facteur n'a de signal (ne devrait pas arriver, le prix varie
        # quasi toujours). On renvoie un score neutre plutôt que de planter.
        df["score_opportunite"] = 0.5

    df["nom_commune"] = df["nom_commune"].astype(str).str.title()
    return df.sort_values("score_opportunite", ascending=False).reset_index(drop=True)


def get_price_growth_by_commune(region=None) -> pd.DataFrame:
    """
    Domain 6 (angle gentrification) : croissance annuelle (YoY) du prix médian €/m²
    par commune, jointe au revenu médian INSEE.

    On calcule le prix médian €/m² par commune ET par année (colonne 'annee' de
    fact_dvf), puis le taux de croissance entre la PREMIÈRE et la DERNIÈRE année
    disponibles : (prix_fin - prix_debut) / prix_debut. Croisé avec le revenu médian,
    cela permet un nuage "revenu vs croissance" (les communes à revenu élevé sont-elles
    celles où les prix montent le plus ?).

    Nécessite au moins 2 années dans fact_dvf (sinon renvoie un DataFrame vide).
    Tolère l'absence de dim_commune (revenu_median -> NULL).
    """
    dept_filter = _get_dept_filter(region, "f")
    con = _con()

    if _table_existe("dim_commune"):
        join_commune = "LEFT JOIN dim_commune c ON p.code_commune = c.code_commune"
        col_revenu = "c.revenu_median"
    else:
        join_commune = ""
        col_revenu = "CAST(NULL AS DOUBLE) AS revenu_median"

    try:
        df = con.execute(f"""
            WITH prix_annee AS (
                -- Prix médian €/m² par commune × année (au moins 5 ventes par couple).
                SELECT
                    v.code_commune,
                    ANY_VALUE(v.nom_commune) AS nom_commune,
                    f.annee,
                    MEDIAN(f.prix_m2) AS prix_m2_median,
                    COUNT(f.id_mutation) AS nb_ventes
                FROM fact_dvf f
                JOIN dim_adresses v ON f.id_adresse = v.id_adresse
                WHERE f.surface_reelle_bati > 0
                  AND f.valeur_fonciere > 0
                  AND f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
                  AND v.code_commune IS NOT NULL
                  AND f.annee IS NOT NULL
                  {dept_filter}
                GROUP BY v.code_commune, f.annee
                HAVING nb_ventes >= 5
            ),
            bornes AS (
                -- Première et dernière année disponibles par commune.
                SELECT
                    code_commune,
                    ANY_VALUE(nom_commune) AS nom_commune,
                    MIN(annee) AS annee_debut,
                    MAX(annee) AS annee_fin
                FROM prix_annee
                GROUP BY code_commune
                HAVING annee_fin > annee_debut
            ),
            p AS (
                SELECT
                    b.code_commune,
                    b.nom_commune,
                    b.annee_debut,
                    b.annee_fin,
                    pd.prix_m2_median AS prix_debut,
                    pf.prix_m2_median AS prix_fin
                FROM bornes b
                JOIN prix_annee pd ON pd.code_commune = b.code_commune AND pd.annee = b.annee_debut
                JOIN prix_annee pf ON pf.code_commune = b.code_commune AND pf.annee = b.annee_fin
            )
            SELECT
                p.code_commune,
                p.nom_commune,
                p.annee_debut,
                p.annee_fin,
                CAST(p.prix_debut AS INTEGER) AS prix_m2_debut,
                CAST(p.prix_fin AS INTEGER)   AS prix_m2_fin,
                -- Croissance totale entre première et dernière année, en %.
                ROUND(100.0 * (p.prix_fin - p.prix_debut) / NULLIF(p.prix_debut, 0), 1) AS croissance_pct,
                {col_revenu}
            FROM p
            {join_commune}
            WHERE p.prix_debut > 0
            ORDER BY croissance_pct DESC
        """).df()
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)

    if not df.empty:
        df["nom_commune"] = df["nom_commune"].astype(str).str.title()
    return df


# --- 6. MOTEUR DE RECHERCHE ---

def search_properties(
    commune: str = "",
    type_local: str = "Tous",
    nb_pieces_min: int = 1,
    surface_min: float = 10.0,
    budget_min: float = 50_000,
    budget_max: float = 1_500_000,
    prix_m2_max: float = 20_000,
    dist_gare_max: float = None,
    dist_ecole_max: float = None
) -> pd.DataFrame:
    """Moteur de recherche multicritères avec calcul du prix moyen de la commune."""
    conditions = [
        "f.surface_reelle_bati >= ?",
        "f.valeur_fonciere BETWEEN ? AND ?",
        "f.prix_m2 <= ?",
        "f.nombre_pieces_principales >= ?",
        "f.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')",
    ]
    params: list = [surface_min, budget_min, budget_max, prix_m2_max, nb_pieces_min]

    if commune.strip():
        conditions.append("LOWER(v.nom_commune) LIKE ?")
        params.append(f"%{commune.strip().lower()}%")

    if type_local and type_local != "Tous":
        conditions.append("f.type_local = ?")
        params.append(type_local)

    if dist_gare_max is not None:
        conditions.append("v.distance_gare_metres <= ?")
        params.append(dist_gare_max * 1000)

    if dist_ecole_max is not None:
        conditions.append("v.distance_ecole_metres <= ?")
        params.append(dist_ecole_max * 1000)

    where = " AND ".join(conditions)
    con = _con()
    try:
        df = _search_properties_query(con, where, params)
    finally:
        con.close()  # ferme même en cas d'exception (pas de fuite de connexion)
    return df


def _search_properties_query(con, where: str, params: list) -> pd.DataFrame:
    """Exécute la requête comparables DPE-aware du moteur de recherche.

    Extrait dans une fonction interne pour garder search_properties dans un bloc
    try/finally lisible (la connexion est fermée par l'appelant même si execute lève).
    """
    # Domain 4 : estimateur "bonne affaire" renforcé par comparables DPE-aware.
    # On garde la médiane communale globale (prix_m2_commune) comme repère de secours,
    # MAIS on ajoute une référence plus fine prix_m2_comparable : médiane des ventes
    # RÉCENTES de la MÊME commune, du MÊME type de bien et de la MÊME étiquette DPE
    # ou d'une étiquette ADJACENTE (±1 cran, ex. pour D on compare à C/D/E). Cela évite
    # de juger un bien classé G face à des biens A/B de la même commune.
    # NOTE : "récentes" = on ne borne pas l'année ici (fact_dvf est déjà filtré par la
    #        sélection de l'ETL) ; le grain temporel pourra être ajouté si besoin.
    df = con.execute(f"""
        WITH ventes_valides AS (
            -- Base commune : ventes propres servant à calculer toutes les médianes.
            SELECT
                v_sub.nom_commune,
                f_sub.type_local,
                v_sub.etiquette_dpe,
                f_sub.valeur_fonciere / NULLIF(f_sub.surface_reelle_bati, 0) AS prix_m2
            FROM fact_dvf f_sub
            JOIN dim_adresses v_sub ON f_sub.id_adresse = v_sub.id_adresse
            WHERE f_sub.surface_reelle_bati > 0 AND f_sub.valeur_fonciere > 0
              AND f_sub.type_local IN ('Maison', 'Appartement', 'Local industriel. commercial ou assimilé')
        ),
        commune_medians AS (
            -- Repère de secours : médiane communale tous types / toutes étiquettes.
            SELECT nom_commune, MEDIAN(prix_m2) AS prix_m2_commune
            FROM ventes_valides
            GROUP BY nom_commune
        ),
        comparables AS (
            -- Référence fine : médiane par commune × type × étiquette DPE.
            SELECT nom_commune, type_local, etiquette_dpe,
                   MEDIAN(prix_m2) AS prix_m2_etiquette,
                   COUNT(*) AS nb_comparables
            FROM ventes_valides
            WHERE etiquette_dpe IN ('A','B','C','D','E','F','G')
            GROUP BY nom_commune, type_local, etiquette_dpe
        )
        SELECT
            v.nom_commune,
            v.nom_voie,
            v.code_postal,
            f.date_mutation,
            f.valeur_fonciere,
            f.surface_reelle_bati,
            f.nombre_pieces_principales,
            f.type_local,
            v.etiquette_dpe,
            -- Domain 5 : zone de bruit aéroportuaire (PEB) RÉELLE issue du rapprochement
            -- spatial (NULL = hors zone PEB) + code OACI de l'aéroport concerné. Remplace
            -- l'ancienne simulation np.random.choice côté front.
            v.zone_peb,
            v.code_oaci,
            ROUND(f.prix_m2, 0) AS prix_m2,
            ROUND(cm.prix_m2_commune, 0) AS prix_m2_commune,
            -- Comparable DPE-aware : médiane des étiquettes voisines (±1 cran) dans la
            -- commune, pondérée par le nb de comparables. Repli sur la médiane communale.
            ROUND(COALESCE(cmp.prix_m2_comparable, cm.prix_m2_commune), 0) AS prix_m2_comparable,
            COALESCE(cmp.nb_comparables, 0) AS nb_comparables,
            v.nom_gare_proche,
            ROUND(v.distance_gare_metres  / 1000.0, 2) AS dist_gare_km,
            v.nom_ecole_proche,
            ROUND(v.distance_ecole_metres / 1000.0, 2) AS dist_ecole_km,
            v.lat,
            v.lon
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        LEFT JOIN commune_medians cm ON v.nom_commune = cm.nom_commune
        -- Comparables : même commune, même type, étiquette identique OU adjacente (±1).
        LEFT JOIN LATERAL (
            SELECT
                SUM(c.prix_m2_etiquette * c.nb_comparables) / NULLIF(SUM(c.nb_comparables), 0) AS prix_m2_comparable,
                SUM(c.nb_comparables) AS nb_comparables
            FROM comparables c
            WHERE c.nom_commune = v.nom_commune
              AND c.type_local = f.type_local
              AND v.etiquette_dpe IN ('A','B','C','D','E','F','G')
              AND ABS(
                    (ASCII(c.etiquette_dpe) - ASCII('A'))
                  - (ASCII(v.etiquette_dpe) - ASCII('A'))
                  ) <= 1
        ) cmp ON TRUE
        WHERE {where}
        ORDER BY f.date_mutation DESC
        LIMIT 200
    """, params).df()
    return df