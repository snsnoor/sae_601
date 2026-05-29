-- jointure entre dvf et adresses 
SELECT 
   adr.numero AS adresse_numero,
   LOWER(adr.nom_voie) AS adresse_nom_voie,
   adr.code_postal
FROM main.dvf dvf
INNER JOIN main.adresses adr 
    ON dvf.adresse_numero = adr.numero
   AND LOWER(dvf.adresse_nom_voie) = LOWER(adr.nom_voie)
   AND dvf.code_postal = adr.code_postal;