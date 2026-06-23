"""Crawler headless du localisateur Société Générale (agences.sg.fr).

⚠️ À LANCER SUR TA MACHINE (pas dans un sandbox) : les fiches SG sont rendues en
JavaScript (widget tiers « evermaps »), donc un simple `requests` ne voit pas le
message de transfert. Il faut un navigateur headless.

Installation :
    pip install playwright
    playwright install chromium

Usage :
    python tools/locator_crawl_sg.py            # crawl complet (lent : ~1450 fiches)
    python tools/locator_crawl_sg.py --max 50   # échantillon

Sortie : data/cache/sg_crawl.json — liste de
    {commune, departement, adresse, date_fermeture, destination, code_guichet, url}
Ensuite `python run.py` ingère automatiquement ce fichier (cf. sg_locator.crawled_closures).

NB IMPORTANT (constat vérifié) : SG est le seul grand réseau dont le localisateur
public affiche un message de fermeture/transfert à l'avance. BNP, Crédit Agricole,
Crédit Mutuel, CIC, LCL, Caisse d'Épargne, Banque Populaire, HSBC/CCF n'exposent PAS
cette information sur leur localisateur → pour eux, la presse (run.py) est la source.
Respecte le robots.txt et les CGU ; throttle (1 fiche/seconde).
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.collectors import sg_locator  # noqa: E402

BASE = "https://agences.sg.fr"
RACINE = f"{BASE}/banque-assurance/particulier/"
SORTIE = ROOT / "data" / "cache" / "sg_crawl.json"

_RE_FICHE = re.compile(r"/banque-assurance/particulier/agence-[a-z0-9-]+-id\d+", re.I)
_RE_VILLE = re.compile(r"/banque-assurance/particulier/agences-[a-z0-9-]+-C\d+", re.I)
_RE_ADRESSE = re.compile(r"\d{1,4}[^,<\n]{2,60},?\s*\d{5}\s+[A-Za-zÀ-ÿ' -]{2,40}")
_RE_CP = re.compile(r"\b(\d{5})\b")


def _departement_from_cp(cp: str):
    if not cp:
        return None
    return cp[:3] if cp[:2] in ("97", "98") else cp[:2]


def crawl(max_fiches=None, throttle=1.0):
    from playwright.sync_api import sync_playwright  # import tardif (dépendance optionnelle)

    fiches, resultats = set(), []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # 1) Enumération : page racine -> pages ville -> fiches.
        page.goto(RACINE, wait_until="networkidle")
        html = page.content()
        villes = set(re.findall(_RE_VILLE, html))
        for v in list(villes):
            try:
                page.goto(BASE + v, wait_until="networkidle")
                fiches.update(re.findall(_RE_FICHE, page.content()))
            except Exception as exc:
                print(f"[crawl] ville {v}: {exc}")
            time.sleep(throttle)
            if max_fiches and len(fiches) >= max_fiches:
                break

        # 2) Visite des fiches : détection du message de transfert.
        for url in list(fiches)[: max_fiches or None]:
            try:
                page.goto(BASE + url, wait_until="networkidle")
                texte = page.inner_text("body")
            except Exception as exc:
                print(f"[crawl] fiche {url}: {exc}")
                time.sleep(throttle)
                continue
            if sg_locator.est_fermeture_future(texte):
                infos = sg_locator.parse_message(texte)
                adresse = (_RE_ADRESSE.search(texte) or [None])[0] if _RE_ADRESSE.search(texte) else None
                cp = (_RE_CP.search(adresse).group(1) if adresse and _RE_CP.search(adresse) else None)
                nom = url.split("agence-")[1].rsplit("-id", 1)[0].replace("-", " ").title()
                resultats.append({
                    "commune": nom,
                    "departement": _departement_from_cp(cp),
                    "adresse": adresse,
                    "date_fermeture": infos["date_fermeture"],
                    "destination": infos["destination"],
                    "code_guichet": infos["code_guichet"],
                    "url": BASE + url,
                })
                print(f"[crawl] FERMETURE détectée : {nom} ({infos['date_fermeture']})")
            time.sleep(throttle)
        browser.close()
    return resultats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=None, help="limite de fiches (test)")
    ap.add_argument("--throttle", type=float, default=1.0, help="pause entre requêtes (s)")
    args = ap.parse_args()
    resultats = crawl(max_fiches=args.max, throttle=args.throttle)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(resultats)} fermetures écrites dans {SORTIE}")


if __name__ == "__main__":
    main()
