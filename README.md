# SAE 601 — French Real Estate Market Analysis

## Business Question

> Given a price, a location, and a set of property characteristics, is this a good deal?
This project is developed as part of the SAE 601 unit of the last year of  BUT Sciences des Données program. The central business question driving the work is: **given a price, a location, and a set of property characteristics, is this a good deal?**

The objective is to build a complete Business Intelligence tool that helps buyers, sellers, and real estate professionals assess whether a property is fairly priced. This involves collecting, cleaning, cross-referencing, and exposing data from multiple French public sources, covering transaction history, energy performance, noise exposure, socio-economic context, and geographic information.

## Team

| Name |
|---|
| Noor Nguia Ada |
| Nouhayla Bahaddou |
| Quentin Ezano |

## Stack

| Tool | Usage |
|---|---|
| Python | Ingestion, transformation, orchestration |
| DuckDB | Base analytique locale — raw storage, cleaning, SQL |
| Streamlit | Dashboard interactif |

## Data Sources

| Source | Description | Join key |
|---|---|---|
| DVF geo-enrichi | Ventes immobilieres 2024-2025 avec coordonnees | adresse + code_commune |
| DPE | Diagnostics energetiques (A-G) | adresse + code_commune |
| PEB | Zones de bruit aeroportuaire (A-D) | spatial (point-in-polygon) — TODO |
| BAN | Adresses nationales (geocodage) | adresse -> lat/lng |
| SNCF / Ecoles | Gares et etablissements scolaires | lat/lng (proximite) |
| IRIS | Zones geographiques INSEE | geometrie |

## Getting Started

### 1. Install dependencies

```
pip install -r requirements.txt
```

### 2. Download BAN addresses

```
python download_data.py
```

### 3. Load DPE data

**Option A — API ADEME (complet, ~30 min) :**
```
python dpe_api.py
```

**Option B — fichier CSV local (pour les tests) :**
Placez votre fichier dans `data/dpe.csv` et passez directement a l'etape 4.

### 4. Build the database

```
python init_base.py
```

This loads DVF (streamed from data.gouv.fr, filtered to 2024-2025), SNCF stations,
schools, and IRIS data. Builds `fact_dvf` and `dim_adresses` with station/school
distances in metres. Output: `info_appart_2.duckdb`.

### 5. Launch the dashboard

```
streamlit run dashboard/front.py
```

The dashboard detects whether the database is ready and shows real data
if `fact_dvf` exists, or falls back to demo mode otherwise.

## Architecture

```
download_data.py  ->  data/adresses-france.csv.gz
dpe_api.py        ->  info_appart_2.duckdb (table dpe_final)
init_base.py      ->  info_appart_2.duckdb (adresses, dvf, gares, ecoles, iris,
                                             dpe_final, dim_adresses, fact_dvf)
dashboard/front.py  <-  info_appart_2.duckdb (read-only via back.py)
```

## Key Technical Notes

- DVF is deduplicated before any aggregation: one row per transaction,
  keeping Maison > Appartement > other, then largest surface.
- DPE is deduplicated by `numero_dpe`, keeping the most recent modification.
- Station and school distances use ST_Distance with ST_Transform to EPSG:2154
  (Lambert-93) for accurate metric results.
- The dashboard falls back to demo mode when the database has not been built yet.

## TODO

- [ ] Integrate PEB noise zones (DGAC GeoJSON, ST_Within spatial join)
- [ ] Add choropleth map (IGN Admin Express boundaries)
- [ ] Wire DPE to DVF join (by normalized address + commune code)
- [ ] Add INSEE socio-economic data (commune income, unemployment)
- [ ] Add Folium map in "Trouver un logement" page
