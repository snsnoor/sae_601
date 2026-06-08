import os
import tempfile
from pathlib import Path
import duckdb
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape


import config

# Configuration de la base

DB_PATH = str(Path(__file__).resolve().parent / 'info_appart.duckdb')
print(f"Connexion à la base {DB_PATH}...")
con = duckdb.connect(DB_PATH)

# Initialisation obligatoire de l'extension spatiale pour DuckDB
print("Chargement de l'extension spatiale DuckDB...")
con.execute("INSTALL spatial;")
con.execute("LOAD spatial;")

# ------------------- Domain 4 : macro SQL de normalisation d'adresse -------------------
# NOTE (Domain 4) : on crée une MACRO scalaire DuckDB réutilisable côté DVF et côté DPE
# pour fabriquer une clé de jointure textuelle commune (norm_adresse). Elle :
#   - met en minuscules,
#   - retire les accents (strip_accents),
#   - développe les abréviations de voie (r.->rue, av.->avenue, bd->boulevard, st->saint),
#   - supprime la ponctuation,
#   - réduit les espaces multiples à un seul espace puis TRIM.
# L'ordre est important : on développe les abréviations AVANT de supprimer les points,
# sinon "av." aurait déjà perdu son point et matcherait le mot "av".
# NOTE : la table d'abréviations est volontairement minimale (cas demandés) ; on encadre
#        chaque abréviation d'espaces (' av. '->' avenue ') pour ne pas casser des mots
#        contenant la même sous-chaîne (ex. "stade" ne devient pas "sainade").
con.execute(r"""
    CREATE OR REPLACE MACRO normaliser_adresse(adr) AS (
        TRIM(
            REGEXP_REPLACE(  -- 5) espaces multiples -> un seul
                REGEXP_REPLACE(  -- 4) ponctuation restante -> espace
                    REPLACE(REPLACE(REPLACE(REPLACE(  -- 3) abréviations de voie (entourées d'espaces)
                        ' ' || LOWER(strip_accents(COALESCE(adr, ''))) || ' ',  -- 1+2) lower + sans accents, encadré d'espaces
                        ' r. ', ' rue '),
                        ' av. ', ' avenue '),
                        ' bd ', ' boulevard '),
                        ' st ', ' saint '),
                    '[^a-z0-9 ]', ' ', 'g'),
                '\s+', ' ', 'g')
        )
    );
""")

# Nettoyage des tables intermédiaires/dimensions reconstruites à chaque run.

tables_to_drop = [
    "dvf", "dim_gares", "dim_ecoles", "dim_peb", "dim_adresses",
    "dpe_final", "peb_geoms_temp", "adresses_utiles_temp",
    # Domain 6 : dimension socio-économique INSEE (revenu médian + population par commune)
    "dim_commune",
    # Domain 7 : dimension géométrique communale (polygones/contours pour le choroplèthe)
    "dim_communes_geo"
]
for t in tables_to_drop:
    con.execute(f"DROP TABLE IF EXISTS {t};")

# ------------------- 2. Table 'dvf' -------------------
print("\n--- 2. Chargement et nettoyage des données DVF (par département × année) ---")

# Sélection pilotée par config (launcher.py -> selection.json), sinon défauts.
DEPARTEMENTS = config.get_departements()
ANNEES = config.get_annees()
DATA_DIR = Path(__file__).parent / "data"
print(f"Départements : {DEPARTEMENTS} | Années : {ANNEES}")

# On construit la liste des sources : fichier local mis en cache par download_data.py
# si présent (data/dvf/{year}/{dept}.csv.gz), sinon l'URL distante geo-DVF.
# NOTE : les fichiers geo-DVF par département utilisent le délimiteur ',' et portent
#        les mêmes colonnes que le fichier national. À confirmer si le schéma évolue.
sources_dvf = []
for annee in ANNEES:
    for dept in DEPARTEMENTS:
        local = DATA_DIR / "dvf" / str(annee) / f"{dept}.csv.gz"
        if local.exists():
            sources_dvf.append(str(local))
        else:
            sources_dvf.append(config.GEO_DVF_URL.format(year=annee, dept=dept))

# Accumulation via union_by_name : DuckDB lit toutes les sources d'un coup.
# read_csv accepte une liste de chemins/URLs.
liste_sql = "[" + ", ".join(f"'{s}'" for s in sources_dvf) + "]"
con.execute(f"""
    CREATE OR REPLACE TABLE dvf AS
    SELECT
        -- Domain 3 : on sélectionne le VRAI id_mutation source (et id_parcelle si présent),
        -- jusqu'ici omis de la liste SELECT. Ces identifiants permettent de regrouper
        -- les lignes par-parcelle qui appartiennent à une même transaction (mutation).
        -- NOTE : dans les fichiers geo-DVF par département, id_mutation est un VARCHAR
        --        (ex. "2024-123456") répété sur chaque parcelle d'une même vente, et
        --        id_parcelle identifie chaque parcelle cadastrale de la mutation.
        CAST(id_mutation AS VARCHAR) AS id_mutation,
        CAST(id_parcelle AS VARCHAR) AS id_parcelle,
        CAST(date_mutation AS DATE) AS date_mutation,
        valeur_fonciere, surface_reelle_bati, surface_terrain,
        adresse_numero, adresse_suffixe, adresse_code_voie, adresse_nom_voie,
        nombre_pieces_principales, type_local, nature_mutation,
        longitude, latitude,
        -- Domain 6/7 : on PRÉSERVE le code commune INSEE (zéro-padding sur 5 caractères).
        -- Indispensable à la jointure INSEE (revenu/population, Domain 6) et au
        -- choroplèthe communal (Domain 7). Auparavant lu mais jamais propagé.
        LPAD(CAST(code_commune AS VARCHAR), 5, '0') AS code_commune,
        code_postal,
        nom_commune, code_departement
    FROM read_csv(
        {liste_sql},
        delim=',', header=True, union_by_name=True, ignore_errors=True
    )
    -- Domain 3 (qualité) : on RESTREINT aux VRAIES ventes de marché. Règle explicite et
    -- défendable : on garde 'Vente' et 'Vente en l'état futur d'achèvement' (VEFA, achat
    -- de neuf sur plan). On EXCLUT :
    --   - 'Echange'              : pas de prix de marché (troc),
    --   - 'Adjudication'         : ventes aux enchères, prix atypiques,
    --   - 'Vente terrain à bâtir': terrain nu (pas de surface bâtie) -> fausserait le €/m².
    WHERE valeur_fonciere IS NOT NULL
      AND nature_mutation IN ('Vente', 'Vente en l''état futur d''achèvement')
""")

# Nettoyage des valeurs NULL de DVF
cols_numeric = ["surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude", "adresse_numero"]
cols_text = ["type_local", "adresse_code_voie", "adresse_nom_voie", "adresse_suffixe", "code_postal"]

for col in cols_numeric:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')
for col in cols_text:
    # Selon le département, DuckDB peut inférer une colonne comme code_postal en
    # type numérique (ex. dépt 53). On force le type texte avant d'y écrire 'NR'.
    con.execute(f'ALTER TABLE dvf ALTER COLUMN "{col}" TYPE VARCHAR')
    con.execute(f"UPDATE dvf SET \"{col}\" = 'NR' WHERE \"{col}\" IS NULL")

print("Table 'dvf' créée et nettoyée.")

# ------------------- 3. Table 'dim_gares' -------------------
print("\n--- 3. Téléchargement des données des gares SNCF ---")
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
        ST_X(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154', always_xy := true)) AS x_2154,
        ST_Y(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154', always_xy := true)) AS y_2154,
        ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154', always_xy := true) AS geom_2154
    FROM df_gares_temp
    WHERE longitude IS NOT NULL AND latitude IS NOT NULL
""")
print(f"Table 'dim_gares' créée.")

# ------------------- 4. Table 'dim_ecoles' (SHAPEFILE) -------------------

print("\n--- 4. Téléchargement et structuration de dim_ecoles (Shapefile) ---")
_depts3 = [str(d).zfill(3) for d in config.get_departements()]
_where_ecoles = "code_departement in (" + ", ".join(f'"{d}"' for d in _depts3) + ")"
url_ecoles = ("https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
              "fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre/exports/shp")
try:
    response = requests.get(url_ecoles, params={"where": _where_ecoles}, timeout=120)
    response.raise_for_status()

    # Sauvegarde temporaire de l'archive Shapefile (.zip) pour lecture par GeoPandas.
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(response.content)
        temp_path = f.name

    # geopandas lit directement l'archive Shapefile via le préfixe virtuel 'zip://'.
    gdf_ecoles = gpd.read_file(f"zip://{temp_path}")

    # CRS issu du .prj (EPSG:4326) ; repli explicite si jamais absent.
    if gdf_ecoles.crs is None:
        gdf_ecoles = gdf_ecoles.set_crs("EPSG:4326")
    gdf_ecoles = gdf_ecoles.to_crs("EPSG:4326")

    gdf_ecoles["longitude"] = gdf_ecoles.geometry.x
    gdf_ecoles["latitude"] = gdf_ecoles.geometry.y

    # Nom de l'établissement : 'appellation_officielle' (GeoJSON/API) OU 'appellation'
    # (Shapefile : tronqué à 10 car. par le DBF). On gère les deux + d'autres schémas.
    for _cand in ('appellation_officielle', 'appellation', 'name', 'l_etablissement'):
        if 'nom_etablissement' not in gdf_ecoles.columns and _cand in gdf_ecoles.columns:
            gdf_ecoles = gdf_ecoles.rename(columns={_cand: 'nom_etablissement'})
            break

    con.register('df_ecole_temp', gdf_ecoles[['nom_etablissement', 'longitude', 'latitude']])

    con.execute("""
        CREATE OR REPLACE TABLE dim_ecoles AS
        SELECT
            ROW_NUMBER() OVER () AS id_ecole,
            nom_etablissement AS nom_ecole,
            longitude,
            latitude,
            ST_X(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154', always_xy := true)) AS x_2154,
            ST_Y(ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154', always_xy := true)) AS y_2154,
            ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:2154', always_xy := true) AS geom_2154
        FROM df_ecole_temp
        WHERE longitude IS NOT NULL
    """)
    print(f"Table 'dim_ecoles' créée.")

except Exception as e:
    # En cas d'échec de l'API, on crée une table vide pour ne pas casser la suite du pipeline
    print(f"⚠️ Erreur lors de la récupération de l'API écoles : {e}")
    con.execute("CREATE OR REPLACE TABLE dim_ecoles (id_ecole BIGINT, nom_ecole VARCHAR, longitude DOUBLE, latitude DOUBLE, x_2154 DOUBLE, y_2154 DOUBLE, geom_2154 GEOMETRY)")

# ------------------- 5. Table 'dim_peb' (zones de bruit aéroportuaire PEB) -------------------
# NOTE (Domain 5) : cette table était historiquement mal nommée 'dim_iris'. Elle ne
# contient PAS de découpage IRIS de l'INSEE mais les polygones du Plan d'Exposition au
# Bruit (PEB) des aéroports : ZONE = sévérité A/B/C/D, CODE_OACI = code aéroport, NOM.
print("\n--- 5. Téléchargement et structuration des zones de bruit aéroportuaire (PEB) ---")
url = "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"

# Revue [MED] — l'appel réseau PEB était NU (pas de timeout, pas de try/except),
# contrairement à l'étape écoles : une panne réseau interrompait alors TOUT l'ETL.
# On l'enveloppe désormais comme les écoles (timeout + try/except). En cas d'échec,
# on N'INTERROMPT PAS le pipeline : on saute simplement l'étape PEB (dim_peb absente),
# et les étapes en aval (peb_geoms_temp, peb_calc, BILAN) tolèrent cette absence.
try:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
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

    # Sauvegarde essentielle de la géométrie au format texte WKT pour DuckDB
    gdf['geom_wkt'] = gdf['geometry'].apply(lambda x: x.wkt if x else None)
    df_peb_temp = pd.DataFrame(gdf.drop(columns='geometry'))

    con.register('df_peb_temp', df_peb_temp)

    # Création avec typage strict basé sur ton schéma
    con.execute("""
        CREATE OR REPLACE TABLE dim_peb AS
        SELECT
            ROW_NUMBER() OVER () AS id_peb,
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
        FROM df_peb_temp
    """)
    print("Table 'dim_peb' créée.")
except Exception as e:
    # Échec réseau / parsing : on saute l'étape PEB sans casser l'ETL (dim_peb absente).
    print(f"⚠️ Erreur lors de la récupération des polygones PEB : {e}")
    print("⚠️ Étape PEB ignorée — dim_peb absente, les zones de bruit aéroportuaire "
          "(zone_peb/code_oaci/nom_peb) resteront NULL sur dim_adresses.")

# ------------------- 6. Table 'dpe_final' -------------------
print("\n--- 6. Chargement et nettoyage des données DPE ---")
# Chemin multiplateforme via pathlib (évite le backslash Windows non portable)
DPE_FILE = str(Path("data") / "dpe.csv")

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
    cols_header = con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv('{DPE_FILE}', auto_detect=TRUE, all_varchar=TRUE, sample_size=1))").fetchdf()["column_name"].tolist()
    cols_ok = [c for c in COLS_TO_KEEP if c in cols_header]
    select_clause = ", ".join([f'"{c}"' for c in cols_ok])

    con.execute(f"CREATE OR REPLACE TABLE dpe_raw AS SELECT {select_clause} FROM read_csv('{DPE_FILE}', auto_detect=TRUE, all_varchar=TRUE, ignore_errors=True)")

    NUMERIC_IMPUTE = [c for c in ["conso_5_usages_ep", "conso_5_usages_par_m2_ep", "conso_5 usages_ef", "conso_5 usages_par_m2_ef", "emission_ges_5_usages", "emission_ges_5_usages par_m2", "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_refroidissement", "cout_eclairage", "cout_auxiliaires", "surface_habitable_logement", "nombre_niveau_logement", "conso_chauffage_ef"] if c in cols_ok]
    
    medianes = {}
    for col in NUMERIC_IMPUTE:
        val = con.execute(f'SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE)) FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != \'\'').fetchone()[0]
        medianes[col] = val if val is not None else 0
    NUMERIC_IMPUTE = [c for c in ["conso_5_usages_ep", "conso_5_usages_par_m2_ep", "conso_5 usages_ef", "conso_5 usages_par_m2_ef", "emission_ges_5_usages", "emission_ges_5_usages par_m2", "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_refroidissement", "cout_eclairage", "cout_auxiliaires", "surface_habitable_logement", "nombre_niveau_logement", "conso_chauffage_ef"] if c in cols_ok]
    
    medianes = {}
    for col in NUMERIC_IMPUTE:
        val = con.execute(f'SELECT MEDIAN(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE)) FROM dpe_raw WHERE "{col}" IS NOT NULL AND TRIM("{col}") != \'\'').fetchone()[0]
        medianes[col] = val if val is not None else 0

    median_expr = ",\n        ".join([f'COALESCE(TRY_CAST(REPLACE(REPLACE("{col}", \',\', \'.\'), \' \', \'\') AS DOUBLE), {medianes[col]}) AS "{col}"' for col in NUMERIC_IMPUTE])
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

# ------------------- 6bis. Table 'dim_commune' (données socio-économiques INSEE) -------------------
# Domain 6 : on construit une dimension commune portant le revenu médian (FiLoSoFi)

print("\n--- 6bis. Chargement des données socio-économiques INSEE (dim_commune) ---")
INSEE_REVENU_FILE = Path("data") / "insee_filosofi.xlsx"
INSEE_POPULATION_FILE = Path("data") / "insee_population.csv"


def _detecter_colonne(colonnes, prefixes):
    """Renvoie la 1re colonne dont le nom (majuscule) commence par l'un des préfixes."""
    cols_up = {str(c).upper(): c for c in colonnes}
    for nom_up, nom_reel in cols_up.items():
        for p in prefixes:
            if nom_up.startswith(p):
                return nom_reel
    return None


def _charger_revenu_filosofi(chemin):
    """Charge le revenu médian FiLoSoFi : DataFrame [code_commune, revenu_median] ou None."""
    if not chemin.exists():
        print(f"⚠️ Fichier revenus INSEE absent ({chemin}). Revenu médian ignoré.")
        return None
    # NOTE : FiLoSoFi commence par des lignes de métadonnées ; on tente plusieurs
    #        valeurs de skiprows jusqu'à trouver une feuille contenant 'CODGEO'.
    for skip in (5, 0, 4, 6, 3):
        try:
            df = pd.read_excel(chemin, skiprows=skip)
        except Exception as e:
            print(f"⚠️ Lecture FiLoSoFi (skiprows={skip}) échouée : {e}")
            continue
        col_codgeo = _detecter_colonne(df.columns, ["CODGEO"])
        col_med = _detecter_colonne(df.columns, ["MED"])
        if col_codgeo is not None and col_med is not None:
            out = df[[col_codgeo, col_med]].copy()
            out.columns = ["code_commune", "revenu_median"]
            out["code_commune"] = out["code_commune"].astype(str).str.strip().str.zfill(5)
            out["revenu_median"] = pd.to_numeric(out["revenu_median"], errors="coerce")
            out = out.dropna(subset=["code_commune"])
            return out
    print("⚠️ Colonnes CODGEO/MED* introuvables dans le fichier FiLoSoFi — revenu ignoré.")
    return None


def _charger_population(chemin):
    """Charge la population communale au format TEMPOREL multi-millésimes :
    DataFrame [code_commune, annee, population, nom_commune?] ou None.
    Rétro-compatible avec l'ancien format mono-année (sans colonne ANNEE)."""
    if not chemin.exists():
        print(f"⚠️ Fichier population INSEE absent ({chemin}). Population ignorée.")
        return None
    try:
        # On laisse pandas détecter le séparateur (sep=None + moteur python).
        df = pd.read_csv(chemin, sep=None, engine="python", dtype=str)
    except Exception:
        try:
            df = pd.read_excel(chemin)
        except Exception as e:
            print(f"⚠️ Lecture population INSEE échouée : {e}")
            return None
    col_codgeo = _detecter_colonne(df.columns, ["CODGEO", "CODE_COMMUNE", "COM"])
    col_pop = _detecter_colonne(df.columns, ["PMUN", "PTOT", "P_POP", "POP", "P21", "P20", "P19"])
    if col_codgeo is None or col_pop is None:
        print("⚠️ Colonnes CODGEO/population introuvables — population ignorée.")
        return None
    col_annee = _detecter_colonne(df.columns, ["ANNEE", "MILLESIME", "YEAR"])
    col_nom = _detecter_colonne(df.columns, ["LIBGEO", "NOM_COMMUNE", "NOM"])
    cols = [col_codgeo, col_pop] + ([col_annee] if col_annee else []) + ([col_nom] if col_nom else [])
    out = df[cols].copy()
    out.columns = ["code_commune", "population"] + (["annee"] if col_annee else []) + (["nom_commune"] if col_nom else [])
    out["code_commune"] = out["code_commune"].astype(str).str.strip().str.zfill(5)
    out["population"] = pd.to_numeric(out["population"], errors="coerce")
    if "annee" in out.columns:
        out["annee"] = pd.to_numeric(out["annee"], errors="coerce").astype("Int64")
    else:
        out["annee"] = pd.NA  # ancien format mono-année : millésime non porté par le fichier
    out = out.dropna(subset=["code_commune"])
    return out


_df_revenu = _charger_revenu_filosofi(INSEE_REVENU_FILE)
_df_pop = _charger_population(INSEE_POPULATION_FILE)

# Millésime du revenu (source "niveau de vie médian" = 2021). Matérialisé pour rattacher
# le revenu au bon millésime dans la dimension temporelle (Domain temps / SCD).
REVENU_ANNEE = 2021

if _df_revenu is None and _df_pop is None:
    # Aucune source INSEE disponible : on saute proprement (le reste du pipeline,
    # back.py et le dashboard, tolèrent l'absence de dim_commune / dim_commune_temporel).
    print("⚠️ Aucune donnée INSEE (revenu + population) — étapes dim_commune* ignorées.")
else:
    # ----- 1) DIMENSION TEMPORELLE dim_commune_temporel : grain (code_commune, annee) -----
    # « The data model must account for time » : la population varie chaque millésime
    # (recensement annuel, ici 2020→2023) ; le revenu n'est connu que pour 2021 mais le
    # MODÈLE porte l'année, prêt à accueillir d'autres millésimes de revenu plus tard.
    if _df_pop is not None:
        pop = _df_pop.copy()
    else:
        # Pas de population : on fabrique au moins les lignes du millésime revenu.
        pop = pd.DataFrame({"code_commune": _df_revenu["code_commune"], "annee": REVENU_ANNEE, "population": pd.NA})
    if "nom_commune" not in pop.columns:
        pop["nom_commune"] = pd.NA

    rev = _df_revenu.copy() if _df_revenu is not None else pd.DataFrame(columns=["code_commune", "revenu_median"])
    rev["annee"] = REVENU_ANNEE

    # population(année) <- revenu(année) ; le revenu ne se rattache qu'à REVENU_ANNEE.
    temporel = pop.merge(rev[["code_commune", "annee", "revenu_median"]], on=["code_commune", "annee"], how="left")
    # Communes présentes UNIQUEMENT côté revenu (millésime 2021) et absentes de la population.
    if len(rev):
        manquantes = rev[~rev["code_commune"].isin(pop["code_commune"])].copy()
        if len(manquantes):
            manquantes["population"] = pd.NA
            manquantes["nom_commune"] = pd.NA
            temporel = pd.concat(
                [temporel, manquantes[["code_commune", "annee", "population", "nom_commune", "revenu_median"]]],
                ignore_index=True,
            )

    con.register("df_commune_temporel", temporel[["code_commune", "annee", "population", "revenu_median", "nom_commune"]])
    con.execute("""
        CREATE OR REPLACE TABLE dim_commune_temporel AS
        SELECT
            LPAD(CAST(code_commune AS VARCHAR), 5, '0') AS code_commune,
            TRY_CAST(annee AS INTEGER)        AS annee,
            TRY_CAST(population AS DOUBLE)     AS population,
            TRY_CAST(revenu_median AS DOUBLE) AS revenu_median,
            CAST(nom_commune AS VARCHAR)      AS nom_commune
        FROM df_commune_temporel
        WHERE code_commune IS NOT NULL AND annee IS NOT NULL
        -- 1 ligne par (commune, année).
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY LPAD(CAST(code_commune AS VARCHAR), 5, '0'), annee
            ORDER BY population DESC NULLS LAST
        ) = 1
    """)
    _nb_t = con.execute("SELECT COUNT(*) FROM dim_commune_temporel").fetchone()[0]
    _nb_y = con.execute("SELECT COUNT(DISTINCT annee) FROM dim_commune_temporel").fetchone()[0]
    print(f"Table 'dim_commune_temporel' créée : {_nb_t:,} lignes commune×année ({_nb_y} millésimes).")

    # ----- 2) SNAPSHOT dim_commune (1 ligne/commune) pour le dashboard (compat back.py) -----
    # Population du millésime le PLUS RÉCENT + dernier revenu connu, dérivés du temporel.
    con.execute("""
        CREATE OR REPLACE TABLE dim_commune AS
        WITH pop_recente AS (
            SELECT code_commune, population, nom_commune,
                   ROW_NUMBER() OVER (PARTITION BY code_commune ORDER BY annee DESC NULLS LAST) AS _rn
            FROM dim_commune_temporel
        ),
        rev_connu AS (
            SELECT code_commune, revenu_median,
                   ROW_NUMBER() OVER (PARTITION BY code_commune ORDER BY annee DESC NULLS LAST) AS _rn
            FROM dim_commune_temporel WHERE revenu_median IS NOT NULL
        )
        SELECT p.code_commune, r.revenu_median, p.population, p.nom_commune
        FROM (SELECT * FROM pop_recente WHERE _rn = 1) p
        LEFT JOIN (SELECT * FROM rev_connu WHERE _rn = 1) r USING (code_commune)
    """)
    _nb_commune = con.execute("SELECT COUNT(*) FROM dim_commune").fetchone()[0]
    _nb_rev = con.execute("SELECT COUNT(*) FROM dim_commune WHERE revenu_median IS NOT NULL").fetchone()[0]
    print(f"Table 'dim_commune' créée : {_nb_commune:,} communes (snapshot récent, {_nb_rev:,} avec revenu médian).")


# ------------------- 6ter. Table 'dim_communes_geo' (polygones communaux, Domain 7) -------------------
# Domain 7 : on ingère les contours (polygones) des communes pour permettre une carte
# CHOROPLÈTHE clé par code commune INSEE (au lieu d'une carte de points).
# Le fichier data/communes.geojson est produit par download_data.py via geo.api.gouv.fr
# (propriétés 'code' = code INSEE 5 car. + 'nom', géométrie = contour communal).
#
# Cette étape est OPTIONNELLE et DÉFENSIVE : si le fichier de polygones est absent ou
# illisible, on saute proprement (⚠️ + continue), exactement comme les étapes DPE/INSEE,
# afin que le pipeline tourne sans ce fichier (le dashboard bascule alors sur la carte
# de points).
#
# NOTE (équipe) : la géométrie est stockée en WKT (colonne geom_wkt) ET en GeoJSON brut
# (colonne geom_geojson) pour que back.get_communes_geojson() puisse reconstruire un
# FeatureCollection sans dépendre de l'extension spatiale côté lecture.
print("\n--- 6ter. Ingestion des polygones communaux (dim_communes_geo, Domain 7) ---")
COMMUNES_GEOJSON_FILE = DATA_DIR / "communes.geojson"

if not COMMUNES_GEOJSON_FILE.exists():
    print(f"⚠️ Fichier polygones communaux absent ({COMMUNES_GEOJSON_FILE}). "
          "Étape dim_communes_geo ignorée (le choroplèthe basculera sur la carte de points).")
else:
    try:
        import json as _json
        with open(COMMUNES_GEOJSON_FILE, "r", encoding="utf-8") as _f:
            _fc = _json.load(_f)
        _features = _fc.get("features", []) if isinstance(_fc, dict) else []

        # On normalise chaque feature : code INSEE zéro-paddé 5, nom, WKT (via shapely) et
        # GeoJSON de la géométrie. On ignore les features sans géométrie/sans code.
        _rows = []
        for _feat in _features:
            if not isinstance(_feat, dict):
                continue
            _props = _feat.get("properties") or {}
            _geom = _feat.get("geometry")
            _code = _props.get("code") or _props.get("insee") or _props.get("codgeo")
            _nom = _props.get("nom") or _props.get("name")
            if not _code or not _geom:
                continue
            _code = str(_code).strip().zfill(5)
            try:
                _wkt = shape(_geom).wkt  # shapely -> WKT (réutilise l'import existant)
            except Exception:
                _wkt = None
            _rows.append({
                "code_commune": _code,
                "nom_commune": _nom,
                "geom_wkt": _wkt,
                "geom_geojson": _json.dumps(_geom),
            })

        if not _rows:
            print("⚠️ Aucune commune exploitable dans communes.geojson — dim_communes_geo ignorée.")
        else:
            _df_geo = pd.DataFrame(_rows)
            con.register("df_communes_geo_temp", _df_geo)
            con.execute("""
                CREATE OR REPLACE TABLE dim_communes_geo AS
                SELECT
                    -- Clé : code commune INSEE zéro-paddé sur 5 (cohérent avec dim_adresses).
                    LPAD(CAST(code_commune AS VARCHAR), 5, '0') AS code_commune,
                    CAST(nom_commune AS VARCHAR)  AS nom_commune,
                    CAST(geom_wkt AS VARCHAR)     AS geom_wkt,
                    CAST(geom_geojson AS VARCHAR) AS geom_geojson
                FROM df_communes_geo_temp
                WHERE code_commune IS NOT NULL
                -- 1 ligne par commune en cas de doublon.
                QUALIFY ROW_NUMBER() OVER (PARTITION BY LPAD(CAST(code_commune AS VARCHAR), 5, '0') ORDER BY nom_commune) = 1
            """)
            _nb_geo = con.execute("SELECT COUNT(*) FROM dim_communes_geo").fetchone()[0]
            print(f"Table 'dim_communes_geo' créée : {_nb_geo:,} communes avec polygone.")
    except Exception as _e:
        # NOTE : tout échec (JSON corrompu, shapely, etc.) est non bloquant.
        print(f"⚠️ Lecture/ingestion des polygones communaux échouée : {_e} — étape ignorée.")


# ------------------- 7. Modèle en Étoile (Calculs Spatiaux Corrigés) -------------------
print("\n--- 7. RESTRUCTURATION EN MODÈLE EN ÉTOILE (POINT-IN-POLYGON) ---")

# ----- Étape 0 (Domain 8 — géocodage BAN par département) -----
# « Geocoding at scale » : certaines lignes DVF n'ont PAS de coordonnées (geo-DVF a
# parfois échoué à les géocoder). Plutôt que de les JETER, on récupère lon/lat depuis la
# BAN (Base Adresse Nationale) PAR DÉPARTEMENT, par appariement de chaînes
# (numéro + nom de voie NORMALISÉ + code postal). On construit une table de correspondance
# ban_adresses (1 point moyen par clé). DÉFENSIF : si les fichiers BAN sont absents,
# ban_adresses est vide et on retombe sur le comportement précédent (lignes sans coords
# écartées). Source : adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{dept}.csv.gz
print("Étape 0 : Chargement BAN (géocodage des adresses DVF sans coordonnées)...")
_ban_files = [str(DATA_DIR / "ban" / f"{d}.csv.gz") for d in config.get_departements()
              if (DATA_DIR / "ban" / f"{d}.csv.gz").exists()]
if _ban_files:
    _ban_sql = "[" + ", ".join(f"'{p}'" for p in _ban_files) + "]"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ban_adresses AS
        SELECT
            TRY_CAST(numero AS INTEGER)                 AS numero,
            LPAD(CAST(code_postal AS VARCHAR), 5, '0')  AS code_postal,
            normaliser_adresse(nom_voie)                AS norm_voie,
            AVG(TRY_CAST(lon AS DOUBLE))                AS lon,
            AVG(TRY_CAST(lat AS DOUBLE))                AS lat
        FROM read_csv({_ban_sql}, delim=';', header=True, union_by_name=True, ignore_errors=True)
        WHERE lon IS NOT NULL AND lat IS NOT NULL AND numero IS NOT NULL
        GROUP BY 1, 2, 3
    """)
    _nb_ban = con.execute("SELECT COUNT(*) FROM ban_adresses").fetchone()[0]
    print(f"   BAN chargée : {_nb_ban:,} clés (numéro+voie+CP) pour {config.get_departements()}.")
else:
    print("⚠️ Aucun fichier BAN (data/ban/{dept}.csv.gz) — géocodage BAN ignoré.")
    con.execute("CREATE OR REPLACE TEMP TABLE ban_adresses (numero INTEGER, code_postal VARCHAR, norm_voie VARCHAR, lon DOUBLE, lat DOUBLE)")

print("Étape 1 : Indexation des adresses uniques de DVF...")
# Revue [HIGH] — Correction du FAN-OUT d'adresses.
# AVANT : un SELECT DISTINCT sur la ligne ENTIÈRE (commune, lon, lat, code_commune…)
# pouvait produire PLUSIEURS lignes pour une même clé (numero, nom_voie, code_postal)
# dès que les coordonnées ou la commune variaient légèrement entre parcelles. Comme la
# jointure finale fact_dvf se fait UNIQUEMENT sur ces 3 colonnes, chaque clé dupliquée
# multipliait les lignes-parcelles → SUM(surface_reelle_bati)/SUM(surface_terrain)
# gonflées par mutation.
# APRÈS : on garantit UNE SEULE ligne (= un seul futur id_adresse) par clé
# (numero, nom_voie, code_postal). On choisit une parcelle/commune REPRÉSENTATIVE de
# façon DÉTERMINISTE via QUALIFY ROW_NUMBER() (commune et coordonnées les plus
# fréquentes/stables, départagées par valeurs ASC) afin que le résultat soit
# reproductible d'un run à l'autre. La clé adresse devient ainsi réellement unique et
# la jointure finale ne peut plus démultiplier les parcelles.
con.execute("""
    CREATE OR REPLACE TEMP TABLE adresses_utiles_temp AS
    SELECT
        numero, nom_voie, code_postal, nom_commune, code_commune,
        lon, lat,
        ST_X(ST_Transform(ST_Point(lon, lat), 'EPSG:4326', 'EPSG:2154', always_xy := true)) AS x_2154,
        ST_Y(ST_Transform(ST_Point(lon, lat), 'EPSG:4326', 'EPSG:2154', always_xy := true)) AS y_2154,
        ST_Transform(ST_Point(lon, lat), 'EPSG:4326', 'EPSG:2154', always_xy := true) AS geom_2154
    FROM (
        SELECT
            dvf.adresse_numero AS numero, dvf.adresse_nom_voie AS nom_voie,
            dvf.code_postal, dvf.nom_commune,
            -- Domain 6/7 : on porte le code commune INSEE jusque dans dim_adresses.
            dvf.code_commune,
            -- Domain 8 : coordonnées DVF si présentes (!=0), SINON récupérées via la BAN
            -- (appariement numéro + voie normalisée + code postal). On NE JETTE donc plus
            -- les adresses DVF dépourvues de coordonnées quand la BAN peut les géocoder.
            COALESCE(NULLIF(dvf.longitude, 0), ban.lon) AS lon,
            COALESCE(NULLIF(dvf.latitude, 0), ban.lat)  AS lat
        FROM dvf
        LEFT JOIN ban_adresses ban
            ON ban.numero = TRY_CAST(dvf.adresse_numero AS INTEGER)
           AND ban.code_postal = LPAD(CAST(dvf.code_postal AS VARCHAR), 5, '0')
           AND ban.norm_voie = normaliser_adresse(dvf.adresse_nom_voie)
        -- On garde la ligne si elle a des coordonnées APRÈS repli BAN (DVF ou BAN).
        WHERE COALESCE(NULLIF(dvf.longitude, 0), ban.lon) IS NOT NULL
          AND COALESCE(NULLIF(dvf.latitude, 0), ban.lat) IS NOT NULL
        -- Une seule ligne représentative par clé adresse (déterministe).
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY dvf.adresse_numero, dvf.adresse_nom_voie, dvf.code_postal
            ORDER BY dvf.code_commune, dvf.nom_commune,
                     COALESCE(NULLIF(dvf.longitude, 0), ban.lon),
                     COALESCE(NULLIF(dvf.latitude, 0), ban.lat)
        ) = 1
    );
""")

print("Étape 2 : Pré-filtrage par Bounding Box des géométries PEB (Optimisation vitesse)...")
# Revue [MED] — dim_peb est désormais OPTIONNELLE (l'étape 5 peut être sautée en cas
# de panne réseau). On construit peb_geoms_temp à partir de dim_peb SI elle existe,
# sinon on crée un peb_geoms_temp VIDE au bon schéma : ainsi le LEFT JOIN de peb_calc
# fonctionne quand même et laisse zone_peb/code_oaci/nom_peb à NULL (= hors zone PEB),
# ce qui préserve le SET DE COLONNES de dim_adresses (contrat ETL→back→front).
_peb_presente = "dim_peb" in [r[0] for r in con.execute("SHOW TABLES").fetchall()]
if _peb_presente:
    con.execute("""
        CREATE OR REPLACE TEMP TABLE peb_geoms_temp AS
        SELECT
            id_peb, ZONE, CODE_OACI, NOM,
            ST_GeomFromText(geom_wkt) AS geom,
            ST_XMin(ST_GeomFromText(geom_wkt)) AS lon_min,
            ST_XMax(ST_GeomFromText(geom_wkt)) AS lon_max,
            ST_YMin(ST_GeomFromText(geom_wkt)) AS lat_min,
            ST_YMax(ST_GeomFromText(geom_wkt)) AS lat_max
        FROM dim_peb
        WHERE geom_wkt IS NOT NULL;
    """)
else:
    # dim_peb absente : peb_geoms_temp vide (schéma identique) pour ne pas casser peb_calc.
    print("⚠️ dim_peb absente — peb_geoms_temp vide (aucune zone PEB propagée).")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE peb_geoms_temp (
            id_peb BIGINT, ZONE VARCHAR, CODE_OACI VARCHAR, NOM VARCHAR,
            geom GEOMETRY,
            lon_min DOUBLE, lon_max DOUBLE, lat_min DOUBLE, lat_max DOUBLE
        );
    """)

print("Étape 3 : Génération de dim_adresses (LEFT JOIN pour garder toutes les adresses)...")
# NOTE (Domain 2) : dim_adresses est reconstruite à partir du 'dvf' courant (= seulement
# les départements sélectionnés). Pour un upsert multi-départements robuste où d'anciens
# départements restent interrogeables, il faudrait rendre dim_adresses persistante elle
# aussi (clé naturelle numero+nom_voie+code_postal). À arbitrer par l'équipe : pour
# l'instant, relancer un sous-ensemble suppose de relancer l'ETL sur l'ensemble voulu.
# On porte depuis test_jointure.py la CTE ecoles_calc (distance_ecole_metres / nom_ecole_proche)
# en plus des gares et de la propagation des zones de bruit aéroportuaire PEB
# (zone_peb / code_oaci / nom_peb) via les polygones du Plan d'Exposition au Bruit (table dim_peb)
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
            e.id_ecole AS id_ecole_proche,
            e.nom_ecole AS nom_ecole_proche,
            ST_Distance(adr.geom_2154, e.geom_2154) AS distance_ecole_metres
        FROM adresses_utiles_temp adr
        INNER JOIN dim_ecoles e ON e.x_2154 BETWEEN adr.x_2154 - 30000 AND adr.x_2154 + 30000
                              AND e.y_2154 BETWEEN adr.y_2154 - 30000 AND adr.y_2154 + 30000
        QUALIFY ROW_NUMBER() OVER(PARTITION BY adr.numero, adr.nom_voie, adr.code_postal ORDER BY distance_ecole_metres ASC) = 1
    ),
    peb_calc AS (
        -- Domain 5 : propagation des zones de bruit aéroportuaire (PEB) sur les adresses.
        -- On rapproche chaque adresse du polygone PEB qui la CONTIENT (point-in-polygon)
        -- et on porte la sévérité (zone_peb) ET le code aéroport (code_oaci) DU MÊME
        -- polygone, pour qu'ils soient toujours cohérents entre eux.
        SELECT
            adr.numero, adr.nom_voie, adr.code_postal,
            i.id_peb,
            i.ZONE AS zone_peb,
            i.CODE_OACI AS code_oaci,
            i.NOM AS nom_peb
        FROM adresses_utiles_temp adr
        -- Le LEFT JOIN préserve l'adresse même si elle n'est pas dans un polygone aéroportuaire
        -- (dans ce cas zone_peb/code_oaci/nom_peb restent NULL = "hors zone PEB").
        LEFT JOIN peb_geoms_temp i
            ON adr.lon BETWEEN i.lon_min AND i.lon_max
           AND adr.lat BETWEEN i.lat_min AND i.lat_max
           AND ST_Contains(i.geom, ST_Point(adr.lon, adr.lat))
        -- En cas de chevauchement de polygones, on retient la zone la PLUS sévère
        -- (A > B > C > D) afin que zone_peb et code_oaci proviennent du même polygone.
        QUALIFY ROW_NUMBER() OVER(
            PARTITION BY adr.numero, adr.nom_voie, adr.code_postal
            ORDER BY i.ZONE ASC NULLS LAST, i.id_peb
        ) = 1
    )
    SELECT
        ROW_NUMBER() OVER () AS id_adresse,
        adr.numero, adr.nom_voie, adr.code_postal, adr.nom_commune,
        -- Domain 6/7 : code commune INSEE conservé dans la table finale dim_adresses.
        adr.code_commune,
        adr.lon, adr.lat,
        -- Domain 4 : on CONSERVE les coordonnées Lambert-93 (EPSG:2154) dans dim_adresses
        -- (auparavant calculées seulement dans le temp et perdues), nécessaires au
        -- rapprochement spatial DPE. On garde aussi la géométrie geom_2154.
        adr.x_2154, adr.y_2154, adr.geom_2154,
        -- Domain 4 : clé de jointure adresse normalisée (numéro + voie) côté DVF,
        -- pour départager le rapprochement DPE quand plusieurs DPE sont équidistants.
        normaliser_adresse(CAST(adr.numero AS VARCHAR) || ' ' || adr.nom_voie) AS norm_adresse,
        gc.id_gare_proche, gc.nom_gare_proche, gc.distance_gare_metres,
        ec.id_ecole_proche, ec.nom_ecole_proche, ec.distance_ecole_metres,
        pc.id_peb, pc.zone_peb, pc.code_oaci, pc.nom_peb
    FROM adresses_utiles_temp adr
    LEFT JOIN gares_calc gc ON adr.numero = gc.numero AND adr.nom_voie = gc.nom_voie AND adr.code_postal = gc.code_postal
    LEFT JOIN ecoles_calc ec ON adr.numero = ec.numero AND adr.nom_voie = ec.nom_voie AND adr.code_postal = ec.code_postal
    LEFT JOIN peb_calc pc ON adr.numero = pc.numero AND adr.nom_voie = pc.nom_voie AND adr.code_postal = pc.code_postal;
""")

# ------------------- Domain 4 : rapprochement DPE <-> dim_adresses -------------------
# Objectif : la table dpe_final était ORPHELINE (jamais jointe aux ventes). On la
# relie ici à dim_adresses par un PLUS PROCHE VOISIN spatial en EPSG:2154, restreint
# à la même commune (via code INSEE), avec pré-filtre par bounding box ±200 m (même
# logique d'optimisation que les gares/écoles), départagé par l'adresse normalisée.
# On enrichit ENSUITE dim_adresses avec : id_dpe, etiquette_dpe, etiquette_ges,
# conso_5_usages_par_m2_ep, distance_dpe_metres.
#
# NOTE (CRS des coordonnées DPE — À CONFIRMER IMPÉRATIVEMENT SUR DONNÉES) :
#       coordonnee_cartographique_x/y_ban sont SUPPOSÉES être en Lambert-93 (EPSG:2154),
#       comme dim_adresses.x_2154/y_2154 — on compare donc directement (pré-filtre bbox
#       ±200 m + ST_Distance). Si l'ADEME publiait ces colonnes dans un AUTRE CRS (ex.
#       EPSG:4326), le pré-filtre bbox ±200 m ne matcherait JAMAIS rien et TOUS les
#       rapprochements tomberaient à 0 SANS lever d'erreur. Pour éviter cet échec
#       silencieux, on ajoute plus bas une ASSERTION DE GARDE : si dpe_final contient
#       des lignes exploitables mais qu'AUCUNE adresse n'obtient d'étiquette DPE, on
#       affiche un avertissement ⚠️ bruyant signalant un CRS probablement erroné.
#       Le correctif définitif (si confirmé) : reprojeter ici via ST_Transform.

if "dpe_final" in [r[0] for r in con.execute("SHOW TABLES").fetchall()]:
    print("Étape 3bis : Rapprochement spatial DPE <-> dim_adresses (plus proche voisin, ±200 m, même commune)...")
    # On reconstruit une géométrie 2154 pour les DPE valides (coords != -999 sentinelle).
    con.execute("""
        CREATE OR REPLACE TEMP TABLE dpe_geoms_temp AS
        SELECT
            numero_dpe AS id_dpe,
            code_insee_ban,
            etiquette_dpe,
            etiquette_ges,
            conso_5_usages_par_m2_ep,
            normaliser_adresse(adresse_brut) AS norm_adresse,
            coordonnee_cartographique_x_ban AS x_2154,
            coordonnee_cartographique_y_ban AS y_2154,
            ST_Point(coordonnee_cartographique_x_ban, coordonnee_cartographique_y_ban) AS geom_2154
        FROM dpe_final
        WHERE coordonnee_cartographique_x_ban IS NOT NULL
          AND coordonnee_cartographique_x_ban > 0
          AND coordonnee_cartographique_y_ban IS NOT NULL
          AND coordonnee_cartographique_y_ban > 0;
    """)

    # NOTE : dim_adresses ne porte pas le code INSEE commune (Domain 6), on restreint
    #        donc le voisinage par la bbox ±200 m EPSG:2154 (suffisant pour rester
    #        dans la même commune en pratique) et on départage par norm_adresse égale.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE dpe_match_temp AS
        SELECT
            a.id_adresse,
            d.id_dpe,
            d.etiquette_dpe,
            d.etiquette_ges,
            d.conso_5_usages_par_m2_ep,
            ST_Distance(a.geom_2154, d.geom_2154) AS distance_dpe_metres
        FROM dim_adresses a
        INNER JOIN dpe_geoms_temp d
            ON d.x_2154 BETWEEN a.x_2154 - 200 AND a.x_2154 + 200
           AND d.y_2154 BETWEEN a.y_2154 - 200 AND a.y_2154 + 200
        WHERE a.x_2154 IS NOT NULL AND a.y_2154 IS NOT NULL
        -- Plus proche voisin ; à distance égale, on préfère l'adresse normalisée identique.
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY a.id_adresse
            ORDER BY ST_Distance(a.geom_2154, d.geom_2154) ASC,
                     (a.norm_adresse = d.norm_adresse) DESC
        ) = 1;
    """)

    # On matérialise dim_adresses enrichie (LEFT JOIN -> NULL si pas de DPE proche).
    con.execute("""
        CREATE OR REPLACE TABLE dim_adresses AS
        SELECT
            a.*,
            m.id_dpe,
            m.etiquette_dpe,
            m.etiquette_ges,
            m.conso_5_usages_par_m2_ep,
            m.distance_dpe_metres
        FROM dim_adresses a
        LEFT JOIN dpe_match_temp m ON a.id_adresse = m.id_adresse;
    """)
    nb_dpe_match = con.execute("SELECT COUNT(*) FROM dim_adresses WHERE etiquette_dpe IS NOT NULL").fetchone()[0]
    nb_adr_tot = con.execute("SELECT COUNT(*) FROM dim_adresses").fetchone()[0]
    print(f"   ✅ DPE rapprochés : {nb_dpe_match:,} / {nb_adr_tot:,} adresses dotées d'une étiquette DPE.")

    # Revue [HIGH] — ASSERTION DE GARDE sur le CRS des coordonnées DPE.
    # Si dpe_final contient des DPE GÉOLOCALISABLES (coords valides) mais qu'AUCUNE
    # adresse n'a obtenu d'étiquette DPE, c'est le symptôme typique d'un CRS erroné
    # (coordonnees_cartographique_x/y_ban PAS en EPSG:2154) : le pré-filtre bbox ±200 m
    # ne matche rien. On le signale BRUYAMMENT pour qu'un vrai run échoue de façon
    # visible plutôt que de produire silencieusement 0 match.
    nb_dpe_geolocalisables = con.execute("""
        SELECT COUNT(*) FROM dpe_final
        WHERE coordonnee_cartographique_x_ban IS NOT NULL
          AND coordonnee_cartographique_x_ban > 0
          AND coordonnee_cartographique_y_ban IS NOT NULL
          AND coordonnee_cartographique_y_ban > 0
    """).fetchone()[0]
    if nb_dpe_geolocalisables > 0 and nb_dpe_match == 0:
        print("=======================================================================")
        print("⚠️⚠️⚠️ ALERTE CRS DPE : 0 adresse rapprochée alors que "
              f"{nb_dpe_geolocalisables:,} DPE sont géolocalisables.")
        print("⚠️ Le CRS de coordonnee_cartographique_x/y_ban n'est PROBABLEMENT PAS")
        print("⚠️ EPSG:2154 (Lambert-93). Vérifiez le CRS sur un échantillon ADEME et")
        print("⚠️ reprojetez via ST_Transform avant le rapprochement (cf. NOTE ci-dessus).")
        print("=======================================================================")

    con.execute("DROP TABLE IF EXISTS dpe_geoms_temp; DROP TABLE IF EXISTS dpe_match_temp;")
else:
    # Pas de DPE chargé : on ajoute quand même les colonnes (NULL) pour que back.py
    # puisse les interroger sans condition d'existence (schéma stable).
    print("⚠️ dpe_final absent — ajout de colonnes DPE vides sur dim_adresses.")
    con.execute("ALTER TABLE dim_adresses ADD COLUMN id_dpe VARCHAR;")
    con.execute("ALTER TABLE dim_adresses ADD COLUMN etiquette_dpe VARCHAR;")
    con.execute("ALTER TABLE dim_adresses ADD COLUMN etiquette_ges VARCHAR;")
    con.execute("ALTER TABLE dim_adresses ADD COLUMN conso_5_usages_par_m2_ep DOUBLE;")
    con.execute("ALTER TABLE dim_adresses ADD COLUMN distance_dpe_metres DOUBLE;")

print("Étape 4 : Liaison finale avec la table de faits 'fact_dvf' (upsert idempotent par département × année)...")

# NOTE (Domain 2 — idempotence) : fact_dvf est PERSISTANTE entre les runs.
# On la crée si absente, puis pour chaque (département, année) sélectionné on
# SUPPRIME les lignes correspondantes avant de les ré-insérer. Ainsi, relancer
# l'ingestion d'un seul département laisse les autres départements intacts.
# On ajoute une colonne 'annee' (dérivée de date_mutation, qui reste typée DATE).
#
# Domain 3 : id_mutation est désormais le VRAI identifiant source (VARCHAR) et
# fait office de clé de grain — une ligne = une transaction (mutation), plus une
# ligne = une parcelle. On ajoute surface_terrain (somme par mutation).
con.execute("""
    CREATE TABLE IF NOT EXISTS fact_dvf (
        id_mutation VARCHAR,
        id_adresse BIGINT,
        date_mutation DATE,
        valeur_fonciere DOUBLE,
        surface_reelle_bati DOUBLE,
        surface_terrain DOUBLE,
        nombre_pieces_principales DOUBLE,
        type_local VARCHAR,
        nature_mutation VARCHAR,
        code_departement VARCHAR,
        annee INTEGER,
        prix_m2 DOUBLE
    );
""")

# Migration : ajoute prix_m2 si la table existait avant cette version.
existing_cols = [r[0] for r in con.execute("DESCRIBE fact_dvf").fetchall()]
if "prix_m2" not in existing_cols:
    con.execute("ALTER TABLE fact_dvf ADD COLUMN prix_m2 DOUBLE;")

# Suppression ciblée des lignes (département, année) qu'on s'apprête à recharger.
depts_sql = "[" + ", ".join(f"'{d}'" for d in DEPARTEMENTS) + "]"
annees_sql = "[" + ", ".join(str(a) for a in ANNEES) + "]"
con.execute(f"""
    DELETE FROM fact_dvf
    WHERE code_departement IN {depts_sql}
      AND annee IN {annees_sql};
""")

# ------------------- Domain 3 : règles d'outliers documentées au niveau ETL -------------------

PRIX_M2_MIN = 50
PRIX_M2_MAX = 400000

# ------------------- Domain 3 : déduplication / agrégation par transaction -------------------

con.execute(f"""
    INSERT INTO fact_dvf
    WITH dvf_jointe AS (
        -- Jointure parcelle -> adresse géocodée AVANT regroupement par mutation.
        SELECT
            dvf.id_mutation,
            dvf.id_parcelle,
            v.id_adresse,
            dvf.date_mutation,
            dvf.valeur_fonciere,
            dvf.surface_reelle_bati,
            dvf.surface_terrain,
            dvf.nombre_pieces_principales,
            dvf.type_local,
            dvf.nature_mutation,
            dvf.code_departement
        FROM dvf
        INNER JOIN dim_adresses v
            ON dvf.adresse_numero = v.numero
           AND dvf.adresse_nom_voie = v.nom_voie
           AND dvf.code_postal = v.code_postal
        WHERE dvf.id_mutation IS NOT NULL
    ),
    parcelle_representative AS (
        -- Choix déterministe de la parcelle qui portera adresse / type / nature.
        SELECT
            id_mutation, id_adresse, type_local, nature_mutation, date_mutation,
            nombre_pieces_principales,
            ROW_NUMBER() OVER (
                PARTITION BY id_mutation
                ORDER BY surface_reelle_bati DESC NULLS LAST, id_parcelle
            ) AS _rn
        FROM dvf_jointe
    ),
    agrege AS (
        -- 1 ligne par mutation : valeur_fonciere = MAX (répétée), surfaces sommées.
        SELECT
            id_mutation,
            MAX(valeur_fonciere)      AS valeur_fonciere,
            SUM(surface_reelle_bati)  AS surface_reelle_bati,
            SUM(surface_terrain)      AS surface_terrain,
            ANY_VALUE(code_departement) AS code_departement
        FROM dvf_jointe
        GROUP BY id_mutation
    )
    SELECT
        a.id_mutation,
        r.id_adresse,
        r.date_mutation,
        a.valeur_fonciere,
        a.surface_reelle_bati,
        a.surface_terrain,
        r.nombre_pieces_principales,
        r.type_local,
        r.nature_mutation,
        a.code_departement,
        CAST(YEAR(r.date_mutation) AS INTEGER) AS annee,
        ROUND(a.valeur_fonciere / NULLIF(a.surface_reelle_bati, 0), 2) AS prix_m2
    FROM agrege a
    INNER JOIN parcelle_representative r
        ON a.id_mutation = r.id_mutation AND r._rn = 1
    -- Application des règles d'outliers documentées ci-dessus (qualité prix).
    WHERE a.valeur_fonciere > 1
      AND a.surface_reelle_bati > 0
      AND a.valeur_fonciere / NULLIF(a.surface_reelle_bati, 0)
          BETWEEN {PRIX_M2_MIN} AND {PRIX_M2_MAX};
""")

# ------------------- Domain 3 : contrôles qualité explicites et tracés -------------------
# Comptage AVANT dédoublonnage : nombre de lignes-parcelles (jointes) pour le
# périmètre rechargé, et nombre de mutations distinctes attendues. On compare au
# nombre de lignes effectivement insérées (après dédoublonnage + filtres outliers).
nb_lignes_parcelles = con.execute(f"""
    SELECT COUNT(*) FROM dvf
    INNER JOIN dim_adresses v
        ON dvf.adresse_numero = v.numero
       AND dvf.adresse_nom_voie = v.nom_voie
       AND dvf.code_postal = v.code_postal
    WHERE dvf.id_mutation IS NOT NULL
""").fetchone()[0]
nb_mutations_brutes = con.execute("""
    SELECT COUNT(DISTINCT id_mutation) FROM dvf WHERE id_mutation IS NOT NULL
""").fetchone()[0]
nb_apres = con.execute(f"""
    SELECT COUNT(*) FROM fact_dvf
    WHERE code_departement IN {depts_sql} AND annee IN {annees_sql}
""").fetchone()[0]

print("\n--- Contrôles qualité Domain 3 (DVF dédoublonnage) ---")
print(f"   Lignes-parcelles (avant dédoublonnage)       : {nb_lignes_parcelles:,}")
print(f"   Mutations distinctes (id_mutation source)    : {nb_mutations_brutes:,}")
print(f"   Lignes insérées dans fact_dvf (après filtres): {nb_apres:,}")

# Contrôle 1 : id_mutation doit être UNIQUE dans fact_dvf (1 ligne = 1 transaction).
nb_doublons = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT id_mutation FROM fact_dvf GROUP BY id_mutation HAVING COUNT(*) > 1
    )
""").fetchone()[0]
if nb_doublons > 0:
    raise ValueError(
        f"⚠️ QUALITÉ : {nb_doublons} id_mutation dupliqué(s) dans fact_dvf — "
        "la déduplication par transaction a échoué."
    )
print(f"   ✅ id_mutation unique dans fact_dvf (0 doublon).")

# Contrôle 2 : pas de NULL inattendu sur les colonnes critiques.
nb_nulls = con.execute("""
    SELECT COUNT(*) FROM fact_dvf
    WHERE valeur_fonciere IS NULL
       OR surface_reelle_bati IS NULL
       OR id_adresse IS NULL
""").fetchone()[0]
if nb_nulls > 0:
    print(
        f"⚠️ QUALITÉ : {nb_nulls} ligne(s) de fact_dvf avec NULL sur "
        "valeur_fonciere / surface_reelle_bati / id_adresse — à investiguer."
    )
else:
    print("   ✅ Aucun NULL inattendu sur valeur_fonciere / surface_reelle_bati / id_adresse.")

# Nettoyage final des index géométriques lourds et intermédiaires pour libérer de l'espace
con.execute("DROP TABLE IF EXISTS dvf; DROP TABLE IF EXISTS adresses_utiles_temp; DROP TABLE IF EXISTS peb_geoms_temp;")
con.execute("ALTER TABLE dim_gares DROP COLUMN geom_2154; ALTER TABLE dim_gares DROP COLUMN x_2154; ALTER TABLE dim_gares DROP COLUMN y_2154;")
# Nettoyage des colonnes géométriques de calcul devenues inutiles sur dim_ecoles
con.execute("ALTER TABLE dim_ecoles DROP COLUMN geom_2154; ALTER TABLE dim_ecoles DROP COLUMN x_2154; ALTER TABLE dim_ecoles DROP COLUMN y_2154;")

# ------------------- Fin du script -------------------

print("\n=======================================================================")
print("📊 BILAN DU PROLOGUE")
print("=======================================================================")
print(f"-> Table 'fact_dvf' (Faits)         : {con.execute('SELECT COUNT(*) FROM fact_dvf').fetchone()[0]:,} ventes")
print(f"-> Table 'dim_adresses' (Spatial)   : {con.execute('SELECT COUNT(*) FROM dim_adresses').fetchone()[0]:,} adresses structurées")
# Revue [MED] : dim_peb est optionnelle (sautée si l'appel réseau PEB échoue) — on garde le COUNT sous garde d'existence pour ne pas planter le BILAN.
if "dim_peb" in [r[0] for r in con.execute("SHOW TABLES").fetchall()]:
    print(f"-> Table 'dim_peb' (Dimension)      : {con.execute('SELECT COUNT(*) FROM dim_peb').fetchone()[0]:,} zones de bruit aéroportuaire (PEB) enregistrées")
else:
    print("-> Table 'dim_peb' (Dimension)      : absente (étape PEB sautée, échec réseau)")
# Domain 5 : nb d'adresses effectivement situées dans une zone PEB (couverture réelle).
_nb_peb = con.execute("SELECT COUNT(*) FROM dim_adresses WHERE zone_peb IS NOT NULL").fetchone()[0]
print(f"-> dim_adresses en zone PEB         : {_nb_peb:,} adresses (zone_peb/code_oaci renseignés, Domain 5)")
print(f"-> Table 'dim_gares' (Dimension)    : {con.execute('SELECT COUNT(*) FROM dim_gares').fetchone()[0]:,} gares routières/SNCF enregistrées")
print(f"-> Table 'dim_ecoles' (Dimension)   : {con.execute('SELECT COUNT(*) FROM dim_ecoles').fetchone()[0]:,} établissements scolaires enregistrés")
# Revue 2026-06-05 : dpe_final est optionnelle (sautée si data/dpe.csv absent) — on garde le COUNT pour ne pas planter le BILAN.
if "dpe_final" in [r[0] for r in con.execute("SHOW TABLES").fetchall()]:
    print(f"-> Table 'dpe_final' (Logements)    : {con.execute('SELECT COUNT(*) FROM dpe_final').fetchone()[0]:,} diagnostics uniques")
else:
    print("-> Table 'dpe_final' (Logements)    : absente (étape DPE sautée, data/dpe.csv manquant)")
# Domain 4 : taux d'adresses dotées d'une étiquette DPE après rapprochement spatial.
_nb_dpe = con.execute("SELECT COUNT(*) FROM dim_adresses WHERE etiquette_dpe IS NOT NULL").fetchone()[0]
print(f"-> dim_adresses avec étiquette DPE  : {_nb_dpe:,} adresses rapprochées (Domain 4)")
# Domain 6 : dimension socio-économique INSEE (optionnelle — peut être absente).
_tables_finales = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
if "dim_commune" in _tables_finales:
    _nb_commune_bilan = con.execute("SELECT COUNT(*) FROM dim_commune").fetchone()[0]
    _nb_revenu = con.execute("SELECT COUNT(*) FROM dim_commune WHERE revenu_median IS NOT NULL").fetchone()[0]
    print(f"-> Table 'dim_commune' (INSEE)      : {_nb_commune_bilan:,} communes ({_nb_revenu:,} avec revenu médian, Domain 6)")
else:
    print("-> Table 'dim_commune' (INSEE)      : absente (fichiers INSEE non fournis, Domain 6)")
# Domain 7 : dimension géométrique communale (optionnelle — peut être absente).
if "dim_communes_geo" in _tables_finales:
    _nb_geo_bilan = con.execute("SELECT COUNT(*) FROM dim_communes_geo").fetchone()[0]
    print(f"-> Table 'dim_communes_geo' (Géo)   : {_nb_geo_bilan:,} polygones communaux (choroplèthe, Domain 7)")
else:
    print("-> Table 'dim_communes_geo' (Géo)   : absente (communes.geojson non fourni, Domain 7)")
print("=======================================================================")

con.close()
print("\nProcessus terminé avec succès.")
print("\nProcessus terminé avec succès.")
