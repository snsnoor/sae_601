import duckdb
import requests
import pandas as pd
import time
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


con = duckdb.connect('info_appart.duckdb')

#-------------------------------------------------------
# Table dpe — via API ADEME (2024-2025, régions 52 et 53)
#-------------------------------------------------------
print("\nRécupération des données DPE via l'API ADEME (2024-2025)...")

API_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
PAGE_SIZE = 10000

COLS_TO_KEEP = [
    "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe",
    "date_derniere_modification_dpe",
    "code_insee_ban", "code_departement_ban", "code_region_ban",
    "coordonnee_cartographique_x_ban", "coordonnee_cartographique_y_ban", "score_ban",
    "nom_commune_ban", "code_postal_ban", "adresse_brut", "nom_commune_brut", "code_postal_brut",
    "etiquette_dpe", "etiquette_ges",
    "conso_5_usages_ep", "conso_5_usages_par_m2_ep",
    "emission_ges_5_usages",
    "cout_total_5_usages", "cout_chauffage", "cout_ecs",
    "cout_refroidissement", "cout_eclairage", "cout_auxiliaires",
    "type_batiment", "typologie_logement", "surface_habitable_logement",
    "periode_construction", "indicateur_confort_ete",
    "nombre_niveau_logement", "zone_climatique", "classe_altitude",
    "type_energie_principale_chauffage", "type_generateur_chauffage_principal",
    "qualite_isolation_enveloppe", "qualite_isolation_murs",
    "qualite_isolation_menuiseries", "ubat_w_par_m2_k", "isolation_toiture", "conso_chauffage_ef"
]

NUMERIC_IMPUTE = [
    "conso_5_usages_ep", "conso_5_usages_par_m2_ep",
    "emission_ges_5_usages",
    "cout_total_5_usages", "cout_chauffage", "cout_ecs",
    "cout_refroidissement", "cout_eclairage", "cout_auxiliaires",
    "surface_habitable_logement", "nombre_niveau_logement", "conso_chauffage_ef",
]

def make_session():
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session

def fetch_dpe_api(date_min: str, date_max: str, region: str) -> list:
    session = make_session()
    all_results = []
    params = {
        "date_etablissement_dpe_gte": date_min,
        "date_etablissement_dpe_lte": date_max,
        "code_region_ban_eq": region,
        "select": ",".join(COLS_TO_KEEP),
        "size": PAGE_SIZE,
    }

    # Premier appel
    resp = session.get(API_URL, params=params, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    total = data.get("total", 0)
    print(f"  → Région {region} | {date_min[:4]} : {total:,} DPE à récupérer")

    results = data.get("results", [])
    all_results.extend(results)
    print(f"     {len(all_results):,} / {total:,}")
    url = data.get("next")

    while url:
        for attempt in range(5):
            try:
                resp = session.get(url, timeout=120)
                resp.raise_for_status()
                break
            except Exception as e:
                if attempt < 4:
                    time.sleep(2 ** (attempt + 1))
                else:
                    raise e

        data = resp.json()
        results = data.get("results", [])
        all_results.extend(results)
        url = data.get("next")

        # Affiche la progression toutes les 50 000 lignes ou à la fin
        if len(all_results) % 50000 < PAGE_SIZE or url is None:
            print(f"     {len(all_results):,} / {total:,}")

    return all_results


# Récupération régions 52 (Pays de la Loire) et 53 (Bretagne), 2024 et 2025
all_results = []
for region in ["52", "53"]:
    for date_min, date_max in [("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")]:
        try:
            results = fetch_dpe_api(date_min, date_max, region)
            all_results.extend(results)
        except Exception as e:
            print(f"  ❌ Erreur région {region} {date_min[:4]} : {e}")

print(f"\n  → Total brut : {len(all_results):,} lignes récupérées")

# Construction du DataFrame
df_all = pd.DataFrame(all_results)

cols_ok = [c for c in COLS_TO_KEEP if c in df_all.columns]
cols_absentes = [c for c in COLS_TO_KEEP if c not in df_all.columns]
if cols_absentes:
    print(f"  ⚠️ Colonnes absentes dans l'API : {cols_absentes}")

df_all = df_all[cols_ok].copy()
df_all = df_all.astype(str).replace("None", "").replace("nan", "")

# Injection dans DuckDB
con.execute("DROP TABLE IF EXISTS dpe_raw")
con.register("dpe_api_view", df_all)
con.execute("CREATE TABLE dpe_raw AS SELECT * FROM dpe_api_view")
con.unregister("dpe_api_view")
print(f"  → dpe_raw chargée ({len(df_all):,} lignes)")

#-------------------------------------------------------
# Calcul des médianes pour imputation
#-------------------------------------------------------
medianes = {}
for col in NUMERIC_IMPUTE:
    if col not in cols_ok:
        medianes[col] = 0
        continue
    val = con.execute(f"""
        SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", ',', '.'), ' ', '') AS DOUBLE))
        FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != ''
    """).fetchone()[0]
    medianes[col] = val if val is not None else 0

#-------------------------------------------------------
# Imputation
#-------------------------------------------------------
median_expr = ",\n        ".join([
    f'COALESCE(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE), {medianes[col]}) AS "{col}"'
    for col in NUMERIC_IMPUTE if col in cols_ok
])

con.execute("DROP TABLE IF EXISTS dpe_imputed")
con.execute(f"""
    CREATE TABLE dpe_imputed AS
    SELECT
        numero_dpe, date_etablissement_dpe, date_fin_validite_dpe, date_derniere_modification_dpe,
        COALESCE(NULLIF(TRIM(code_insee_ban),       ''), 'NR') AS code_insee_ban,
        COALESCE(NULLIF(TRIM(code_departement_ban), ''), 'NR') AS code_departement_ban,
        COALESCE(NULLIF(TRIM(code_region_ban),      ''), 'NR') AS code_region_ban,
        COALESCE(NULLIF(TRIM(nom_commune_ban),  ''), NULLIF(TRIM(nom_commune_brut),  ''), 'NR') AS nom_commune_ban,
        COALESCE(NULLIF(TRIM(code_postal_ban),  ''), NULLIF(TRIM(code_postal_brut),  ''), 'NR') AS code_postal_ban,
        COALESCE(TRY_CAST(coordonnee_cartographique_x_ban AS DOUBLE), -999) AS coordonnee_cartographique_x_ban,
        COALESCE(TRY_CAST(coordonnee_cartographique_y_ban AS DOUBLE), -999) AS coordonnee_cartographique_y_ban,
        COALESCE(TRY_CAST(score_ban AS DOUBLE), 0.0) AS score_ban,
        COALESCE(adresse_brut, '') AS adresse_brut,
        COALESCE(nom_commune_brut, '') AS nom_commune_brut,
        code_postal_brut,
        UPPER(TRIM(etiquette_dpe)) AS etiquette_dpe,
        UPPER(TRIM(etiquette_ges)) AS etiquette_ges,
        {median_expr},
        COALESCE(NULLIF(TRIM(zone_climatique),  ''), 'NR') AS zone_climatique,
        COALESCE(NULLIF(TRIM(classe_altitude),  ''), 'NR') AS classe_altitude,
        COALESCE(NULLIF(TRIM(qualite_isolation_murs), ''), 'NR') AS qualite_isolation_murs,
        COALESCE(NULLIF(TRIM(type_generateur_chauffage_principal), ''), 'NR') AS type_generateur_chauffage_principal,
        COALESCE(NULLIF(TRIM(typologie_logement), ''), 'NR') AS typologie_logement,
        periode_construction, type_batiment, type_energie_principale_chauffage,
        qualite_isolation_enveloppe, qualite_isolation_menuiseries, ubat_w_par_m2_k,
        COALESCE(TRY_CAST(indicateur_confort_ete AS INTEGER), 0) AS indicateur_confort_ete,
        COALESCE(NULLIF(TRIM(isolation_toiture), ''), 'Inconnu') AS isolation_toiture
    FROM dpe_raw
""")

#-------------------------------------------------------
# Dédoublonnage → table finale
#-------------------------------------------------------
con.execute("DROP TABLE IF EXISTS dpe_final")
con.execute("""
    CREATE TABLE dpe_final AS
    SELECT * FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY numero_dpe
                   ORDER BY date_derniere_modification_dpe DESC NULLS LAST
               ) AS _rn
        FROM dpe_imputed WHERE numero_dpe IS NOT NULL
    ) WHERE _rn = 1
""")
con.execute("ALTER TABLE dpe_final DROP COLUMN _rn")

con.execute("DROP TABLE IF EXISTS dpe_raw")
con.execute("DROP TABLE IF EXISTS dpe_imputed")

n_final = con.execute("SELECT COUNT(*) FROM dpe_final").fetchone()[0]
print(f"Table 'dpe_final' créée avec {n_final:,} entrées.")

con.close()
print("Processus terminé.")