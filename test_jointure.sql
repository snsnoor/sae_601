-- 1. Activation de l'extension spatiale (obligatoire pour DuckDB)
INSTALL spatial;
LOAD spatial;

-- 2. Bloc de traitement complet
WITH Echantillon_Adresses AS (
    -- On prend les 5 000 premières lignes de la table adresses
    SELECT * FROM adresses 
    LIMIT 5000
),

DVF_Normalise AS (
    SELECT 
        *,
        -- [TRANSFORMATION 1] : Normalisation de l'adresse DVF
        LOWER(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    TRIM(COALESCE(CAST(adresse_numero AS VARCHAR), '')) || ' ' || LOWER(TRIM(COALESCE(adresse_nom_voie, ''))),
                    '\b(r\.|r)\b', 'rue', 'g'
                ),
                '\b(av\.|av)\b', 'avenue', 'g'
            )
        ) AS dvf_adresse_normalisee,
        
        -- Création de la géométrie DVF pour les calculs spatiaux
        ST_Point(longitude, latitude) AS dvf_geom
    FROM dvf
    WHERE longitude IS NOT NULL AND latitude IS NOT NULL AND longitude != 0
),

DVF_Dedup AS (
    -- [TRANSFORMATION 2] : Déduplication (On collapse les parcelles multiples en 1 seule ligne)
    SELECT * FROM DVF_Normalise
    QUALIFY ROW_NUMBER() OVER(
        PARTITION BY date_mutation, valeur_fonciere, code_commune, longitude, latitude 
        ORDER BY surface_reelle_bati DESC
    ) = 1
),

Gares_Geom AS (
    -- Préparation géométrique des gares
    SELECT *, ST_Point(longitude, latitude) AS gare_geom 
    FROM gares 
    WHERE longitude IS NOT NULL AND latitude IS NOT NULL
)

-- [JOINTURES & PROXIMITÉ] : Assemblage final
SELECT 
    -- Infos de la transaction DVF dédupliquée
    d.date_mutation,
    d.valeur_fonciere,
    d.type_local,
    d.surface_reelle_bati,
    d.dvf_adresse_normalisee,
    
    -- [JOINTURE 1] : Match avec notre échantillon de la table ADRESSES (via le code commune)
    a.id AS adresse_id_ban, -- (ou le nom de ta colonne ID/Clé dans la table adresses)
    a.code_commune AS commune_ban,
    
    -- [PROXIMITÉ] : Calcul de distance à la gare la plus proche (en mètres)
    (
        SELECT MIN(ST_Distance_Spheroid(d.dvf_geom, g.gare_geom))
        FROM Gares_Geom g
    ) AS distance_gare_metres

FROM DVF_Dedup d
-- Jointure sur le code commune pour lier les transactions à l'échantillon de test
INNER JOIN Echantillon_Adresses a 
    ON d.code_commune = a.code_commune;