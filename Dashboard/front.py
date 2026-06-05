# front.py — Immo France Dashboard (Version Finale Complète)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import random
import back
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import pandas as pd

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Immo France", layout="wide", initial_sidebar_state="expanded")

# ── CSS injection ─────────────────────────────────────────────────────────────
def local_css(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"Fichier CSS introuvable au chemin : {path}. Vérifie tes dossiers !")

local_css("Dashboard/CSS/style.css")

# ── Données réelles disponibles ? ─────────────────────────────────────────────
DB_READY = back.db_ready()

# ── Session state : page active ───────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Vue Globale"

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sidebar-logo">
      <svg width="36" height="36" viewBox="0 0 36 36" fill="none"
           xmlns="http://www.w3.org/2000/svg" aria-label="Immo France logo">
        <rect width="36" height="36" rx="9" fill="#3a6b3f"/>
        <path d="M18 7 L8 16 L8 29 L15 29 L15 21 L21 21 L21 29 L28 29 L28 16 Z"
              fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>
        <circle cx="18" cy="13" r="2.5" fill="#fff" opacity="0.85"/>
      </svg>
      <div>
        <div class="sidebar-logo-text">ImmoFrance</div>
        <div class="sidebar-logo-sub">Analyse immobilière</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    PAGES = [
        ("Vue Globale",         "Indicateurs & cartographie"),
        ("Trouver un logement", "Recherche filtrée"),
        ("Analyses",            "Corrélations & modèles"),
        ("Impact DPE",          "Prime énergétique (DVF × DPE)"),
        ("Opportunités",        "Communes à fort potentiel (INSEE)"),
    ]

    st.markdown('<div class="nav-section-label">Navigation</div>', unsafe_allow_html=True)

    for name, desc in PAGES:
        if st.button(name, key=f"nav_{name}", use_container_width=True, help=desc):
            st.session_state.page = name
            st.rerun()

    st.markdown("""
    <div class="sidebar-footer">
      <strong>Projet BUT Sciences des Données · 2025-2026</strong><br>
      Nouhayla Bahaddou<br>Quentin Ezanno<br>Noor Nguia Ada
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DONNÉES DE DÉMO (utilisées uniquement quand DB_READY est False)
# ─────────────────────────────────────────────────────────────────────────────
random.seed(42)

COMMUNES_SAMPLE = [
    ("Paris 15e",    4820, 9_450), ("Lyon 3e",      2341, 5_200),
    ("Marseille 8e", 1895, 3_870), ("Bordeaux",     1740, 4_120),
    ("Nantes",       1620, 3_650)
]
COMMUNES_SEARCH = [c[0] for c in COMMUNES_SAMPLE] + ["Lille", "Grenoble", "Toulon"]

DEMO_BANNER = """
<div class="demo-banner">
  <strong>Mode démo</strong> — données simulées.
  Lancez <code>python init_base.py</code> pour afficher les vraies données DVF.
</div>
"""

def fmt_num(n):
    return f"{n:,}".replace(",", " ")


# ─────────────────────────────────────────────────────────────────────────────
# THÉMAGE PLOTLY PARTAGÉ — charte beige · marron · vert
# Centralise le fond beige, la police marron, les grilles #E6DBC9 et un hover
# unifié pour toutes les figures (cohérence visuelle + moins de duplication).
# ─────────────────────────────────────────────────────────────────────────────
CHARTE = dict(
    fig_bg="#FAF6EF", grille="#E6DBC9", encre="#3D2B1F", encre_douce="#7A6A58",
    vert="#3A6B3F", vert_fonce="#2C5230", vert_clair="#6B9E70",
    accent="#A6643C", bonne="#2D6A4F", surcote="#B23A2E", neutre="#C9A227",
)

# Hover unifié : surface beige, bordure charte, encre marron.
HOVER = dict(bgcolor="#F6EFE3", bordercolor="#E6DBC9",
             font=dict(family="Satoshi, sans-serif", color="#3D2B1F", size=12))


def styliser_figure(fig, hauteur=300, marges=None, titre_y="€/m²"):
    """Applique la charte (fond, police, grilles, hover) à une figure Plotly."""
    fig.update_layout(
        plot_bgcolor=CHARTE["fig_bg"], paper_bgcolor=CHARTE["fig_bg"],
        font=dict(family="Satoshi, sans-serif", color=CHARTE["encre"], size=12),
        margin=marges or dict(t=24, b=12, l=8, r=8),
        height=hauteur,
        hoverlabel=HOVER,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# DPE — échelle de couleurs (Domain 4) alignée sur le CSS .dpe-A .. .dpe-G
# ─────────────────────────────────────────────────────────────────────────────
DPE_COLORS = {
    "A": "#00b050", "B": "#92d050", "C": "#ffff00", "D": "#ffbf00",
    "E": "#ff9900", "F": "#ff3300", "G": "#c00000",
}

def dpe_badge_html(etiquette):
    """Rend le badge coloré .dpe-badge .dpe-X pour une étiquette DPE (ou tiret si absente)."""
    if etiquette is None or str(etiquette).strip().upper() not in DPE_COLORS:
        # Couleur neutre alignée sur la charte (marron secondaire).
        return '<span class="dpe-badge" style="background:#7A6A58;color:#FAF6EF;">–</span>'
    lettre = str(etiquette).strip().upper()
    return f'<span class="dpe-badge dpe-{lettre}">{lettre}</span>'


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — VUE GLOBALE
# ─────────────────────────────────────────────────────────────────────────────
def page_vue_globale():
    st.markdown("""
    <div class="page-header">
      <h1>Vue Globale du Marché</h1>
      <p>Indicateurs agrégés · données DVF + DPE</p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # --- SÉLECTEURS : RÉGION + TYPE DE BIEN + ANNÉE (Domain 7 : choroplèthe filtrable) ---
    region_selectionnee = "Toutes les régions"
    type_selectionne = "Tous"
    annee_selectionnee = None
    if DB_READY:
        # Surtitre : on signale clairement la zone de filtres.
        st.markdown('<div class="filter-section-title">Filtres du marché</div>', unsafe_allow_html=True)
        liste_regions = back.get_regions()
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            region_selectionnee = st.selectbox("🌍 Région", liste_regions)
        with col_f2:
            type_selectionne = st.selectbox("🏠 Type de bien", ["Tous", "Maison", "Appartement"])
        with col_f3:
            # L'année alimente le filtre du choroplèthe (None = toutes les années).
            annees_dispo = back.get_annees_disponibles(region_selectionnee)
            options_annee = ["Toutes"] + [str(a) for a in annees_dispo]
            choix_annee = st.selectbox("📅 Année", options_annee)
            annee_selectionnee = None if choix_annee == "Toutes" else int(choix_annee)

    with st.spinner("Analyse des transactions en cours..."):
        # ── KPIs ──────────────────────────────────────────────────────────────────
        if DB_READY:
            kpis    = back.get_kpis(region_selectionnee)
            nb_tx   = fmt_num(kpis["nb_transactions"])
            nb_com  = fmt_num(kpis["nb_communes"])
            prix_md = f"{int(kpis['prix_m2_median']):,} €".replace(",", " ")
            surf_md = f"{int(kpis['surface_mediane'])} m²"
            periode = "DVF 2024-2025"

            var_data  = back.get_variation_prix(region_selectionnee)
            variation = var_data.get("variation")
            if variation is not None:
                if variation > 0:
                    var_html = f'<div class="prix-variation prix-variation-up">↑ +{variation:.1f}% vs 2024</div>'
                elif variation < 0:
                    var_html = f'<div class="prix-variation prix-variation-down">↓ {variation:.1f}% vs 2024</div>'
                else:
                    var_html = f'<div class="prix-variation prix-variation-flat">→ {variation:.1f}% vs 2024</div>'
            else:
                var_html = ""
        else:
            nb_tx, nb_com, prix_md, surf_md, periode = ("847 320", "24 601", "3 480 €", "72 m²", "DVF 2020-2024 (démo)")
            var_html = ""

        st.markdown(f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Transactions totales</div>
            <div class="kpi-value">{nb_tx}</div>
            <div class="kpi-sub">{periode}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Communes couvertes</div>
            <div class="kpi-value">{nb_com}</div>
            <div class="kpi-sub">avec ventes 2024-2025</div>
          </div>
          <div class="kpi-card kpi-accent">
            <div class="kpi-label">Prix médian / m²</div>
            <div class="kpi-value">{prix_md}</div>
            <div class="kpi-sub">Maisons & Appartements</div>
            {var_html}
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Surface médiane</div>
            <div class="kpi-value">{surf_md}</div>
            <div class="kpi-sub">Logements vendus</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        col_left, col_right = st.columns([1, 1.4], gap="medium")

        with col_left:
            # TOP 5 PLUS CHÈRES
            st.markdown("""
            <div class="card" style="margin-bottom: 16px;">
              <div class="card-title">📈 Top 5 — Les plus chères</div>
              <ul class="commune-list">
            """, unsafe_allow_html=True)

            if DB_READY and not kpis["top_cheres"].empty:
                rows_c = [(r.nom_commune, int(r.nb_ventes), int(r.prix_m2_median or 0)) for r in kpis["top_cheres"].itertuples(index=False)]
            else:
                rows_c = COMMUNES_SAMPLE[:5]

            for i, (name, ventes, prix_m2) in enumerate(rows_c, 1):
                st.markdown(f"""
                <li class="commune-item">
                  <span class="commune-rank">{i}</span>
                  <span class="commune-name">{name}</span>
                  <span class="commune-stats">
                    <div class="commune-prix">{fmt_num(prix_m2)} €/m²</div>
                    <div class="commune-ventes">{fmt_num(ventes)} ventes</div>
                  </span>
                </li>
                """, unsafe_allow_html=True)
            st.markdown("</ul></div>", unsafe_allow_html=True)

            # TOP 5 MOINS CHÈRES
            st.markdown("""
            <div class="card">
              <div class="card-title">📉 Top 5 — Les moins chères</div>
              <ul class="commune-list">
            """, unsafe_allow_html=True)

            if DB_READY and not kpis["top_moins_cheres"].empty:
                rows_mc = [(r.nom_commune, int(r.nb_ventes), int(r.prix_m2_median or 0)) for r in kpis["top_moins_cheres"].itertuples(index=False)]
            else:
                rows_mc = COMMUNES_SAMPLE[::-1][:5]

            for i, (name, ventes, prix_m2) in enumerate(rows_mc, 1):
                st.markdown(f"""
                <li class="commune-item">
                  <span class="commune-rank">{i}</span>
                  <span class="commune-name">{name}</span>
                  <span class="commune-stats">
                    <div class="commune-prix">{fmt_num(prix_m2)} €/m²</div>
                    <div class="commune-ventes">{fmt_num(ventes)} ventes</div>
                  </span>
                </li>
                """, unsafe_allow_html=True)
            st.markdown("</ul></div>", unsafe_allow_html=True)

        with col_right:
            # REGROUPEMENT : Forme rectangle titre + Carte intégrée
            st.markdown("""
            <div class="card" style="height:100%;">
              <div class="card-title" style="margin-bottom: 10px;">
                🗺️ Carte des prix médians au m² par commune
              </div>
            """, unsafe_allow_html=True)
            
            if DB_READY:
                df_prix = back.get_prix_median_par_commune(
                    region_selectionnee, type_local=type_selectionne, annee=annee_selectionnee
                )
                if not df_prix.empty:
                    zoom_level = 4.5 if region_selectionnee == 'Toutes les régions' else 6.5
                    range_color = [
                        df_prix['prix_m2_median'].quantile(0.05),
                        df_prix['prix_m2_median'].quantile(0.85),
                    ]

                    # Domain 7 : on privilégie un CHOROPLÈTHE (polygones communaux) clé par
                    # code commune INSEE. Si les polygones (dim_communes_geo) sont absents
                    # ou ne couvrent aucune commune de la sélection, on bascule sur l'ancienne
                    # carte de POINTS (scatter_map) pour ne jamais planter.
                    geojson = back.get_communes_geojson(region_selectionnee)
                    a_des_polygones = bool(geojson.get("features"))

                    if a_des_polygones:
                        fig_map = px.choropleth_map(
                            df_prix,
                            geojson=geojson,
                            locations="code_commune",
                            featureidkey="properties.code",
                            color="prix_m2_median",
                            hover_name="nom_commune",
                            hover_data={"volume_ventes": True, "code_commune": False},
                            # Échelle séquentielle charte : beige -> vert principal -> vert foncé.
                            color_continuous_scale=[
                                [0.0, "#FAF6EF"], [0.5, "#3A6B3F"], [1.0, "#2C5230"]
                            ],
                            range_color=range_color,
                            map_style="carto-positron", zoom=zoom_level,
                            center={"lat": 46.2276, "lon": 2.2137},
                            opacity=0.7,
                            labels={'prix_m2_median': 'Prix médian (€/m²)', 'volume_ventes': 'Nb transactions'}
                        )
                    else:
                        # Repli : carte de points (centroïdes communaux).
                        fig_map = px.scatter_map(
                            df_prix, lat="latitude", lon="longitude", color="prix_m2_median",
                            size="volume_ventes", hover_name="nom_commune",
                            # Échelle séquentielle charte : beige -> vert principal -> vert foncé.
                            color_continuous_scale=[
                                [0.0, "#FAF6EF"], [0.5, "#3A6B3F"], [1.0, "#2C5230"]
                            ],
                            range_color=range_color,
                            map_style="carto-positron", zoom=zoom_level,
                            center={"lat": 46.2276, "lon": 2.2137}, opacity=0.8,
                            labels={'prix_m2_median': 'Prix médian (€/m²)', 'volume_ventes': 'Nb transactions'}
                        )
                    fig_map.update_layout(
                        margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=500,
                        hoverlabel=HOVER,
                        coloraxis_colorbar=dict(
                            title="€/m²", thickness=12, len=0.7,
                            tickfont=dict(color=CHARTE["encre"], size=10),
                        ),
                    )
                    st.plotly_chart(fig_map, use_container_width=True)
                    if not a_des_polygones:
                        st.caption("Polygones communaux indisponibles — affichage en carte de points (centroïdes).")
                else:
                    st.info("🗺️ Aucune commune géolocalisée pour cette sélection. Élargissez la région ou l'année.")
            else:
                st.info("🗺️ Carte interactive disponible une fois la base initialisée (mode démo actif).")
            st.markdown("</div>", unsafe_allow_html=True)

        # ── Top communes par type ─────────────────────────────────────────────────
        if DB_READY:
            df_top_types = back.get_top_communes_par_type(n=12, region=region_selectionnee)
            if not df_top_types.empty:
                max_prix = float(df_top_types['prix_tous'].max()) if df_top_types['prix_tous'].notna().any() else 1.0
                rows_html = ""
                for _, r in df_top_types.iterrows():
                    pct    = int((float(r['prix_tous'] or 0) / max_prix) * 100) if max_prix else 0
                    p_tous = f"{int(r['prix_tous']):,}".replace(',', ' ') + ' €' if pd.notna(r['prix_tous']) else '—'
                    p_appt = f"{int(r['prix_appart']):,}".replace(',', ' ') if pd.notna(r['prix_appart']) else '—'
                    p_mais = f"{int(r['prix_maison']):,}".replace(',', ' ') if pd.notna(r['prix_maison']) else '—'
                    rows_html += f"""
                    <div class="commune-bar-item">
                      <div class="commune-bar-name">{str(r['nom_commune']).title()}</div>
                      <div class="commune-bar-wrap">
                        <div class="commune-bar-fill" style="width:{pct}%"></div>
                      </div>
                      <div class="commune-bar-prix">{p_tous}/m²</div>
                      <div class="commune-bar-sub">Appt: {p_appt} · Maison: {p_mais}</div>
                    </div>
                    """
                st.markdown(f"""
                <div class="card" style="margin-top:16px;">
                  <div class="card-title">🏘️ Top communes — Prix médian par type</div>
                  <div class="commune-bar-list">{rows_html}</div>
                </div>
                """, unsafe_allow_html=True)

        # ── Evolution mensuelle ────────────────────────────────────────────────────
        st.markdown("""
        <div class="card" style="margin-top:16px;">
          <div class="card-title">📅 Évolution du prix médian / m²</div>
        """, unsafe_allow_html=True)

        if DB_READY:
            df_mois = back.get_prix_par_mois(region_selectionnee)
            x_vals  = df_mois["mois"].tolist()
            y_vals  = [float(v) for v in df_mois["prix_m2_median"].tolist()]
            colors  = ["#3A6B3F"] * len(x_vals)
        else:
            x_vals = [2020, 2021, 2022, 2023, 2024]
            y_vals = [2950, 3150, 3420, 3510, 3480]
            colors = ["#6B9E70", "#6B9E70", "#3A6B3F", "#3A6B3F", "#3A6B3F"]

        max_y = max(y_vals) if y_vals else 0

        fig_bar = go.Figure(go.Bar(
            x=x_vals, y=y_vals, marker_color=colors,
            text=[f"{int(p):,} €".replace(",", " ") for p in y_vals], textposition="outside",
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} €/m²<extra></extra>",
        ))
        styliser_figure(fig_bar, hauteur=240, marges=dict(t=28, b=12, l=8, r=8))
        fig_bar.update_layout(
            yaxis=dict(showgrid=True, gridcolor=CHARTE["grille"], title="Prix médian (€/m²)",
                       range=[0, max_y * 1.2], tickformat=",.0f"),
            xaxis=dict(showgrid=False, title=None),
            showlegend=False, separators=", ",
        )
        st.plotly_chart(fig_bar, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — TROUVER UN LOGEMENT
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _get_communes_dispo():
    """Liste des communes disponibles (mise en cache 5 min pour éviter une requête à chaque render)."""
    return back.get_communes_dispo() if back.db_ready() else []


@st.cache_data
def charger_et_preparer_donnees(commune, type_local, nb_pieces, surface, budget_min, budget_max, prix_m2_max, dist_gare, dist_ecole):
    import pandas as pd
    import numpy as np
    
    # 1. Requête à la base
    df = back.search_properties(
        commune=commune, type_local=type_local, nb_pieces_min=nb_pieces,
        surface_min=float(surface), budget_min=float(budget_min), budget_max=float(budget_max),
        prix_m2_max=float(prix_m2_max), dist_gare_max=dist_gare, dist_ecole_max=dist_ecole
    )
    
    if df.empty:
        return df, pd.DataFrame()
        
    # 2. Domain 5 : zone de bruit aéroportuaire PEB RÉELLE (issue du rapprochement
    #    spatial dans dim_adresses), surface via search_properties (v.zone_peb / v.code_oaci).
    #    Remplace l'ancienne simulation np.random.choice. NULL = hors de toute zone PEB.
    if "zone_peb" not in df.columns:
        df["zone_peb"] = None
    if "code_oaci" not in df.columns:
        df["code_oaci"] = None

    # Libellés lisibles des sévérités PEB (A = la plus bruyante).
    libelles_peb = {
        "A": "A (Très fort)", "B": "B (Fort)", "C": "C (Modéré)", "D": "D (Faible)"
    }

    def libelle_zone_peb(row):
        z = row.get("zone_peb")
        if pd.isna(z) or not str(z).strip():
            return "Hors zone"
        z = str(z).strip().upper()
        base = libelles_peb.get(z, f"Zone {z}")
        oaci = row.get("code_oaci")
        if pd.notna(oaci) and str(oaci).strip():
            return f"{base} — {str(oaci).strip()}"
        return base

    df["zone_peb_label"] = df.apply(libelle_zone_peb, axis=1)

    # 3. Évaluation "Bonne affaire" — Domain 4 : référence DPE-aware.
    # On compare au prix des comparables (même commune + type + étiquette ±1 cran)
    # quand il existe (prix_m2_comparable), sinon repli sur la médiane communale.
    def ref_comparable(row):
        ref = row.get("prix_m2_comparable")
        if pd.isna(ref) or not ref:
            ref = row.get("prix_m2_commune")
        return ref

    def evaluer_affaire(row):
        ref = ref_comparable(row)
        if pd.isna(ref) or pd.isna(row['prix_m2']) or not ref:
            return "➖"
        ratio = row['prix_m2'] / ref
        if ratio <= 0.90:
            return "✅ Bonne affaire"
        elif ratio >= 1.10:
            return "❌ Surcoté"
        else:
            return "➖ Dans la moyenne"

    df["prix_m2_reference"] = df.apply(ref_comparable, axis=1)
    df["Évaluation"] = df.apply(evaluer_affaire, axis=1)
    # Colonne DPE : on garantit la présence d'etiquette_dpe (NULL -> '–').
    if "etiquette_dpe" not in df.columns:
        df["etiquette_dpe"] = None
    df["DPE"] = df["etiquette_dpe"].apply(lambda e: str(e).strip().upper() if pd.notna(e) and str(e).strip() else "–")

    # 4. Préparation du tableau final pour l'affichage (renommage)
    df_display = df[[
        "nom_commune", "DPE", "valeur_fonciere", "surface_reelle_bati",
        "nombre_pieces_principales", "prix_m2", "prix_m2_reference", "Évaluation",
        "dist_gare_km", "dist_ecole_km", "zone_peb_label"
    ]].rename(columns={
        "nom_commune": "Commune", "valeur_fonciere": "Prix (€)",
        "surface_reelle_bati": "Surface (m²)", "nombre_pieces_principales": "Pièces",
        "prix_m2": "€/m² (Bien)", "prix_m2_reference": "€/m² (Comparables)",
        "dist_gare_km": "Dist. gare (km)", "dist_ecole_km": "Dist. école (km)",
        # Domain 5 : zone de bruit aéroportuaire PEB réelle (✈️).
        "zone_peb_label": "✈️ Bruit (PEB)"
    })

    return df, df_display


def page_trouver():
    st.markdown("""
    <div class="page-header">
      <h1>Trouver un Logement</h1>
      <p>Renseignez vos critères — résultats issus des ventes DVF</p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── Critères d'achat ──────────────────────────────────────────────────────
    st.markdown("<div class=\"filter-section-title\">Critères d'achat</div>", unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns([2, 1.2, 0.9, 0.9, 1.5, 1.2])
    with c1:
        if DB_READY:
            communes_dispo = _get_communes_dispo()
            commune_choisie = st.selectbox("Commune", communes_dispo, index=0)
            commune_input = "" if commune_choisie == "Toutes les communes" else commune_choisie
        else:
            commune_input = st.text_input("Commune", placeholder="Ex : Nantes, Lyon...")
    with c2:
        type_logement = st.selectbox("Type de logement", ["Tous", "Maison", "Appartement"], label_visibility="visible")
    with c3:
        nb_pieces = st.number_input("Nb pièces", min_value=1, max_value=10, value=3, step=1, label_visibility="visible")
    with c4:
        surface = st.number_input("Surface (m²)", min_value=10, max_value=500, value=60, step=5, label_visibility="visible")
    with c5:
        prix_range = st.slider("Budget (€)", 50_000, 1_500_000, (150_000, 450_000), step=5_000, format="%d €", label_visibility="visible")
    with c6:
        prix_m2_max = st.number_input("Prix max / m² (€)", min_value=500, max_value=20_000, value=6_000, step=100, label_visibility="visible")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Mobilité & Environnement ────────────────────────────────────
    st.markdown("<div class=\"filter-section-title\">🚉 Mobilité & Proximité</div>", unsafe_allow_html=True)
    
    classes_distance = {
        "Peu importe": None,
        "< 1 km (Très proche)": 1.0,
        "< 3 km (Proche)": 3.0,
        "< 5 km (Moyen)": 5.0,
        "< 10 km (Éloigné)": 10.0
    }

    m1, m2 = st.columns(2)
    with m1:
        choix_gare = st.selectbox("Distance max. jusqu'à une Gare", list(classes_distance.keys()))
        dist_gare_val = classes_distance[choix_gare]
    with m2:
        choix_ecole = st.selectbox("Distance max. jusqu'à une École", list(classes_distance.keys()))
        dist_ecole_val = classes_distance[choix_ecole]
        
    st.markdown("</div>", unsafe_allow_html=True)

    col_btn = st.columns([3, 1])[1]
    with col_btn:
        # Le bouton déclenche réellement la recherche (déposé en session_state).
        if st.button("🔍 Rechercher", use_container_width=True, type="primary"):
            st.session_state.recherche_lancee = True

    st.markdown("---")

    if not DB_READY:
        st.info("Base non initialisée. Lancez le script d'initialisation pour activer la recherche.")
        return

    # Tant que l'utilisateur n'a pas lancé sa recherche, on affiche un état d'accueil
    # explicite plutôt qu'un tableau vide ou une requête prématurée.
    if not st.session_state.get("recherche_lancee"):
        st.info("👋 Renseignez vos critères ci-dessus puis cliquez sur **🔍 Rechercher** "
                "pour comparer les biens au prix du marché.")
        return

    # ── Résultats réels avec Appel au Cache ──────────────────────────────────
    with st.spinner("Recherche des biens correspondants dans la base DVF..."):
        df_results, df_display = charger_et_preparer_donnees(
            commune_input, type_logement, nb_pieces, surface,
            prix_range[0], prix_range[1], prix_m2_max, dist_gare_val, dist_ecole_val
        )

    col_map, col_info = st.columns([1.7, 1], gap="medium")

    with col_map:
        st.markdown('<div class="card-title">🔍 Résultats de recherche</div>', unsafe_allow_html=True)

        if df_results.empty:
            st.info("🔎 Aucun bien ne correspond à ces critères. "
                    "Essayez d'élargir le budget, la surface ou la distance.")
        else:
            st.caption(f"{fmt_num(len(df_results))} transaction(s) trouvée(s) · "
                       "✅ bonne affaire (−10 %) · ➖ dans la moyenne · ❌ surcoté (+10 %) — "
                       "cliquez sur une ligne pour l'analyser.")
            
            evenement_selection = st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",           
                selection_mode="single-row",
                key="tableau_biens_immo" 
            )
            
        st.markdown("</div>", unsafe_allow_html=True)

        # ── DÉPLACEMENT ICI : ESTIMATEUR DE PRIX (SOUS LE TABLEAU) ──
        if not df_results.empty:
            st.markdown("""
            <div class="card" style="margin-top:16px; padding-bottom: 10px;">
              <div class="card-title">⚖️ Analyseur de prix individuel</div>
            """, unsafe_allow_html=True)

            lignes_selectionnees = evenement_selection.selection.rows
            
            if lignes_selectionnees:
                import plotly.graph_objects as go
                idx = lignes_selectionnees[0] 
                
                nom_ville = str(df_results.iloc[idx]["nom_commune"]).title()
                prix_bien_m2 = float(df_results.iloc[idx]["prix_m2"])
                # Domain 4 : référence = comparables DPE-aware (repli médiane communale).
                ref_val = df_results.iloc[idx].get("prix_m2_reference")
                if pd.isna(ref_val) or not ref_val:
                    ref_val = df_results.iloc[idx]["prix_m2_commune"]
                prix_ville_m2 = float(ref_val)
                statut_affaire = df_results.iloc[idx]["Évaluation"]
                etiquette_bien = df_results.iloc[idx].get("etiquette_dpe")

                # Domain 4 : badge DPE coloré du bien sélectionné (classes CSS .dpe-X).
                st.markdown(
                    f'<div style="margin-bottom:8px;">Étiquette énergétique (DPE) : '
                    f'{dpe_badge_html(etiquette_bien)}</div>',
                    unsafe_allow_html=True
                )

                fig_gauge = go.Figure(go.Indicator(
                    mode = "gauge+number+delta",
                    value = prix_bien_m2,
                    title = {'text': f"<b>{nom_ville}</b> — {statut_affaire}", 'font': {'size': 14, 'family': 'Inter', 'color': "#3D2B1F"}},
                    # Sémantique charte : hausse = surcoté (rouge), baisse = bonne affaire (vert).
                    delta = {'reference': prix_ville_m2, 'increasing': {'color': "#B23A2E"}, 'decreasing': {'color': "#2D6A4F"}, 'font': {'size': 14}},
                    gauge = {
                        'axis': {'range': [None, max(prix_bien_m2, prix_ville_m2) * 1.3], 'tickfont': {'size': 10, 'color': "#3D2B1F"}},
                        'bar': {'color': "#7A6A58"},
                        'steps' : [
                            # Sémantique charte : bonne affaire / neutre / surcoté.
                            {'range': [0, prix_ville_m2 * 0.9], 'color': "#2D6A4F"},
                            {'range': [prix_ville_m2 * 0.9, prix_ville_m2 * 1.1], 'color': "#C9A227"},
                            {'range': [prix_ville_m2 * 1.1, max(prix_bien_m2, prix_ville_m2) * 1.3], 'color': "#B23A2E"}
                        ],
                        'threshold' : {'line': {'color': "#3D2B1F", 'width': 3}, 'thickness': 0.75, 'value': prix_ville_m2}
                    }
                ))

                fig_gauge.update_layout(
                    margin=dict(t=52, b=16, l=24, r=24),  # On aère les marges
                    height=250,  # Hauteur suffisante pour éviter la superposition du texte
                    font=dict(family="Satoshi, sans-serif", color="#3D2B1F"),
                    paper_bgcolor=CHARTE["fig_bg"],
                    hoverlabel=HOVER,
                )

                st.plotly_chart(fig_gauge, use_container_width=True)
                # Légende sémantique de la jauge (verdict bonne affaire / neutre / surcoté).
                st.caption("La barre marron = prix du bien ; le repère noir = prix de référence des comparables. "
                           "🟢 sous −10 % = bonne affaire · 🟡 ±10 % = dans la moyenne · 🔴 au-delà de +10 % = surcoté.")
            else:
                st.info("💡 **Cliquez sur une ligne** du tableau ci-dessus pour comparer précisément "
                        "ce bien au prix des biens comparables de sa commune.")
                
            st.markdown("</div>", unsafe_allow_html=True)

    with col_info:
        if not df_results.empty:
            med_prix = df_results["prix_m2"].median()
            med_surf = df_results["surface_reelle_bati"].median()
            med_ville = df_results["prix_m2_commune"].median()

            st.markdown(f"""
            <div class="card">
              <div class="card-title">Statistiques de la sélection</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;text-align:center; padding-top:10px;">
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3D2B1F">{int(med_prix):,} €</div>
                  <div style="font-size:0.75rem;color:#7A6A58;text-transform:uppercase">Prix médian /m²</div>
                </div>
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3D2B1F">{int(med_ville):,} €</div>
                  <div style="font-size:0.75rem;color:#7A6A58;text-transform:uppercase">Moyenne Ville /m²</div>
                </div>
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3D2B1F">{int(med_surf)} m²</div>
                  <div style="font-size:0.75rem;color:#7A6A58;text-transform:uppercase">Surface médiane</div>
                </div>
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3D2B1F">{len(df_results)}</div>
                  <div style="font-size:0.75rem;color:#7A6A58;text-transform:uppercase">Transactions</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — ANALYSES
# ─────────────────────────────────────────────────────────────────────────────
def page_analyses():
    st.markdown("""
    <div class="page-header">
      <h1>Analyses</h1>
      <p>Corrélations, distributions et modèles exploratoires</p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    with st.spinner("Calcul des corrélations prix · proximité..."):
        if DB_READY:
            df_prox   = back.get_prix_vs_proximite()
            dist_gare = df_prox["dist_gare_km"].values
            dist_eco  = df_prox["dist_ecole_km"].values
            prix_m2   = df_prox["prix_m2"].values
        else:
            rng = np.random.default_rng(42)
            n = 300
            dist_gare = rng.exponential(scale=3, size=n).clip(0.1, 20)
            dist_eco  = rng.exponential(scale=2, size=n).clip(0.1, 10)
            prix_m2   = (3500 + rng.normal(0, 1000, n) - dist_gare * 80 - dist_eco * 30).clip(500, 15000)
            # base_price_an n'est utilisé que par le repli démo de la décote PEB ci-dessous.
            base_price_an = 3480

    col1, col2 = st.columns(2, gap="medium")

    with col1:
        st.markdown("""
        <div class="card">
          <div class="card-title" style="margin-bottom:12px">Prix/m² vs. proximité gare</div>
        """, unsafe_allow_html=True)
        
        fig1 = go.Figure(go.Scatter(
            x=dist_gare, y=prix_m2, mode="markers",
            marker=dict(color=CHARTE["vert"], size=5, opacity=0.5),
            hovertemplate="Dist. gare : %{x:.2f} km<br>Prix : %{y:,.0f} €/m²<extra></extra>",
        ))
        styliser_figure(fig1, hauteur=280, marges=dict(t=10, b=10, l=8, r=8))
        fig1.update_layout(
            xaxis=dict(title="Distance à la gare (km)", showgrid=True, gridcolor=CHARTE["grille"]),
            yaxis=dict(title="Prix (€/m²)", showgrid=True, gridcolor=CHARTE["grille"], tickformat=",.0f"),
            separators=", ",
        )
        st.plotly_chart(fig1, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        # REGROUPEMENT : Forme rectangle titre + Nuage de points École
        st.markdown("""
        <div class="card">
          <div class="card-title" style="margin-bottom:12px">Prix/m² vs. proximité école</div>
        """, unsafe_allow_html=True)
        
        fig2 = go.Figure(go.Scatter(
            x=dist_eco, y=prix_m2, mode="markers",
            marker=dict(color=CHARTE["vert_clair"], size=5, opacity=0.5),
            hovertemplate="Dist. école : %{x:.2f} km<br>Prix : %{y:,.0f} €/m²<extra></extra>",
        ))
        styliser_figure(fig2, hauteur=280, marges=dict(t=10, b=10, l=8, r=8))
        fig2.update_layout(
            xaxis=dict(title="Distance à l'école (km)", showgrid=True, gridcolor=CHARTE["grille"]),
            yaxis=dict(title="Prix (€/m²)", showgrid=True, gridcolor=CHARTE["grille"], tickformat=",.0f"),
            separators=", ",
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Matrice de corrélation ─────────────────────────────────────────────────
    st.markdown("""
    <div class="card" style="margin-top:16px; padding-bottom: 0;">
      <div class="card-title">✈️ Impact du bruit aéroportuaire sur le prix / m²</div>
    """, unsafe_allow_html=True)

    # Domain 5 : libellés + ordre canonique des zones PEB (A le plus bruyant -> Hors zone).
    PEB_LABELS = {
        "A": "A (Très fort)", "B": "B (Fort)", "C": "C (Modéré)",
        "D": "D (Faible)", "Hors zone": "Hors zone",
    }
    PEB_ORDER = ["A", "B", "C", "D", "Hors zone"]
    # Sémantique charte : zones bruyantes = surcoté (rouge), modéré = neutre (jaune),
    # faible/hors zone = bonne affaire (vert clair/principal).
    PEB_COLORS = {
        "A": "#B23A2E", "B": "#A6643C", "C": "#C9A227",
        "D": "#6B9E70", "Hors zone": "#2D6A4F",
    }
    # Seuil minimal de ventes pour qu'une zone soit affichée (couverture PEB très partielle).
    SEUIL_MIN_VENTES = 5

    if DB_READY:
        # Domain 5 : décote RÉELLE par zone PEB (remplace les multiplicateurs simulés).
        # NOTE : page_analyses n'expose pas de sélecteur de région -> on agrège au national.
        df_zone = back.get_noise_discount_by_zone(None)
    else:
        # Fallback démo (DB indisponible) : ordres de grandeur illustratifs, signalés comme tels.
        df_zone = pd.DataFrame({
            "zone_peb": ["A", "B", "C", "D", "Hors zone"],
            "type_local": ["Appartement"] * 5,
            "prix_m2_median": [int(base_price_an * m) for m in (0.80, 0.85, 0.92, 0.98, 1.0)],
            "nb_ventes": [40, 60, 120, 300, 5000],
        })

    # Agrégation tous types : médiane pondérée approchée -> on reprend la médiane par zone
    # en sommant les ventes (le détail Maison/Appartement est dans df_zone si besoin).
    if not df_zone.empty:
        df_zone_agg = (
            df_zone.groupby("zone_peb", as_index=False)
            .agg(prix_m2_median=("prix_m2_median", "median"),
                 nb_ventes=("nb_ventes", "sum"))
        )
    else:
        df_zone_agg = df_zone

    # On ne garde QUE les zones suffisamment couvertes (évite des barres trompeuses).
    df_zone_aff = df_zone_agg[df_zone_agg["nb_ventes"] >= SEUIL_MIN_VENTES].copy()
    # On ordonne A -> B -> C -> D -> Hors zone.
    df_zone_aff["__ord"] = df_zone_aff["zone_peb"].apply(
        lambda z: PEB_ORDER.index(z) if z in PEB_ORDER else len(PEB_ORDER)
    )
    df_zone_aff = df_zone_aff.sort_values("__ord")

    # Zones réellement exposées (hors "Hors zone") avec assez de ventes ?
    zones_exposees = df_zone_aff[df_zone_aff["zone_peb"] != "Hors zone"]

    if zones_exposees.empty:
        # Domain 5 : couverture PEB insuffisante -> message informatif, pas de barres trompeuses.
        st.info(
            "ℹ️ Couverture PEB insuffisante sur le périmètre courant : aucune (ou trop peu de) "
            "vente n'est située dans une zone de bruit aéroportuaire. Le Plan d'Exposition au "
            "Bruit (PEB) ne couvre que quelques aéroports. Aucune décote fiable ne peut être "
            "calculée ici."
        )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        df_zone_aff["Zone"] = df_zone_aff["zone_peb"].map(PEB_LABELS).fillna(df_zone_aff["zone_peb"])
        couleurs_bruit = [PEB_COLORS.get(z, "#7A6A58") for z in df_zone_aff["zone_peb"]]
        y_max = float(df_zone_aff["prix_m2_median"].max()) * 1.3

        fig_peb = go.Figure(go.Bar(
            x=df_zone_aff["Zone"],
            y=df_zone_aff["prix_m2_median"],
            marker_color=couleurs_bruit,
            text=[f"{int(p):,} €".replace(",", " ") for p in df_zone_aff["prix_m2_median"]],
            textposition="outside",
            customdata=df_zone_aff["nb_ventes"],
            hovertemplate="<b>Zone %{x}</b><br>Prix médian : %{y:,.0f} €/m²<br>%{customdata:,} ventes<extra></extra>"
        ))

        styliser_figure(fig_peb, hauteur=240, marges=dict(t=28, b=12, l=8, r=8))
        fig_peb.update_layout(
            xaxis=dict(title="Zone d'exposition au bruit (PEB)", showgrid=False),
            yaxis=dict(title="Prix médian (€/m²)", showgrid=True, gridcolor=CHARTE["grille"],
                       range=[0, y_max], tickformat=",.0f"),
            showlegend=False, separators=", ",
        )

        st.plotly_chart(fig_peb, use_container_width=True)

        legende = "Données réelles (médiane DVF par zone PEB)" if DB_READY else "Mode démo — données simulées"
        st.markdown(f"""
          <div style="font-size:0.7rem;color:#7A6A58; text-align: right; margin-top:-10px; padding-bottom: 10px;">
            {legende} · zones affichées si ≥ {SEUIL_MIN_VENTES} ventes
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Domain 5 : ventilation par aéroport (code OACI) ───────────────────────
        if DB_READY:
            df_aero = back.get_noise_discount_by_airport(None)
            df_aero = df_aero[df_aero["nb_ventes"] >= SEUIL_MIN_VENTES] if not df_aero.empty else df_aero
            if df_aero is None or df_aero.empty:
                st.caption("Pas assez de ventes par aéroport pour une ventilation fiable (couverture PEB limitée).")
            else:
                df_aero = df_aero.copy()
                df_aero["__ord"] = df_aero["zone_peb"].apply(
                    lambda z: PEB_ORDER.index(z) if z in PEB_ORDER else len(PEB_ORDER)
                )
                df_aero = df_aero.sort_values(["code_oaci", "__ord"])
                df_aero["Zone"] = df_aero["zone_peb"].map(PEB_LABELS).fillna(df_aero["zone_peb"])

                st.markdown(
                    '<div class="card-title" style="margin-top:10px;font-size:0.9rem">'
                    '✈️ Détail par aéroport (code OACI) × zone PEB</div>',
                    unsafe_allow_html=True
                )
                fig_aero = go.Figure()
                for zone in PEB_ORDER:
                    sub = df_aero[df_aero["zone_peb"] == zone]
                    if sub.empty:
                        continue
                    fig_aero.add_trace(go.Bar(
                        name=PEB_LABELS.get(zone, zone),
                        x=sub["code_oaci"],
                        y=sub["prix_m2_median"],
                        marker_color=PEB_COLORS.get(zone, "#7A6A58"),
                        customdata=sub["nb_ventes"],
                        hovertemplate="<b>%{x}</b> — " + PEB_LABELS.get(zone, zone) +
                                      "<br>Prix médian : %{y:,.0f} €/m²<br>%{customdata:,} ventes<extra></extra>"
                    ))
                styliser_figure(fig_aero, hauteur=260, marges=dict(t=12, b=12, l=8, r=8))
                fig_aero.update_layout(
                    barmode="group",
                    xaxis=dict(title="Aéroport (code OACI)", showgrid=False),
                    yaxis=dict(title="Prix médian (€/m²)", showgrid=True, gridcolor=CHARTE["grille"],
                               tickformat=",.0f"),
                    legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=10),
                                title_text="Zone PEB"),
                    separators=", ",
                )
                st.plotly_chart(fig_aero, use_container_width=True)

    # ── Matrice de correlation ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div class="card-title" style="margin-bottom:12px;font-size:0.95rem">
      Matrice de correlation — variables numeriques cles
    </div>
    """, unsafe_allow_html=True)

    if DB_READY:
        surface_v  = df_prox["surface_reelle_bati"].values.astype(float)
        mat_data   = np.column_stack([prix_m2, dist_gare, dist_eco, surface_v])
        vars_labels = ["Prix/m²", "Dist. gare", "Dist. ecole", "Surface"]
    else:
        rng2 = np.random.default_rng(42)
        n2 = 300
        dg2  = rng2.exponential(scale=3, size=n2).clip(0.1, 20)
        de2  = rng2.exponential(scale=2, size=n2).clip(0.1, 10)
        pm2  = (3500 + rng2.normal(0, 1000, n2) - dg2 * 80).clip(500, 15000)
        sf2  = rng2.normal(75, 30, n2).clip(15, 300)
        np2  = (sf2 / 20 + rng2.normal(0, 0.5, n2)).clip(1, 8).astype(int)
        mat_data    = np.column_stack([pm2, sf2, np2, dg2, de2])
        vars_labels = ["Valeur", "Surface", "Nb pieces", "Dist. gare", "Dist. ecole"]

    corr = np.corrcoef(mat_data.T)
    fig3 = go.Figure(go.Heatmap(
        z=corr, x=vars_labels, y=vars_labels,
        # Échelle divergente charte : marron chaud (négatif) -> beige (0) -> vert (positif).
        colorscale=[[0, CHARTE["accent"]], [0.5, CHARTE["fig_bg"]], [1, CHARTE["vert"]]],
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in corr],
        texttemplate="%{text}",
        hovertemplate="<b>%{x}</b> × <b>%{y}</b><br>r = %{z:.2f}<extra></extra>",
        colorbar=dict(title="r", thickness=12, len=0.85,
                      tickfont=dict(color=CHARTE["encre"], size=10)),
    ))
    styliser_figure(fig3, hauteur=340, marges=dict(t=12, b=12, l=8, r=8))
    fig3.update_layout(xaxis=dict(showgrid=False), yaxis=dict(showgrid=False, autorange="reversed"))
    st.plotly_chart(fig3, use_container_width=True)

    # ── Domain 6 : gentrification — revenu médian vs. croissance des prix ────────
    st.markdown("---")
    st.markdown("""
    <div class="card-title" style="margin-bottom:12px;font-size:0.95rem">
      💎 Gentrification — Revenu médian (INSEE) vs. croissance des prix (YoY)
    </div>
    """, unsafe_allow_html=True)

    if DB_READY:
        df_growth = back.get_price_growth_by_commune(None)
    else:
        # Repli démo : corrélation positive bruitée revenu / croissance.
        rng3 = np.random.default_rng(11)
        n3 = 60
        rev = rng3.integers(18000, 32000, n3)
        croiss = (rev - 18000) / 1400.0 + rng3.normal(0, 4, n3)
        df_growth = pd.DataFrame({
            "nom_commune": [f"Commune {i}" for i in range(n3)],
            "revenu_median": rev,
            "croissance_pct": croiss.round(1),
            "annee_debut": 2024, "annee_fin": 2025,
        })

    if df_growth is None or df_growth.empty or df_growth["revenu_median"].isna().all():
        st.info(
            "Données insuffisantes pour le nuage revenu-vs-croissance : il faut au moins "
            "2 années dans fact_dvf ET les revenus INSEE (dim_commune). "
            "Voir le NOTE Domain 6 sur les fichiers INSEE."
        )
    else:
        df_g = df_growth.dropna(subset=["revenu_median", "croissance_pct"]).copy()
        # NOTE : la ligne de tendance OLS nécessite statsmodels ; repli sans tendance si absent.
        scatter_kwargs = dict(
            x="revenu_median", y="croissance_pct",
            hover_name="nom_commune",
            labels={"revenu_median": "Revenu médian (€)", "croissance_pct": "Croissance des prix (%)"},
            color_discrete_sequence=[CHARTE["vert"]],
        )
        try:
            import statsmodels  # noqa: F401
            fig_gent = px.scatter(df_g, trendline="ols", **scatter_kwargs)
            fig_gent.update_traces(line=dict(color=CHARTE["accent"], width=2),
                                   selector=dict(mode="lines"))
        except Exception:
            fig_gent = px.scatter(df_g, **scatter_kwargs)
        fig_gent.update_traces(marker=dict(size=7, opacity=0.6), selector=dict(mode="markers"))
        styliser_figure(fig_gent, hauteur=340, marges=dict(t=12, b=12, l=8, r=8))
        fig_gent.update_layout(
            xaxis=dict(showgrid=True, gridcolor=CHARTE["grille"], tickformat=",.0f"),
            yaxis=dict(showgrid=True, gridcolor=CHARTE["grille"]),
            separators=", ",
        )
        st.plotly_chart(fig_gent, use_container_width=True)
        st.caption(
            "Une pente positive suggère un effet de gentrification : les communes à revenu "
            "élevé sont aussi celles où les prix progressent le plus."
        )

    # ── Domain TEMPS : évolution de la population communale (dimension temporelle) ──
    st.markdown("""
    <div class="card" style="margin-top:18px">
      <div class="card-title" style="margin-bottom:12px">Évolution de la population (recensements INSEE)</div>
    """, unsafe_allow_html=True)
    df_pop_t = back.get_population_temporelle() if DB_READY else None
    if df_pop_t is not None and not df_pop_t.empty:
        fig_pop = go.Figure(go.Scatter(
            x=df_pop_t["annee"], y=df_pop_t["population_totale"],
            mode="lines+markers",
            line=dict(color=CHARTE["vert"], width=3),
            marker=dict(size=8, color=CHARTE["accent"]),
            hovertemplate="Année %{x}<br>Population : %{y:,.0f}<extra></extra>",
        ))
        styliser_figure(fig_pop, hauteur=300, marges=dict(t=10, b=10, l=8, r=8))
        fig_pop.update_layout(
            xaxis=dict(title="Millésime du recensement", dtick=1, showgrid=False),
            yaxis=dict(title="Population municipale totale", showgrid=True,
                       gridcolor=CHARTE["grille"], tickformat=",.0f"),
            separators=", ",
        )
        st.plotly_chart(fig_pop, use_container_width=True)
        st.caption(
            "Dimension temporelle (dim_commune_temporel) : la population communale est suivie "
            "sur plusieurs millésimes (2020–2023) — illustration de la prise en compte du "
            "temps dans le modèle de données (Slowly Changing Data)."
        )
    else:
        st.caption("Données de population temporelle indisponibles (dim_commune_temporel absente).")
    st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4 — IMPACT DPE (Domain 4 — prime énergétique)
# ─────────────────────────────────────────────────────────────────────────────
def page_impact_dpe():
    st.markdown("""
    <div class="page-header">
      <h1>Impact DPE</h1>
      <p>Prime énergétique : prix médian /m² par étiquette DPE (DVF × DPE)</p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── Sélecteur de région (réutilise le filtre départemental partagé du back) ──
    region_selectionnee = "Toutes les régions"
    if DB_READY:
        region_selectionnee = st.selectbox("🌍 Filtrer par région", back.get_regions())

    ordre_dpe = ["A", "B", "C", "D", "E", "F", "G"]

    # ── 1) Barres : prix médian /m² par étiquette DPE ──────────────────────────
    st.markdown("""
    <div class="card">
      <div class="card-title">⚡ Prix médian /m² par étiquette DPE</div>
    """, unsafe_allow_html=True)

    if DB_READY:
        df_dpe = back.get_prix_par_dpe(region_selectionnee)
        if df_dpe.empty:
            st.warning("Aucune vente avec étiquette DPE rapprochée pour ce périmètre.")
            st.markdown("</div>", unsafe_allow_html=True)
            return
        # Agrégat tous types confondus : moyenne des médianes pondérée par le nb de ventes
        # (médiane pondérée approchée). Calcul vectorisé -> évite le FutureWarning de
        # groupby().apply() sur les colonnes de groupe.
        df_w = df_dpe.assign(_pondere=df_dpe["prix_m2_median"] * df_dpe["nb_ventes"])
        agg = (df_w.groupby("etiquette_dpe")[["_pondere", "nb_ventes"]].sum()
                   .pipe(lambda g: g["_pondere"] / g["nb_ventes"])
                   .reindex(ordre_dpe).dropna())
        x_vals = list(agg.index)
        y_vals = [float(v) for v in agg.values]
    else:
        # Démo : prime énergétique décroissante de A à G.
        x_vals = ordre_dpe
        y_vals = [4200, 4050, 3850, 3600, 3300, 2950, 2700]
        df_dpe = pd.DataFrame()

    colors = [DPE_COLORS.get(x, "#7A6A58") for x in x_vals]
    fig_dpe = go.Figure(go.Bar(
        x=x_vals, y=y_vals, marker_color=colors,
        text=[f"{int(p):,} €".replace(",", " ") for p in y_vals], textposition="outside",
        hovertemplate="<b>DPE %{x}</b><br>%{y:,.0f} €/m²<extra></extra>",
    ))
    styliser_figure(fig_dpe, hauteur=300, marges=dict(t=28, b=12, l=8, r=8))
    fig_dpe.update_layout(
        xaxis=dict(title="Étiquette énergétique (DPE)", showgrid=False),
        yaxis=dict(title="Prix médian (€/m²)", showgrid=True, gridcolor=CHARTE["grille"],
                   range=[0, (max(y_vals) if y_vals else 0) * 1.2], tickformat=",.0f"),
        showlegend=False, separators=", ",
    )
    st.plotly_chart(fig_dpe, use_container_width=True)
    # Lecture : "est-ce un prix juste vu l'énergie ?" -> écart A vs G chiffré.
    if y_vals:
        ecart = (y_vals[0] / y_vals[-1] - 1) * 100 if y_vals[-1] else 0
        st.caption(f"Prime énergétique : un bien classé **{x_vals[0]}** se négocie environ "
                   f"**{ecart:+.0f} %** par rapport à un bien classé **{x_vals[-1]}** (médianes DVF × DPE).")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── 2) Détail par type de bien + évolution temporelle ──────────────────────
    col_a, col_b = st.columns(2, gap="medium")

    with col_a:
        st.markdown("""
        <div class="card">
          <div class="card-title">🏠 €/m² par étiquette et type de bien</div>
        """, unsafe_allow_html=True)
        if DB_READY and not df_dpe.empty:
            fig_type = px.bar(
                df_dpe.assign(etiquette_dpe=pd.Categorical(df_dpe["etiquette_dpe"], ordre_dpe, ordered=True))
                      .sort_values("etiquette_dpe"),
                x="etiquette_dpe", y="prix_m2_median", color="type_local",
                barmode="group",
                color_discrete_map={"Maison": CHARTE["vert"], "Appartement": CHARTE["accent"]},
                labels={"etiquette_dpe": "Étiquette DPE", "prix_m2_median": "Prix médian (€/m²)",
                        "type_local": "Type"},
            )
            styliser_figure(fig_type, hauteur=300, marges=dict(t=12, b=12, l=8, r=8))
            fig_type.update_layout(
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor=CHARTE["grille"], tickformat=",.0f"),
                legend=dict(orientation="h", y=-0.22, x=0, title_text=None),
                separators=", ",
            )
            st.plotly_chart(fig_type, use_container_width=True)
        else:
            st.info("Détail par type indisponible en mode démo.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_b:
        st.markdown("""
        <div class="card">
          <div class="card-title">📅 Évolution de la prime énergétique (A/B vs F/G)</div>
        """, unsafe_allow_html=True)
        if DB_READY:
            df_tmp = back.get_dpe_premium_temporel(region_selectionnee)
            if not df_tmp.empty:
                fig_tmp = px.line(
                    df_tmp.assign(etiquette_dpe=pd.Categorical(df_tmp["etiquette_dpe"], ordre_dpe, ordered=True)),
                    x="mois", y="prix_m2_median", color="etiquette_dpe",
                    color_discrete_map=DPE_COLORS,
                    labels={"mois": "Mois", "prix_m2_median": "Prix médian (€/m²)", "etiquette_dpe": "DPE"},
                )
                styliser_figure(fig_tmp, hauteur=300, marges=dict(t=12, b=12, l=8, r=8))
                fig_tmp.update_layout(
                    xaxis=dict(showgrid=False, title=None),
                    yaxis=dict(showgrid=True, gridcolor=CHARTE["grille"], tickformat=",.0f"),
                    legend=dict(orientation="h", y=-0.22, x=0, title_text="DPE"),
                    separators=", ",
                )
                st.plotly_chart(fig_tmp, use_container_width=True)
                st.caption("Si l'écart A/B vs F/G se creuse, la sensibilité du marché à l'énergie augmente.")
            else:
                st.warning("Pas assez de points temporels DPE pour ce périmètre.")
        else:
            # Démo : écart qui se creuse dans le temps.
            mois = ["2024-01", "2024-04", "2024-07", "2024-10", "2025-01"]
            fig_tmp = go.Figure()
            fig_tmp.add_trace(go.Scatter(x=mois, y=[4100, 4150, 4220, 4300, 4380],
                                         name="A/B", line=dict(color=DPE_COLORS["B"], width=3)))
            fig_tmp.add_trace(go.Scatter(x=mois, y=[2800, 2780, 2740, 2700, 2650],
                                         name="F/G", line=dict(color=DPE_COLORS["F"], width=3)))
            styliser_figure(fig_tmp, hauteur=300, marges=dict(t=12, b=12, l=8, r=8))
            fig_tmp.update_layout(
                xaxis=dict(showgrid=False),
                yaxis=dict(title="Prix médian (€/m²)", gridcolor=CHARTE["grille"], tickformat=",.0f"),
                legend=dict(orientation="h", y=-0.22, x=0, title_text=None),
                separators=", ",
            )
            st.plotly_chart(fig_tmp, use_container_width=True)
            st.caption("Données simulées (mode démo).")
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5 — OPPORTUNITY FINDER (Domain 6 — score composite par commune)
# ─────────────────────────────────────────────────────────────────────────────
def page_opportunity():
    st.markdown("""
    <div class="page-header">
      <h1>Opportunités d'achat</h1>
      <p>Communes à fort potentiel — score composite (prix · revenu INSEE · énergie · bruit)</p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── Légende des 4 composantes du score ──────────────────────────────────────
    st.markdown("""
    <div class="card" style="margin-bottom:16px;">
      <div class="card-title">🧭 Comment lire le score</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding-top:8px;font-size:0.8rem;">
        <div><strong>💰 Prix (35%)</strong><br>€/m² sous la moyenne = mieux</div>
        <div><strong>👛 Revenu (25%)</strong><br>Revenu médian INSEE élevé = mieux</div>
        <div><strong>⚡ Énergie (25%)</strong><br>Part de DPE A/B/C élevée = mieux</div>
        <div><strong>✈️ Bruit (15%)</strong><br>Faible exposition PEB = mieux</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Sélecteur de commune ────────────────────────────────────────────────────
    commune_selectionnee = "Toutes les communes"
    if DB_READY:
        commune_selectionnee = st.selectbox("🏙️ Filtrer par ville", back.get_communes_dispo())

    if DB_READY:
        df_opp = back.get_opportunity_finder(commune_selectionnee)
        if df_opp.empty:
            st.info(
                "Aucune commune ne satisfait le seuil minimal (≥ 10 ventes) sur ce périmètre, "
                "ou les données socio-économiques INSEE (dim_commune) ne sont pas chargées."
            )
            return
    else:
        # ── Repli démo : données simulées (DB indisponible) ─────────────────────
        rng = np.random.default_rng(7)
        noms = ["Nantes", "Rennes", "Angers", "Le Mans", "La Roche-sur-Yon",
                "Laval", "Cholet", "Saint-Nazaire", "Vannes", "Quimper"]
        df_opp = pd.DataFrame({
            "code_commune": [f"{44000 + i}" for i in range(len(noms))],
            "nom_commune": noms,
            "prix_m2_median": rng.integers(1800, 4200, len(noms)),
            "nb_ventes": rng.integers(15, 400, len(noms)),
            "revenu_median": rng.integers(20000, 28000, len(noms)),
            "part_dpe_bon": rng.uniform(0.2, 0.7, len(noms)),
            "part_bruit": rng.uniform(0.0, 0.2, len(noms)),
        })
        df_opp["score_prix"] = 1 - (df_opp["prix_m2_median"] - df_opp["prix_m2_median"].min()) / (df_opp["prix_m2_median"].max() - df_opp["prix_m2_median"].min())
        df_opp["score_revenu"] = (df_opp["revenu_median"] - df_opp["revenu_median"].min()) / (df_opp["revenu_median"].max() - df_opp["revenu_median"].min())
        df_opp["score_energie"] = df_opp["part_dpe_bon"]
        df_opp["score_bruit"] = 1 - df_opp["part_bruit"]
        df_opp["score_opportunite"] = (
            df_opp["score_prix"] * 0.35 + df_opp["score_revenu"] * 0.25
            + df_opp["score_energie"] * 0.25 + df_opp["score_bruit"] * 0.15
        )
        df_opp = df_opp.sort_values("score_opportunite", ascending=False).reset_index(drop=True)

    # ── Top-N à afficher ────────────────────────────────────────────────────────
    top_n = st.slider("Nombre de communes affichées", 5, 30, 15, step=5)
    df_top = df_opp.head(top_n).copy()

    col_chart, col_table = st.columns([1.2, 1], gap="medium")

    with col_chart:
        st.markdown('<div class="card-title">🏆 Communes les mieux notées</div>', unsafe_allow_html=True)
        # Barres horizontales empilées des 4 sous-scores pondérés (lecture des contributions).
        POIDS = {"score_prix": 0.35, "score_revenu": 0.25, "score_energie": 0.25, "score_bruit": 0.15}
        # Composantes recolorées sur la charte : vert foncé / marron chaud / vert clair / vert principal.
        composantes = [
            ("score_prix", "💰 Prix", "#2C5230"),
            ("score_revenu", "👛 Revenu", "#A6643C"),
            ("score_energie", "⚡ Énergie", "#6B9E70"),
            ("score_bruit", "✈️ Bruit", "#3A6B3F"),
        ]
        df_plot = df_top.iloc[::-1]  # meilleure commune en haut
        fig_opp = go.Figure()
        for col, label, color in composantes:
            fig_opp.add_trace(go.Bar(
                y=df_plot["nom_commune"], x=df_plot[col] * POIDS[col],
                name=label, orientation="h", marker_color=color,
                hovertemplate="<b>%{y}</b><br>" + label + " : %{x:.3f}<extra></extra>",
            ))
        styliser_figure(fig_opp, hauteur=max(320, top_n * 26), marges=dict(t=12, b=12, l=8, r=8))
        fig_opp.update_layout(
            barmode="stack",
            xaxis=dict(title="Score d'opportunité (contributions pondérées, 0–1)",
                       showgrid=True, gridcolor=CHARTE["grille"]),
            yaxis=dict(showgrid=False, title=None),
            legend=dict(orientation="h", y=-0.12, x=0, font=dict(size=10), title_text=None),
        )
        st.plotly_chart(fig_opp, use_container_width=True)
        st.caption("Chaque barre additionne les 4 composantes pondérées du score : "
                   "plus elle est longue, plus la commune est attractive.")

    with col_table:
        st.markdown('<div class="card-title">📋 Classement détaillé</div>', unsafe_allow_html=True)
        df_aff = df_top[[
            "nom_commune", "score_opportunite", "prix_m2_median",
            "revenu_median", "nb_ventes"
        ]].copy()
        df_aff["score_opportunite"] = (df_aff["score_opportunite"] * 100).round(1)
        df_aff = df_aff.rename(columns={
            "nom_commune": "Commune", "score_opportunite": "Score /100",
            "prix_m2_median": "€/m²", "revenu_median": "Revenu médian (€)",
            "nb_ventes": "Ventes",
        })
        st.dataframe(df_aff, use_container_width=True, hide_index=True)
        if df_top["revenu_median"].isna().all():
            st.caption("ℹ️ Revenu médian indisponible (dim_commune INSEE non chargée) — "
                       "score_revenu neutralisé à 0.5.")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────────────────────────────────────
page = st.session_state.page
if page == "Vue Globale":
    page_vue_globale()
elif page == "Trouver un logement":
    page_trouver()
elif page == "Analyses":
    page_analyses()
elif page == "Impact DPE":
    page_impact_dpe()
elif page == "Opportunités":
    page_opportunity()