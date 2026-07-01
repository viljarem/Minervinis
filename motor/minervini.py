"""
minervini.py – Mark Minervinis "Trend Template": de 7 kriteriene.

Vi regner kriteriene for HVER dag i historikken (ikke bare siste dag). Da kan vi
både se dagens status OG finne alle historiske perioder der aksjen var i full
7/7-trend – som igjen kan markeres i chartet.

Kriteriene (regnet på Close = sluttkurs):
  1. Close > SMA150 OG Close > SMA200
  2. SMA150 > SMA200
  3. SMA200 stiger (i dag > for 22 dager siden)
  4. SMA50 > SMA150 > SMA200
  5. Close > SMA50
  6. Close minst X % over 52-ukers lav        (X styres av preset)
  7. Close maks Y % under 52-ukers høy         (Y styres av preset)
"""
from __future__ import annotations

import pandas as pd

from . import konfig
from .konfig import Preset

KRITERIE_KOLONNER = ["k1", "k2", "k3", "k4", "k5", "k6", "k7"]

KRITERIE_TEKST = {
    "k1": "Close > SMA150 og SMA200",
    "k2": "SMA150 > SMA200",
    "k3": "SMA200 stiger",
    "k4": "SMA50 > SMA150 > SMA200",
    "k5": "Close > SMA50",
    "k6": "Godt over 52u lav",
    "k7": "Nær 52u høy",
}


def kriterie_kolonner(d: pd.DataFrame, preset: Preset = konfig.STANDARD) -> pd.DataFrame:
    """Regner de 7 kriteriene for hver dag og returnerer en tabell med True/False + score."""
    c = d["Close"]
    k = pd.DataFrame(index=d.index)
    k["k1"] = (c > d["SMA150"]) & (c > d["SMA200"])
    k["k2"] = d["SMA150"] > d["SMA200"]
    k["k3"] = d["SMA200"] > d["SMA200"].shift(konfig.SMA200_STIGNING_DAGER)
    k["k4"] = (d["SMA50"] > d["SMA150"]) & (d["SMA150"] > d["SMA200"])
    k["k5"] = c > d["SMA50"]
    k["k6"] = c >= d["Low_52w"] * (1 + preset.over_lav)
    k["k7"] = c >= d["High_52w"] * (1 - preset.under_hoy)
    k["score"] = k[KRITERIE_KOLONNER].sum(axis=1)
    return k


def historiske_perioder(oppfylt: pd.Series) -> list[tuple]:
    """
    Finner alle sammenhengende perioder der 'oppfylt' er True.
    Returnerer en liste med (startdato, sluttdato).
    """
    verdier = oppfylt.values
    datoer = oppfylt.index
    perioder: list[tuple] = []
    i, n = 0, len(verdier)
    while i < n:
        if verdier[i]:
            j = i
            while j + 1 < n and verdier[j + 1]:
                j += 1
            perioder.append((datoer[i], datoer[j]))
            i = j + 1
        else:
            i += 1
    return perioder


def full_trend(k: pd.DataFrame, krev_antall: int) -> pd.Series:
    """True på dager der aksjen oppfyller minst så mange kriterier (f.eks. 7 av 7)."""
    return k["score"] >= krev_antall


def kvalifiseringsdato(d: pd.DataFrame, k: pd.DataFrame, krev_antall: int) -> tuple:
    """
    Finner NÅR aksjen sist gikk inn i full trend (starten på nyeste periode),
    og om det skjedde med volumstøtte (volum >= 1.4x snittet av forutgående dager).

    Returnerer (dato eller None, volumstøtte True/False).
    """
    perioder = historiske_perioder(full_trend(k, krev_antall))
    if not perioder:
        return None, False
    start, _slutt = perioder[-1]
    # Snittvolum av de FORUTGÅENDE dagene (shift 1 ekskluderer dagen selv).
    snitt50 = d["Volume"].rolling(50, min_periods=10).mean().shift(1)
    try:
        volumstotte = bool(d["Volume"].loc[start] >= konfig.BRUDD_VOLUM_FAKTOR * snitt50.loc[start])
    except (KeyError, TypeError):
        volumstotte = False
    return start, volumstotte
