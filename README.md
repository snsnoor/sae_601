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
| DPE | Energy performance audits — rating A to G | CSV | address + commune code |
| PEB (GeoRisques / DGAC) | Airport noise exposure zones (A, B, C, D) | JSON / GeoJSON | lat/lng (spatial join) |
| BAN | National address database — address to GPS coordinates | CSV | address -> lat/lng |
| Transport and Schools (SNCF / OSM) | Train station and school locations | JSON / REST API | lat/lng (proximity join) |

The DVF geo-enriched file is the central fact table. All other sources are joined to it via commune code, normalized address, or spatial coordinates.

## Pipeline Architecture

The pipeline is structured in three stages:

### Stage 1 — Data Ingestion

Raw data is collected from all sources and persisted to DuckDB raw tables. The DVF national file and others are loaded directly from its remote URL using DuckDB's native `read_csv` with streaming, filtered to 2024-2025 at load time to limit volume.

### Stage 2 — Quality Control and Transformation

This stage cleans and joins the raw sources into analysis-ready tables. Key steps include removing rows with null `valeur_fonciere`, replacing missing values, deduplicating rows, and filtering outliers.

### Stage 3 — Reporting (Streamlit)

The Streamlit dashboard exposes the clean, aggregated data through interactive views allowing users to explore and compare property prices across locations, time periods, and property types.

## Getting Started

### 1. Install dependencies

All required packages are listed in `requirements.txt`. Install them with:

```
pip install -r requirements.txt
```

### 2. Download the data

The source files are not included in this repository due to their size. Run the download script once to fetch them into the `data/` folder:

```
python download_data.py
```

This will download all necessary files automatically. Already-downloaded files are skipped if you run it again.

### 3. Run the scripts

This file loads, cleans, and builds all DuckDB tables from the source files

```
python init_base.py
```

### 4. Launch the Streamlit dashboard

```
streamlit run dashboard/app.py
```

## Key Technical Notes

- The DVF national file contains tens of millions of rows. Filtering to 2024-2025 at load time avoids downloading and materializing the full dataset locally.
- DuckDB is used as the single analytical database throughout — no external database server is required.
- DVF can contain multiple rows per transaction when a sale involves multiple cadastral parcels. Deduplication by transaction key is required before any price analysis.
