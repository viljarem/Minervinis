"""Tester for motor/aksjeinfo.py – fil-basert lagring av shares + sektor."""
import json

from motor import aksjeinfo


def test_last_mangler_fil_gir_tom_dict(tmp_path):
    assert aksjeinfo.last(str(tmp_path / "finnes_ikke.json")) == {}


def test_last_leser_gyldig_fil(tmp_path):
    sti = tmp_path / "aksjeinfo.json"
    sti.write_text(json.dumps({"EQNR.OL": {"utestaende": 100.0, "sektor": "Energy"}}),
                   encoding="utf-8")
    data = aksjeinfo.last(str(sti))
    assert data["EQNR.OL"]["utestaende"] == 100.0
    assert data["EQNR.OL"]["sektor"] == "Energy"


def test_last_ugyldig_json_gir_tom_dict(tmp_path):
    sti = tmp_path / "ugyldig.json"
    sti.write_text("{ ikke gyldig json", encoding="utf-8")
    assert aksjeinfo.last(str(sti)) == {}


def test_oppdater_lagrer_gyldige_svar(tmp_path, monkeypatch):
    sti = tmp_path / "aksjeinfo.json"
    svar = {
        "EQNR.OL": {"ticker": "EQNR.OL", "utestaende": 2980.0,
                    "sektor": "Energy", "industri": "Oil"},
        "DNB.OL": {"ticker": "DNB.OL", "utestaende": 1500.0,
                   "sektor": "Financials", "industri": "Banks"},
    }
    monkeypatch.setattr(aksjeinfo.fundamenta, "hent_aksjeinfo",
                        lambda t: svar.get(t, {"utestaende": None}))
    monkeypatch.setattr(aksjeinfo.time, "sleep", lambda *_: None)

    data = aksjeinfo.oppdater(str(sti), ["EQNR.OL", "DNB.OL"], pause=0)
    assert data["EQNR.OL"]["utestaende"] == 2980.0
    assert data["DNB.OL"]["sektor"] == "Financials"
    # Lagret til fil?
    paa_disk = json.loads(sti.read_text(encoding="utf-8"))
    assert paa_disk["EQNR.OL"]["utestaende"] == 2980.0


def test_oppdater_beholder_gammel_verdi_ved_feil(tmp_path, monkeypatch):
    sti = tmp_path / "aksjeinfo.json"
    sti.write_text(json.dumps({"EQNR.OL": {"utestaende": 999.0, "sektor": "Energy"}}),
                   encoding="utf-8")
    # Yahoo gir nå tomt svar (rate-limit) – vi skal BEHOLDE det gamle, gode tallet.
    monkeypatch.setattr(aksjeinfo.fundamenta, "hent_aksjeinfo",
                        lambda t: {"utestaende": None, "sektor": None, "industri": None})
    monkeypatch.setattr(aksjeinfo.time, "sleep", lambda *_: None)

    data = aksjeinfo.oppdater(str(sti), ["EQNR.OL"], pause=0)
    assert data["EQNR.OL"]["utestaende"] == 999.0
