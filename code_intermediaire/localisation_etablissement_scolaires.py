import requests
import geopandas as gpd
import tempfile

# URL du jeu de donnÃ©es
url = "https://www.data.gouv.fr/api/1/datasets/r/000f281d-81ec-4f57-be64-e3dbae5ef9ff"

try:
    # TÃ©lÃ©chargement
    response = requests.get(url)
    response.raise_for_status()

    print("TÃ©lÃ©chargement rÃ©ussi.")

    # Sauvegarde temporaire du GeoJSON
    with tempfile.NamedTemporaryFile(
        suffix=".geojson",
        delete=False
    ) as f:
        f.write(response.content)
        temp_path = f.name

    # Lecture avec GeoPandas
    gdf_ecoles = gpd.read_file(temp_path)

    print(f"Nombre d'Ã©tablissements : {len(gdf_ecoles)}")
    print(f"CRS initial : {gdf_ecoles.crs}")

    # Si aucun CRS n'est dÃ©tectÃ©
    if gdf_ecoles.crs is None:
        gdf_ecoles = gdf_ecoles.set_crs("EPSG:3857")

    # Conversion en coordonnÃ©es GPS
    gdf_ecoles = gdf_ecoles.to_crs("EPSG:4326")

    # Extraction longitude / latitude
    gdf_ecoles["longitude"] = gdf_ecoles.geometry.x
    gdf_ecoles["latitude"] = gdf_ecoles.geometry.y

    # Colonnes utiles
    colonnes = [
        "name",
        "school-FR",
        "operator-type",
        "longitude",
        "latitude",
        "geometry"
    ]

    colonnes_existantes = [
        c for c in colonnes
        if c in gdf_ecoles.columns
    ]

    print("\nAperÃ§u des donnÃ©es :")
    print(gdf_ecoles[colonnes_existantes].head())

    print("\nColonnes disponibles :")
    print(gdf_ecoles.columns.tolist())

except requests.exceptions.RequestException as e:
    print(f"Erreur de tÃ©lÃ©chargement : {e}")

except Exception as e:
    print(f"Erreur : {e}")