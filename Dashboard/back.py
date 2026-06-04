"""1
back.py — Requetes DuckDB pour le dashboard.
Chaque fonction ouvre une connexion read-only et la referme apres usage.
"""

import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "info_appart_2.duckdb"


def _con():
    return duckdb.connect(str(DB_PATH), read_only=True)


def db_ready() -> bool:
    """Retourne True si la base existe et contient fact_dvf."""
    if not DB_PATH.exists():
        return False
    try:
        con = _con()
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return "fact_dvf" in tables
    except Exception:
        return False


def get_kpis() -> dict:
    con = _con()
    row = con.execute("""
        SELECT
            COUNT(*)                                                      AS nb_transactions,
            COUNT(DISTINCT v.nom_commune)                                 AS nb_communes,
            MEDIAN(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0)) AS prix_m2_median,
            MEDIAN(f.surface_reelle_bati)                                 AS surface_mediane
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.surface_reelle_bati > 0
          AND f.type_local IN ('Maison', 'Appartement')
    """).fetchone()
    con.close()
    return {
        "nb_transactions": int(row[0] or 0),
        "nb_communes":     int(row[1] or 0),
        "prix_m2_median":  round(float(row[2]), 0) if row[2] else 0,
        "surface_mediane": round(float(row[3]), 0) if row[3] else 0,
    }


def get_top_communes(n: int = 10) -> pd.DataFrame:
    con = _con()
    df = con.execute(f"""
        SELECT
            v.nom_commune,
            COUNT(*) AS nb_transactions,
            ROUND(MEDIAN(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0)), 0) AS prix_m2_median
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE f.surface_reelle_bati > 0
          AND f.type_local IN ('Maison', 'Appartement')
        GROUP BY v.nom_commune
        ORDER BY nb_transactions DESC
        LIMIT {n}
    """).df()
    con.close()
    return df


def get_prix_par_mois() -> pd.DataFrame:
    con = _con()
    df = con.execute("""
        SELECT
            STRFTIME(CAST(date_mutation AS DATE), '%Y-%m') AS mois,
            ROUND(MEDIAN(valeur_fonciere / NULLIF(surface_reelle_bati, 0)), 0) AS prix_m2_median,
            COUNT(*) AS nb_transactions
        FROM fact_dvf
        WHERE surface_reelle_bati > 0
          AND type_local IN ('Maison', 'Appartement')
        GROUP BY mois
        ORDER BY mois
    """).df()
    con.close()
    return df


def get_prix_vs_proximite(limit: int = 2000) -> pd.DataFrame:
    """Echantillon pour les scatter plots prix vs distance gare/ecole."""
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
) -> pd.DataFrame:
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

    where = " AND ".join(conditions)
    con = _con()
    df = con.execute(f"""
        SELECT
            v.nom_commune,
            v.nom_voie,
            v.code_postal,
            f.date_mutation,
            f.valeur_fonciere,
            f.surface_reelle_bati,
            f.nombre_pieces_principales,
            f.type_local,
            ROUND(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0), 0) AS prix_m2,
            v.nom_gare_proche,
            ROUND(v.distance_gare_metres  / 1000.0, 2) AS dist_gare_km,
            v.nom_ecole_proche,
            ROUND(v.distance_ecole_metres / 1000.0, 2) AS dist_ecole_km,
            v.lat,
            v.lon
        FROM fact_dvf f
        JOIN dim_adresses v ON f.id_adresse = v.id_adresse
        WHERE {where}
        ORDER BY f.date_mutation DESC
        LIMIT 200
    """, params).df()
    con.close()
    return df
