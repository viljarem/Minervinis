"""
Tester for motor/journal_tall.py – all matematikken bak tradingjournalen.

Låser fast at R, P&L, delsalg, Time Value, posisjonsstørrelse, heat, winrate,
expectancy, profit factor og porteføljekurven regner riktig. Ingen database.

Kjør:  pytest -q
"""
import math
from datetime import date

from motor import journal_tall as jt


# --- handelsdager ----------------------------------------------------------
def test_handelsdager_hopper_over_helg():
    # man 2026-11-09 til fre 2026-11-13 = 5 handelsdager
    assert jt.handelsdager("2026-11-09", "2026-11-13") == 5
    # fredag til mandag = 2 handelsdager (helg teller ikke)
    assert jt.handelsdager("2026-11-13", "2026-11-16") == 2
    # samme dag = minst 1
    assert jt.handelsdager("2026-11-10", "2026-11-10") == 1


def test_handelsdager_ugyldig():
    assert jt.handelsdager("2026-11-13", "2026-11-09") is None
    assert jt.handelsdager(None, "2026-11-13") is None


# --- enkel lukket handel ---------------------------------------------------
def test_lukket_handel_r_og_pnl():
    # Kjøp 100, 10 stk, stop 90. Selg alt på 120.
    t = jt.handelstall(100, 10, 90, kjop_dato="2026-11-02",
                       delsalg=[{"salg_kurs": 120, "antall": 10, "salg_dato": "2026-11-06"}])
    assert t["status"] == "CLOSED"
    assert t["vinn"] is True
    assert t["total_pnl"] == 200.0          # (120-100)*10
    assert t["risiko"] == 100.0             # (100-90)*10
    assert t["r"] == 2.0                    # 200/100
    assert t["pnl_pct"] == 20.0
    assert t["holdedager"] == 5             # man-fre
    assert t["time_value"] == round(2.0 / 5, 4)


def test_tap_gir_negativ_r():
    t = jt.handelstall(100, 5, 90,
                       delsalg=[{"salg_kurs": 90, "antall": 5, "salg_dato": "2026-11-06"}])
    assert t["vinn"] is False
    assert t["total_pnl"] == -50.0
    assert t["r"] == -1.0


# --- delsalg / trailing ----------------------------------------------------
def test_delsalg_summerer_riktig():
    # Kjøp 100, 10 stk, stop 90. Selg 5 på 110, 5 på 130.
    t = jt.handelstall(100, 10, 90, kjop_dato="2026-11-02", delsalg=[
        {"salg_kurs": 110, "antall": 5, "salg_dato": "2026-11-04"},
        {"salg_kurs": 130, "antall": 5, "salg_dato": "2026-11-06"},
    ])
    assert t["status"] == "CLOSED"
    assert t["antall_solgt"] == 10.0
    assert t["total_pnl"] == 50 + 150       # (110-100)*5 + (130-100)*5 = 200
    assert t["r"] == 2.0                     # 200 / ((100-90)*10)
    # Sluttdato er siste delsalg
    assert t["holdedager"] == jt.handelsdager("2026-11-02", "2026-11-06")


def test_delvis_solgt_er_fortsatt_apen():
    # Solgt 4 av 10 → fortsatt OPEN, resten verdsettes mot kurs_naa.
    t = jt.handelstall(100, 10, 90, kjop_dato="2026-11-02",
                       delsalg=[{"salg_kurs": 120, "antall": 4, "salg_dato": "2026-11-04"}],
                       kurs_naa=115, i_dag="2026-11-06")
    assert t["status"] == "OPEN"
    assert t["vinn"] is None
    assert t["antall_igjen"] == 6.0
    assert t["realisert_pnl"] == 80.0       # (120-100)*4
    assert t["urealisert_pnl"] == 90.0      # (115-100)*6
    assert t["total_pnl"] == 170.0


def test_apen_uten_kurs_har_ingen_total():
    t = jt.handelstall(100, 10, 90, kjop_dato="2026-11-02", i_dag="2026-11-06")
    assert t["status"] == "OPEN"
    assert t["total_pnl"] is None
    assert t["r"] is None
    assert t["holdedager"] == 5             # åpen: teller til i_dag


def test_handel_uten_stop_har_ingen_r():
    t = jt.handelstall(100, 10, None,
                       delsalg=[{"salg_kurs": 110, "antall": 10, "salg_dato": "2026-11-06"}])
    assert t["total_pnl"] == 100.0
    assert t["r"] is None
    assert t["time_value"] is None


# --- posisjonsstørrelse ----------------------------------------------------
def test_posisjonsstorrelse_1pct():
    # 100 000 kr konto, risiker 1 % = 1000 kr. Entry 100, stop 90 → 10 kr/aksje.
    p = jt.posisjonsstorrelse(entry=100, stop=90, kapital=100_000, risiko_pct=1.0)
    assert p["antall"] == 100               # 1000 // 10
    assert p["risiko_belop"] == 1000.0
    assert p["kostnad"] == 10_000.0
    assert p["andel_pct"] == 10.0


def test_posisjonsstorrelse_runder_ned():
    p = jt.posisjonsstorrelse(entry=100, stop=93, kapital=100_000, risiko_pct=1.0)
    # 1000 // 7 = 142
    assert p["antall"] == 142


def test_posisjonsstorrelse_ugyldig():
    assert jt.posisjonsstorrelse(100, 110, 100_000, 1.0)["antall"] == 0  # stop over entry
    assert jt.posisjonsstorrelse(0, 90, 100_000, 1.0)["antall"] == 0


# --- heat ------------------------------------------------------------------
def test_heat_summerer_apen_risiko():
    apne = [
        {"kjop_kurs": 100, "antall": 100, "stop": 95},   # risiko 500
        {"kjop_kurs": 50, "antall": 200, "stop": 48},    # risiko 400
    ]
    h = jt.heat(apne, kapital=100_000)
    assert h["risiko_belop"] == 900.0
    assert h["risiko_pct"] == 0.9


def test_heat_bruker_ferdig_risiko():
    h = jt.heat([{"risiko": 500}, {"risiko": 300}], kapital=50_000)
    assert h["risiko_belop"] == 800.0
    assert h["risiko_pct"] == 1.6


# --- ATR-stop --------------------------------------------------------------
def test_atr_stop():
    assert jt.atr_stop(entry=100, atr=3, multippel=2) == 94.0
    assert jt.atr_stop(entry=100, atr=0) is None


# --- statistikk ------------------------------------------------------------
def _h(r, pnl, vinn, status="CLOSED", **extra):
    return {"status": status, "r": r, "total_pnl": pnl, "vinn": vinn, **extra}


def test_statistikk_winrate_expectancy_profitfactor():
    handler = [
        _h(2.0, 200, True),
        _h(1.0, 100, True),
        _h(-1.0, -100, False),
        _h(-1.0, -100, False),
    ]
    s = jt.statistikk(handler)
    assert s["lukket"] == 4
    assert s["winrate"] == 0.5
    # expectancy = snitt R = (2+1-1-1)/4 = 0.25
    assert s["expectancy_r"] == 0.25
    # profit factor = 300 / 200 = 1.5
    assert s["profit_factor"] == 1.5
    assert s["sum_realisert"] == 100.0


def test_statistikk_skiller_apne():
    handler = [
        _h(2.0, 200, True),
        _h(None, None, None, status="OPEN", urealisert_pnl=50),
    ]
    s = jt.statistikk(handler)
    assert s["lukket"] == 1
    assert s["apne"] == 1
    assert s["urealisert"] == 50.0


def test_statistikk_bare_vinnere_gir_uendelig_pf():
    s = jt.statistikk([_h(1.0, 100, True), _h(2.0, 200, True)])
    assert s["profit_factor"] == math.inf


def test_statistikk_tom():
    s = jt.statistikk([])
    assert s["winrate"] is None
    assert s["profit_factor"] is None
    assert s["lukket"] == 0


def test_statistikk_per_grupperer():
    handler = [
        _h(2.0, 200, True, setup="VCP"),
        _h(-1.0, -100, False, setup="VCP"),
        _h(3.0, 300, True, setup="Breakout"),
    ]
    per = jt.statistikk_per(handler, "setup")
    navn = {p["gruppe"]: p for p in per}
    assert navn["VCP"]["lukket"] == 2
    assert navn["Breakout"]["lukket"] == 1
    assert navn["Breakout"]["winrate"] == 1.0


# --- kumulativ R -----------------------------------------------------------
def test_kumulativ_r_kurve():
    handler = [
        _h(1.0, 100, True, slutt_dato="2026-11-02"),
        _h(-1.0, -100, False, slutt_dato="2026-11-05"),
        _h(2.0, 200, True, slutt_dato="2026-11-09"),
    ]
    kurve = jt.kumulativ_r(handler)
    assert [p["kum_r"] for p in kurve] == [1.0, 0.0, 2.0]
    assert kurve[0]["dato"] == date(2026, 11, 2)
