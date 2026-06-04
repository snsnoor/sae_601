"""
run.py — Lance le pipeline complet et ouvre le dashboard.

Usage :
    python run.py          -> pipeline normal (saute les etapes deja faites)
    python run.py --reset  -> repart de zero (reconstruit la base)
"""

import subprocess
import sys
from pathlib import Path

ROOT    = Path(__file__).parent
DB      = ROOT / "info_appart_2.duckdb"
DPE_CSV = ROOT / "data" / "dpe.csv"


# ── Helpers ───────────────────────────────────────────────────────────────────

def header(titre):
    print(f"\n{'='*58}")
    print(f"  {titre}")
    print(f"{'='*58}")

def run_step(titre, script, fatal=True):
    header(titre)
    result = subprocess.run([sys.executable, str(ROOT / script)])
    if result.returncode != 0:
        if fatal:
            print(f"\n  Echec de {script} (code {result.returncode}). Arret.")
            sys.exit(result.returncode)
        else:
            print(f"\n  Avertissement : {script} a echoue (code {result.returncode}).")
            print("  Etape ignoree — le pipeline continue.")
            return False
    return True

def table_exists(table_name: str) -> bool:
    if not DB.exists():
        return False
    try:
        import duckdb
        con = duckdb.connect(str(DB), read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return table_name in tables
    except Exception:
        return False

def ask(question: str) -> bool:
    return input(f"\n  {question} [o/N] : ").strip().lower() == "o"


# ── Argument --reset ──────────────────────────────────────────────────────────

reset = "--reset" in sys.argv
if reset:
    header("MODE RESET — suppression de la base existante")
    if DB.exists():
        DB.unlink()
        print(f"  {DB.name} supprimee.")
    else:
        print("  Aucune base a supprimer.")


# ── Bandeau ───────────────────────────────────────────────────────────────────

print("\n" + "="*58)
print("  IMMOFRANCE — Pipeline complet")
print("="*58)
print(f"  Base cible : {DB.name}")
print(f"  Python     : {sys.executable}")


# ── Etape 1 — BAN ─────────────────────────────────────────────────────────────
# La BAN est optionnelle : DVF geo-enrichi contient deja les coordonnees.
# Si le telechargement echoue (reseau, pare-feu), le pipeline continue.

ban_files = list((ROOT / "data").glob("adresses-*.csv*"))
if ban_files:
    print(f"\n  [OK] BAN deja presente ({ban_files[0].name}) — download saute.")
else:
    run_step("Etape 1/3 — Telechargement BAN (optionnel)", "download_data.py", fatal=False)


# ── Etape 2 — DPE ─────────────────────────────────────────────────────────────

if table_exists("dpe_final"):
    print("\n  [OK] dpe_final deja dans la base — etape DPE sautee.")
elif DPE_CSV.exists():
    print(f"\n  [OK] {DPE_CSV.name} trouve — sera charge par init_base.py.")
else:
    header("Etape 2/3 — Donnees DPE manquantes")
    print("  Option A : lancer dpe_api.py  (API ADEME, environ 30 min)")
    print("  Option B : placer manuellement data/dpe.csv et relancer")
    if ask("Lancer dpe_api.py maintenant ?"):
        run_step("Etape 2/3 — Telechargement DPE via API ADEME", "dpe_api.py")
    else:
        print("  DPE ignore — la base sera construite sans donnees energetiques.")


# ── Etape 3 — Base de donnees ─────────────────────────────────────────────────

if table_exists("fact_dvf") and not reset:
    print("\n  [OK] fact_dvf deja presente dans la base.")
    if ask("Reconstruire quand meme la base ?"):
        run_step("Etape 3/3 — Reconstruction de la base", "init_base.py")
    else:
        print("  Base existante conservee.")
else:
    run_step("Etape 3/3 — Construction de la base (DVF + gares + ecoles + IRIS + DPE)", "init_base.py")


# ── Etape 4 — Dashboard ───────────────────────────────────────────────────────

header("Lancement du dashboard Streamlit")
print("  Adresse : http://localhost:8501")
print("  Ctrl+C  : pour arreter\n")

subprocess.run(
    [sys.executable, "-m", "streamlit", "run",
     str(ROOT / "dashboard" / "front.py")],
    cwd=str(ROOT / "dashboard"),
)
