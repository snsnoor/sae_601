# front.py — Immo France Dashboard
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

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Immo France", layout="wide", initial_sidebar_state="expanded")

# ── CSS injection ──────────────────────────────────────────────────────────────
def local_css(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"Fichier CSS introuvable : {path}")

local_css("Dashboard/CSS/style.css")

# ── DB disponible ? ────────────────────────────────────────────────────────────
DB_READY = back.db_ready()

# ── Session state : page active ────────────────────────────────────────────────
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
        ("Vue Globale",         "📊", "Indicateurs & cartographie"),
        ("Trouver un logement", "🔍", "Recherche filtrée"),
        ("Analyses",            "📈", "Corrélations & modèles"),
    ]

    st.markdown('<div class="nav-section-label">Navigation</div>', unsafe_allow_html=True)

    for name, icon, desc in PAGES:
        if st.button(f"{icon}  {name}", key=f"nav_{name}", use_container_width=True, help=desc):
            st.session_state.page = name
            st.rerun()

    st.markdown("""
    <div class="sidebar-footer">
      <strong>Projet BUT Sciences des Données · 2025-2026</strong><br>
      Nouhayla Bahaddou<br>Quentin Ezanno<br>Noor Nguia Ada
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DONNÉES DE DÉMO
# ─────────────────────────────────────────────────────────────────────────────
random.seed(42)

COMMUNES_SAMPLE = [
    ("Paris 15e",    4820, 9_450), ("Lyon 3e",      2341, 5_200),
    ("Marseille 8e", 1895, 3_870), ("Bordeaux",     1740, 4_120),
    ("Nantes",       1620, 3_650), ("Lille",         980, 3_200),
    ("Grenoble",      870, 3_050), ("Toulon",         760, 2_980),
    ("Rennes",        730, 3_100), ("Montpellier",    690, 3_400),
]

DEMO_BANNER = """
<div class="demo-banner">
  <strong>Mode démo</strong> — données simulées.
  Lancez <code>python init_base.py</code> pour afficher les vraies données DVF.
</div>
"""

def fmt_num(n):
    return f"{n:,}".replace(",", " ")


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

    # --- FILTRES ---
    f1, f2 = st.columns([2, 1])
    with f1:
        region_selectionnee = "Toutes les régions"
        if DB_READY:
            region_selectionnee = st.selectbox("🌍 Filtrer par région", back.get_regions())
    with f2:
        type_local_filter = st.radio(
            "Type de bien",
            options=["Tous", "Appartement", "Maison"],
            horizontal=True,
        )

    with st.spinner("Analyse des transactions en cours..."):

        # ── KPIs ──────────────────────────────────────────────────────────────
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
            nb_tx, nb_com, prix_md, surf_md, periode = ("847 320", "24 601", "3 480 €", "72 m²", "DVF démo")
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
                rows_c = [(r.nom_commune, int(r.nb_ventes), int(r.prix_m2_median or 0))
                          for r in kpis["top_cheres"].itertuples(index=False)]
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
                rows_mc = [(r.nom_commune, int(r.nb_ventes), int(r.prix_m2_median or 0))
                           for r in kpis["top_moins_cheres"].itertuples(index=False)]
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
            st.markdown("""
            <div class="card" style="height:100%;">
              <div class="card-title" style="margin-bottom: 10px;">
                🗺️ Carte des prix médians au m² par commune
              </div>
            """, unsafe_allow_html=True)

            if DB_READY:
                df_prix = back.get_prix_median_par_commune(region_selectionnee)
                if not df_prix.empty:
                    zoom_level = 4.5 if region_selectionnee == 'Toutes les régions' else 6.5
                    fig_map = px.scatter_mapbox(
                        df_prix, lat="latitude", lon="longitude",
                        color="prix_m2_median", size="volume_ventes",
                        hover_name="nom_commune",
                        color_continuous_scale="YlOrRd",
                        range_color=[df_prix['prix_m2_median'].quantile(0.05),
                                     df_prix['prix_m2_median'].quantile(0.85)],
                        mapbox_style="carto-positron", zoom=zoom_level,
                        center={"lat": 46.2276, "lon": 2.2137}, opacity=0.8,
                        labels={'prix_m2_median': 'Prix médian (€/m²)', 'volume_ventes': 'Nb transactions'}
                    )
                    fig_map.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=500)
                    st.plotly_chart(fig_map, use_container_width=True)
                else:
                    st.warning("Aucune donnée géographique pour cette région.")
            else:
                st.info("Carte dynamique désactivée en mode démo.")
            st.markdown("</div>", unsafe_allow_html=True)

        # ── Top communes par type ──────────────────────────────────────────────
        if DB_READY:
            df_top = back.get_top_communes_par_type(n=12, region=region_selectionnee)
            if not df_top.empty:
                max_prix = float(df_top['prix_tous'].max()) if df_top['prix_tous'].notna().any() else 1.0
                rows_html = ""
                for _, r in df_top.iterrows():
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

        # ── Évolution mensuelle ────────────────────────────────────────────────
        st.markdown("""
        <div class="card" style="margin-top:16px;">
          <div class="card-title">📅 Évolution du prix médian / m²</div>
        """, unsafe_allow_html=True)

        if DB_READY:
            df_mois = back.get_prix_par_mois(region_selectionnee, type_local_filter)
            x_vals  = df_mois["mois"].tolist()
            y_vals  = [float(v) for v in df_mois["prix_m2_median"].tolist()]
            colors  = ["#3a6b3f"] * len(x_vals)
        else:
            x_vals = [2020, 2021, 2022, 2023, 2024]
            y_vals = [2950, 3150, 3420, 3510, 3480]
            colors = ["#6b9e70"] * 3 + ["#3a6b3f"] * 2

        max_y = max(y_vals) if y_vals else 0

        fig_bar = go.Figure(go.Bar(
            x=x_vals, y=y_vals, marker_color=colors,
            text=[f"{int(p):,} €".replace(",", " ") for p in y_vals],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>%{y:,} €/m²<extra></extra>",
        ))
        fig_bar.update_layout(
            plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
            font=dict(family="Satoshi, sans-serif", color="#2a1f14", size=12),
            margin=dict(t=25, b=10, l=0, r=0), height=220,
            yaxis=dict(showgrid=True, gridcolor="#ede8df", title="€/m²",
                       range=[0, max_y * 1.2]),
            xaxis=dict(showgrid=False), showlegend=False,
        )
        st.plotly_chart(fig_bar, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — TROUVER UN LOGEMENT
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def charger_et_preparer_donnees(commune, type_local, nb_pieces, surface,
                                budget_min, budget_max, prix_m2_max,
                                dist_gare, dist_ecole):
    df = back.search_properties(
        commune=commune, type_local=type_local, nb_pieces_min=nb_pieces,
        surface_min=float(surface), budget_min=float(budget_min),
        budget_max=float(budget_max), prix_m2_max=float(prix_m2_max),
        dist_gare_max=dist_gare, dist_ecole_max=dist_ecole,
    )

    if df.empty:
        return df, pd.DataFrame()

    np.random.seed(42)
    zones = ["Hors zone", "D (Faible)", "C (Modéré)", "B (Fort)", "A (Très fort)"]
    probs = [0.80, 0.10, 0.05, 0.03, 0.02]
    df["zone_peb"] = np.random.choice(zones, size=len(df), p=probs)

    def evaluer_affaire(row):
        if pd.isna(row['prix_m2_commune']) or pd.isna(row['prix_m2']):
            return "➖"
        ratio = row['prix_m2'] / row['prix_m2_commune']
        if ratio <= 0.90:
            return "✅ Bonne affaire"
        elif ratio >= 1.10:
            return "❌ Surcoté"
        return "➖ Dans la moyenne"

    df["Évaluation"] = df.apply(evaluer_affaire, axis=1)

    df_display = df[[
        "nom_commune", "code_postal", "type_local", "valeur_fonciere",
        "surface_reelle_bati", "nombre_pieces_principales",
        "prix_m2", "prix_m2_commune", "Évaluation",
        "dist_gare_km", "dist_ecole_km",
    ]].rename(columns={
        "nom_commune":               "Commune",
        "code_postal":               "CP",
        "type_local":                "Type",
        "valeur_fonciere":           "Prix (€)",
        "surface_reelle_bati":       "Surface (m²)",
        "nombre_pieces_principales": "Pièces",
        "prix_m2":                   "€/m² (Bien)",
        "prix_m2_commune":           "€/m² (Ville)",
        "dist_gare_km":              "Dist. gare (km)",
        "dist_ecole_km":             "Dist. école (km)",
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

    st.markdown("<div class=\"filter-section-title\">Critères d'achat</div>", unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns([2, 1.2, 0.9, 0.9, 1.5, 1.2])
    with c1:
        commune_input = st.text_input("Commune", placeholder="Ex : Nantes, Lyon...")
    with c2:
        type_logement = st.selectbox("Type", ["Tous", "Maison", "Appartement"])
    with c3:
        nb_pieces = st.number_input("Nb pièces", min_value=1, max_value=10, value=3, step=1)
    with c4:
        surface = st.number_input("Surface (m²)", min_value=10, max_value=500, value=60, step=5)
    with c5:
        prix_range = st.slider("Budget (€)", 50_000, 1_500_000, (150_000, 450_000),
                               step=5_000, format="%d €")
    with c6:
        prix_m2_max = st.number_input("Prix max / m² (€)", min_value=500, max_value=20_000,
                                      value=6_000, step=100)

    st.markdown("<div class=\"filter-section-title\">🏷️ Diagnostic de Performance Énergétique</div>",
                unsafe_allow_html=True)
    st.multiselect(
        "Classes DPE (filtre à venir)",
        options=["A", "B", "C", "D", "E", "F", "G"],
        default=[],
        help="Le filtre DPE sera activé dès que les données sont intégrées à la base.",
    )

    st.markdown("<div class=\"filter-section-title\">🚉 Mobilité & Proximité</div>", unsafe_allow_html=True)

    classes_distance = {
        "Peu importe":          None,
        "< 1 km (Très proche)": 1.0,
        "< 3 km (Proche)":      3.0,
        "< 5 km (Moyen)":       5.0,
        "< 10 km (Éloigné)":   10.0,
    }

    m1, m2 = st.columns(2)
    with m1:
        choix_gare  = st.selectbox("Distance max. jusqu'à une Gare",  list(classes_distance.keys()))
        dist_gare_val  = classes_distance[choix_gare]
    with m2:
        choix_ecole = st.selectbox("Distance max. jusqu'à une École", list(classes_distance.keys()))
        dist_ecole_val = classes_distance[choix_ecole]

    st.markdown("<div class=\"filter-section-title\">📍 Infos à afficher dans les résultats</div>",
                unsafe_allow_html=True)
    fac1, fac2, fac3 = st.columns(3)
    with fac1:
        show_gares    = st.checkbox("Gares proches",           value=True)
    with fac2:
        show_ecoles   = st.checkbox("Écoles proches",          value=True)
    with fac3:
        show_aeroport = st.checkbox("Aéroport le plus proche", value=False)

    col_btn = st.columns([3, 1])[1]
    with col_btn:
        st.button("🔍 Rechercher", use_container_width=True)

    st.markdown("---")

    if not DB_READY:
        st.info("Base non initialisée. Lancez le script d'initialisation pour activer la recherche.")
        return

    with st.spinner("Recherche dans la base de données..."):
        df_results, df_display = charger_et_preparer_donnees(
            commune_input, type_logement, nb_pieces, surface,
            prix_range[0], prix_range[1], prix_m2_max,
            dist_gare_val, dist_ecole_val,
        )

    col_map, col_info = st.columns([1.7, 1], gap="medium")

    with col_map:
        st.markdown('<div class="card-title">🔍 Résultats de recherche</div>', unsafe_allow_html=True)

        if df_results.empty:
            st.warning("Aucun résultat. Essayez d'élargir le budget ou la distance.")
        else:
            st.caption(f"{len(df_results)} transaction(s) — Cliquez sur une ligne pour l'analyser")
            evenement_selection = st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="tableau_biens_immo",
            )

        if not df_results.empty:
            st.markdown("""
            <div class="card" style="margin-top:16px; padding-bottom: 10px;">
              <div class="card-title">⚖️ Analyseur de prix individuel</div>
            """, unsafe_allow_html=True)

            lignes_selectionnees = evenement_selection.selection.rows

            if lignes_selectionnees:
                idx           = lignes_selectionnees[0]
                nom_ville     = str(df_results.iloc[idx]["nom_commune"]).title()
                prix_bien_m2  = float(df_results.iloc[idx]["prix_m2"])
                prix_ville_m2 = float(df_results.iloc[idx]["prix_m2_commune"])
                statut        = df_results.iloc[idx]["Évaluation"]

                fig_gauge = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=prix_bien_m2,
                    title={'text': f"<b>{nom_ville}</b> — {statut}",
                           'font': {'size': 14, 'family': 'Inter'}},
                    delta={'reference': prix_ville_m2,
                           'increasing': {'color': "#D62828"},
                           'decreasing': {'color': "#2D6A4F"},
                           'font': {'size': 14}},
                    gauge={
                        'axis': {'range': [None, max(prix_bien_m2, prix_ville_m2) * 1.3],
                                 'tickfont': {'size': 10}},
                        'bar': {'color': "#495057"},
                        'steps': [
                            {'range': [0, prix_ville_m2 * 0.9],  'color': "#2D6A4F"},
                            {'range': [prix_ville_m2 * 0.9, prix_ville_m2 * 1.1], 'color': "#FFC107"},
                            {'range': [prix_ville_m2 * 1.1,
                                       max(prix_bien_m2, prix_ville_m2) * 1.3], 'color': "#D62828"},
                        ],
                        'threshold': {'line': {'color': "black", 'width': 3},
                                      'thickness': 0.75, 'value': prix_ville_m2},
                    }
                ))
                fig_gauge.update_layout(
                    margin=dict(t=50, b=20, l=20, r=20), height=250,
                    paper_bgcolor="#faf7f2",
                )
                st.plotly_chart(fig_gauge, use_container_width=True)
            else:
                st.info("💡 Cliquez sur une ligne du tableau pour comparer ce bien au marché.")

            st.markdown("</div>", unsafe_allow_html=True)

    with col_info:
        if not df_results.empty:
            med_prix  = df_results["prix_m2"].median()
            med_surf  = df_results["surface_reelle_bati"].median()
            med_ville = df_results["prix_m2_commune"].median()

            st.markdown(f"""
            <div class="card">
              <div class="card-title">Statistiques de la sélection</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;
                          text-align:center;padding-top:10px;">
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3d2b1f">{int(med_prix):,} €</div>
                  <div style="font-size:0.75rem;color:#b8a898;text-transform:uppercase">Prix médian /m²</div>
                </div>
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3d2b1f">{int(med_ville):,} €</div>
                  <div style="font-size:0.75rem;color:#b8a898;text-transform:uppercase">Moyenne Ville /m²</div>
                </div>
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3d2b1f">{int(med_surf)} m²</div>
                  <div style="font-size:0.75rem;color:#b8a898;text-transform:uppercase">Surface médiane</div>
                </div>
                <div>
                  <div style="font-size:1.2rem;font-weight:800;color:#3d2b1f">{len(df_results)}</div>
                  <div style="font-size:0.75rem;color:#b8a898;text-transform:uppercase">Transactions</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            if show_gares and "nom_gare_proche" in df_results.columns:
                gares = (df_results[["nom_gare_proche", "dist_gare_km"]]
                         .dropna(subset=["nom_gare_proche"])
                         .drop_duplicates("nom_gare_proche")
                         .sort_values("dist_gare_km")
                         .head(8))
                if not gares.empty:
                    items = "".join(
                        f'<div class="facility-item">🚉 <strong>{r.nom_gare_proche}</strong>'
                        f' — {r.dist_gare_km:.1f} km</div>'
                        for r in gares.itertuples(index=False)
                    )
                    st.markdown(f"""
                    <div class="facility-panel">
                      <div class="facility-panel-title">Gares proches</div>
                      {items}
                    </div>
                    """, unsafe_allow_html=True)

            if show_ecoles and "nom_ecole_proche" in df_results.columns:
                ecoles = (df_results[["nom_ecole_proche", "dist_ecole_km"]]
                          .dropna(subset=["nom_ecole_proche"])
                          .drop_duplicates("nom_ecole_proche")
                          .sort_values("dist_ecole_km")
                          .head(8))
                if not ecoles.empty:
                    items = "".join(
                        f'<div class="facility-item">🏫 <strong>{r.nom_ecole_proche}</strong>'
                        f' — {r.dist_ecole_km:.1f} km</div>'
                        for r in ecoles.itertuples(index=False)
                    )
                    st.markdown(f"""
                    <div class="facility-panel">
                      <div class="facility-panel-title">Écoles proches</div>
                      {items}
                    </div>
                    """, unsafe_allow_html=True)

            if show_aeroport and "nom_aeroport_proche" in df_results.columns:
                aero_df = (df_results[["nom_aeroport_proche", "dist_aeroport_km"]]
                           .dropna(subset=["nom_aeroport_proche"])
                           .sort_values("dist_aeroport_km"))
                if not aero_df.empty:
                    row = aero_df.iloc[0]
                    st.markdown(f"""
                    <div class="facility-panel">
                      <div class="facility-panel-title">Aéroport le plus proche</div>
                      <div class="facility-item">✈️ <strong>{row['nom_aeroport_proche']}</strong>
                       — {int(row['dist_aeroport_km'])} km</div>
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

    with st.spinner("Calcul des corrélations..."):
        if DB_READY:
            df_prox       = back.get_prix_vs_proximite()
            dist_gare     = df_prox["dist_gare_km"].values
            dist_eco      = df_prox["dist_ecole_km"].values
            prix_m2       = df_prox["prix_m2"].values
            base_price_an = back.get_kpis()["prix_m2_median"]
        else:
            rng = np.random.default_rng(42)
            n = 300
            dist_gare     = rng.exponential(scale=3, size=n).clip(0.1, 20)
            dist_eco      = rng.exponential(scale=2, size=n).clip(0.1, 10)
            prix_m2       = (3500 + rng.normal(0, 1000, n) - dist_gare * 80 - dist_eco * 30).clip(500, 15000)
            base_price_an = 3480

    col1, col2 = st.columns(2, gap="medium")

    with col1:
        st.markdown("""
        <div class="card">
          <div class="card-title" style="margin-bottom:12px">Prix/m² vs. proximité gare</div>
        """, unsafe_allow_html=True)
        fig1 = go.Figure(go.Scatter(
            x=dist_gare, y=prix_m2, mode="markers",
            marker=dict(color="#3a6b3f", size=5, opacity=0.5),
            hovertemplate="Dist. gare : %{x:.2f} km<br>Prix : %{y:,.0f} €/m²<extra></extra>",
        ))
        fig1.update_layout(
            plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
            font=dict(family="Satoshi,sans-serif", color="#2a1f14", size=11),
            margin=dict(t=8, b=8, l=0, r=0), height=280,
            xaxis=dict(title="Distance gare (km)", showgrid=True, gridcolor="#ede8df"),
            yaxis=dict(title="€/m²", showgrid=True, gridcolor="#ede8df"),
        )
        st.plotly_chart(fig1, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="card">
          <div class="card-title" style="margin-bottom:12px">Prix/m² vs. proximité école</div>
        """, unsafe_allow_html=True)
        fig2 = go.Figure(go.Scatter(
            x=dist_eco, y=prix_m2, mode="markers",
            marker=dict(color="#e07b39", size=5, opacity=0.5),
            hovertemplate="Dist. école : %{x:.2f} km<br>Prix : %{y:,.0f} €/m²<extra></extra>",
        ))
        fig2.update_layout(
            plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
            font=dict(family="Satoshi,sans-serif", color="#2a1f14", size=11),
            margin=dict(t=8, b=8, l=0, r=0), height=280,
            xaxis=dict(title="Distance école (km)", showgrid=True, gridcolor="#ede8df"),
            yaxis=dict(title="€/m²", showgrid=True, gridcolor="#ede8df"),
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Impact bruit aéroportuaire ──────────────────────────────────────────
    st.markdown("""
    <div class="card" style="margin-top:16px; padding-bottom: 0;">
      <div class="card-title">✈️ Impact du bruit aéroportuaire sur le prix / m²</div>
    """, unsafe_allow_html=True)

    df_peb = pd.DataFrame({
        "Zone": ["A (Très fort)", "B (Fort)", "C (Modéré)", "D (Faible)", "Hors zone"],
        "Prix": [base_price_an * 0.80, base_price_an * 0.85,
                 base_price_an * 0.92, base_price_an * 0.98, base_price_an],
    })
    couleurs_bruit = ["#B00020", "#D62828", "#FFC107", "#81B29A", "#2D6A4F"]

    fig_peb = go.Figure(go.Bar(
        x=df_peb["Zone"], y=df_peb["Prix"],
        marker_color=couleurs_bruit,
        text=[f"{int(p):,} €".replace(",", " ") for p in df_peb["Prix"]],
        textposition="outside",
        hovertemplate="<b>Zone %{x}</b><br>Prix moyen : %{y:,.0f} €/m²<extra></extra>",
    ))
    fig_peb.update_layout(
        plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
        font=dict(family="Satoshi, sans-serif", color="#2a1f14", size=11),
        margin=dict(t=25, b=10, l=0, r=0), height=220,
        xaxis=dict(showgrid=False),
        yaxis=dict(title="€/m²", showgrid=True, gridcolor="#ede8df",
                   range=[0, base_price_an * 1.3]),
        showlegend=False,
    )
    st.plotly_chart(fig_peb, use_container_width=True)
    st.markdown("""
      <div style="font-size:0.7rem;color:#7a6a58;text-align:right;margin-top:-10px;padding-bottom:10px;">
        *Données simulées basées sur le prix médian national ou régional global
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Matrice de corrélation ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div class="card-title" style="margin-bottom:12px;font-size:0.95rem">
      Matrice de corrélation — variables numériques clés
    </div>
    """, unsafe_allow_html=True)

    if DB_READY:
        surface_v   = df_prox["surface_reelle_bati"].values.astype(float)
        mat_data    = np.column_stack([prix_m2, dist_gare, dist_eco, surface_v])
        vars_labels = ["Prix/m²", "Dist. gare", "Dist. école", "Surface"]
    else:
        rng2 = np.random.default_rng(42)
        n2   = 300
        dg2  = rng2.exponential(scale=3, size=n2).clip(0.1, 20)
        de2  = rng2.exponential(scale=2, size=n2).clip(0.1, 10)
        pm2  = (3500 + rng2.normal(0, 1000, n2) - dg2 * 80).clip(500, 15000)
        sf2  = rng2.normal(75, 30, n2).clip(15, 300)
        np2  = (sf2 / 20 + rng2.normal(0, 0.5, n2)).clip(1, 8).astype(int)
        mat_data    = np.column_stack([pm2, sf2, np2, dg2, de2])
        vars_labels = ["Valeur", "Surface", "Nb pièces", "Dist. gare", "Dist. école"]

    corr = np.corrcoef(mat_data.T)
    fig3 = go.Figure(go.Heatmap(
        z=corr, x=vars_labels, y=vars_labels,
        colorscale=[[0, "#c4a882"], [0.5, "#faf7f2"], [1, "#3a6b3f"]],
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in corr],
        texttemplate="%{text}",
        hovertemplate="<b>%{x}</b> x <b>%{y}</b><br>r = %{z:.2f}<extra></extra>",
    ))
    fig3.update_layout(
        plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
        font=dict(family="Satoshi,sans-serif", color="#2a1f14", size=11),
        margin=dict(t=10, b=10, l=0, r=0), height=320,
    )
    st.plotly_chart(fig3, width='stretch')


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
