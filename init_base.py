"""
init_base.py — Construit toutes les tables DuckDB depuis les sources.
Base cible : info_appart_2.duckdb

Ordre d'execution :
  1. python download_data.py   (BAN — optionnel)
  2. python dpe_api.py         (DPE via API ADEME, ~30 min)
     OU placez data/dpe.csv manuellement pour les tests
  3. python init_base.py
  4. streamlit run dashboard/front.py
"""

from pathlib import Path
import duckdb
import requests
import pandas as pd
import geopandas as gpd
import tempfile
from shapely.geometry import shape

DB_PATH  = Path(__file__).parent / "info_appart_2.duckdb"
DATA_DIR = Path(__file__).parent / "data"

print(f"Connexion a {DB_PATH}...")
con = duckdb.connect(str(DB_PATH))

print("Chargement de l'extension spatiale DuckDB...")
con.execute("INSTALL spatial;")
con.execute("LOAD spatial;")

for t in [
    "dvf", "dvf_raw",
    "dim_iris", "iris_geoms_temp", "dim_gares", "dim_ecoles", "dim_aeroports",
    "dpe_raw", "dpe_imputed",
    "dim_adresses", "fact_dvf", "adresses_utiles_temp",
]:
    con.execute(f"DROP TABLE IF EXISTS {t};")

# NOTE BAN : la table adresses sera utile pour la jointure DVF<->DPE
# (normalisation des adresses). Elle n'est pas encore utilisee dans le
# modele en etoile actuel. A integrer quand la jointure DVF-DPE sera implementee.


# ── 2. DVF 2024-2025 + deduplication ─────────────────────────────────────────
print("\n--- 2. Chargement DVF 2024-2025 ---")
print("  (streaming depuis data.gouv.fr...)")
con.execute("""
    CREATE OR REPLACE TABLE dvf_raw AS
    SELECT
        date_mutation, valeur_fonciere, surface_reelle_bati,
        adresse_numero, adresse_suffixe, adresse_code_voie, adresse_nom_voie,
        nombre_pieces_principales, type_local, nature_mutation,
        longitude, latitude, code_commune, code_postal, nom_commune, code_departement
    FROM read_csv(
        'https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres-geolocalisees/20260424-090024/dvf.csv.gz',
        delim=',', header=True, ignore_errors=True
    )
    WHERE YEAR(CAST(date_mutation AS DATE)) IN (2024, 2025)
      AND valeur_fonciere IS NOT NULL
""")
print(f"  -> {con.execute('SELECT COUNT(*) FROM dvf_raw').fetchone()[0]:,} lignes brutes.")

# Deduplication : une vente peut generer N lignes (une par parcelle cadastrale).
# On garde UNE ligne par transaction : Maison > Appartement > autres,
# puis la plus grande surface. La valeur_fonciere (prix total) reste correcte.
con.execute("""
    CREATE OR REPLACE TABLE dvf AS
    SELECT * EXCLUDE(_rn)
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY date_mutation, valeur_fonciere,
                                code_commune, adresse_numero, adresse_nom_voie
                   ORDER BY
                       CASE type_local
                           WHEN 'Maison'      THEN 1
                           WHEN 'Appartement' THEN 2
                           ELSE 3
                       END ASC,
                       surface_reelle_bati DESC NULLS LAST
               ) AS _rn
        FROM dvf_raw
    )
    WHERE _rn = 1
""")
con.execute("DROP TABLE dvf_raw")

for col in ["surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude", "adresse_numero"]:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')
for col in ["type_local", "adresse_code_voie", "adresse_nom_voie", "adresse_suffixe", "code_postal"]:
    con.execute(f"UPDATE dvf SET \"{col}\" = 'NR' WHERE \"{col}\" IS NULL")
print(f"  -> {con.execute('SELECT COUNT(*) FROM dvf').fetchone()[0]:,} transactions apres deduplication.")


# ── 3. dim_gares ──────────────────────────────────────────────────────────────
print("\n--- 3. Telechargement dim_gares ---")
base_url = "https://data.sncf.com/api/explore/v2.1/catalog/datasets/liste-des-gares/records"
limit, offset, toutes_les_gares = 100, 0, []
while True:
    params = {"select": "libelle, commune, c_geo", "limit": limit, "offset": offset}
    r = requests.get(base_url, params=params)
    r.raise_for_status()
    records = r.json().get("results", [])
    if not records:
        break
    toutes_les_gares.extend(records)
    offset += limit

df_gares = pd.DataFrame(toutes_les_gares)
df_gares["latitude"]  = df_gares["c_geo"].apply(lambda x: x.get("lat") if isinstance(x, dict) else None)
df_gares["longitude"] = df_gares["c_geo"].apply(lambda x: x.get("lon") if isinstance(x, dict) else None)
con.register("df_gares_temp", df_gares.drop(columns=["c_geo"]))

# x_2154 / y_2154 pre-calcules une seule fois pour le bbox filter
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
print(f"  -> {con.execute('SELECT COUNT(*) FROM dim_gares').fetchone()[0]:,} gares.")


# ── 4. dim_ecoles ─────────────────────────────────────────────────────────────
print("\n--- 4. Telechargement dim_ecoles ---")
try:
    r = requests.get("https://www.data.gouv.fr/api/1/datasets/r/000f281d-81ec-4f57-be64-e3dbae5ef9ff")
    r.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
        f.write(r.content)
        temp_path = f.name
    gdf_ecoles = gpd.read_file(temp_path)
    if gdf_ecoles.crs is None:
        gdf_ecoles = gdf_ecoles.set_crs("EPSG:3857")
    gdf_ecoles = gdf_ecoles.to_crs("EPSG:4326")
    gdf_ecoles["longitude"] = gdf_ecoles.geometry.x
    gdf_ecoles["latitude"]  = gdf_ecoles.geometry.y
    for src, dst in [("name", "nom_etablissement"), ("l_etablissement", "nom_etablissement")]:
        if "nom_etablissement" not in gdf_ecoles.columns and src in gdf_ecoles.columns:
            gdf_ecoles = gdf_ecoles.rename(columns={src: "nom_etablissement"})
    if "nom_etablissement" not in gdf_ecoles.columns:
        gdf_ecoles["nom_etablissement"] = "Inconnu"
    con.register("df_ecole_temp", gdf_ecoles[["nom_etablissement", "longitude", "latitude"]])
    con.execute("""
        CREATE OR REPLACE TABLE dim_ecoles AS
        SELECT
            ROW_NUMBER() OVER () AS id_ecole,
            nom_etablissement AS nom_ecole,
            longitude,
            latitude,
            ST_X(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154')) AS x_2154,
            ST_Y(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154')) AS y_2154,
            ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154') AS geom_2154
        FROM df_ecole_temp
        WHERE longitude IS NOT NULL AND latitude IS NOT NULL
    """)
    print(f"  -> {con.execute('SELECT COUNT(*) FROM dim_ecoles').fetchone()[0]:,} ecoles.")
except Exception as e:
    print(f"  Erreur API ecoles : {e}. Table vide creee.")
    con.execute("""
        CREATE OR REPLACE TABLE dim_ecoles (
            id_ecole BIGINT, nom_ecole VARCHAR, longitude DOUBLE, latitude DOUBLE,
            x_2154 DOUBLE, y_2154 DOUBLE
        )
    """)


# ── 5. dim_iris ───────────────────────────────────────────────────────────────
print("\n--- 5. Telechargement dim_iris ---")
try:
    geojson_data = requests.get(
        "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"
    ).json()
    features_valides = []
    for f in geojson_data.get("features", []):
        geom_data = f.get("geometry")
        if geom_data and geom_data.get("coordinates"):
            try:
                s = shape(geom_data)
                if s.is_valid and s.area > 0:
                    features_valides.append(f)
            except Exception:
                continue
    if not features_valides:
        raise ValueError("Aucune geometrie valide.")
    gdf = gpd.GeoDataFrame.from_features(features_valides)
    gdf["geom_wkt"] = gdf["geometry"].apply(lambda x: x.wkt if x else None)
    df_iris_temp = pd.DataFrame(gdf.drop(columns=["geometry"]))
    con.register("df_iris_temp", df_iris_temp)
    con.execute("CREATE OR REPLACE TABLE dim_iris AS SELECT ROW_NUMBER() OVER () AS id_iris, * FROM df_iris_temp")
    print(f"  -> {con.execute('SELECT COUNT(*) FROM dim_iris').fetchone()[0]:,} zones IRIS.")
except Exception as e:
    print(f"  Erreur IRIS : {e}. Table vide creee.")
    con.execute("CREATE OR REPLACE TABLE dim_iris (id_iris BIGINT, ZONE VARCHAR, geom_wkt VARCHAR)")


# ── 6. dim_aeroports ──────────────────────────────────────────────────────────
print("\n--- 6. Chargement dim_aeroports ---")
AEROPORTS_FALLBACK = [
    {"iata": "CDG", "nom": "Paris Charles de Gaulle",  "latitude": 49.0097, "longitude":  2.5479},
    {"iata": "ORY", "nom": "Paris Orly",               "latitude": 48.7233, "longitude":  2.3794},
    {"iata": "NCE", "nom": "Nice Cote d Azur",         "latitude": 43.6584, "longitude":  7.2159},
    {"iata": "LYS", "nom": "Lyon Saint-Exupery",       "latitude": 45.7256, "longitude":  5.0811},
    {"iata": "MRS", "nom": "Marseille Provence",       "latitude": 43.4393, "longitude":  5.2214},
    {"iata": "TLS", "nom": "Toulouse-Blagnac",         "latitude": 43.6293, "longitude":  1.3638},
    {"iata": "BOD", "nom": "Bordeaux-Merignac",        "latitude": 44.8283, "longitude": -0.7156},
    {"iata": "NTE", "nom": "Nantes Atlantique",        "latitude": 47.1569, "longitude": -1.6119},
    {"iata": "LIL", "nom": "Lille-Lesquin",            "latitude": 50.5633, "longitude":  3.0894},
    {"iata": "SXB", "nom": "Strasbourg",               "latitude": 48.5383, "longitude":  7.6283},
    {"iata": "MPL", "nom": "Montpellier-Mediterranee", "latitude": 43.5762, "longitude":  3.9630},
    {"iata": "BIQ", "nom": "Biarritz-Pays Basque",    "latitude": 43.4683, "longitude": -1.5231},
    {"iata": "RNS", "nom": "Rennes",                   "latitude": 48.0695, "longitude": -1.7348},
    {"iata": "BVA", "nom": "Beauvais-Tille",           "latitude": 49.4544, "longitude":  2.1128},
    {"iata": "GNB", "nom": "Grenoble-Isere",           "latitude": 45.3629, "longitude":  5.3294},
    {"iata": "ETZ", "nom": "Metz-Nancy-Lorraine",      "latitude": 48.9822, "longitude":  6.2517},
    {"iata": "LRH", "nom": "La Rochelle-Ile de Re",    "latitude": 46.1792, "longitude": -1.1953},
    {"iata": "AJA", "nom": "Ajaccio Napoleon Bonaparte","latitude": 41.9236, "longitude":  8.8029},
    {"iata": "FSC", "nom": "Figari Sud-Corse",         "latitude": 41.5006, "longitude":  9.0978},
    {"iata": "CLY", "nom": "Calvi-Sainte-Catherine",   "latitude": 42.5244, "longitude":  8.7933},
]
try:
    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": "[out:json][timeout:60];(node[\"aeroway\"=\"aerodrome\"][\"iata\"](41,-5,51,10);way[\"aeroway\"=\"aerodrome\"][\"iata\"](41,-5,51,10););out center;"},
        timeout=90,
    )
    r.raise_for_status()
    elements = r.json().get("elements", [])
    airports = []
    for elem in elements:
        lat = elem.get("lat") or elem.get("center", {}).get("lat")
        lon = elem.get("lon") or elem.get("center", {}).get("lon")
        tags = elem.get("tags", {})
        if lat and lon:
            airports.append({
                "iata": tags.get("iata", ""),
                "nom":  tags.get("name", tags.get("iata", "Inconnu")),
                "latitude": float(lat), "longitude": float(lon),
            })
    if not airports:
        raise ValueError("Aucun aeroport retourne.")
    print(f"  -> {len(airports)} aeroports via Overpass/OSM.")
except Exception as e:
    print(f"  Overpass indisponible ({e}). Fallback : {len(AEROPORTS_FALLBACK)} aeroports.")
    airports = AEROPORTS_FALLBACK

df_aero = pd.DataFrame(airports)
con.register("df_aero_temp", df_aero)
con.execute("""
    CREATE OR REPLACE TABLE dim_aeroports AS
    SELECT
        ROW_NUMBER() OVER () AS id_aeroport,
        iata AS code_iata,
        nom  AS nom_aeroport,
        longitude,
        latitude,
        ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154') AS geom_2154
    FROM df_aero_temp
    WHERE longitude IS NOT NULL AND latitude IS NOT NULL
""")
print(f"  -> {con.execute('SELECT COUNT(*) FROM dim_aeroports').fetchone()[0]:,} aeroports.")


# ── 7. DPE ────────────────────────────────────────────────────────────────────
print("\n--- 7. Traitement DPE ---")
tables_existantes = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
if "dpe_final" in tables_existantes:
    n = con.execute("SELECT COUNT(*) FROM dpe_final").fetchone()[0]
    print(f"  -> dpe_final deja presente ({n:,} lignes) — etape sautee.")
    print("     Pour recharger : supprimez la table et relancez.")
else:
    dpe_path = DATA_DIR / "dpe.csv"
    if not dpe_path.exists():
        print("  data/dpe.csv introuvable. Lancez dpe_api.py ou placez le fichier manuellement.")
    else:
        DPE_FILE = "data/dpe.csv"
        COLS_TO_KEEP = [
            "numero_dpe", "date_etablissement_dpe", "date_fin_validite_dpe",
            "date_derniere_modification_dpe",
            "code_insee_ban", "code_departement_ban", "code_region_ban",
            "coordonnee_cartographique_x_ban", "coordonnee_cartographique_y_ban", "score_ban",
            "nom_commune_ban", "code_postal_ban", "adresse_brut", "nom_commune_brut", "code_postal_brut",
            "etiquette_dpe", "etiquette_ges",
            "conso_5_usages_ep", "conso_5_usages_par_m2_ep", "emission_ges_5_usages",
            "cout_total_5_usages", "cout_chauffage", "cout_ecs",
            "cout_refroidissement", "cout_eclairage", "cout_auxiliaires",
            "type_batiment", "typologie_logement", "surface_habitable_logement",
            "periode_construction", "indicateur_confort_ete", "nombre_niveau_logement",
            "zone_climatique", "classe_altitude", "type_energie_principale_chauffage",
            "type_generateur_chauffage_principal", "qualite_isolation_enveloppe",
            "qualite_isolation_murs", "qualite_isolation_menuiseries",
            "ubat_w_par_m2_k", "isolation_toiture", "conso_chauffage_ef",
        ]
        NUMERIC_IMPUTE = [
            "conso_5_usages_ep", "conso_5_usages_par_m2_ep", "emission_ges_5_usages",
            "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_refroidissement",
            "cout_eclairage", "cout_auxiliaires", "surface_habitable_logement",
            "nombre_niveau_logement", "conso_chauffage_ef",
        ]
        con.execute(f"""
            CREATE OR REPLACE TABLE dpe_raw AS
            SELECT * FROM read_csv_auto('{DPE_FILE}', all_varchar=TRUE, ignore_errors=TRUE)
        """)
        cols_presentes = [row[0] for row in con.execute("DESCRIBE dpe_raw").fetchall()]
        for col in COLS_TO_KEEP:
            if col not in cols_presentes:
                con.execute(f'ALTER TABLE dpe_raw ADD COLUMN "{col}" VARCHAR;')
        medianes = {}
        for col in NUMERIC_IMPUTE:
            val = con.execute(f"""
                SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", ',', '.'), ' ', '') AS DOUBLE))
                FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != ''
            """).fetchone()[0]
            medianes[col] = val if val is not None else 0
        median_expr = ",\n            ".join([
            f'COALESCE(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE), {medianes[col]}) AS "{col}"'
            for col in NUMERIC_IMPUTE
        ])
        con.execute(f"""
            CREATE TABLE dpe_imputed AS
            SELECT
                numero_dpe, date_etablissement_dpe, date_fin_validite_dpe,
                date_derniere_modification_dpe,
                COALESCE(NULLIF(TRIM(code_insee_ban),       ''), 'NR') AS code_insee_ban,
                COALESCE(NULLIF(TRIM(code_departement_ban), ''), 'NR') AS code_departement_ban,
                COALESCE(NULLIF(TRIM(code_region_ban),      ''), 'NR') AS code_region_ban,
                COALESCE(NULLIF(TRIM(nom_commune_ban),  ''), NULLIF(TRIM(nom_commune_brut), ''), 'NR') AS nom_commune_ban,
                COALESCE(NULLIF(TRIM(code_postal_ban),  ''), NULLIF(TRIM(code_postal_brut), ''), 'NR') AS code_postal_ban,
                COALESCE(TRY_CAST(coordonnee_cartographique_x_ban AS DOUBLE), -999) AS coordonnee_cartographique_x_ban,
                COALESCE(TRY_CAST(coordonnee_cartographique_y_ban AS DOUBLE), -999) AS coordonnee_cartographique_y_ban,
                COALESCE(TRY_CAST(score_ban AS DOUBLE), 0.0) AS score_ban,
                COALESCE(adresse_brut,     '') AS adresse_brut,
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
            CREATE TABLE dpe_final AS
            SELECT * EXCLUDE(_rn) FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY numero_dpe
                           ORDER BY date_derniere_modification_dpe DESC NULLS LAST
                       ) AS _rn
                FROM dpe_imputed WHERE numero_dpe IS NOT NULL
            ) WHERE _rn = 1
        """)
        con.execute("DROP TABLE IF EXISTS dpe_raw")
        con.execute("DROP TABLE IF EXISTS dpe_imputed")
        print(f"  -> {con.execute('SELECT COUNT(*) FROM dpe_final').fetchone()[0]:,} diagnostics DPE uniques.")


# ── 8. Modele en etoile ───────────────────────────────────────────────────────
print("\n--- 8. MODELE EN ETOILE ---")
for t in ["fact_dvf", "dim_adresses"]:
    con.execute(f"DROP TABLE IF EXISTS {t}")

# Etape 1 : projections pre-calculees une seule fois par adresse unique
print("  Etape 1 : projection des adresses uniques en Lambert-93...")
con.execute("""
    CREATE OR REPLACE TEMP TABLE adresses_utiles_temp AS
    SELECT DISTINCT
        dvf.adresse_numero   AS numero,
        dvf.adresse_nom_voie AS nom_voie,
        dvf.code_postal,
        dvf.nom_commune,
        dvf.longitude AS lon,
        dvf.latitude  AS lat,
        ST_X(ST_Transform(ST_Point(dvf.longitude, dvf.latitude), 'EPSG:4326', 'EPSG:2154')) AS x_2154,
        ST_Y(ST_Transform(ST_Point(dvf.longitude, dvf.latitude), 'EPSG:4326', 'EPSG:2154')) AS y_2154,
        ST_Transform(ST_Point(dvf.longitude, dvf.latitude), 'EPSG:4326', 'EPSG:2154') AS geom_2154
    FROM dvf
    WHERE dvf.longitude IS NOT NULL AND dvf.longitude != 0
      AND dvf.latitude  IS NOT NULL AND dvf.latitude  != 0
""")
print(f"  -> {con.execute('SELECT COUNT(*) FROM adresses_utiles_temp').fetchone()[0]:,} adresses uniques.")

# Etape 2 : dim_adresses — bbox 50km gares, bbox 30km ecoles, CROSS JOIN aeroports
print("  Etape 2 : calcul distances gares / ecoles / aeroports en metres...")
con.execute("""
    CREATE OR REPLACE TABLE dim_adresses AS
    WITH gares_calc AS (
        SELECT
            adr.numero, adr.nom_voie, adr.code_postal,
            g.id_gare  AS id_gare_proche,
            g.nom_gare AS nom_gare_proche,
            ST_Distance(adr.geom_2154, g.geom_2154) AS distance_gare_metres
        FROM adresses_utiles_temp adr
        INNER JOIN dim_gares g
            ON g.x_2154 BETWEEN adr.x_2154 - 50000 AND adr.x_2154 + 50000
           AND g.y_2154 BETWEEN adr.y_2154 - 50000 AND adr.y_2154 + 50000
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY adr.numero, adr.nom_voie, adr.code_postal
            ORDER BY distance_gare_metres ASC
        ) = 1
    ),
    ecoles_calc AS (
        SELECT
            adr.numero, adr.nom_voie, adr.code_postal,
            e.id_ecole  AS id_ecole_proche,
            e.nom_ecole AS nom_ecole_proche,
            ST_Distance(adr.geom_2154, e.geom_2154) AS distance_ecole_metres
        FROM adresses_utiles_temp adr
        INNER JOIN dim_ecoles e
            ON e.x_2154 BETWEEN adr.x_2154 - 30000 AND adr.x_2154 + 30000
           AND e.y_2154 BETWEEN adr.y_2154 - 30000 AND adr.y_2154 + 30000
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY adr.numero, adr.nom_voie, adr.code_postal
            ORDER BY distance_ecole_metres ASC
        ) = 1
    ),
    aero_calc AS (
        -- ~20-100 aeroports : CROSS JOIN suffisant, pas de bbox necessaire
        SELECT
            adr.numero, adr.nom_voie, adr.code_postal,
            a.code_iata        AS code_aeroport_proche,
            a.nom_aeroport     AS nom_aeroport_proche,
            ST_Distance(adr.geom_2154, a.geom_2154) AS distance_aeroport_metres
        FROM adresses_utiles_temp adr
        CROSS JOIN dim_aeroports a
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY adr.numero, adr.nom_voie, adr.code_postal
            ORDER BY distance_aeroport_metres ASC
        ) = 1
    )
    SELECT
        ROW_NUMBER() OVER () AS id_adresse,
        adr.numero, adr.nom_voie, adr.code_postal, adr.nom_commune,
        adr.lon, adr.lat,
        gc.id_gare_proche,
        gc.nom_gare_proche,
        gc.distance_gare_metres,
        ec.id_ecole_proche,
        ec.nom_ecole_proche,
        ec.distance_ecole_metres,
        ac.code_aeroport_proche,
        ac.nom_aeroport_proche,
        ac.distance_aeroport_metres,
        NULL::BIGINT  AS id_iris,
        NULL::VARCHAR AS zone_iris
    FROM adresses_utiles_temp adr
    LEFT JOIN gares_calc  gc ON adr.numero = gc.numero AND adr.nom_voie = gc.nom_voie AND adr.code_postal = gc.code_postal
    LEFT JOIN ecoles_calc ec ON adr.numero = ec.numero AND adr.nom_voie = ec.nom_voie AND adr.code_postal = ec.code_postal
    LEFT JOIN aero_calc   ac ON adr.numero = ac.numero AND adr.nom_voie = ac.nom_voie AND adr.code_postal = ac.code_postal
""")
print(f"  -> {con.execute('SELECT COUNT(*) FROM dim_adresses').fetchone()[0]:,} adresses dans dim_adresses.")

# Etape 2.5 : jointure IRIS optimisee — bounding boxes pre-calculees une seule fois
# Evite N_adresses x N_iris comparaisons ST_Contains (potentiellement 50k x 50k).
print("  Etape 2.5 : jointure spatiale IRIS (bbox pre-filter + point-in-polygon)...")
con.execute("""
    CREATE OR REPLACE TEMP TABLE iris_geoms_temp AS
    SELECT
        id_iris,
        ZONE,
        ST_GeomFromText(geom_wkt)         AS geom,
        ST_XMin(ST_GeomFromText(geom_wkt)) AS lon_min,
        ST_XMax(ST_GeomFromText(geom_wkt)) AS lon_max,
        ST_YMin(ST_GeomFromText(geom_wkt)) AS lat_min,
        ST_YMax(ST_GeomFromText(geom_wkt)) AS lat_max
    FROM dim_iris
    WHERE geom_wkt IS NOT NULL AND TRIM(geom_wkt) != ''
""")
con.execute("""
    WITH adresse_iris_match AS (
        SELECT
            adr.id_adresse,
            i.id_iris,
            i.ZONE AS zone_iris
        FROM dim_adresses adr
        JOIN iris_geoms_temp i
            ON adr.lon BETWEEN i.lon_min AND i.lon_max
           AND adr.lat BETWEEN i.lat_min AND i.lat_max
           AND ST_Contains(i.geom, ST_Point(adr.lon, adr.lat))
        QUALIFY ROW_NUMBER() OVER (PARTITION BY adr.id_adresse ORDER BY i.id_iris) = 1
    )
    UPDATE dim_adresses
    SET
        id_iris   = adresse_iris_match.id_iris,
        zone_iris = adresse_iris_match.zone_iris
    FROM adresse_iris_match
    WHERE dim_adresses.id_adresse = adresse_iris_match.id_adresse
""")
n_iris = con.execute("SELECT COUNT(*) FROM dim_adresses WHERE id_iris IS NOT NULL").fetchone()[0]
print(f"  -> {n_iris:,} adresses associees a une zone IRIS.")

# Etape 3 : fact_dvf
print("  Etape 3 : construction de fact_dvf...")
con.execute("""
    CREATE OR REPLACE TABLE fact_dvf AS
    SELECT
        ROW_NUMBER() OVER () AS id_mutation,
        v.id_adresse,
        dvf.date_mutation,
        dvf.valeur_fonciere,
        dvf.surface_reelle_bati,
        dvf.nombre_pieces_principales,
        dvf.type_local,
        dvf.nature_mutation,
        dvf.code_departement
    FROM dvf
    INNER JOIN dim_adresses v
        ON dvf.adresse_numero   = v.numero
       AND dvf.adresse_nom_voie = v.nom_voie
       AND dvf.code_postal      = v.code_postal
""")
print(f"  -> {con.execute('SELECT COUNT(*) FROM fact_dvf').fetchone()[0]:,} transactions dans fact_dvf.")

# Nettoyage
for t in ["dvf", "adresses_utiles_temp", "iris_geoms_temp"]:
    con.execute(f"DROP TABLE IF EXISTS {t}")
con.execute("ALTER TABLE dim_gares DROP COLUMN geom_2154;")
con.execute("ALTER TABLE dim_gares DROP COLUMN x_2154;")
con.execute("ALTER TABLE dim_gares DROP COLUMN y_2154;")
con.execute("ALTER TABLE dim_ecoles DROP COLUMN geom_2154;")
con.execute("ALTER TABLE dim_ecoles DROP COLUMN x_2154;")
con.execute("ALTER TABLE dim_ecoles DROP COLUMN y_2154;")
con.execute("ALTER TABLE dim_aeroports DROP COLUMN geom_2154;")


# ── Bilan ──────────────────────────────────────────────────────────────────────
tables_finales = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("\n" + "=" * 65)
print("BILAN — info_appart_2.duckdb")
print("=" * 65)
for table, label in [
    ("fact_dvf",      "Faits — ventes DVF 2024-2025"),
    ("dim_adresses",  "Dimension adresses (gares / ecoles / aeroports / IRIS)"),
    ("dim_gares",     "Dimension gares SNCF"),
    ("dim_ecoles",    "Dimension etablissements scolaires"),
    ("dim_aeroports", "Dimension aeroports"),
    ("dim_iris",      "Dimension zones IRIS"),
    ("dpe_final",     "DPE — diagnostics energetiques"),
]:
    if table in tables_finales:
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<22} : {n:>10,}  ({label})")
    else:
        print(f"  {table:<22} : absente")
print("=" * 65)

con.close()
print("Termine.")
