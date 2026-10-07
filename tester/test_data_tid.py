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
# Rått live relativt volum (ingen klokkeslett-projeksjon)
# ---------------------------------------------------------------------------
def _oslo(tid: str):
    return pd.Timestamp(tid, tz="Europe/Oslo")


def test_live_rvol_er_raa_faktor():
    """RVol (live) = volum-så-langt / snitt50, uten projeksjon.

    Halvveis til et normalt dagsvolum → 0,5. Klokkeslett skal ikke påvirke.
    """
    snitt = 1_000_000
    for tid in ["2026-07-02 10:00", "2026-07-02 12:30", "2026-07-02 15:00"]:
        naa = _oslo(tid)
        assert datamod.live_rvol(snitt // 2, snitt, naa) == 0.5
        assert datamod.live_rvol(snitt, snitt, naa) == 1.0
        assert datamod.live_rvol(snitt * 2, snitt, naa) == 2.0


def test_live_rvol_uten_tidspunkt():
    """`naa` er valgfri nå – skal fungere uten tidspunkt."""
    assert datamod.live_rvol(500_000, 1_000_000) == 0.5


def test_live_rvol_mangler_tall_gir_nan():
    """Manglende/ugyldige tall skal gi NaN, ikke krasj."""
    naa = _oslo("2026-07-02 12:00")
    assert pd.isna(datamod.live_rvol(None, 1000, naa))
    assert pd.isna(datamod.live_rvol(1000, 0, naa))
    assert pd.isna(datamod.live_rvol(float("nan"), 1000, naa))
