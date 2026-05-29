import requests

url = "https://www.data.gouv.fr/api/1/datasets/r/000f281d-81ec-4f57-be64-e3dbae5ef9ff"

try:
    # Envoi de la requête pour récupérer le fichier
    response = requests.get(url)
    
    # Lève une erreur si le téléchargement a échoué (ex: erreur 404 ou 500)
    response.raise_for_status()
    
    # Conversion du contenu de la réponse en objet Python (dict ou list)
    donnees_json = response.json()
    print("Fichier JSON importé avec succès !")
    
    # Petite inspection rapide du contenu
    if isinstance(donnees_json, dict):
        print("Le JSON est un dictionnaire. Clés principales :", list(donnees_json.keys()))
    elif isinstance(donnees_json, list):
        print(f"Le JSON est une liste contenant {len(donnees_json)} éléments.")
        if donnees_json:
            print("Exemple du premier élément :", donnees_json[0])

except requests.exceptions.RequestException as e:
    print(f"Erreur lors de la récupération du fichier : {e}")
except ValueError as e:
    print(f"Le fichier récupéré n'est pas un JSON valide : {e}")