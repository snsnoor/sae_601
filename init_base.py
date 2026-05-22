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
url = "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20260405-002321/valeursfoncieres-2025.txt.zip"
zip_path = "valeursfoncieres-2025.zip"

print("Téléchargement des données DVF...")
urllib.request.urlretrieve(url, zip_path)

with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall(".")
    txt_path = z.namelist()[0]

print(f"Chargement de {txt_path} dans la base...")
con.execute(f"""
    CREATE OR REPLACE TABLE dvf AS
    SELECT * FROM read_csv_auto('{txt_path}', delim='|', header=True, ignore_errors=True)
""")

# Nettoyage rapide de la table DVF
cols_numeric = ["Surface reelle bati", "Nombre pieces principales", "Code postal"]
cols_text = ["Type local", "Code voie", "Voie"]

for col in cols_numeric:
    con.execute(f'UPDATE dvf SET "{col}" = 0 WHERE "{col}" IS NULL')
for col in cols_text:
    con.execute(f'UPDATE dvf SET "{col}" = \'NR\' WHERE "{col}" IS NULL')

print("Table 'dvf' créée et nettoyée.")

con.close()
