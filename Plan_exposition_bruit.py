import requests

url = "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"

# Faire la requête GET pour récupérer les données
reponse = requests.get(url)

# Vérifier si la requête a réussi (code 200)
if reponse.status_code == 200:
    # Convertir la réponse en dictionnaire Python (JSON)
    geojson_data = reponse.json()
    print("Fichier GeoJSON importé avec succès !")
    
    # Afficher le type géométrique général et le nombre d'éléments
    print(f"Type : {geojson_data.get('type')}")
    print(f"Nombre de caractéristiques (features) : {len(geojson_data.get('features', []))}")
    
    # Afficher les propriétés du premier élément
    if geojson_data.get('features'):
        print("Propriétés du 1er élément :", geojson_data['features'][0]['properties'])
else:
    print(f"Erreur lors de l'importation. Code de statut : {reponse.status_code}")
