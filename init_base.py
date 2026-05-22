import duckdb
import glob
import urllib.request
import zipfile

# Connexion à la base
con = duckdb.connect('info_appart.duckdb')

# ------------------- adresses -------------------

# 1. Lister tous les fichiers
fichiers = glob.glob('data/adresses-*.csv')

# 2. Création de la table 'adresses' dans DuckDB
print("Chargement des données dans la base...")

con.execute("""
    CREATE OR REPLACE TABLE adresses AS 
    SELECT * FROM read_csv_auto('data/adresses-*.csv', sep=';', union_by_name=True, ignore_errors=True)
""")

# 3. Vérification du nombre de lignes total
nombre_lignes = con.execute("SELECT COUNT(*) FROM adresses").fetchone()[0]
print(f"Succès ! La table 'adresses' contient {nombre_lignes} lignes.")

# ------------------- 'dvf' (Téléchargement & Intégration) -------------------

con.execute("""
    CREATE TABLE dvf AS
    SELECT
        date_mutation, valeur_fonciere, surface_reelle_bati,
        adresse_numero, adresse_suffixe, adresse_code_voie, adresse_nom_voie,
        nombre_pieces_principales, type_local, nature_mutation,
        longitude, latitude, code_commune, code_postal,
        nom_commune, code_departement
    FROM read_csv(
        'https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres-geolocalisees/20260424-090024/dvf.csv.gz',
        delim=',',
        header=True,
        ignore_errors=True
    )
    WHERE YEAR(CAST(date_mutation AS DATE)) IN (2024, 2025)
    AND valeur_fonciere IS NOT NULL
""")

total = con.execute("SELECT COUNT(*) FROM dvf").fetchone()[0]
print(f"\n Nombre de lignes chargées : {total:,}")

# --------Nettoyage et modification de la table DVF

# Colonnes numériques : 0
cols_numeric = ["surface_reelle_bati", "nombre_pieces_principales",
                "longitude", "latitude", "adresse_numero"]
for col in cols_numeric:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')

# Colonnes texte : 'NR'
cols_text = ["type_local", "adresse_code_voie", "adresse_nom_voie",
             "adresse_suffixe", "code_postal"]
for col in cols_text:
    con.execute(f"UPDATE dvf SET \"{col}\" = 'NR' WHERE \"{col}\" IS NULL")

























print("Table 'dvf' créée et nettoyée.")

con.close()
