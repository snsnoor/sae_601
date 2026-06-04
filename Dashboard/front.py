# front.py  —  ImmoFrance Dashboard
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import random
import back

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ImmoFrance",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
def local_css(path):
    with open(path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

local_css("css/style.css")

# ── DB state ──────────────────────────────────────────────────────────────────
DB_READY = back.db_ready()

# ── Brand header ──────────────────────────────────────────────────────────────
st.markdown("""
<div class="nav-brand-row">
  <div class="nav-brand">
    <svg width="22" height="22" viewBox="0 0 36 36" fill="none">
      <rect width="36" height="36" rx="9" fill="#3a6b3f"/>
      <path d="M18 7 L8 16 L8 29 L15 29 L15 21 L21 21 L21 29 L28 29 L28 16 Z"
            fill="none" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/>
    </svg>
    Immo<span>France</span>
  </div>
  <div class="nav-team">
    <strong>BUT Sciences des Données · 2025-2026</strong>
    Nouhayla Bahaddou · Quentin Ezanno · Noor Nguia Ada
  </div>
</div>
""", unsafe_allow_html=True)

# ── Navigation (tabs) ─────────────────────────────────────────────────────────
tab_vg, tab_tr, tab_an = st.tabs([
    "📊  Vue Globale",
    "🔍  Trouver un logement",
    "📈  Analyses",
])

# ── Données démo ──────────────────────────────────────────────────────────────
random.seed(42)

DEMO_COMMUNES = [
    ("Paris 15e",    "75015", 4820, 9_450, 10_200, 8_300),
    ("Lyon 3e",      "69003", 2341, 5_200, 5_800,  4_700),
    ("Marseille 8e", "13008", 1895, 3_870, 4_100,  3_500),
    ("Bordeaux",     "33000", 1740, 4_120, 4_600,  3_800),
    ("Nantes",       "44000", 1620, 3_650, 4_000,  3_300),
    ("Toulouse",     "31000", 1580, 3_490, 3_800,  3_100),
    ("Montpellier",  "34000", 1340, 3_210, 3_600,  2_900),
    ("Rennes",       "35000", 1210, 3_080, 3_400,  2_800),
    ("Strasbourg",   "67000", 1050, 3_720, 4_100,  3_300),
    ("Nice",         "06000",  980, 5_650, 6_200,  5_100),
]

DEMO_BANNER = """
<div class="demo-banner">
  <strong>Mode démo</strong> — données simulées.
  Lancez <code>python init_base.py</code> pour afficher les vraies données DVF.
</div>
"""

def fmt(n, unit=""):
    if n is None:
        return "—"
    s = f"{int(n):,}".replace(",", " ")
    return f"{s}{unit}"


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — VUE GLOBALE
# ─────────────────────────────────────────────────────────────────────────────
with tab_vg:
    import plotly.graph_objects as go
    import numpy as np

    st.markdown("""
    <div class="page-header">
      <h1>Vue Globale du Marché Immobilier</h1>
      <p class="page-desc">
        Explorez les prix médians au m², les tendances mensuelles et les communes
        les plus actives en France — sur les transactions DVF 2024-2025.
        Sélectionnez une commune pour affiner tous les indicateurs.
      </p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── Filtres ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([2.5, 2, 2])
    with fc1:
        if DB_READY:
            communes_list = ["— France entière —"] + back.get_communes_list()
            commune_sel = st.selectbox("Commune / Ville", communes_list,
                                       label_visibility="visible")
            commune_q = "" if commune_sel.startswith("—") else commune_sel
        else:
            commune_sel = st.selectbox("Commune / Ville",
                                       ["— France entière —"] + [c[0] for c in DEMO_COMMUNES],
                                       label_visibility="visible")
            commune_q = ""
    with fc2:
        type_sel = st.radio("Type de bien", ["Tous", "Appartement", "Maison"],
                            horizontal=True, label_visibility="visible")
    with fc3:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── Layout principal ──────────────────────────────────────────────────────
    col_left, col_right = st.columns([2, 3], gap="large")

    # ── Colonne gauche : prix hero + KPIs ─────────────────────────────────────
    with col_left:
        if DB_READY:
            kpis     = back.get_kpis(commune_q)
            var_data = back.get_variation_prix(commune_q)
            prix_med = int(kpis["prix_m2_median"]) if kpis["prix_m2_median"] else 0
            variation = var_data["variation"]
        else:
            prix_med  = 3_610
            variation = -5.0

        # Grand prix
        st.markdown(f"""
        <div class="prix-hero">
          <div>
            <span class="prix-hero-value">{fmt(prix_med)} €</span>
            <span class="prix-hero-unit">/m²</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Badge variation
        if variation is not None:
            if variation > 0:
                badge_cls, arrow, label = "up",   "↑", f"+{variation:.1f}% vs 2024"
            elif variation < 0:
                badge_cls, arrow, label = "down", "↓", f"{variation:.1f}% vs 2024"
            else:
                badge_cls, arrow, label = "flat", "→", "Stable vs 2024"
            st.markdown(
                f'<div class="prix-variation {badge_cls}">{arrow} {label}</div>',
                unsafe_allow_html=True,
            )

        # KPI mini-cards
        if DB_READY:
            nb_tx  = kpis["nb_transactions"]
            nb_com = kpis["nb_communes"]
            surf   = kpis["surface_mediane"]
        else:
            nb_tx, nb_com, surf = 847_320, 24_601, 72

        st.markdown(f"""
        <div class="kpi-grid" style="grid-template-columns:1fr 1fr;margin-top:16px">
          <div class="kpi-card kpi-accent">
            <div class="kpi-label">Transactions</div>
            <div class="kpi-value">{fmt(nb_tx)}</div>
            <div class="kpi-sub">ventes 2024-2025</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Communes</div>
            <div class="kpi-value">{fmt(nb_com)}</div>
            <div class="kpi-sub">avec au moins 1 vente</div>
          </div>
          <div class="kpi-card" style="grid-column:span 2">
            <div class="kpi-label">Surface médiane</div>
            <div class="kpi-value">{fmt(surf)} m²</div>
            <div class="kpi-sub">maisons & appartements</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Colonne droite : région + évolution ───────────────────────────────────
    with col_right:

        # DANS LA RÉGION
        st.markdown("""
        <div class="card-title" style="margin-bottom:10px">
          📍 DANS LA RÉGION
        </div>
        """, unsafe_allow_html=True)

        if DB_READY:
            df_top = back.get_top_communes_par_type(12, commune_q)
            top_rows = [
                (r.nom_commune, r.code_postal, int(r.nb_transactions),
                 r.prix_tous, r.prix_appart, r.prix_maison)
                for r in df_top.itertuples()
            ]
        else:
            top_rows = [(c[0], c[1], c[2], c[3], c[4], c[5]) for c in DEMO_COMMUNES]

        # Filtrage selon le type sélectionné
        if type_sel == "Appartement":
            price_field = 4
        elif type_sel == "Maison":
            price_field = 5
        else:
            price_field = 3

        # Calcul du max pour les barres
        prix_values = [r[price_field] for r in top_rows if r[price_field]]
        prix_max = max(prix_values) if prix_values else 1

        html_items = []
        for i, (nom, cp, nb, p_tous, p_appart, p_maison) in enumerate(top_rows):
            prix_display = {3: p_tous, 4: p_appart, 5: p_maison}[price_field]
            bar_pct = round((prix_display or 0) / prix_max * 100, 1) if prix_max else 0

            appart_str = f"{fmt(p_appart)} €" if p_appart else "—"
            maison_str = f"{fmt(p_maison)} €" if p_maison else "—"

            highlight = "commune-rank-highlight" if i == 0 else ""
            html_items.append(f"""
            <li class="commune-item {highlight}">
              <div class="commune-header">
                <span class="commune-name">{nom}</span>
                <span class="commune-price-main">{fmt(prix_display)} €/m²</span>
              </div>
              <div class="commune-sub">
                <span>{fmt(nb)} ventes</span>
                <span class="commune-price-types">
                  <span class="commune-price-type">appart <strong>{appart_str}/m²</strong></span>
                  <span class="commune-price-type">maison <strong>{maison_str}/m²</strong></span>
                </span>
              </div>
              <div class="commune-bar-bg">
                <div class="commune-bar-fill" style="width:{bar_pct}%"></div>
              </div>
            </li>
            """)

        st.markdown(
            '<ul class="commune-list">' + "".join(html_items) + "</ul>",
            unsafe_allow_html=True,
        )

        st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)

        # ÉVOLUTION DU PRIX /m²
        st.markdown("""
        <div class="card-title" style="margin-bottom:6px">
          📈 ÉVOLUTION PRIX /m²
        </div>
        """, unsafe_allow_html=True)

        if DB_READY:
            df_ev = back.get_prix_par_mois(commune_q, type_sel if type_sel != "Tous" else "")
            x_ev  = df_ev["mois"].tolist()
            y_ev  = [float(v) for v in df_ev["prix_m2_median"].tolist()]
        else:
            x_ev = ["2024-01","2024-03","2024-05","2024-07","2024-09","2024-11",
                    "2025-01","2025-03"]
            y_ev = [3_200, 3_310, 3_450, 3_580, 3_520, 3_490, 3_560, 3_610]

        if x_ev:
            fig_ev = go.Figure()
            fig_ev.add_trace(go.Scatter(
                x=x_ev, y=y_ev,
                mode="lines",
                line=dict(color="#e07b39", width=2.5, shape="spline"),
                fill="tozeroy",
                fillcolor="rgba(224,123,57,0.10)",
                hovertemplate="%{x}<br><b>%{y:,.0f} €/m²</b><extra></extra>",
            ))
            # Annotations premier et dernier point
            if len(x_ev) >= 2:
                fig_ev.add_annotation(x=x_ev[0],  y=y_ev[0],
                    text=f"{x_ev[0]} · {fmt(y_ev[0])} €",
                    showarrow=False, font=dict(size=10, color="#b8a898"),
                    xanchor="left", yanchor="bottom", yshift=6)
                fig_ev.add_annotation(x=x_ev[-1], y=y_ev[-1],
                    text=f"{x_ev[-1]} · {fmt(y_ev[-1])} €",
                    showarrow=False, font=dict(size=10, color="#e07b39", family="Satoshi"),
                    xanchor="right", yanchor="bottom", yshift=6, font_weight=700)
            fig_ev.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Satoshi, sans-serif", color="#7a6a58", size=11),
                margin=dict(t=16, b=8, l=0, r=0), height=190,
                xaxis=dict(showgrid=False, showline=False, tickfont=dict(size=10)),
                yaxis=dict(showgrid=True, gridcolor="#ede8df", showline=False,
                           tickfont=dict(size=10), tickformat=",.0f"),
                showlegend=False,
            )
            st.plotly_chart(fig_ev, width="stretch")
        else:
            st.caption("Pas assez de données pour tracer l'évolution.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — TROUVER UN LOGEMENT
# ─────────────────────────────────────────────────────────────────────────────
with tab_tr:
    st.markdown("""
    <div class="page-header">
      <h1>Trouver un Logement</h1>
      <p class="page-desc">
        Filtrez les ventes réelles DVF 2024-2025 par commune, type, budget et surface.
        Les résultats affichent aussi les gares et écoles les plus proches.
      </p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── Critères ──────────────────────────────────────────────────────────────
    st.markdown('<div class="filter-section-title">Critères de recherche</div>',
                unsafe_allow_html=True)

    r1c1, r1c2, r1c3, r1c4 = st.columns([2.5, 2, 1.2, 1.2])
    with r1c1:
        commune_rech = st.text_input("Commune", placeholder="Ex : Nantes, Lyon...",
                                     label_visibility="visible")
    with r1c2:
        if DB_READY:
            types_dispo = ["Tous"] + back.get_types_locaux()
        else:
            types_dispo = ["Tous", "Appartement", "Maison",
                           "Local industriel. commercial ou assimilé", "Dépendance"]
        type_rech = st.selectbox("Type de bien", types_dispo, label_visibility="visible")
    with r1c3:
        nb_pieces_min = st.number_input("Pièces min", min_value=1, max_value=10,
                                        value=1, step=1, label_visibility="visible")
    with r1c4:
        surface_min = st.number_input("Surface min (m²)", min_value=10, max_value=500,
                                      value=20, step=5, label_visibility="visible")

    r2c1, r2c2, r2c3 = st.columns([3, 1.5, 1.5])
    with r2c1:
        prix_range = st.slider("Budget (€)", 50_000, 1_500_000,
                               (100_000, 500_000), step=5_000,
                               format="%d €", label_visibility="visible")
    with r2c2:
        prix_m2_max = st.number_input("Prix max /m² (€)", min_value=500,
                                      max_value=25_000, value=8_000,
                                      step=100, label_visibility="visible")
    with r2c3:
        dpe_filter = st.multiselect("Étiquette DPE",
                                    ["A","B","C","D","E","F","G"],
                                    default=["A","B","C","D"],
                                    label_visibility="visible")

    # Options proximité
    st.markdown('<div style="margin-top:4px"></div>', unsafe_allow_html=True)
    px1, px2, _ = st.columns([1.5, 1.5, 5])
    with px1:
        proche_gare   = st.checkbox("🚉 Afficher gares proches",  value=False)
    with px2:
        proche_ecole  = st.checkbox("📚 Afficher écoles proches", value=False)

    col_btn = st.columns([5, 1])[1]
    with col_btn:
        rechercher = st.button("🔍 Rechercher", width="stretch")

    st.markdown("---")

    if not DB_READY:
        st.info("Base non initialisée — lancez `python init_base.py` pour activer la recherche.")
    else:
        df_r = back.search_properties(
            commune=commune_rech,
            type_local=type_rech,
            nb_pieces_min=nb_pieces_min,
            surface_min=float(surface_min),
            budget_min=float(prix_range[0]),
            budget_max=float(prix_range[1]),
            prix_m2_max=float(prix_m2_max),
        )

        col_res, col_prox = st.columns([3, 2], gap="medium")

        with col_res:
            if df_r.empty:
                st.warning("Aucun résultat — essayez d'élargir vos critères.")
            else:
                st.caption(f"{len(df_r)} transaction(s) — 200 max affichées")
                st.dataframe(
                    df_r[[
                        "nom_commune", "code_postal", "date_mutation",
                        "valeur_fonciere", "surface_reelle_bati",
                        "nombre_pieces_principales", "type_local", "prix_m2",
                    ]].rename(columns={
                        "nom_commune": "Commune", "code_postal": "CP",
                        "date_mutation": "Date", "valeur_fonciere": "Prix (€)",
                        "surface_reelle_bati": "Surface (m²)",
                        "nombre_pieces_principales": "Pièces",
                        "type_local": "Type", "prix_m2": "€/m²",
                    }),
                    width="stretch", hide_index=True,
                )

            st.markdown("""
            <div class="map-placeholder">
              <svg width="42" height="42" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="1.5">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/>
                <circle cx="12" cy="10" r="3"/>
              </svg>
              <span>Carte Folium — TODO</span>
              <span style="font-size:0.72rem">lat/lon disponibles dans df_results</span>
            </div>
            """, unsafe_allow_html=True)

        with col_prox:
            if not df_r.empty:
                # Stats rapides
                med_prix = df_r["prix_m2"].median()
                med_surf = df_r["surface_reelle_bati"].median()
                st.markdown(f"""
                <div class="card">
                  <div class="card-title">Sélection</div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;text-align:center">
                    <div>
                      <div style="font-size:1.3rem;font-weight:800;color:#3d2b1f;font-family:'Cabinet Grotesk',sans-serif">
                        {fmt(med_prix)} €</div>
                      <div style="font-size:0.68rem;color:#b8a898;text-transform:uppercase">Prix médian /m²</div>
                    </div>
                    <div>
                      <div style="font-size:1.3rem;font-weight:800;color:#3d2b1f;font-family:'Cabinet Grotesk',sans-serif">
                        {fmt(med_surf)} m²</div>
                      <div style="font-size:0.68rem;color:#b8a898;text-transform:uppercase">Surface médiane</div>
                    </div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

            # Panel gares proches
            if proche_gare and not df_r.empty:
                gares_proches = (
                    df_r[["nom_gare_proche", "dist_gare_km"]]
                    .dropna()
                    .sort_values("dist_gare_km")
                    .drop_duplicates("nom_gare_proche")
                    .head(8)
                )
                items_html = "".join([
                    f'<div class="facility-item">'
                    f'<span class="facility-item-name">🚉 {row.nom_gare_proche}</span>'
                    f'<span class="facility-item-dist">{row.dist_gare_km:.1f} km</span>'
                    f'</div>'
                    for row in gares_proches.itertuples()
                ])
                st.markdown(f"""
                <div class="facility-panel">
                  <div class="facility-panel-title">🚉 Gares les plus proches</div>
                  {items_html if items_html else '<div style="font-size:0.8rem;color:#b8a898">Aucune donnée</div>'}
                </div>
                """, unsafe_allow_html=True)

            # Panel écoles proches
            if proche_ecole and not df_r.empty:
                ecoles_proches = (
                    df_r[["nom_ecole_proche", "dist_ecole_km"]]
                    .dropna()
                    .sort_values("dist_ecole_km")
                    .drop_duplicates("nom_ecole_proche")
                    .head(8)
                )
                items_html = "".join([
                    f'<div class="facility-item">'
                    f'<span class="facility-item-name">📚 {row.nom_ecole_proche}</span>'
                    f'<span class="facility-item-dist">{row.dist_ecole_km:.1f} km</span>'
                    f'</div>'
                    for row in ecoles_proches.itertuples()
                ])
                st.markdown(f"""
                <div class="facility-panel">
                  <div class="facility-panel-title">📚 Écoles les plus proches</div>
                  {items_html if items_html else '<div style="font-size:0.8rem;color:#b8a898">Aucune donnée</div>'}
                </div>
                """, unsafe_allow_html=True)

            # Aéroport le plus proche
            if not df_r.empty and "nom_aeroport_proche" in df_r.columns:
                aero = (
                    df_r[["nom_aeroport_proche", "dist_aeroport_km"]]
                    .dropna()
                    .sort_values("dist_aeroport_km")
                    .iloc[0] if not df_r[["nom_aeroport_proche", "dist_aeroport_km"]].dropna().empty else None
                )
                if aero is not None:
                    st.markdown(f"""
                    <div class="facility-panel" style="margin-top:8px">
                      <div class="facility-panel-title">✈️ Aéroport le plus proche</div>
                      <div class="facility-item">
                        <span class="facility-item-name">{aero.nom_aeroport_proche}</span>
                        <span class="facility-item-dist">{aero.dist_aeroport_km:.0f} km</span>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — ANALYSES
# ─────────────────────────────────────────────────────────────────────────────
with tab_an:
    import plotly.graph_objects as go
    import numpy as np

    st.markdown("""
    <div class="page-header">
      <h1>Analyses</h1>
      <p class="page-desc">
        Corrélations entre le prix au m² et la proximité des équipements.
        Basé sur un échantillon de 2 000 transactions DVF 2024-2025.
      </p>
    </div>
    """, unsafe_allow_html=True)

    if not DB_READY:
        st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    if DB_READY:
        df_prox   = back.get_prix_vs_proximite(2000)
        dist_gare = df_prox["dist_gare_km"].values
        dist_eco  = df_prox["dist_ecole_km"].values
        prix_m2   = df_prox["prix_m2"].values
        surf      = df_prox["surface_reelle_bati"].values
    else:
        rng = np.random.default_rng(42)
        n = 400
        dist_gare = rng.exponential(scale=3, size=n).clip(0.1, 20)
        dist_eco  = rng.exponential(scale=2, size=n).clip(0.1, 10)
        prix_m2   = (3_500 + rng.normal(0, 1_000, n) - dist_gare * 80 - dist_eco * 30).clip(500, 15_000)
        surf      = rng.normal(75, 30, n).clip(15, 300)

    col1, col2 = st.columns(2, gap="medium")

    with col1:
        st.markdown('<div class="chart-area">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">Prix/m² vs. Distance gare (km)</div>',
                    unsafe_allow_html=True)
        fig1 = go.Figure(go.Scatter(
            x=dist_gare, y=prix_m2, mode="markers",
            marker=dict(color="#3a6b3f", size=4, opacity=0.45),
            hovertemplate="Dist. gare : %{x:.2f} km<br>Prix : %{y:,.0f} €/m²<extra></extra>",
        ))
        fig1.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Satoshi", color="#7a6a58", size=11),
            margin=dict(t=4, b=4, l=0, r=0), height=260,
            xaxis=dict(title="Distance gare (km)", showgrid=True, gridcolor="#ede8df"),
            yaxis=dict(title="€/m²", showgrid=True, gridcolor="#ede8df"),
        )
        st.plotly_chart(fig1, width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="chart-area">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">Prix/m² vs. Distance école (km)</div>',
                    unsafe_allow_html=True)
        fig2 = go.Figure(go.Scatter(
            x=dist_eco, y=prix_m2, mode="markers",
            marker=dict(color="#e07b39", size=4, opacity=0.45),
            hovertemplate="Dist. école : %{x:.2f} km<br>Prix : %{y:,.0f} €/m²<extra></extra>",
        ))
        fig2.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Satoshi", color="#7a6a58", size=11),
            margin=dict(t=4, b=4, l=0, r=0), height=260,
            xaxis=dict(title="Distance école (km)", showgrid=True, gridcolor="#ede8df"),
            yaxis=dict(title="€/m²", showgrid=True, gridcolor="#ede8df"),
        )
        st.plotly_chart(fig2, width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

    # Matrice de corrélation
    st.markdown("---")
    if DB_READY:
        mat   = np.column_stack([prix_m2, dist_gare, dist_eco, surf])
        lbls  = ["Prix/m²", "Dist. gare", "Dist. école", "Surface"]
    else:
        nb_p  = (surf / 20 + np.random.default_rng(1).normal(0, 0.5, len(surf))).clip(1,8).astype(int)
        mat   = np.column_stack([prix_m2, surf, nb_p, dist_gare, dist_eco])
        lbls  = ["Prix/m²", "Surface", "Nb pièces", "Dist. gare", "Dist. école"]

    corr = np.corrcoef(mat.T)
    fig3 = go.Figure(go.Heatmap(
        z=corr, x=lbls, y=lbls,
        colorscale=[[0,"#c4a882"],[0.5,"#faf7f2"],[1,"#3a6b3f"]],
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in corr],
        texttemplate="%{text}",
        hovertemplate="<b>%{x}</b> × <b>%{y}</b><br>r = %{z:.2f}<extra></extra>",
    ))
    fig3.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Satoshi", color="#7a6a58", size=11),
        margin=dict(t=10, b=10, l=0, r=0), height=320,
        title=dict(text="Matrice de corrélation — variables clés", font=dict(size=13, color="#7a6a58"), x=0)
    )
    st.plotly_chart(fig3, width="stretch")
