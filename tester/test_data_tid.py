"""
Tester for oppdateringstid (metadata) og live-henting i motor/data.py.

Disse låser fast to viktige ting:
  1. «Sist hentet»-tida lagres og leses tilbake i NORSK tid (så UI aldri viser
     feil klokkeslett igjen).
  2. Live-hentingen er robust: tom input gir tom dict, og den rører aldri fila.

Kjør slik (fra prosjektmappa):  pytest -q
"""
import os
import tempfile
from datetime import timedelta

import pandas as pd

from motor import data as datamod


def test_oppdateringstid_roundtrip_er_norsk_tid():
    """Skriv og les tilbake – tida skal bevares og være tidssone-bevisst (norsk offset)."""
    sti = os.path.join(tempfile.gettempdir(), "test_sist_oppdatert.json")
    try:
        datamod.skriv_oppdateringstid(sti)
        lest = datamod.les_oppdateringstid(sti)
        assert lest is not None
        assert lest.tzinfo is not None                       # må ha tidssone
        # Norsk tid er UTC+1 (vinter) eller UTC+2 (sommer) – aldri naiv/UTC.
        assert lest.utcoffset() in (timedelta(hours=1), timedelta(hours=2))
    finally:
        if os.path.exists(sti):
            os.remove(sti)


def test_les_oppdateringstid_manglende_fil_gir_none():
    """Mangler metadatafila, skal vi få None (og appen faller pent tilbake)."""
    assert datamod.les_oppdateringstid("/finnes/virkelig/ikke.json") is None


def test_hent_sanntid_tom_input_gir_tom_dict():
    """Uten tickere skal live-hentingen returnere tom dict UTEN nettverkskall."""
    assert datamod.hent_sanntid([]) == {}


def test_hent_sanntid_returnerer_dict_type():
    """Selv om Yahoo skulle feile, skal vi alltid få en dict (aldri kaste)."""
    ut = datamod.hent_sanntid(["___ikke_en_ekte_ticker___"])
    assert isinstance(ut, dict)


# ---------------------------------------------------------------------------
# Projisert live relativt volum (volumkurve)
# ---------------------------------------------------------------------------
def _oslo(tid: str):
    return pd.Timestamp(tid, tz="Europe/Oslo")


def test_dagsandel_oker_utover_dagen():
    """Andelen av dagsvolum skal vokse gjennom børsdagen."""
    d10 = datamod.dagsandel(_oslo("2026-07-02 10:00"))
    d13 = datamod.dagsandel(_oslo("2026-07-02 13:00"))
    d16 = datamod.dagsandel(_oslo("2026-07-02 16:00"))
    assert 0 < d10 < d13 < d16 <= 1.0


def test_dagsandel_utenfor_borstid_er_full():
    """Før åpning og etter stengning er økta komplett (1.0)."""
    assert datamod.dagsandel(_oslo("2026-07-02 07:00")) == 1.0
    assert datamod.dagsandel(_oslo("2026-07-02 20:00")) == 1.0


def test_live_rvol_normal_dag_er_naer_1():
    """Følger dagens volum den TYPISKE kurven, skal RVol ≈ 1,0 – uansett klokkeslett.

    Dette er hele poenget: tallet skal ikke være kunstig lavt om morgenen.
    """
    snitt = 1_000_000
    for tid in ["2026-07-02 10:00", "2026-07-02 12:30", "2026-07-02 15:00"]:
        naa = _oslo(tid)
        volum_saa_langt = datamod.dagsandel(naa) * snitt        # «normalt» tempo
        assert abs(datamod.live_rvol(volum_saa_langt, snitt, naa) - 1.0) < 0.01


def test_live_rvol_dobbelt_tempo_gir_2():
    """Dobbelt så mye volum som normalt på klokkeslettet → RVol ≈ 2,0."""
    naa = _oslo("2026-07-02 13:00")
    snitt = 500_000
    volum = datamod.dagsandel(naa) * snitt * 2
    assert abs(datamod.live_rvol(volum, snitt, naa) - 2.0) < 0.02


def test_live_rvol_mangler_tall_gir_nan():
    """Manglende/ugyldige tall skal gi NaN, ikke krasj."""
    naa = _oslo("2026-07-02 12:00")
    assert pd.isna(datamod.live_rvol(None, 1000, naa))
    assert pd.isna(datamod.live_rvol(1000, 0, naa))
    assert pd.isna(datamod.live_rvol(float("nan"), 1000, naa))
