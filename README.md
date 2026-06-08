# SAE 601 — French Real Estate Market Analysis

## Overview

This project is developed as part of the SAE 601 unit of the BUT Sciences des Données program. The central business question driving the work is: **given a price, a location, and a set of property characteristics, is this a good deal?**

The objective is to build a complete Business Intelligence tool that helps buyers, sellers, and real estate professionals assess whether a property is fairly priced. This involves collecting, cleaning, cross-referencing, and exposing data from multiple French public sources, covering transaction history, energy performance, noise exposure, socio-economic context, and geographic information.

## Team

| Name |
|---|
| Noor Nguia Ada |
| Nouhayla Bahaddou |
| Quentin Ezano |

## Tools and Technologies

| Tool | Usage |
|---|---|
| Python | Data ingestion, transformation, and orchestration |
| DuckDB | Local analytical database — raw storage, cleaning, and SQL transformations |
| Streamlit | Interactive dashboard and data exploration interface |

## Data Sources

The pipeline integrates seven public data sources:

| Source | Description | Format | Primary Join Key |
|---|---|---|---|
| DVF (geo-enriched) | All property sales in France with coordinates (2021-present) | CSV (.gz) | address + commune code |
| DPE (ADEME) | Energy performance audits — rating A to G | REST API → CSV | address (spatial NN) |
| PEB (GeoRisques / DGAC) | Airport noise exposure zones (A, B, C, D) | JSON / GeoJSON | lat/lng (spatial join) |
| Transport (SNCF) | Train station locations | JSON / REST API | lat/lng (proximity join) |
| Schools (Éducation nationale) | School / établissement locations | **Shapefile** (.shp) | lat/lng (proximity join) |
| Communes (geo.api.gouv) | Communal polygon contours | GeoJSON | commune code (choropleth) |
| Revenue (data.gouv "niveau de vie") | Median standard of living per commune | Excel (.xlsx) | commune code |
| Population (INSEE recensement) | Municipal population, **2020→2023** | Excel (.xlsx) | commune code + year |
| BAN (Base Adresse Nationale) | National address base, **per-department** | CSV (.gz) | numéro + voie + CP (geocoding) |

The DVF geo-enriched file is the central fact table. All other sources are joined to it via
commune code, normalized address, or spatial coordinates. **All six formats required by the
brief are ingested**: CSV (DVF, BAN, population), Excel (revenue, population), JSON/REST APIs
(SNCF, ADEME DPE, geo.api.gouv), GeoJSON (communes, PEB), and **Shapefile** (schools).


## Pipeline Architecture

The pipeline is structured in three stages:

### Stage 1 — Data Ingestion

Raw data is collected from all sources and persisted to DuckDB raw tables. The DVF national file and others are loaded directly from its remote URL using DuckDB's native `read_csv` with streaming, filtered to 2024-2025 at load time to limit volume.

### Stage 2 — Quality Control and Transformation

This stage cleans and joins the raw sources into analysis-ready tables. Key steps include removing rows with null `valeur_fonciere`, replacing missing values, deduplicating rows, and filtering outliers.

### Stage 3 — Reporting (Streamlit)

The Streamlit dashboard exposes the clean, aggregated data through interactive views allowing users to explore and compare property prices across locations, time periods, and property types.

## Lancer le projet

### Une seule commande

```
pip install -r requirements.txt
python run.py --departements 53 --annees 2024,2025
```

`run.py` enchaîne tout automatiquement : téléchargement des données → construction de la base → lancement du dashboard. Ctrl-C pour arrêter.

Pas besoin de créer un environnement virtuel — un `pip install` global dans Anaconda suffit.

### Options utiles

| Option | Effet |
|---|---|
| `--departements "53,35"` | choisir plusieurs départements |
| `--region Bretagne` | choisir une région entière |
| `--annees 2022,2023,2024` | choisir les années DVF |
| `--skip-download` | réutiliser les fichiers `data/` déjà téléchargés |
| `--skip-etl` | ne pas reconstruire la base |
| `--rebuild` | supprimer et reconstruire `info_appart.duckdb` |
| `--no-dashboard` | préparer les données sans lancer Streamlit |
| `--port 8502` | utiliser un autre port si 8501 est occupé |

**Ré-ouvrir le dashboard sans rien reconstruire :**
```
python run.py --skip-download --skip-etl
```

Si `selection.json` est absent, les défauts s'appliquent : `departements=["53"]`, `annees=[2024, 2025]`.
