import duckdb
import pandas as pd

DB_PATH = '../test_jointure.duckdb'

def get_donnees_globales():
    return "Voici un aperçu de l'état du marché immobilier français."

def get_modele_estimation():
    return "Le modèle d'estimation sera intégré ici."

def get_prix_median_par_commune():
    """
    Se connecte à DuckDB et calcule le prix médian au m² par commune.
    On exclut les surfaces à 0 pour éviter les erreurs de division.
    """
    # read_only=True permet à Streamlit de lire la base sans la bloquer
    con = duckdb.connect('info_appart_2.duckdb')
    
    query = """
        SELECT 
            a.nom_commune,
            MEDIAN(f.valeur_fonciere / NULLIF(f.surface_reelle_bati, 0)) AS prix_m2_median
        FROM fact_dvf f
        JOIN dim_adresses a ON f.id_adresse = a.id_adresse
        WHERE f.valeur_fonciere IS NOT NULL 
          AND f.surface_reelle_bati > 0
        GROUP BY a.nom_commune
        HAVING prix_m2_median IS NOT NULL
    """
    
    # Récupération des résultats sous forme de DataFrame Pandas
    df_prix = con.execute(query).df()
    con.close()
    
    return df_prix