import os
import tempfile
import duckdb
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

# Configuration de la base
DB_PATH = 'info_appart.duckdb'
print(f"Connexion à la base {DB_PATH}...")
con = duckdb.connect(DB_PATH)

# Initialisation obligatoire de l'extension spatiale pour DuckDB
print("Chargement de l'extension spatiale DuckDB...")
con.execute("INSTALL spatial;")
con.execute("LOAD spatial;")

# Nettoyage des anciennes tables pour éviter les conflits de schéma
tables_to_drop = [
    "dvf", "adresses", "dim_gares", "dim_ecoles", "dim_iris", "dim_adresses", "fact_dvf", 
    "dpe_final", "iris_geoms_temp", "adresses_utiles_temp"
]
for t in tables_to_drop:
    con.execute(f"DROP TABLE IF EXISTS {t};")

# ------------------- 1. Table 'adresses' -------------------
print("\n--- 1. Chargement des fichiers adresses ---")
con.execute("""
    CREATE OR REPLACE TABLE adresses AS 
    SELECT * FROM read_csv_auto('data/adresses-*.csv*', sep=';', union_by_name=True, ignore_errors=True)
""")
print(f"Table 'adresses' créée.")

# ------------------- 2. Table 'dvf' -------------------
print("\n--- 2. Chargement et nettoyage des données DVF ---")
con.execute("""
    CREATE OR REPLACE TABLE dvf AS
    SELECT
        date_mutation, valeur_fonciere, surface_reelle_bati, surface_terrain,
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

# Nettoyage des valeurs NULL de DVF
cols_numeric = ["surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude", "adresse_numero"]
cols_text = ["type_local", "adresse_code_voie", "adresse_nom_voie", "adresse_suffixe", "code_postal"]

for col in cols_numeric:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')
for col in cols_text:
    con.execute(f"UPDATE dvf SET \"{col}\" = 'NR' WHERE \"{col}\" IS NULL")

print("Table 'dvf' créée et nettoyée.")

# ------------------- 3. Table 'dim_gares' -------------------
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
con.execute("""
    CREATE OR REPLACE TABLE dim_gares AS 
    SELECT 
        ROW_NUMBER() OVER () AS id_gare,
        libelle AS nom_gare,
        commune,
        longitude,
        latitude,
        ST_X(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154')) AS x_2154,
        ST_Y(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154')) AS y_2154,
        ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154') AS geom_2154
    FROM df_gares_temp
    WHERE longitude IS NOT NULL AND latitude IS NOT NULL
""")
print(f"Table 'dim_gares' créée.")

# ------------------- 4. Table 'dim_ecoles' (Ton code sécurisé & corrigé) -------------------
print("\n--- 4. Téléchargement et structuration de dim_ecoles via API data.gouv ---")
url_ecoles = "https://www.data.gouv.fr/api/1/datasets/r/000f281d-81ec-4f57-be64-e3dbae5ef9ff"
try:
    response = requests.get(url_ecoles)
    response.raise_for_status()
    data_json = response.json()

    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
        f.write(response.content)
        temp_path = f.name

    gdf_ecoles = gpd.read_file(temp_path)

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
        
    if gdf_ecoles.crs is None:
        gdf_ecoles = gdf_ecoles.set_crs("EPSG:3857")
    gdf_ecoles = gdf_ecoles.to_crs("EPSG:4326")

    gdf_ecoles["longitude"] = gdf_ecoles.geometry.x
    gdf_ecoles["latitude"] = gdf_ecoles.geometry.y

    if 'nom_etablissement' not in gdf_ecoles.columns and 'name' in gdf_ecoles.columns:
        gdf_ecoles = gdf_ecoles.rename(columns={'name': 'nom_etablissement'})
    if 'nom_etablissement' not in gdf_ecoles.columns and 'l_etablissement' in gdf_ecoles.columns:
        gdf_ecoles = gdf_ecoles.rename(columns={'l_etablissement': 'nom_etablissement'})

    cols = df_ecole_raw.columns.tolist()
    if 'nom_etablissement' not in cols: df_ecole_raw['nom_etablissement'] = 'Inconnu'
    if 'nom_commune' not in cols: df_ecole_raw['nom_commune'] = 'Inconnu'
    if 'longitude' not in cols: df_ecole_raw['longitude'] = None
    if 'latitude' not in cols: df_ecole_raw['latitude'] = None

    con.register('df_ecole_temp', gdf_ecoles[['nom_etablissement', 'longitude', 'latitude']])
    
    # Execution SQL nettoyée (Plus de doublons de requêtes ou de colonnes manquantes)
    con.execute("""
        CREATE OR REPLACE TABLE dim_ecoles AS 
        SELECT 
            ROW_NUMBER() OVER () AS id_ecole,
            nom_etablissement AS nom_ecole,
            TRY_CAST(REPLACE(CAST(longitude AS VARCHAR), ',', '.') AS DOUBLE) AS longitude,
            TRY_CAST(REPLACE(CAST(latitude AS VARCHAR), ',', '.') AS DOUBLE) AS latitude,
            ST_X(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154')) AS x_2154,
            ST_Y(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154')) AS y_2154,
            ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154') AS geom_2154
        FROM df_ecole_temp 
        WHERE longitude IS NOT NULL AND latitude IS NOT NULL
    """)
    print(f"-> Table 'dim_ecoles' créée avec {con.execute('SELECT COUNT(*) FROM dim_ecoles').fetchone()[0]:,} établissements.")

    try:
        os.unlink(temp_path)
    except:
        pass

except Exception as e:
    print(f"⚠️ Erreur lors de la récupération de l'API écoles : {e}. Table vide créée en secours.")
    con.execute("CREATE OR REPLACE TABLE dim_ecoles (id_ecole INT, nom_ecole VARCHAR, longitude DOUBLE, latitude DOUBLE, x_2154 DOUBLE, y_2154 DOUBLE, geom_2154 GEOMETRY)")

# ------------------- 5. Table 'dim_iris' -------------------
print("\n--- 5. Téléchargement et structuration des zones IRIS ---")
url = "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"

response = requests.get(url)
geojson_data = response.json()

features_valides = []
for feature in geojson_data.get('features', []):
    try:
        if feature.get('geometry'):
            geometrie = shape(feature['geometry']) 
            if geometrie.is_valid and geometrie.area > 0:
                features_valides.append(feature)
    except:
        continue

gdf = gpd.GeoDataFrame.from_features(features_valides)
gdf.set_crs("EPSG:4326", inplace=True)

gdf['geom_wkt'] = gdf['geometry'].apply(lambda x: x.wkt if x else None)
df_iris_temp = pd.DataFrame(gdf.drop(columns='geometry'))

con.register('df_iris_temp', df_iris_temp)

con.execute("""
    CREATE OR REPLACE TABLE dim_iris AS 
    SELECT 
        ROW_NUMBER() OVER () AS id_iris,
        CAST(ZONE AS VARCHAR) AS ZONE,
        CAST(CODE_OACI AS VARCHAR) AS CODE_OACI,
        CAST(NOM AS VARCHAR) AS NOM,
        CAST(PRODUCTEUR AS VARCHAR) AS PRODUCTEUR,
        CAST(REF_DOC AS VARCHAR) AS REF_DOC,
        CAST(INDLDENEXT AS VARCHAR) AS INDLDENEXT,
        CAST(INDLDENINT AS VARCHAR) AS INDLDENINT,
        CAST(DATE_ARRET AS VARCHAR) AS DATE_ARRET,
        CAST(DATE_MAJ AS VARCHAR) AS DATE_MAJ,
        CAST(ID_MAP AS VARCHAR) AS ID_MAP,
        geom_wkt
    FROM df_iris_temp
""")
print("Table 'dim_iris' créée.")

# ------------------- 6. Table 'dpe_final' -------------------
print("\n--- 6. Chargement et nettoyage des données DPE ---")
DPE_FILE = r"data\dpe.csv"

if not os.path.exists(DPE_FILE):
    print(f"⚠️ Fichier {DPE_FILE} absent. Étape DPE ignorée.")
else:
    COLS_TO_KEEP = [
        "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe", "date_derniere_modification_dpe",
        "code_insee_ban", "code_departement_ban", "code_region_ban", "coordonnee_cartographique_x_ban", 
        "coordonnee_cartographique_y_ban", "score_ban", "nom_commune_ban", "code_postal_ban", "adresse_brut", 
        "nom_commune_brut", "code_postal_brut", "etiquette_dpe", "etiquette_ges", "conso_5_usages_ep", 
        "conso_5_usages_par_m2_ep", "conso_5 usages_ef", "conso_5 usages_par_m2_ef", "emission_ges_5_usages", 
        "emission_ges_5_usages par_m2", "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_refroidissement", 
        "cout_eclairage", "cout_auxiliaires", "type_batiment", "typologie_logement", "surface_habitable_logement", 
        "periode_construction", "indicateur_confort_ete", "nombre_niveau_logement", "zone_climatique", 
        "classe_altitude", "type_energie_principale_chauffage", "type_generateur_chauffage_principal", 
        "qualite_isolation_enveloppe", "qualite_isolation_murs", "qualite_isolation_menuiseries", 
        "ubat_w_par_m2_k", "isolation_toiture", "conso_chauffage_ef"
    ]

    cols_header = con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv('{DPE_FILE}', auto_detect=TRUE, all_varchar=TRUE, sample_size=1))").fetchdf()["column_name"].tolist()
    cols_ok = [c for c in COLS_TO_KEEP if c in cols_header]
    select_clause = ", ".join([f'"{c}"' for c in cols_ok])

    con.execute(f"CREATE OR REPLACE TABLE dpe_raw AS SELECT {select_clause} FROM read_csv('{DPE_FILE}', auto_detect=TRUE, all_varchar=TRUE, ignore_errors=True)")

    NUMERIC_IMPUTE = [c for c in ["conso_5_usages_ep", "conso_5_usages_par_m2_ep", "conso_5 usages_ef", "conso_5 usages_par_m2_ef", "emission_ges_5_usages", "emission_ges_5_usages par_m2", "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_refroidissement", "cout_eclairage", "cout_auxiliaires", "surface_habitable_logement", "nombre_niveau_logement", "conso_chauffage_ef"] if c in cols_ok]
    
    medianes = {}
    for col in NUMERIC_IMPUTE:
        val = con.execute(f'SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE)) FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != \'\'').fetchone()[0]
        medianes[col] = val if val is not None else 0

    median_expr = ",\n        ".join([f'COALESCE(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE), {medianes[col]}) AS "{col}"' for col in NUMERIC_IMPUTE])

    con.execute(f"""
        CREATE OR REPLACE TABLE dpe_imputed AS
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

    con.execute("""
        CREATE OR REPLACE TABLE dpe_final AS
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY numero_dpe ORDER BY date_derniere_modification_dpe DESC NULLS LAST) AS _rn FROM dpe_imputed
        ) WHERE _rn = 1
    """)
    con.execute("ALTER TABLE dpe_final DROP COLUMN _rn; DROP TABLE dpe_raw; DROP TABLE dpe_imputed;")
    print("Table 'dpe_final' créée.")

# ------------------- 7. Modèle en Étoile (Calculs Spatiaux Corrigés) -------------------
print("\n--- 7. RESTRUCTURATION EN MODÈLE EN ÉTOILE (POINT-IN-POLYGON) ---")

print("Étape 1 : Indexation des adresses uniques de DVF...")
con.execute("""
    CREATE OR REPLACE TEMP TABLE adresses_utiles_temp AS
    SELECT DISTINCT
        dvf.adresse_numero AS numero, dvf.adresse_nom_voie AS nom_voie,
        dvf.code_postal, dvf.nom_commune,
        dvf.longitude AS lon, dvf.latitude AS lat,
        ST_X(ST_Transform(ST_Point(dvf.longitude, dvf.latitude), 'EPSG:4326', 'EPSG:2154')) AS x_2154,
        ST_Y(ST_Transform(ST_Point(dvf.longitude, dvf.latitude), 'EPSG:4326', 'EPSG:2154')) AS y_2154,
        ST_Transform(ST_Point(dvf.longitude, dvf.latitude), 'EPSG:4326', 'EPSG:2154') AS geom_2154
    FROM dvf
    WHERE dvf.longitude IS NOT NULL AND dvf.longitude != 0 AND dvf.latitude IS NOT NULL AND dvf.latitude != 0;
""")

print("Étape 2 : Pré-filtrage par Bounding Box des géométries IRIS ")
con.execute("""
    CREATE OR REPLACE TEMP TABLE iris_geoms_temp AS
    SELECT
        id_iris, CODE_OACI, NOM,
        ST_GeomFromText(geom_wkt) AS geom,
        ST_XMin(ST_GeomFromText(geom_wkt)) AS lon_min,
        ST_XMax(ST_GeomFromText(geom_wkt)) AS lon_max,
        ST_YMin(ST_GeomFromText(geom_wkt)) AS lat_min,
        ST_YMax(ST_GeomFromText(geom_wkt)) AS lat_max
    FROM dim_iris
    WHERE geom_wkt IS NOT NULL;
""")

print("Étape 3 : Génération de dim_adresses (Calcul gares, écoles, et polygones IRIS)...")
con.execute("""
    CREATE OR REPLACE TABLE dim_adresses AS
    WITH gares_calc AS (
        SELECT 
            adr.numero, adr.nom_voie, adr.code_postal,
            g.id_gare AS id_gare_proche,
            g.nom_gare AS nom_gare_proche,
            ST_Distance(adr.geom_2154, g.geom_2154) AS distance_gare_metres
        FROM adresses_utiles_temp adr
        INNER JOIN dim_gares g ON g.x_2154 BETWEEN adr.x_2154 - 50000 AND adr.x_2154 + 50000
                              AND g.y_2154 BETWEEN adr.y_2154 - 50000 AND adr.y_2154 + 50000
        QUALIFY ROW_NUMBER() OVER(PARTITION BY adr.numero, adr.nom_voie, adr.code_postal ORDER BY distance_gare_metres ASC) = 1
    ),
    ecoles_calc AS (
        SELECT 
            adr.numero, adr.nom_voie, adr.code_postal,
            e.nom_ecole AS nom_ecole_proche,
            ST_Distance(adr.geom_2154, e.geom_2154) AS distance_ecole_metres
        FROM adresses_utiles_temp adr
        INNER JOIN dim_ecoles e ON e.x_2154 BETWEEN adr.x_2154 - 10000 AND adr.x_2154 + 10000
                               AND e.y_2154 BETWEEN adr.y_2154 - 10000 AND adr.y_2154 + 10000
        QUALIFY ROW_NUMBER() OVER(PARTITION BY adr.numero, adr.nom_voie, adr.code_postal ORDER BY distance_ecole_metres ASC) = 1
    ),
    iris_calc AS (
        SELECT 
            adr.numero, adr.nom_voie, adr.code_postal,
            i.id_iris,
            i.CODE_OACI AS code_oaci_iris,
            i.NOM AS nom_iris
        FROM adresses_utiles_temp adr
        LEFT JOIN iris_geoms_temp i 
            ON adr.lon BETWEEN i.lon_min AND i.lon_max
           AND adr.lat BETWEEN i.lat_min AND i.lat_max
           AND ST_Contains(i.geom, ST_Point(adr.lon, adr.lat))
        QUALIFY ROW_NUMBER() OVER(PARTITION BY adr.numero, adr.nom_voie, adr.code_postal ORDER BY i.id_iris) = 1
    )
    SELECT 
        ROW_NUMBER() OVER () AS id_adresse,
        adr.numero, adr.nom_voie, adr.code_postal, adr.nom_commune, adr.lon, adr.lat,
        gc.nom_gare_proche, gc.distance_gare_metres,
        ec.nom_ecole_proche, ec.distance_ecole_metres,
        ic.id_iris, ic.code_oaci_iris, ic.nom_iris
    FROM adresses_utiles_temp adr
    LEFT JOIN gares_calc gc ON adr.numero = gc.numero AND adr.nom_voie = gc.nom_voie AND adr.code_postal = gc.code_postal
    LEFT JOIN ecoles_calc ec ON adr.numero = ec.numero AND adr.nom_voie = ec.nom_voie AND adr.code_postal = ec.code_postal
    LEFT JOIN iris_calc ic ON adr.numero = ic.numero AND adr.nom_voie = ic.nom_voie AND adr.code_postal = ic.code_postal;
""")

print("Étape 4 : Liaison finale avec la table de faits 'fact_dvf'...")
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

# Nettoyage final des index géométriques lourds et intermédiaires pour libérer de l'espace
con.execute("DROP TABLE IF EXISTS dvf; DROP TABLE IF EXISTS adresses_utiles_temp; DROP TABLE IF EXISTS iris_geoms_temp;")
con.execute("ALTER TABLE dim_gares DROP COLUMN geom_2154; ALTER TABLE dim_gares DROP COLUMN x_2154; ALTER TABLE dim_gares DROP COLUMN y_2154;")
con.execute("ALTER TABLE dim_ecoles DROP COLUMN geom_2154; ALTER TABLE dim_ecoles DROP COLUMN x_2154; ALTER TABLE dim_ecoles DROP COLUMN y_2154;")

# ------------------- Fin du script -------------------

print("\n=======================================================================")
print("📊 BILAN DU PROLOGUE")
print("=======================================================================")
print(f"-> Table 'fact_dvf' (Faits)         : {con.execute('SELECT COUNT(*) FROM fact_dvf').fetchone()[0]:,} ventes")
print(f"-> Table 'dim_adresses' (Spatial)   : {con.execute('SELECT COUNT(*) FROM dim_adresses').fetchone()[0]:,} adresses structurées")
print(f"-> Table 'dim_iris' (Dimension)     : {con.execute('SELECT COUNT(*) FROM dim_iris').fetchone()[0]:,} zones IRIS enregistrées")
print(f"-> Table 'dim_gares' (Dimension)    : {con.execute('SELECT COUNT(*) FROM dim_gares').fetchone()[0]:,} gares routières/SNCF enregistrées")
print(f"-> Table 'dim_ecoles' (Dimension)   : {con.execute('SELECT COUNT(*) FROM dim_ecoles').fetchone()[0]:,} établissements scolaires enregistrés")
print(f"-> Table 'dpe_final' (Logements)    : {con.execute('SELECT COUNT(*) FROM dpe_final').fetchone()[0]:,} diagnostics uniques")
print("=======================================================================")

con.close()
print("\nProcessus terminé avec succès.")