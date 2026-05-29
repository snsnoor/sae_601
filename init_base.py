import duckdb
import glob
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

# Connexion à la base
con = duckdb.connect('info_appart.duckdb')

# ------------------- 1. Table 'adresses' -------------------
print("Chargement des fichiers adresses...")
con.execute("""
    CREATE OR REPLACE TABLE adresses AS 
    SELECT * FROM read_csv_auto('data/adresses-*.csv', sep=';', union_by_name=True, ignore_errors=True)
""")
print(f"Table 'adresses' créée avec {len(con.execute('SELECT * FROM adresses').fetchall())} entrées.")
print(f"Table 'adresses' créée.")

# ------------------- 2. Table 'dvf' -------------------
print("Chargement et nettoyage des données DVF...")
con.execute("""
    CREATE OR REPLACE TABLE dvf AS
    SELECT
        date_mutation, valeur_fonciere, surface_reelle_bati,
        adresse_numero, adresse_suffixe, adresse_code_voie, adresse_nom_voie,
        nombre_pieces_principales, type_local, nature_mutation,
        longitude, latitude, code_commune, code_postal,
        nom_commune, code_departement
    FROM read_csv(
        'https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres-geolocalisees/20260424-090024/dvf.csv.gz',
        delim=',', header=True, ignore_errors=True
    )
    WHERE YEAR(CAST(date_mutation AS DATE)) IN (2024, 2025)
    AND valeur_fonciere IS NOT NULL
""")
print(f"Table 'dvf' créée avec {len(con.execute('SELECT * FROM dvf').fetchall())} entrées.")
# Nettoyage
cols_numeric = ["surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude", "adresse_numero"]
cols_text = ["type_local", "adresse_code_voie", "adresse_nom_voie", "adresse_suffixe", "code_postal"]

for col in cols_numeric:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')
for col in cols_text:
    con.execute(f"UPDATE dvf SET \"{col}\" = 'NR' WHERE \"{col}\" IS NULL")

print("Table 'dvf' créée et nettoyée.")


# -------------------------------------------------------
# ------------------- 3. Table 'gares' -------------------
# -------------------------------------------------------

print("Téléchargement des données des gares SNCF...")
base_url = "https://data.sncf.com/api/explore/v2.1/catalog/datasets/liste-des-gares/records"
limit = 100
offset = 0
toutes_les_gares = []

while True:
    params = {"select": "code_uic, libelle, commune, departemen, c_geo", "limit": limit, "offset": offset}
    response = requests.get(base_url, params=params)
    response.raise_for_status()
    data = response.json()
    records = data.get("results", [])
    if not records: break
    toutes_les_gares.extend(records)
    offset += limit

df_gares = pd.DataFrame(toutes_les_gares)
# Extraction des coordonnées
df_gares['latitude'] = df_gares['c_geo'].apply(lambda x: x.get('lat') if isinstance(x, dict) else None)
df_gares['longitude'] = df_gares['c_geo'].apply(lambda x: x.get('lon') if isinstance(x, dict) else None)
df_gares = df_gares.drop(columns=['c_geo'])

# Enregistrement du DataFrame dans DuckDB
con.register('df_gares_temp', df_gares)
con.execute("CREATE OR REPLACE TABLE gares AS SELECT * FROM df_gares_temp")

print(f"Table 'gares' créée avec {len(df_gares)} entrées.")


# -------------------------------------------------------
# ------------------- 4. Table 'iris' (GeoJSON) -------------------
# -------------------------------------------------------
print("Téléchargement et nettoyage des données GeoJSON...")
url = "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"

response = requests.get(url)
geojson_data = response.json()

features_valides = []
erreurs = 0

for feature in geojson_data.get('features', []):
    try:
        if feature.get('geometry'):
            geometrie = shape(feature['geometry']) 
        
        features_valides.append(feature)
        
    except Exception as e:
        erreurs += 1

geojson_propre = {
    "type": "FeatureCollection",
    "features": features_valides
}

print(f"Nettoyage terminé : {erreurs} géométrie(s) ignorée(s).")

gdf = gpd.GeoDataFrame.from_features(geojson_propre)
gdf.set_crs("EPSG:4326", inplace=True)

print("\nSuccès ! Voici les premières lignes :")
print(gdf.head())

# Export du GeoDataFrame (converti en DataFrame classique) vers DuckDB
df_iris_temp = pd.DataFrame(gdf.drop(columns='geometry'))
# Note : On retire la colonne 'geometry' complexe car DuckDB natif gère mal les objets 'shape' sans extension spatiale.
con.register('df_iris_temp', df_iris_temp)
con.execute("CREATE OR REPLACE TABLE iris AS SELECT * FROM df_iris_temp")
print("Table 'iris' créée dans DuckDB.")



#-------------------------------------------------------
# Table dpe
#-------------------------------------------------------
print("\nChargement et nettoyage des données DPE...")

DPE_FILE = r"data\dpe.csv"
COLS_TO_KEEP = [
    "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe",
    "date_derniere_modification_dpe",
    "code_insee_ban", "code_departement_ban", "code_region_ban",
    "coordonnee_cartographique_x_ban", "coordonnee_cartographique_y_ban", "score_ban",
    "nom_commune_ban", "code_postal_ban", "adresse_brut", "nom_commune_brut", "code_postal_brut",
    "etiquette_dpe", "etiquette_ges",
    "conso_5_usages_ep", "conso_5_usages_par_m2_ep",
    "conso_5 usages_ef", "conso_5 usages_par_m2_ef",
    "emission_ges_5_usages", "emission_ges_5_usages par_m2",
    "cout_total_5_usages", "cout_chauffage", "cout_ecs",
    "cout_refroidissement", "cout_eclairage", "cout_auxiliaires",
    "type_batiment", "typologie_logement", "surface_habitable_logement",
    "periode_construction", "indicateur_confort_ete",
    "nombre_niveau_logement", "zone_climatique", "classe_altitude",
    "type_energie_principale_chauffage", "type_generateur_chauffage_principal",
    "qualite_isolation_enveloppe", "qualite_isolation_murs",
    "qualite_isolation_menuiseries", "ubat_w_par_m2_k", "isolation_toiture", "conso_chauffage_ef"
]

# Vérification des colonnes disponibles
cols_header = con.execute(f"""
    SELECT column_name FROM (
        DESCRIBE SELECT * FROM read_csv('{DPE_FILE}', auto_detect=TRUE, all_varchar=TRUE, sample_size=1)
    )
""").fetchdf()["column_name"].tolist()

cols_ok = [c for c in COLS_TO_KEEP if c in cols_header]
cols_absentes = [c for c in COLS_TO_KEEP if c not in cols_header]
if cols_absentes:
    print(f"  ⚠️ Colonnes absentes dans le CSV : {cols_absentes}")

# Chargement brut
select_clause = ", ".join([f'"{c}"' for c in cols_ok])
con.execute("DROP TABLE IF EXISTS dpe_raw")
con.execute(f"""
    CREATE TABLE dpe_raw AS
    SELECT {select_clause}
    FROM read_csv('{DPE_FILE}', auto_detect=TRUE, all_varchar=TRUE, ignore_errors=TRUE)
""")

# Calcul des médianes
NUMERIC_IMPUTE = [
    "conso_5_usages_ep", "conso_5_usages_par_m2_ep",
    "conso_5 usages_ef", "conso_5 usages_par_m2_ef",
    "emission_ges_5_usages", "emission_ges_5_usages par_m2",
    "cout_total_5_usages", "cout_chauffage", "cout_ecs",
    "cout_refroidissement", "cout_eclairage", "cout_auxiliaires",
    "surface_habitable_logement", "nombre_niveau_logement", "conso_chauffage_ef",
]
medianes = {}
for col in NUMERIC_IMPUTE:
    val = con.execute(f"""
        SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", ',', '.'), ' ', '') AS DOUBLE))
        FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != ''
    """).fetchone()[0]
    medianes[col] = val if val is not None else 0

# Imputation
median_expr = ",\n        ".join([
    f'COALESCE(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE), {medianes[col]}) AS "{col}"'
    for col in NUMERIC_IMPUTE
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

# Dédoublonnage → table finale
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

# Nettoyage des tables intermédiaires
con.execute("DROP TABLE IF EXISTS dpe_raw")
con.execute("DROP TABLE IF EXISTS dpe_imputed")

n_final = con.execute("SELECT COUNT(*) FROM dpe_final").fetchone()[0]
print(f"Table 'dpe_final' créée avec {n_final:,} entrées.")


#-------------------------------------------------------
# Fermeture de la base
#-------------------------------------------------------

con.close()
print("Processus terminé.")