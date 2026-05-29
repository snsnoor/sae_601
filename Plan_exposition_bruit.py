import requests
import geopandas as gpd
from shapely.geometry import shape

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
        print("\n3. GeoDataFrame créé avec succès !")
        print("\nAperçu :")
        print(gdf[['ZONE', 'NOM', 'geometry']].head())
    else:
        print("Erreur : Aucune géométrie valide n'a été trouvée.")

else:
    print(f"Erreur de téléchargement : {reponse.status_code}")