# =======================================================================
# RESTRUCTURATION GLOBALE EN MODÈLE EN ÉTOILE (CORRECTION SPATIALE & API)
# =======================================================================
import duckdb
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

print("Connexion à la base DuckDB...")
con = duckdb.connect('info_appart_2.duckdb')

# --- INITIALISATION DE L'EXTENSION SPATIALE ---
print("Installation et chargement de l'extension spatiale DuckDB...")
con.execute("INSTALL spatial;")
con.execute("LOAD spatial;")

# Nettoyage préalable de toutes les tables
tables_to_drop = [
    "dvf", "adresses", "iris", "gares", "ecoles", "dpe_raw", 
    "dpe_imputed", "dpe_final", "dim_adresses", "fact_dvf", "adresses_utiles_temp"
]
for t in tables_to_drop:
    con.execute(f"DROP TABLE IF EXISTS {t};")

# ------------------- 1. Table 'adresses' -------------------
print("\n--- 1. Chargement des fichiers adresses ---")
con.execute("""
    CREATE OR REPLACE TABLE adresses AS 
    SELECT * FROM read_csv_auto('data/adresses-*.csv', sep=';', union_by_name=True, ignore_errors=True)
""")
print(f"-> Table 'adresses' créée avec {con.execute('SELECT COUNT(*) FROM adresses').fetchone()[0]:,} entrées.")

# ------------------- 2. Table 'dvf' -------------------
print("\n--- 2. Chargement et nettoyage des données DVF ---")
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

cols_numeric = ["surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude", "adresse_numero"]
cols_text = ["type_local", "adresse_code_voie", "adresse_nom_voie", "adresse_suffixe", "code_postal"]
for col in cols_numeric:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')
for col in cols_text:
    con.execute(f"UPDATE dvf SET \"{col}\" = 'NR' WHERE \"{col}\" IS NULL")
print(f"-> Table 'dvf' nettoyée ({con.execute('SELECT COUNT(*) FROM dvf').fetchone()[0]:,} entrées).")

# ------------------- 3. Table 'gares' -------------------
print("\n--- 3. Téléchargement des données des gares SNCF ---")
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
df_gares['latitude'] = df_gares['c_geo'].apply(lambda x: x.get('lat') if isinstance(x, dict) else None)
df_gares['longitude'] = df_gares['c_geo'].apply(lambda x: x.get('lon') if isinstance(x, dict) else None)
df_gares = df_gares.drop(columns=['c_geo'])
con.register('df_gares_temp', df_gares)
con.execute("CREATE OR REPLACE TABLE gares AS SELECT * FROM df_gares_temp WHERE longitude IS NOT NULL AND latitude IS NOT NULL")
print(f"-> Table 'gares' créée avec {len(df_gares)} entrées.")

# ------------------- 4. Table 'ecoles' (Sécurisation des colonnes pour DuckDB) -------------------
print("\n--- 4. Téléchargement des données Écoles via API data.gouv ---")
url_ecoles = "https://www.data.gouv.fr/api/1/datasets/r/000f281d-81ec-4f57-be64-e3dbae5ef9ff"
try:
    response = requests.get(url_ecoles)
    response.raise_for_status()
    data_json = response.json()
    
    if isinstance(data_json, dict) and 'features' in data_json:
        df_ecole_raw = pd.json_normalize(data_json['features'])
        rename_dict = {}
        for col in df_ecole_raw.columns:
            if col.endswith('nom_etablissement'): rename_dict[col] = 'nom_etablissement'
            elif col.endswith('nom_commune'): rename_dict[col] = 'nom_commune'
            elif col.endswith('longitude'): rename_dict[col] = 'longitude'
            elif col.endswith('latitude'): rename_dict[col] = 'latitude'
        df_ecole_raw = df_ecole_raw.rename(columns=rename_dict)
        
        if 'geometry.coordinates' in df_ecole_raw.columns and 'longitude' not in df_ecole_raw.columns:
            df_ecole_raw['longitude'] = df_ecole_raw['geometry.coordinates'].apply(lambda x: x[0] if isinstance(x, list) and len(x) > 0 else None)
            df_ecole_raw['latitude'] = df_ecole_raw['geometry.coordinates'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)
    elif isinstance(data_json, dict):
        df_ecole_raw = pd.DataFrame.from_dict({k: pd.Series(v) for k, v in data_json.items()})
    else:
        df_ecole_raw = pd.DataFrame(data_json)
    
    # SÉCURITÉ ANTI-BINDER ERROR : On s'assure que les colonnes existent avant l'envoi à DuckDB
    cols = df_ecole_raw.columns.tolist()
    if 'nom_etablissement' not in cols: df_ecole_raw['nom_etablissement'] = 'Inconnu'
    if 'nom_commune' not in cols: df_ecole_raw['nom_commune'] = 'Inconnu'
    if 'longitude' not in cols: df_ecole_raw['longitude'] = None
    if 'latitude' not in cols: df_ecole_raw['latitude'] = None

    con.register('df_ecole_temp', df_ecole_raw)
    con.execute("""
        CREATE OR REPLACE TABLE ecoles AS 
        SELECT 
            CAST(nom_etablissement AS VARCHAR) AS nom_etablissement, 
            CAST(nom_commune AS VARCHAR) AS nom_commune, 
            TRY_CAST(REPLACE(CAST(longitude AS VARCHAR), ',', '.') AS DOUBLE) AS longitude,
            TRY_CAST(REPLACE(CAST(latitude AS VARCHAR), ',', '.') AS DOUBLE) AS latitude
        FROM df_ecole_temp
        WHERE longitude IS NOT NULL AND latitude IS NOT NULL
    """)
    print(f"-> Table 'ecoles' chargée avec {con.execute('SELECT COUNT(*) FROM ecoles').fetchone()[0]:,} établissements.")
except Exception as e:
    print(f"⚠️ Erreur lors de la récupération de l'API écoles : {e}. Table vide créée en secours.")
    con.execute("CREATE OR REPLACE TABLE ecoles (nom_etablissement VARCHAR, nom_commune VARCHAR, longitude DOUBLE, latitude DOUBLE)")

# ------------------- 5. Table 'iris' (Intégration du code du collègue) -------------------
print("\n--- 5. Téléchargement des données IRIS ---")
url = "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"
print("1. Téléchargement des données en cours...")
reponse = requests.get(url)

if reponse.status_code == 200:
    geojson_data = reponse.json()
    features_propres = []
    compteur_erreurs = 0
    
    print("2. Analyse et nettoyage des géométries...")
    for feature in geojson_data.get('features', []):
        if not feature.get('geometry'):
            continue
            
        try:
            geom = shape(feature['geometry'])
            features_propres.append(feature)
        except Exception:
            compteur_erreurs += 1

    print(f"-> Nettoyage terminé : {compteur_erreurs} géométrie(s) corrompue(s) supprimée(s).")
    
    if features_propres:
        gdf = gpd.GeoDataFrame.from_features(features_propres)
        print("3. GeoDataFrame créé avec succès !")
        
        # Transformation pour DuckDB : on convertit la géométrie en format lisible (WKT) et on retire l'objet shapely
        gdf['geom_wkt'] = gdf['geometry'].apply(lambda x: x.wkt if x else None)
        df_iris_temp = pd.DataFrame(gdf.drop(columns=['geometry']))
        
        con.register('df_iris_temp', df_iris_temp)
        con.execute("CREATE OR REPLACE TABLE iris AS SELECT * FROM df_iris_temp")
        print(f"-> Table 'iris' finalisée dans DuckDB avec {con.execute('SELECT COUNT(*) FROM iris').fetchone()[0]:,} enregistrements.")
    else:
        print("Erreur : Aucune géométrie valide n'a été trouvée.")
else:
    print(f"Erreur de téléchargement : {reponse.status_code}")

# ------------------- 6. Table 'dpe' (CSV Local + Logique Complète d'Imputation) -------------------
print("\n--- 6. Traitement DPE depuis fichier CSV local ---")
DPE_FILE = "data/dpe.csv"

COLS_TO_KEEP = [
    "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe", "date_derniere_modification_dpe",
    "code_insee_ban", "code_departement_ban", "code_region_ban", "coordonnee_cartographique_x_ban", 
    "coordonnee_cartographique_y_ban", "score_ban", "nom_commune_ban", "code_postal_ban", 
    "adresse_brut", "nom_commune_brut", "code_postal_brut", "etiquette_dpe", "etiquette_ges",
    "conso_5_usages_ep", "conso_5_usages_par_m2_ep", "emission_ges_5_usages", "cout_total_5_usages", 
    "cout_chauffage", "cout_ecs", "cout_refroidissement", "cout_eclairage", "cout_auxiliaires",
    "type_batiment", "typologie_logement", "surface_habitable_logement", "periode_construction", 
    "indicateur_confort_ete", "nombre_niveau_logement", "zone_climatique", "classe_altitude",
    "type_energie_principale_chauffage", "type_generateur_chauffage_principal",
    "qualite_isolation_enveloppe", "qualite_isolation_murs", "qualite_isolation_menuiseries", 
    "ubat_w_par_m2_k", "isolation_toiture", "conso_chauffage_ef"
]

NUMERIC_IMPUTE = [
    "conso_5_usages_ep", "conso_5_usages_par_m2_ep", "emission_ges_5_usages",
    "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_refroidissement", 
    "cout_eclairage", "cout_auxiliaires", "surface_habitable_logement", 
    "nombre_niveau_logement", "conso_chauffage_ef"
]

print("Lecture brute du CSV DPE...")
con.execute(f"CREATE OR REPLACE TABLE dpe_raw AS SELECT * FROM read_csv_auto('{DPE_FILE}', all_varchar=TRUE, ignore_errors=TRUE)")

cols_presentes = [row[0] for row in con.execute("DESCRIBE dpe_raw").fetchall()]
for col in COLS_TO_KEEP:
    if col not in cols_presentes:
        con.execute(f"ALTER TABLE dpe_raw ADD COLUMN {col} VARCHAR;")

print("Calcul des médianes sur le fichier local...")
medianes = {}
for col in NUMERIC_IMPUTE:
    val = con.execute(f"""
        SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", ',', '.'), ' ', '') AS DOUBLE))
        FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != ''
    """).fetchone()[0]
    medianes[col] = val if val is not None else 0

median_expr = ",\n        ".join([
    f'COALESCE(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE), {medianes[col]}) AS "{col}"'
    for col in NUMERIC_IMPUTE
])

print("Application des règles de nettoyage et d'imputation...")
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

print("Dédoublonnage de la table finale DPE...")
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
con.execute("DROP TABLE dpe_raw")
con.execute("DROP TABLE dpe_imputed")
print(f"-> Table 'dpe_final' créée avec {con.execute('SELECT COUNT(*) FROM dpe_final').fetchone()[0]:,} lignes.")


# ------------------- 7. Modèle en Étoile Réduit & Calcul Spatial Mètres -------------------
print("\n--- 7. RESTRUCTURATION EN MODÈLE EN ÉTOILE (ST_DISTANCE METRES) ---")
print("Étape 1 : Isolation des adresses uniques présentes dans DVF...")
con.execute("""
    CREATE OR REPLACE TEMP TABLE adresses_utiles_temp AS
    SELECT DISTINCT
        dvf.adresse_numero AS numero, dvf.adresse_nom_voie AS nom_voie,
        dvf.code_postal, dvf.nom_commune,
        dvf.longitude AS lon, dvf.latitude AS lat
    FROM dvf
    WHERE dvf.longitude IS NOT NULL AND dvf.latitude IS NOT NULL;
""")
print(f"-> Nombre d'adresses uniques cibles : {con.execute('SELECT COUNT(*) FROM adresses_utiles_temp').fetchone()[0]:,}")

print("Étape 2 : Calcul spatial des distances exactes en mètres (Gares et Écoles)...")
con.execute("""
    CREATE OR REPLACE TABLE dim_adresses AS
    WITH gares_calc AS (
        SELECT 
            adr.numero, adr.nom_voie, adr.code_postal,
            g.libelle AS nom_gare_proche,
            ST_Distance(
                ST_Transform(ST_Point(adr.lon, adr.lat), 'EPSG:4326', 'EPSG:2154'), 
                ST_Transform(ST_Point(g.longitude, g.latitude), 'EPSG:4326', 'EPSG:2154')
            ) AS distance_gare_metres
        FROM adresses_utiles_temp adr
        INNER JOIN gares g ON LOWER(SPLIT_PART(TRIM(adr.nom_commune), ' ', 1)) = LOWER(SPLIT_PART(TRIM(g.commune), ' ', 1))
        QUALIFY ROW_NUMBER() OVER(PARTITION BY adr.numero, adr.nom_voie, adr.code_postal ORDER BY distance_gare_metres ASC) = 1
    ),
    ecoles_calc AS (
        SELECT 
            adr.numero, adr.nom_voie, adr.code_postal,
            e.nom_etablissement AS nom_ecole_proche,
            ST_Distance(
                ST_Transform(ST_Point(adr.lon, adr.lat), 'EPSG:4326', 'EPSG:2154'), 
                ST_Transform(ST_Point(e.longitude, e.latitude), 'EPSG:4326', 'EPSG:2154')
            ) AS distance_ecole_metres
        FROM adresses_utiles_temp adr
        INNER JOIN ecoles e ON LOWER(SPLIT_PART(TRIM(adr.nom_commune), ' ', 1)) = LOWER(SPLIT_PART(TRIM(e.nom_commune), ' ', 1))
        QUALIFY ROW_NUMBER() OVER(PARTITION BY adr.numero, adr.nom_voie, adr.code_postal ORDER BY distance_ecole_metres ASC) = 1
    )
    SELECT 
        ROW_NUMBER() OVER () AS id_adresse,
        adr.*,
        gc.nom_gare_proche,
        gc.distance_gare_metres,
        ec.nom_ecole_proche,
        ec.distance_ecole_metres
    FROM adresses_utiles_temp adr
    LEFT JOIN gares_calc gc 
        ON adr.numero = gc.numero AND adr.nom_voie = gc.nom_voie AND adr.code_postal = gc.code_postal
    LEFT JOIN ecoles_calc ec 
        ON adr.numero = ec.numero AND adr.nom_voie = ec.nom_voie AND adr.code_postal = ec.code_postal;
""")

print("Étape 3 : Association à la table de faits centrale 'fact_dvf'...")
con.execute("""
    CREATE OR REPLACE TABLE fact_dvf AS
    SELECT 
        ROW_NUMBER() OVER () AS id_mutation,
        v.id_adresse,
        dvf.date_mutation, dvf.valeur_fonciere, dvf.surface_reelle_bati,
        dvf.nombre_pieces_principales, dvf.type_local, dvf.nature_mutation, dvf.code_departement
    FROM dvf
    INNER JOIN dim_adresses v
        ON dvf.adresse_numero = v.numero
       AND dvf.adresse_nom_voie = v.nom_voie
       AND dvf.code_postal = v.code_postal;
""")

print("\nÉtape 4 : Nettoyage final...")
tables_to_drop_final = ["dvf", "adresses", "gares", "ecoles", "adresses_utiles_temp","dim_dpe"]
for t in tables_to_drop_final:
    con.execute(f"DROP TABLE IF EXISTS {t};")

print("\n=======================================================================")
print("📊 BILAN DU PROLOGUE")
print("=======================================================================")
print(f"-> Table 'fact_dvf' (Faits)         : {con.execute('SELECT COUNT(*) FROM fact_dvf').fetchone()[0]:,} ventes")
print(f"-> Table 'dim_adresses' (Spatial)   : {con.execute('SELECT COUNT(*) FROM dim_adresses').fetchone()[0]:,} adresses avec gares & écoles en mètres")
print(f"-> Table 'dpe_final' (Logements)    : {con.execute('SELECT COUNT(*) FROM dpe_final').fetchone()[0]:,} diagnostics uniques")
print("=======================================================================")

con.close()
print("Processus global exécuté avec succès.")
