# front.py
import streamlit as st
import back
import plotly.express as px
import urllib.request
import json

# 1. Configuration de la page
st.set_page_config(page_title="Immo France", layout="wide")

# Fonction pour charger le CSS depuis le sous-dossier
def local_css(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# 2. Injection de la charte graphique
local_css("css/style.css")

# 3. Bandeau à gauche (Navigation)
st.sidebar.title("Menu")
page = st.sidebar.radio(
    "Navigation",
    ["Vue Globale", "Estimation du Prix"],
    label_visibility="collapsed"
)

# Ajout du nom en bas de la sidebar
st.sidebar.markdown('<div class="sidebar-footer">Quentda</div>', unsafe_allow_html=True)

# 4. Affichage des pages selon la sélection
if page == "Vue Globale":
    st.title("Vue Globale du Marché")
    st.write(back.get_donnees_globales())
    
    st.markdown("---")
    st.subheader("Carte des prix médians au m² par commune")
    
    # Ajout d'un spinner le temps que DuckDB calcule et que la carte charge
    with st.spinner("Analyse des données en cours..."):
        # Récupération des données depuis le back
        df_prix = back.get_prix_median_par_commune()
        
        # URL d'un GeoJSON simplifié des communes françaises (pour éviter de surcharger Streamlit)
        url_geojson = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/communes-version-simplifiee.geojson"
        
        # Création de la carte Choropleth avec Plotly
        fig = px.choropleth_mapbox(
            df_prix,
            geojson=url_geojson,
            locations="nom_commune",           # Colonne de notre DataFrame
            featureidkey="properties.nom",     # Clé correspondante dans le GeoJSON
            color="prix_m2_median",            # La valeur qui définit la couleur
            color_continuous_scale="YlOrRd",   # Échelle de couleurs (Jaune vers Rouge, raccord avec ta charte)
            range_color=[df_prix['prix_m2_median'].quantile(0.1), df_prix['prix_m2_median'].quantile(0.9)], # Évite que les valeurs extrêmes n'écrasent l'échelle
            mapbox_style="carto-positron",
            zoom=4.5,
            center={"lat": 46.2276, "lon": 2.2137}, # Centre de la France
            opacity=0.7,
            labels={'prix_m2_median': 'Prix médian (€/m²)'}
        )
        
        # Ajustement des marges pour que la carte prenne bien tout l'espace
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
        
        # Affichage dans Streamlit
        st.plotly_chart(fig, use_container_width=True)

elif page == "Estimation du Prix":
    st.title("Estimation de Prix Immobilier")
    st.write(back.get_modele_estimation())