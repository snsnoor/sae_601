import requests
import pandas as pd

base_url = "https://data.sncf.com/api/explore/v2.1/catalog/datasets/liste-des-gares/records"

limit = 100
offset = 0
toutes_les_gares = []

print("Téléchargement des données en cours...")

while True:
    params = {
        "select": "code_uic, libelle, commune, departemen, c_geo",
        "limit": limit,
        "offset": offset
    }
    
    response = requests.get(base_url, params=params)
    response.raise_for_status()

    data = response.json()
    records = data.get("results", [])
    
    if not records:
        break
        
    toutes_les_gares.extend(records)
    offset += limit
    
df_gares = pd.DataFrame(toutes_les_gares)

print(df_gares.head())
print(f"\nNombre total d'individus récupérés : {df_gares.shape[0]}")

df_gares['latitude'] = df_gares['c_geo'].str['lat']
df_gares['longitude'] = df_gares['c_geo'].str['lon']

df_gares = df_gares.drop(columns=['c_geo'])

print("Nouvelles colonnes créées avec succès :")
print(df_gares.head())