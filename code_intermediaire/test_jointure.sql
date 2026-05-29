-- jointure sur sql avant de tout mettre au propre dans init_base.py avec les bonnes cles primaire et etranger 
-- jointure entre dvf et adresses 
CREATE VIEW main.vue_dvf_adresses_complete AS
SELECT 
    dvf.*,
    -- On applique LOWER sur la voie de DVF pour l'uniformiser dans la vue
    LOWER(dvf.adresse_nom_voie) AS adresse_nom_voie_clean,
    adr.*,
    adr.nom_voie AS adresses_nom_voie_officiel
FROM main.dvf dvf
INNER JOIN main.adresses adr 
    ON dvf.adresse_numero = adr.numero
   AND LOWER(dvf.adresse_nom_voie) = LOWER(adr.nom_voie)
   AND dvf.code_postal = adr.code_postal;
  
  -- jointure entre dvf-adresses et gare 


WITH gares_calculees AS (
    SELECT 
        v.*,
        g.libelle AS nom_gare_proche,
        -- Calcul de la distance géométrique (Pythagore sur coordonnées)
        ((v.lon - g.longitude) * (v.lon - g.longitude) + (v.lat - g.latitude) * (v.lat - g.latitude)) AS distance_degres,
        -- On classe les gares de la plus proche à la plus lointaine pour chaque adresse
        ROW_NUMBER() OVER(
            PARTITION BY v.adresse_numero, v.adresse_nom_voie_clean, v.code_postal 
            ORDER BY ((v.lon - g.longitude) * (v.lon - g.longitude) + (v.lat - g.latitude) * (v.lat - g.latitude)) ASC
        ) AS rang
    FROM main.vue_dvf_adresses_complete v
    INNER JOIN main.gares g 
        -- Nettoyage pour ne garder que le premier mot (ex: "Paris") sans les arrondissements
        ON LOWER(SPLIT_PART(TRIM(v.nom_commune), ' ', 1)) = LOWER(SPLIT_PART(TRIM(g.commune), ' ', 1))
)
SELECT * FROM gares_calculees
WHERE rang = 1;
  