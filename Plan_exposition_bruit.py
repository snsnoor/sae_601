import requests

url = "https://www.data.gouv.fr/api/1/datasets/r/04e47e6e-0e91-44cb-a165-2faafdc4fb86"

# Faire la requête GET pour récupérer les données
reponse = requests.get(url)

# Vérifier si la requête a réussi (code 200)
if reponse.status_code == 200:
    # Convertir la réponse en dictionnaire Python (JSON)
    geojson_data = reponse.json()
    print("Fichier GeoJSON importé avec succès !")
    
    # Sécurité : vérifier qu'il y a bien des éléments dans le fichier
    if geojson_data.get('features'):
        # On isole le tout premier élément de la liste
        premier_element = geojson_data['features'][0]
        
        # 1. Extraction des propriétés (les colonnes de données)
        proprietes = premier_element.get('properties', {})
        print("\n--- PROPRIÉTÉS ---")
        print(f"Zone de bruit : {proprietes.get('ZONE')}")
        print(f"Aérodrome : {proprietes.get('NOM')} ({proprietes.get('CODE_OACI')})")
        
        # 2. Extraction de la géométrie (les polygones)
        geometrie = premier_element.get('geometry', {})
        print("\n--- GÉOMÉTRIE ---")
        print(f"Type de forme : {geometrie.get('type')}") # Ex: MultiPolygon
        
        # On affiche juste un petit bout des coordonnées pour vérifier que c'est là
        # (car il peut y en avoir des milliers pour un seul polygone)
        coordonnees = geometrie.get('coordinates', [])
        print(f"Aperçu des premières coordonnées : {str(coordonnees)[:100]}...")
        
else:
    print(f"Erreur lors de l'importation. Code de statut : {reponse.status_code}")

