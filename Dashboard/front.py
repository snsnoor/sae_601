# front.py
import streamlit as st
import back

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

# 4. Affichage des pages selon la sélection
if page == "Vue Globale":
    st.title("Vue Globale du Marché")
    st.write(back.get_donnees_globales())

elif page == "Estimation du Prix":
    st.title("Estimation de Prix Immobilier")
    st.write(back.get_modele_estimation())

# 5. Nom tout en bas du bandeau de gauche
st.sidebar.markdown('<div class="sidebar-footer">Nouhayla Bahaddou | Quentin Ezanno | Noor Nguia Ada</div>', unsafe_allow_html=True)