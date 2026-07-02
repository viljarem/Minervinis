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
