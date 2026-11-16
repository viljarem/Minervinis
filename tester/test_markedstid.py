"""Tester for markedstid.bors_apen – åpningstid-logikk uten nett."""
from __future__ import annotations

import pandas as pd

from motor import markedstid as mt


def _oslo(dato_tid: str) -> pd.Timestamp:
    return pd.Timestamp(dato_tid, tz="Europe/Oslo")


def _ny(dato_tid: str) -> pd.Timestamp:
    return pd.Timestamp(dato_tid, tz="America/New_York")


# --- Oslo Børs -------------------------------------------------------------
def test_oslo_apen_midt_pa_dagen():
    # Mandag 16.11.2026 kl. 12:00
    assert mt.bors_apen("oslo", _oslo("2026-11-16 12:00")) is True


def test_oslo_stengt_for_apning():
    assert mt.bors_apen("oslo", _oslo("2026-11-16 08:30")) is False


def test_oslo_stengt_etter_stenging():
    assert mt.bors_apen("oslo", _oslo("2026-11-16 16:30")) is False


def test_oslo_apen_helt_ved_apning_og_stenging():
    assert mt.bors_apen("oslo", _oslo("2026-11-16 09:00")) is True
    assert mt.bors_apen("oslo", _oslo("2026-11-16 16:20")) is True


def test_oslo_stengt_i_helg():
    # Lørdag 14.11.2026 kl. 12:00
    assert mt.bors_apen("oslo", _oslo("2026-11-14 12:00")) is False


# --- S&P 500 ---------------------------------------------------------------
def test_sp500_apen_midt_pa_dagen():
    assert mt.bors_apen("sp500", _ny("2026-11-16 11:00")) is True


def test_sp500_stengt_for_apning():
    assert mt.bors_apen("sp500", _ny("2026-11-16 09:00")) is False


def test_sp500_apen_ved_apning():
    assert mt.bors_apen("sp500", _ny("2026-11-16 09:30")) is True


# --- robusthet -------------------------------------------------------------
def test_ukjent_kind_gir_stengt():
    assert mt.bors_apen("tull", _oslo("2026-11-16 12:00")) is False


def test_naiv_tid_tolkes_som_borstid():
    # Naiv tid (ingen tz) skal tolkes som børsens lokaltid.
    assert mt.bors_apen("oslo", pd.Timestamp("2026-11-16 12:00")) is True
