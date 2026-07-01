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
