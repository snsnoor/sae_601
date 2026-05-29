import requests
import geopandas as gpd

url = "https://www.data.gouv.fr/api/1/datasets/r/000f281d-81ec-4f57-be64-e3dbae5ef9ff"

try:
    # Envoi de la requête pour récupérer le fichier
    response = requests.get(url)
    
    # Lève une erreur si le téléchargement a échoué (ex: erreur 404 ou 500)
    response.raise_for_status()
    
    # Conversion du contenu de la réponse en objet Python (dict ou list)
    df_ecole = response.json()
    print("Fichier JSON importé avec succès !")
    
    # Petite inspection rapide du contenu
    if isinstance(df_ecole, dict):
        print("Le JSON est un dictionnaire. Clés principales :", list(df_ecole.keys()))
    elif isinstance(df_ecole, list):
        print(f"Le JSON est une liste contenant {len(df_ecole)} éléments.")
        if df_ecole:
            print("Exemple du premier élément :", df_ecole[0])

except requests.exceptions.RequestException as e:
    print(f"Erreur lors de la récupération du fichier : {e}")
except ValueError as e:
    print(f"Le fichier récupéré n'est pas un JSON valide : {e}")

gdf_ecoles = gpd.GeoDataFrame(
    df_ecole,
    geometry=gpd.points_from_xy(df_ecole['longitude'], df_ecole['latitude']),
    crs="EPSG:4326"
)
