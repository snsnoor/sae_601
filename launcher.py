"""
launcher.py — Sélection des départements AVANT l'ingestion (Domain 2).

Capture les départements (et années) à ingérer puis les persiste dans
selection.json, lu ensuite par config.get_departements()/get_annees().

Usage :
    python launcher.py --departements 53,35
    python launcher.py --region Bretagne
    python launcher.py --departements 53 --annees 2022,2023,2024
    python launcher.py                      # mode interactif (fallback)

Le flux complet est ensuite :
    python launcher.py  ->  python download_data.py  ->  python init_base.py
"""

import argparse
import json
import sys

import config


def _parse_liste(valeur: str) -> list:
    """Découpe une chaîne 'a,b,c' en liste nettoyée, en ignorant les vides."""
    return [x.strip() for x in valeur.split(",") if x.strip()]


def resoudre_departements(args) -> list:
    """
    Détermine la liste des départements depuis (par ordre de priorité) :
      1. --departements 53,35
      2. --region Bretagne
      3. prompt interactif
    Retourne une liste normalisée (padding 2 chiffres).
    """
    bruts = []

    if args.departements:
        bruts = _parse_liste(args.departements)

    elif args.region:
        # On accepte le nom exact d'une région du mapping partagé
        depts = config.REGIONS_MAPPING.get(args.region)
        if depts is None:
            print(f"[ERREUR] Région inconnue : {args.region!r}")
            print(f"         Régions valides : {', '.join(k for k in config.REGIONS_MAPPING if k != 'Toutes les régions')}")
            sys.exit(1)
        if not depts:
            print("[ERREUR] 'Toutes les régions' n'est pas une sélection valide pour l'ingestion.")
            sys.exit(1)
        bruts = list(depts)

    else:
        # Fallback interactif : on demande à l'utilisateur de saisir les départements
        print("Aucun argument fourni — mode interactif.")
        print("Saisissez les départements séparés par des virgules (ex : 53,35),")
        print("ou un nom de région (ex : Bretagne).")
        saisie = input("Sélection > ").strip()
        if not saisie:
            print("[ERREUR] Sélection vide — abandon.")
            sys.exit(1)
        # Si la saisie correspond à un nom de région, on le résout, sinon liste de départements
        if saisie in config.REGIONS_MAPPING and config.REGIONS_MAPPING[saisie]:
            bruts = list(config.REGIONS_MAPPING[saisie])
        else:
            bruts = _parse_liste(saisie)

    # Normalisation (padding à 2 chiffres, gestion Corse 2A/2B)
    normalises = [config._normaliser_dept(d) for d in bruts]
    return normalises


def valider_departements(depts: list) -> list:
    """Refuse une sélection vide et vérifie chaque code contre le mapping partagé."""
    if not depts:
        print("[ERREUR] Aucun département sélectionné — abandon.")
        sys.exit(1)

    valides = config.departements_valides()
    inconnus = [d for d in depts if d not in valides]
    if inconnus:
        print(f"[ERREUR] Départements inconnus : {', '.join(inconnus)}")
        sys.exit(1)

    # Déduplication en conservant l'ordre
    uniques = []
    for d in depts:
        if d not in uniques:
            uniques.append(d)
    return uniques


def resoudre_annees(args) -> list:
    """Détermine les années depuis --annees, sinon les défauts de config."""
    if args.annees:
        try:
            return [int(a) for a in _parse_liste(args.annees)]
        except ValueError:
            print("[ERREUR] --annees doit contenir des entiers (ex : 2024,2025).")
            sys.exit(1)
    return list(config.DEFAULT_ANNEES)


def main():
    parser = argparse.ArgumentParser(
        description="Sélection des départements à ingérer (écrit selection.json)."
    )
    parser.add_argument("--departements", help="Codes départements séparés par des virgules (ex : 53,35)")
    parser.add_argument("--region", help="Nom de région (ex : Bretagne) — résolu en départements")
    parser.add_argument("--annees", help="Années séparées par des virgules (ex : 2022,2023,2024)")
    args = parser.parse_args()

    depts = valider_departements(resoudre_departements(args))
    annees = resoudre_annees(args)

    selection = {"departements": depts, "annees": annees}

    with open(config.SELECTION_FILE, "w", encoding="utf-8") as f:
        json.dump(selection, f, ensure_ascii=False, indent=2)

    print("[OK] Sélection enregistrée dans selection.json :")
    print(f"     départements = {depts}")
    print(f"     années       = {annees}")
    print("\nÉtapes suivantes : python download_data.py  ->  python init_base.py")


if __name__ == "__main__":
    main()
