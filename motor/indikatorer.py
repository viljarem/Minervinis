"""
indikatorer.py – regner ut tekniske indikatorer for én aksje om gangen.

Alle funksjonene tar inn en tabell (DataFrame) med kolonnene
Open/High/Low/Close/Volume og dato som indeks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import konfig


def legg_til_indikatorer(df: pd.DataFrame) -> pd.DataFrame:
    """Legger til SMA50/150/200, 52-ukers høy/lav, RSI og ATR som nye kolonner."""
    d = df.copy()
    for p in konfig.SMA_PERIODER:
        d[f"SMA{p}"] = d["Close"].rolling(p).mean()
    d["High_52w"] = d["High"].rolling(konfig.VINDU_52U, min_periods=20).max()
    d["Low_52w"] = d["Low"].rolling(konfig.VINDU_52U, min_periods=20).min()
    d["RSI14"] = _rsi(d["Close"], 14)
    d["ATR14"] = _atr(d, 14)
    return d


def _rsi(close: pd.Series, periode: int = 14) -> pd.Series:
    """RSI = mål på om aksjen er "overkjøpt" (høy) eller "oversolgt" (lav). 0–100.

    Bruker Wilders utjevning (EMA), som matcher TradingView/Bloomberg – mer presist
    enn et rett gjennomsnitt.
    """
    endring = close.diff()
    opp = endring.clip(lower=0).ewm(alpha=1 / periode, min_periods=periode, adjust=False).mean()
    ned = (-endring.clip(upper=0)).ewm(alpha=1 / periode, min_periods=periode, adjust=False).mean()
    rs = opp / ned.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(d: pd.DataFrame, periode: int = 14) -> pd.Series:
    """ATR = gjennomsnittlig dagssvingning (hvor mye kursen typisk beveger seg)."""
    hoy_lav = d["High"] - d["Low"]
    hoy_close = (d["High"] - d["Close"].shift()).abs()
    lav_close = (d["Low"] - d["Close"].shift()).abs()
    sann_range = pd.concat([hoy_lav, hoy_close, lav_close], axis=1).max(axis=1)
    return sann_range.rolling(periode).mean()


# ---------------------------------------------------------------------------
# Golden cross (SMA50 krysser SMA200)
# ---------------------------------------------------------------------------
def golden_cross_hendelser(d: pd.DataFrame) -> list[dict]:
    """Finner ALLE golden/death cross mellom SMA50 og SMA200 i historikken.

    Golden cross = SMA50 krysser OPP gjennom SMA200 (klassisk bullish signal).
    Death cross  = SMA50 krysser NED gjennom SMA200 (bearish).
    Returnerer en liste med {"dato": Timestamp, "type": "golden"|"death",
    "pris": sluttkurs} sortert stigende på dato. Tom liste hvis SMA-ene mangler.
    """
    if "SMA50" not in d.columns or "SMA200" not in d.columns:
        return []
    diff = d["SMA50"] - d["SMA200"]
    fortegn = np.sign(diff)                 # +1 når SMA50 over, -1 under, 0 likt
    forrige = fortegn.shift(1)
    hendelser = []
    for dato, naa_f, forr_f, pris in zip(d.index, fortegn, forrige, d["Close"]):
        if pd.isna(naa_f) or pd.isna(forr_f) or naa_f == 0:
            continue
        if forr_f <= 0 and naa_f > 0:
            hendelser.append({"dato": dato, "type": "golden", "pris": float(pris)})
        elif forr_f >= 0 and naa_f < 0:
            hendelser.append({"dato": dato, "type": "death", "pris": float(pris)})
    return hendelser


def golden_cross_status(d: pd.DataFrame) -> dict:
    """Oppsummerer siste golden cross: dato, handelsdager siden, og om vi er over nå.

    {"dato": Timestamp|None, "dager_siden": int|None, "over": bool}. «over» = SMA50
    ligger over SMA200 på siste dag (dvs. vi er i golden-cross-tilstand akkurat nå).
    """
    over = False
    if "SMA50" in d.columns and "SMA200" in d.columns:
        s50, s200 = d["SMA50"].iloc[-1], d["SMA200"].iloc[-1]
        over = bool(pd.notna(s50) and pd.notna(s200) and s50 > s200)
    golden = [h for h in golden_cross_hendelser(d) if h["type"] == "golden"]
    if not golden:
        return {"dato": None, "dager_siden": None, "over": over}
    siste = golden[-1]
    dager = int(len(d.index) - 1 - d.index.get_loc(siste["dato"]))
    return {"dato": siste["dato"], "dager_siden": dager, "over": over}


def multi_timeframe(df: pd.DataFrame) -> dict:
    """Sjekker om den UKENTLIGE trenden bekrefter dagstrenden.

    Minervini: de fleste utbrudd som feiler, feiler når det høyere tidsplanet (uke)
    ikke er med. Vi gjør daglige data om til ukentlige og teller tre enkle signaler:
      1) ukens sluttkurs over 10-ukers snitt,
      2) ukentlig RSI over 50,
      3) 10-ukers snitt over 40-ukers snitt.
    3 av 3 = bullish (✅), 0 av 3 = bearish (❌), ellers blandet (⚠️).
    """
    noytral = {"status": "neutral", "emoji": "⚠️", "tekst": "For lite ukedata"}
    if df is None or df.empty or len(df) < konfig.MTF_MIN_DAGER:
        return noytral
    if not isinstance(df.index, pd.DatetimeIndex):
        return noytral
    try:
        uke = df.resample("W").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        ).dropna()
    except (TypeError, ValueError):
        return noytral
    if len(uke) < konfig.MTF_MIN_UKER:
        return noytral

    sma10 = uke["Close"].rolling(10).mean().iloc[-1]
    sma40 = uke["Close"].rolling(40).mean().iloc[-1]
    rsi = _rsi(uke["Close"], 14).iloc[-1]
    close = uke["Close"].iloc[-1]
    if any(pd.isna(x) for x in (sma10, sma40, rsi)):
        return noytral

    bull = int(close > sma10) + int(rsi > 50) + int(sma10 > sma40)
    if bull >= 3:
        return {"status": "bullish", "emoji": "✅", "tekst": f"Ukentlig opptrend (RSI {rsi:.0f})"}
    if bull == 0:
        return {"status": "bearish", "emoji": "❌", "tekst": f"Ukentlig nedtrend (RSI {rsi:.0f})"}
    return {"status": "neutral", "emoji": "⚠️", "tekst": f"Ukentlig blandet (RSI {rsi:.0f})"}


def rs_avkastning(close: pd.Series) -> float:
    """
    Vektet avkastning brukt i RS-ratingen (IBD-metoden):
      0.40 x (3 mnd) + 0.20 x (6 mnd) + 0.20 x (9 mnd) + 0.20 x (12 mnd)
    Periodene måles i handelsdager (63/126/189/252).
    Returnerer NaN hvis aksjen har for kort historikk.
    """
    if len(close) <= max(konfig.RS_PERIODER):
        return float("nan")
    naa = close.iloc[-1]
    sum_vektet = 0.0
    for periode, vekt in zip(konfig.RS_PERIODER, konfig.RS_VEKTER):
        for_lenge_siden = close.iloc[-1 - periode]
        if for_lenge_siden <= 0:
            return float("nan")
        sum_vektet += vekt * (naa / for_lenge_siden - 1.0)
    return float(sum_vektet)
