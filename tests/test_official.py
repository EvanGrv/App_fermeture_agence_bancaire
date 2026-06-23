from pathlib import Path
from backend.collectors import official

FIXT = Path(__file__).parent / "fixtures" / "regafi_sample.csv"

def test_parse_csv_garde_retraits():
    arts = official.parse_csv(FIXT.read_text(encoding="utf-8"))
    # 2 lignes en retrait (Radié + Cessation), pas l'Actif
    assert len(arts) == 2
    communes = {a["commune"] for a in arts}
    assert communes == {"Rennes", "Brest"}

def test_parse_csv_departement_depuis_cp():
    arts = official.parse_csv(FIXT.read_text(encoding="utf-8"))
    rennes = next(a for a in arts if a["commune"] == "Rennes")
    assert rennes["departement"] == "35"
    assert rennes["source"] == "ACPR"
    assert set(rennes) >= {"titre", "texte", "url", "date", "source", "departement"}

def test_collect_sans_fichier_retourne_vide():
    assert official.collect(loader=lambda: None) == []
