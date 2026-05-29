# =======================================================================
# 5. RESTRUCTURATION EN MODÈLE EN ÉTOILE (OPTIMISATION DASHBOARD)
# =======================================================================
import duckdb
import glob
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
# Connexion à la base
con = duckdb.connect('info_appart_2.duckdb')

con.execute("DROP TABLE IF EXISTS dvf;")
con.execute("DROP TABLE IF EXISTS adresses;")
con.execute("DROP TABLE IF EXISTS iris;")
con.execute("DROP TABLE IF EXISTS gares;")
con.execute("DROP TABLE IF EXISTS dpe;")


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

print("\nÉtape 1 : Extraction et filtrage des adresses uniques présentes dans DVF...")

# On isole uniquement les adresses qui ont au moins une vente enregistrée dans DVF
con.execute("""
    CREATE OR REPLACE TEMP TABLE adresses_utiles_temp AS
    SELECT DISTINCT
        dvf.adresse_numero AS numero,
        dvf.adresse_nom_voie AS nom_voie,
        dvf.code_postal,
        dvf.nom_commune,
        dvf.longitude AS lon,
        dvf.latitude AS lat,
        dvf.code_commune AS code_insee
    FROM dvf
    WHERE dvf.longitude IS NOT NULL AND dvf.latitude IS NOT NULL;
""")

n_utiles = con.execute("SELECT COUNT(*) FROM adresses_utiles_temp").fetchone()[0]
print(f"-> Nombre d'adresses uniques à calculer réduites à : {n_utiles:,}")


print("\nÉtape 2 : Calcul géométrique des gares sur ce jeu d'adresses réduit...")
con.execute("""
    CREATE OR REPLACE TABLE dim_adresses AS
    WITH gares_calculees AS (
        SELECT 
            ROW_NUMBER() OVER () AS id_adresse,
            adr.*,
            g.libelle AS nom_gare_proche,
            -- Calcul de la distance (Pythagore sur coordonnées)
            ((adr.lon - g.longitude) * (adr.lon - g.longitude) + (adr.lat - g.latitude) * (adr.lat - g.latitude)) AS distance_gare_degres,
            ROW_NUMBER() OVER(
                PARTITION BY adr.numero, adr.nom_voie, adr.code_postal 
                ORDER BY ((adr.lon - g.longitude) * (adr.lon - g.longitude) + (adr.lat - g.latitude) * (adr.lat - g.latitude)) ASC
            ) AS rang_gare
        FROM adresses_utiles_temp adr
        INNER JOIN gares g 
            ON LOWER(SPLIT_PART(TRIM(adr.nom_commune), ' ', 1)) = LOWER(SPLIT_PART(TRIM(g.commune), ' ', 1))
    )
    SELECT * EXCLUDE(rang_gare) FROM gares_calculees WHERE rang_gare = 1;
""")

## con.execute("ALTER TABLE dim_adresses ADD PRIMARY KEY (id_adresse);")

print("\nÉtape 3 : Création de la table de faits centrale 'fact_dvf' reliée aux adresses...")
con.execute("""
    CREATE OR REPLACE TABLE fact_dvf AS
    SELECT 
        ROW_NUMBER() OVER () AS id_mutation, -- Clé primaire
        v.id_adresse ,                        -- Clé étrangère vers dim_adresses
        dvf.date_mutation,
        dvf.valeur_fonciere,
        dvf.surface_reelle_bati,
        dvf.nombre_pieces_principales,
        dvf.type_local,
        dvf.nature_mutation,
        dvf.code_departement
    FROM dvf
    INNER JOIN dim_adresses v
        ON dvf.adresse_numero = v.numero
       AND dvf.adresse_nom_voie = v.nom_voie
       AND dvf.code_postal = v.code_postal;
""")


print("\nÉtape 4 : Nettoyage final des données brutes...")
con.execute("DROP TABLE IF EXISTS dvf;")
con.execute("DROP TABLE IF EXISTS adresses;")
con.execute("DROP TABLE IF EXISTS gares;")

print("\n[Terminé] Vos tables 'fact_dvf' et 'dim_adresses' sont liées et optimisées.")
print(f"-> Total des transactions prêtes : {con.execute('SELECT COUNT(*) FROM fact_dvf').fetchone()[0]:,}")

con.close()
print("Processus terminé.")
