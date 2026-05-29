import requests
import geopandas as gpd
from shapely.geometry import shape

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