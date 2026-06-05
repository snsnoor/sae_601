"""
back.py — Requêtes DuckDB pour le dashboard.
"""

import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = 'info_appart_2.duckdb'

# --- 1. MAPPING ET FILTRES ---

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
    "Provence-Alpes-Côte d'Azur": ['04', '05', '06', '13', '83', '84']
}

def get_regions():
    return list(REGIONS_MAPPING.keys())

def _get_dept_filter(region, alias="f"):
    if region and region != 'Toutes les régions':
        depts = REGIONS_MAPPING.get(region, [])
        depts_str = ", ".join([f"'{d}'" for d in depts])
        return f" AND {alias}.code_departement IN ({depts_str}) "
    return ""

# --- 2. CONNEXION ---

def _con():
    return duckdb.connect(str(DB_PATH), read_only=True)

def db_ready() -> bool:
    try:
        con = _con()
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return "fact_dvf" in tables
    except Exception:
        return False

# --- 3. LISTES ---

def get_communes_list() -> list:
    con = _con()
    rows = con.execute("""
        SELECT DISTINCT nom_commune
        FROM dim_adresses
        WHERE nom_commune IS NOT NULL AND nom_commune != ''
        ORDER BY nom_commune
    """).fetchall()
    con.close()
    return [r[0] for r in rows]

def get_types_locaux() -> list:
    con = _con()
    rows = con.execute("""
        SELECT DISTINCT type_local
        FROM fact_dvf
        WHERE type_local IS NOT NULL
        ORDER BY type_local
    """).fetchall()
    con.close()
    return [r[0] for r in rows]

# --- 4. VUE GLOBALE ---

def get_donnees_globales():
    return "Voici un aperçu de l'état du marché immobilier français."

def get_modele_estimation():
    return "L'algorithme d'estimation et son formulaire arriveront ici."

def get_kpis(region=None) -> dict:
    dept_filter = _get_dept_filter(region, "f")
    con = _con()

    row = con.execute(f"""
        SELECT
            COUNT(*)                                                      AS nb_transactions,
            COUNT(DISTINCT v.nom_commune)                                 AS nb_communes,
            MEDIAN(f.valeur_fonciere / NULLIF(f.surface_terrain, 0))      AS prix_m2_median,
            MEDIAN(f.surface_terrain)                                     AS surface_mediane
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.valeur_fonciere > 0
          AND f.surface_terrain > 0
          AND f.type_local IN ('Maison', 'Appartement')
          {dept_filter}
    """).fetchone()

    query_base_tops = f"""
        SELECT
            v.nom_commune,
            CAST(MEDIAN(f.valeur_fonciere / NULLIF(f.surface_terrain, 0)) AS INTEGER) AS prix_m2_median,
            COUNT(f.id_mutation) AS nb_ventes
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.valeur_fonciere > 0
          AND f.surface_terrain > 0
          AND f.type_local IN ('Maison', 'Appartement')
          {dept_filter}
        GROUP BY v.nom_commune
        HAVING nb_ventes >= 10
    """

    df_top_cheres       = con.execute(f"{query_base_tops} ORDER BY prix_m2_median DESC LIMIT 5").df()
    df_top_moins_cheres = con.execute(f"{query_base_tops} ORDER BY prix_m2_median ASC  LIMIT 5").df()
    con.close()

    if not df_top_cheres.empty:
        df_top_cheres['nom_commune'] = df_top_cheres['nom_commune'].astype(str).str.title()
    if not df_top_moins_cheres.empty:
        df_top_moins_cheres['nom_commune'] = df_top_moins_cheres['nom_commune'].astype(str).str.title()

    return {
        "nb_transactions":  int(row[0] or 0),
        "nb_communes":      int(row[1] or 0),
        "prix_m2_median":   round(float(row[2]), 0) if row[2] else 0,
        "surface_mediane":  round(float(row[3]), 0) if row[3] else 0,
        "top_cheres":       df_top_cheres,
        "top_moins_cheres": df_top_moins_cheres,
    }

def get_variation_prix(region=None) -> dict:
    """Variation du prix médian /m² entre 2024 et 2025."""
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    row = con.execute(f"""
        WITH par_annee AS (
            SELECT
                YEAR(CAST(f.date_mutation AS DATE)) AS annee,
                MEDIAN(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0)) AS prix_m2
            FROM fact_dvf f
            JOIN dim_adresses v ON f.id_adresse = v.id_adresse
            WHERE f.surface_reelle_bati > 0
              AND f.type_local IN ('Maison', 'Appartement')
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

def get_top_communes_par_type(n: int = 10, region=None) -> pd.DataFrame:
    """Top N communes par volume de ventes, avec prix médian par type."""
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    df = con.execute(f"""
        SELECT
            v.nom_commune,
            v.code_postal,
            COUNT(*) AS nb_transactions,
            ROUND(MEDIAN(CASE WHEN f.type_local IN ('Maison','Appartement')
                              THEN f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0) END), 0) AS prix_tous,
            ROUND(MEDIAN(CASE WHEN f.type_local = 'Appartement'
                              THEN f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0) END), 0) AS prix_appart,
            ROUND(MEDIAN(CASE WHEN f.type_local = 'Maison'
                              THEN f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0) END), 0) AS prix_maison
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.surface_reelle_bati > 0
          AND f.type_local IN ('Maison', 'Appartement')
          {dept_filter}
        GROUP BY v.nom_commune, v.code_postal
        ORDER BY nb_transactions DESC
        LIMIT {n}
    """).df()
    con.close()
    return df

def get_prix_median_par_commune(region=None) -> pd.DataFrame:
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    df = con.execute(f"""
        SELECT
            v.nom_commune,
            MEDIAN(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0)) AS prix_m2_median,
            AVG(NULLIF(v.lat, 0)) AS latitude,
            AVG(NULLIF(v.lon, 0)) AS longitude,
            COUNT(f.id_mutation) AS volume_ventes
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.valeur_fonciere > 0
          AND f.surface_reelle_bati > 0
          AND f.type_local IN ('Maison', 'Appartement')
          {dept_filter}
        GROUP BY v.nom_commune
        HAVING prix_m2_median IS NOT NULL
           AND latitude IS NOT NULL
    """).df()
    con.close()
    if not df.empty:
        df['nom_commune'] = df['nom_commune'].astype(str).str.title()
    return df

def get_prix_par_mois(region=None, type_local: str = "") -> pd.DataFrame:
    """Évolution mensuelle des prix, avec filtre optionnel par type de bien."""
    dept_filter = _get_dept_filter(region, "f")
    params = []
    type_filter = ""
    if type_local.strip() and type_local not in ("Tous", ""):
        type_filter = "AND f.type_local = ?"
        params.append(type_local.strip())
    con = _con()
    df = con.execute(f"""
        SELECT
            STRFTIME(CAST(date_mutation AS DATE), '%Y-%m') AS mois,
            ROUND(MEDIAN(valeur_fonciere / NULLIF(surface_reelle_bati, 0)), 0) AS prix_m2_median,
            COUNT(*) AS nb_transactions
        FROM fact_dvf f
        WHERE f.surface_reelle_bati > 0
          AND f.type_local IN ('Maison', 'Appartement')
          {dept_filter}
          {type_filter}
        GROUP BY mois
        ORDER BY mois
    """, params).df()
    con.close()
    return df

def get_prix_vs_proximite(region=None, limit: int = 2000) -> pd.DataFrame:
    dept_filter = _get_dept_filter(region, "f")
    con = _con()
    df = con.execute(f"""
        SELECT
            ROUND(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0), 0) AS prix_m2,
            ROUND(v.distance_gare_metres  / 1000.0, 3) AS dist_gare_km,
            ROUND(v.distance_ecole_metres / 1000.0, 3) AS dist_ecole_km,
            f.type_local,
            f.surface_reelle_bati
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.surface_reelle_bati > 0
          AND f.type_local IN ('Maison', 'Appartement')
          AND v.distance_gare_metres  IS NOT NULL
          AND v.distance_ecole_metres IS NOT NULL
          AND f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0) BETWEEN 500 AND 30000
          {dept_filter}
        USING SAMPLE {limit}
    """).df()
    con.close()
    return df

def search_properties(
    commune: str = "",
    type_local: str = "Tous",
    nb_pieces_min: int = 1,
    surface_min: float = 10.0,
    budget_min: float = 50_000,
    budget_max: float = 1_500_000,
    prix_m2_max: float = 20_000,
    dist_gare_max: float = None,
    dist_ecole_max: float = None,
) -> pd.DataFrame:
    """Moteur de recherche multicritères avec prix de référence communal et infos aéroport."""
    conditions = [
        "f.surface_reelle_bati >= ?",
        "f.valeur_fonciere BETWEEN ? AND ?",
        "f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0) <= ?",
        "f.nombre_pieces_principales >= ?",
        "f.type_local IN ('Maison', 'Appartement')",
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
    df = con.execute(f"""
        WITH commune_medians AS (
            SELECT
                v_sub.nom_commune,
                MEDIAN(f_sub.valeur_fonciere / NULLIF(f_sub.surface_reelle_bati, 0)) AS prix_m2_commune
            FROM fact_dvf f_sub
            JOIN dim_adresses v_sub ON f_sub.id_adresse = v_sub.id_adresse
            WHERE f_sub.surface_reelle_bati > 0 AND f_sub.valeur_fonciere > 0
            GROUP BY v_sub.nom_commune
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
            ROUND(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0), 0)  AS prix_m2,
            ROUND(cm.prix_m2_commune, 0)                                    AS prix_m2_commune,
            v.nom_gare_proche,
            ROUND(v.distance_gare_metres   / 1000.0, 2) AS dist_gare_km,
            v.nom_ecole_proche,
            ROUND(v.distance_ecole_metres  / 1000.0, 2) AS dist_ecole_km,
            v.nom_aeroport_proche,
            ROUND(v.distance_aeroport_metres / 1000.0, 0) AS dist_aeroport_km,
            v.lat,
            v.lon
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        LEFT JOIN commune_medians cm ON v.nom_commune = cm.nom_commune
        WHERE {where}
        ORDER BY f.date_mutation DESC
        LIMIT 200
    """, params).df()
    con.close()
    return df