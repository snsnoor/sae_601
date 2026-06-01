# front.py  —  Immo France Dashboard
import streamlit as st
import random, math

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Immo France", layout="wide", initial_sidebar_state="expanded")

# ── CSS injection ─────────────────────────────────────────────────────────────
def local_css(path):
    with open(path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

local_css("css/style.css")

# ── Session state : page active ───────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Vue Globale"

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo
    st.markdown("""
    <div class="sidebar-logo">
      <svg width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Immo France logo">
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

    # Navigation
    PAGES = [
        ("Vue Globale",       "📊", "Indicateurs & cartographie"),
        ("Trouver un logement","🔍", "Recherche filtrée"),
        ("Analyses",          "📈", "Corrélations & modèles"),
    ]

    st.markdown("<div class="nav-section-label">Navigation</div>", unsafe_allow_html=True)

    for name, icon, desc in PAGES:
        active_cls = "active" if st.session_state.page == name else ""
        if st.button(f"{icon}  {name}", key=f"nav_{name}",
                     use_container_width=True,
                     help=desc):
            st.session_state.page = name
            st.rerun()

    # Footer
    st.markdown("""
    <div class="sidebar-footer">
      <strong>Projet BUT Données · 2025-2026</strong>
      Nouhayla Bahaddou · Quentin Ezanno<br>Noor Nguia Ada
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DONNÉES SIMULÉES
# ─────────────────────────────────────────────────────────────────────────────
random.seed(42)

COMMUNES_SAMPLE = [
    ("Paris 15e",     4820, 9_450),
    ("Lyon 3e",       2341, 5_200),
    ("Marseille 8e",  1895, 3_870),
    ("Bordeaux",      1740, 4_120),
    ("Nantes",        1620, 3_650),
    ("Toulouse",      1580, 3_490),
    ("Montpellier",   1340, 3_210),
    ("Rennes",        1210, 3_080),
    ("Strasbourg",    1050, 3_720),
    ("Nice",           980, 5_650),
]

COMMUNES_SEARCH = [c[0] for c in COMMUNES_SAMPLE] + [
    "Paris 1er","Paris 2e","Paris 3e","Lyon 1er","Lyon 2e","Lille","Grenoble","Toulon","Clermont-Ferrand"
]

DEMO_BANNER = """
<div class="demo-banner">
  ⚠️&nbsp;<strong>Mode démo</strong> — données simulées, en attente des fichiers DVF & DPE réels.
</div>
"""

def fmt_num(n): return f"{n:,}".replace(",", " ")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — VUE GLOBALE
# ─────────────────────────────────────────────────────────────────────────────
def page_vue_globale():
    st.markdown("""
    <div class="page-header">
      <h1>Vue Globale du Marché</h1>
      <p>Indicateurs agrégés · données DVF + DPE · France entière</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── KPI row ──────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="kpi-grid">
      <div class="kpi-card kpi-accent">
        <div class="kpi-label">Transactions totales</div>
        <div class="kpi-value">847 320</div>
        <div class="kpi-sub">DVF 2020-2024</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Communes couvertes</div>
        <div class="kpi-value">24 601</div>
        <div class="kpi-sub">sur 34 945 communes</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Prix médian / m²</div>
        <div class="kpi-value">3 480 €</div>
        <div class="kpi-sub">toutes typologies</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Surface médiane</div>
        <div class="kpi-value">72 m²</div>
        <div class="kpi-sub">logements vendus</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Two columns : top 10 + carte ─────────────────────────────────────────
    col_left, col_right = st.columns([1, 1.4], gap="medium")

    with col_left:
        st.markdown("""
        <div class="card">
          <div class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
            Top 10 communes — volume de ventes
          </div>
          <ul class="commune-list">
    """, unsafe_allow_html=True)

        for i, (name, ventes, prix_m2) in enumerate(COMMUNES_SAMPLE, 1):
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
          <div class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2">
              <polygon points="3 11 22 2 13 21 11 13 3 11"/>
            </svg>
            Carte choroplèthe — Prix médian / m² par commune
          </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="map-placeholder">
          <svg width="56" height="56" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5">
            <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/>
            <line x1="9" y1="3" x2="9" y2="18"/>
            <line x1="15" y1="6" x2="15" y2="21"/>
          </svg>
          <span>Carte Folium / Plotly Choroplèthe</span>
          <span style="font-size:0.72rem">Connecter les données DVF réelles pour afficher</span>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # ── Graphique bar chart simulé ────────────────────────────────────────────
    st.markdown("""
    <div class="card" style="margin-top:0">
      <div class="card-title">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="4" height="18"/><rect x="10" y="8" width="4" height="13"/>
          <rect x="18" y="13" width="4" height="8"/>
        </svg>
        Évolution du prix médian / m² (2020–2024)
      </div>
    </div>
    """, unsafe_allow_html=True)

    import plotly.graph_objects as go
    years = [2020, 2021, 2022, 2023, 2024]
    prices = [2950, 3150, 3420, 3510, 3480]
    fig = go.Figure(go.Bar(
        x=years, y=prices,
        marker_color=["#6b9e70","#6b9e70","#3a6b3f","#3a6b3f","#3a6b3f"],
        text=[f"{p:,} €" for p in prices], textposition="outside",
        hovertemplate="<b>%{x}</b><br>%{y:,} €/m²<extra></extra>"
    ))
    fig.update_layout(
        plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
        font=dict(family="Satoshi, sans-serif", color="#2a1f14", size=12),
        margin=dict(t=10, b=10, l=0, r=0), height=220,
        yaxis=dict(showgrid=True, gridcolor="#ede8df", title="€/m²"),
        xaxis=dict(showgrid=False),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — TROUVER UN LOGEMENT
# ─────────────────────────────────────────────────────────────────────────────
def page_trouver():
    st.markdown("""
    <div class="page-header">
      <h1>Trouver un Logement</h1>
      <p>Renseignez vos critères — la carte se met à jour automatiquement</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    # ── Bloc 1 : Critères d"achat ─────────────────────────────────────────────
    st.markdown("<div class="card">", unsafe_allow_html=True)
    st.markdown("<div class="filter-section-title">Critères dachat</div>", unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns([2, 1.2, 0.9, 0.9, 1.5, 1.2])

    with c1:
        commune_input = st.text_input("Commune", placeholder="Ex : Paris, Lyon…",
                                       label_visibility="visible")
        # Autocomplete suggestions
        if commune_input and len(commune_input) >= 2:
            matches = [c for c in COMMUNES_SEARCH
                       if commune_input.lower() in c.lower()][:5]
            if matches:
                st.markdown("<div style="font-size:0.72rem;color:#7a6a58;margin-top:-12px">"
                            + " · ".join(matches) + "</div>", unsafe_allow_html=True)

    with c2:
        type_logement = st.selectbox("Type de logement",
                                      ["Tous", "Maison", "Appartement", "Studio"],
                                      label_visibility="visible")
    with c3:
        nb_pieces = st.number_input("Nb pièces", min_value=1, max_value=10,
                                     value=3, step=1, label_visibility="visible")
    with c4:
        surface = st.number_input("Surface (m²)", min_value=10, max_value=500,
                                   value=60, step=5, label_visibility="visible")
    with c5:
        prix_range = st.slider("Budget (€)", 50_000, 1_500_000,
                                (150_000, 450_000), step=5_000,
                                format="%d €", label_visibility="visible")
    with c6:
        prix_m2_max = st.number_input("Prix max / m² (€)", min_value=500,
                                       max_value=20_000, value=6_000, step=100,
                                       label_visibility="visible")

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Bloc 2 : Mobilité ─────────────────────────────────────────────────────
    st.markdown("<div class="card">", unsafe_allow_html=True)
    st.markdown("<div class="filter-section-title">Mobilité & environnement</div>",
                unsafe_allow_html=True)

    mc1, mc2, mc3 = st.columns([1.2, 1, 1])
    with mc1:
        dist_aeroport = st.select_slider(
            "Distance aéroport (km)",
            options=[f"< {d} km" for d in range(2, 22, 2)],
            value="< 10 km", label_visibility="visible")
    with mc2:
        proche_ecole = st.checkbox("📚 Proche d"une école", value=False)
        proche_train = st.checkbox("🚉 Proche d"une station de train", value=False)
    with mc3:
        dpe_filter = st.multiselect("Étiquette DPE", ["A","B","C","D","E","F","G"],
                                     default=["A","B","C","D"],
                                     label_visibility="visible")

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Bouton recherche ──────────────────────────────────────────────────────
    col_btn = st.columns([3, 1])[1]
    with col_btn:
        recherche = st.button("🔍  Rechercher", use_container_width=True)

    st.markdown("---")

    # ── Résultats : carte + blocs info ────────────────────────────────────────
    col_map, col_info = st.columns([1.6, 1], gap="medium")

    with col_map:
        st.markdown("""
        <div class="card" style="padding:var(--space-4)">
          <div class="card-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/>
              <circle cx="12" cy="10" r="3"/>
            </svg>
            Localisation des logements correspondants
          </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="map-placeholder" style="height:380px">
          <svg width="52" height="52" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/>
            <circle cx="12" cy="10" r="3"/>
          </svg>
          <span>Carte interactive (Folium / Plotly Mapbox)</span>
          <span style="font-size:0.72rem">Les pins affichent surface, pièces, valeur foncière,<br>
            référence parcelle et score DPE</span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col_info:
        # Zone bruit
        zone_type = random.choice(["calme", "bruyante"])
        zone_label = "Zone calme" if zone_type == "calme" else "Zone bruyante"
        zone_icon  = "🌿" if zone_type == "calme" else "🔊"
        st.markdown(f"""
        <div class="card">
          <div class="card-title">Environnement sonore</div>
          <span class="zone-badge zone-{zone_type}">{zone_icon} {zone_label}</span>
        </div>
        """, unsafe_allow_html=True)

        # Stations les + proches
        stations = [("Gare de Lyon", 1.2), ("Gare d"Austerlitz", 2.8)]
        stations_html = "".join([f"""
        <div class="station-card">
          <svg class="station-icon" width="18" height="18" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="4" width="20" height="16" rx="3"/>
            <path d="M2 10h20M12 4v6M8 20l-2 2M16 20l2 2"/>
          </svg>
          <div>
            <div class="station-name">{name}</div>
            <div class="station-dist">{dist} km</div>
          </div>
        </div>""" for name, dist in stations])
        st.markdown(f"""
        <div class="card">
          <div class="card-title">Stations de train les + proches</div>
          {stations_html}
        </div>
        """, unsafe_allow_html=True)

        # Bloc démographique
        st.markdown("""
        <div class="card">
          <div class="card-title">Données démographiques</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;text-align:center">
            <div>
              <div style="font-size:1.15rem;font-weight:800;color:#3d2b1f;font-family:"Cabinet Grotesk",sans-serif">142 k</div>
              <div style="font-size:0.68rem;color:#b8a898;text-transform:uppercase;letter-spacing:.05em">Habitants</div>
            </div>
            <div>
              <div style="font-size:1.15rem;font-weight:800;color:#3d2b1f;font-family:"Cabinet Grotesk",sans-serif">38 ans</div>
              <div style="font-size:0.68rem;color:#b8a898;text-transform:uppercase;letter-spacing:.05em">Âge moyen</div>
            </div>
            <div>
              <div style="font-size:1.15rem;font-weight:800;color:#3d2b1f;font-family:"Cabinet Grotesk",sans-serif">28 k€</div>
              <div style="font-size:0.68rem;color:#b8a898;text-transform:uppercase;letter-spacing:.05em">Rev. médian</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — ANALYSES
# ─────────────────────────────────────────────────────────────────────────────
def page_analyses():
    import plotly.graph_objects as go
    import plotly.figure_factory as ff
    import numpy as np

    st.markdown("""
    <div class="page-header">
      <h1>Analyses</h1>
      <p>Corrélations, distributions et modèles exploratoires</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(DEMO_BANNER, unsafe_allow_html=True)

    rng = np.random.default_rng(42)
    n = 300

    # Données simulées
    dist_train    = rng.exponential(scale=3, size=n).clip(0.1, 20)
    dist_aeroport = rng.exponential(scale=8, size=n).clip(0.5, 50)
    valeur        = 280_000 + rng.normal(0, 80_000, n) - dist_train * 12_000 - dist_aeroport * 2_000
    valeur        = valeur.clip(50_000, 900_000)
    dpe_labels    = rng.choice(["A","B","C","D","E","F","G"], size=n,
                                p=[.05,.12,.22,.28,.18,.10,.05])
    dpe_colors    = {"A":"#00b050","B":"#92d050","C":"#ffff00",
                     "D":"#ffbf00","E":"#ff9900","F":"#ff3300","G":"#c00000"}

    col1, col2 = st.columns(2, gap="medium")

    # ── Scatter valeur ~ distance train ───────────────────────────────────────
    with col1:
        st.markdown("<div class="chart-area">", unsafe_allow_html=True)
        st.markdown("""<div class="card-title" style="margin-bottom:12px">
          Valeur foncière vs. proximité train
        </div>""", unsafe_allow_html=True)

        colors_scatter = [dpe_colors[d] for d in dpe_labels]
        fig1 = go.Figure(go.Scatter(
            x=dist_train, y=valeur/1000,
            mode="markers",
            marker=dict(color=colors_scatter, size=6, opacity=0.7,
                        line=dict(width=0.5, color="white")),
            text=dpe_labels,
            hovertemplate="<b>DPE %{text}</b><br>Distance : %{x:.1f} km<br>Valeur : %{y:.0f} k€<extra></extra>"
        ))
        fig1.update_layout(
            plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
            font=dict(family="Satoshi,sans-serif", color="#2a1f14", size=11),
            margin=dict(t=8, b=8, l=0, r=0), height=280,
            xaxis=dict(title="Distance gare (km)", showgrid=True, gridcolor="#ede8df"),
            yaxis=dict(title="Valeur foncière (k€)", showgrid=True, gridcolor="#ede8df"),
        )
        st.plotly_chart(fig1, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Scatter valeur ~ distance aéroport ────────────────────────────────────
    with col2:
        st.markdown("<div class="chart-area">", unsafe_allow_html=True)
        st.markdown("""<div class="card-title" style="margin-bottom:12px">
          Valeur foncière vs. proximité aéroport
        </div>""", unsafe_allow_html=True)

        fig2 = go.Figure(go.Scatter(
            x=dist_aeroport, y=valeur/1000,
            mode="markers",
            marker=dict(color=colors_scatter, size=6, opacity=0.7,
                        line=dict(width=0.5, color="white")),
            text=dpe_labels,
            hovertemplate="<b>DPE %{text}</b><br>Distance : %{x:.1f} km<br>Valeur : %{y:.0f} k€<extra></extra>"
        ))
        fig2.update_layout(
            plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
            font=dict(family="Satoshi,sans-serif", color="#2a1f14", size=11),
            margin=dict(t=8, b=8, l=0, r=0), height=280,
            xaxis=dict(title="Distance aéroport (km)", showgrid=True, gridcolor="#ede8df"),
            yaxis=dict(title="Valeur foncière (k€)", showgrid=True, gridcolor="#ede8df"),
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Matrice de corrélation ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div class="card-title" style="margin-bottom:12px;font-size:0.95rem">
      Indice de corrélation — variables numériques clés
    </div>
    """, unsafe_allow_html=True)

    surface_sim = rng.normal(75, 30, n).clip(15, 300)
    nb_pieces_sim = (surface_sim / 20 + rng.normal(0, 0.5, n)).clip(1, 8).astype(int)

    vars_labels = ["Valeur foncière", "Surface", "Nb pièces", "Dist. train", "Dist. aéroport"]
    mat_data = np.column_stack([valeur, surface_sim, nb_pieces_sim, dist_train, dist_aeroport])
    corr = np.corrcoef(mat_data.T)

    fig3 = go.Figure(go.Heatmap(
        z=corr,
        x=vars_labels, y=vars_labels,
        colorscale=[[0,"#c4a882"],[0.5,"#faf7f2"],[1,"#3a6b3f"]],
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in corr],
        texttemplate="%{text}",
        hovertemplate="<b>%{x}</b> × <b>%{y}</b><br>r = %{z:.2f}<extra></extra>",
    ))
    fig3.update_layout(
        plot_bgcolor="#faf7f2", paper_bgcolor="#faf7f2",
        font=dict(family="Satoshi,sans-serif", color="#2a1f14", size=11),
        margin=dict(t=10, b=10, l=0, r=0), height=320,
    )
    st.plotly_chart(fig3, use_container_width=True)


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
