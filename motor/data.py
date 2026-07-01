"""
data.py – henter kurser fra Yahoo Finance (biblioteket yfinance), renser dem og
lagrer alt i én parquet-fil.

Parquet er bare et komprimert tabell-format – tenk på det som et Excel-ark som er
raskt for datamaskinen å lese og skrive.

Dataene lagres i "langt format": én rad per (dato, ticker), med kolonnene
Open/High/Low/Close/Volume. Det gjør det enkelt å legge til nye dager senere.
"""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

from . import konfig

KOLONNER = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# Univers (lista over tickere)
# ---------------------------------------------------------------------------
def les_univers(sti: str = konfig.UNIVERS_FIL) -> list[str]:
    """Leser lista over tickere fra en tekstfil (én ticker per linje)."""
    if not os.path.exists(sti):
        return []
    tickere: list[str] = []
    with open(sti, encoding="utf-8") as f:
        for linje in f:
            t = linje.strip().upper()
            if t and not t.startswith("#"):
                tickere.append(t)
    return tickere


# ---------------------------------------------------------------------------
# Nedlasting fra Yahoo
# ---------------------------------------------------------------------------
def _til_langt_format(rå: pd.DataFrame, tickere: list[str]) -> pd.DataFrame:
    """Gjør Yahoo sitt "brede" format om til langt format (én rad per dato+ticker)."""
    rammer = []
    if isinstance(rå.columns, pd.MultiIndex):
        tilgjengelige = set(rå.columns.get_level_values(0))
        for t in tickere:
            if t not in tilgjengelige:
                continue
            del_ = rå[t].copy()
            del_["Ticker"] = t
            rammer.append(del_)
    else:
        # yfinance returnerer flatt format når man ber om bare én ticker
        del_ = rå.copy()
        del_["Ticker"] = tickere[0]
        rammer.append(del_)

    if not rammer:
        return pd.DataFrame(columns=KOLONNER)

    ut = pd.concat(rammer).reset_index()
    if "Datetime" in ut.columns:
        ut = ut.rename(columns={"Datetime": "Date"})
    for kol in ["Open", "High", "Low", "Close", "Volume"]:
        if kol not in ut.columns:
            ut[kol] = np.nan
    return ut[KOLONNER]


def _last_ned(tickere: list[str], periode: str) -> pd.DataFrame:
    """Laster ned én bunt med tickere. Prøver på nytt (med økende ventetid) ved feil."""
    for forsok in range(4):
        try:
            rå = yf.download(
                tickers=tickere,
                period=periode,
                auto_adjust=True,      # justerer for utbytte og splitt
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if rå is None or len(rå) == 0:
                return pd.DataFrame(columns=KOLONNER)
            return _til_langt_format(rå, tickere)
        except Exception as feil:  # noqa: BLE001 – vi vil fange alt og prøve igjen
            ventetid = 5 * (forsok + 1)
            print(f"   Yahoo feilet ({feil}). Prøver igjen om {ventetid}s ...")
            time.sleep(ventetid)
    print("   Ga opp denne bunten etter flere forsøk.")
    return pd.DataFrame(columns=KOLONNER)


def hent_priser(tickere: list[str], periode: str, buntstorrelse: int = 40) -> pd.DataFrame:
    """Henter kurser for mange tickere, i mindre bunter så Yahoo ikke overbelastes."""
    deler = []
    for i in range(0, len(tickere), buntstorrelse):
        bunt = tickere[i:i + buntstorrelse]
        print(f"   Henter {i + 1}-{i + len(bunt)} av {len(tickere)} ...")
        del_ = _last_ned(bunt, periode)
        if not del_.empty:
            deler.append(del_)
        time.sleep(1)  # liten pause av høflighet mot Yahoo
    if not deler:
        return pd.DataFrame(columns=KOLONNER)
    return pd.concat(deler, ignore_index=True)


# ---------------------------------------------------------------------------
# Rensing
# ---------------------------------------------------------------------------
def rens(df: pd.DataFrame) -> pd.DataFrame:
    """Fjerner ugyldige rader og retter åpenbare feil i OHLC (Open/High/Low/Close)."""
    if df.empty:
        return df
    df = df.dropna(subset=["Close"]).copy()
    df = df[df["Close"] > 0]
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    # High skal være høyest og Low lavest av de fire prisene:
    ohlc = df[["Open", "High", "Low", "Close"]]
    df["High"] = ohlc.max(axis=1)
    df["Low"] = ohlc.min(axis=1)
    df["Volume"] = df["Volume"].fillna(0)
    return df


# ---------------------------------------------------------------------------
# Lagring, lesing og fletting av parquet-fila
# ---------------------------------------------------------------------------
def les_priser(sti: str = konfig.PRISER_FIL) -> pd.DataFrame:
    """Leser hele kurshistorikken fra fil (tom tabell hvis fila ikke finnes ennå)."""
    if os.path.exists(sti):
        df = pd.read_parquet(sti)
        df["Date"] = pd.to_datetime(df["Date"])
        return df
    return pd.DataFrame(columns=KOLONNER)


def lagre_priser(df: pd.DataFrame, sti: str = konfig.PRISER_FIL) -> None:
    """Lagrer hele kurshistorikken til fil."""
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    df.to_parquet(sti, index=False)


def flett(gammel: pd.DataFrame, ny: pd.DataFrame) -> pd.DataFrame:
    """Slår sammen gammel historikk med nye dager. Nyeste tall vinner ved dublett."""
    if gammel.empty:
        return ny.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    if ny.empty:
        return gammel
    alt = pd.concat([gammel, ny], ignore_index=True)
    alt["Date"] = pd.to_datetime(alt["Date"])
    alt = alt.sort_values(["Ticker", "Date"])
    alt = alt.drop_duplicates(subset=["Ticker", "Date"], keep="last")
    return alt.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Hent én tickers historikk som en pen tidsserie
# ---------------------------------------------------------------------------
def serie_for(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Plukker ut én tickers rader, sortert etter dato med dato som indeks."""
    d = df[df["Ticker"] == ticker].copy()
    if d.empty:
        return d
    d["Date"] = pd.to_datetime(d["Date"])
    d = d.sort_values("Date").set_index("Date")
    return d[["Open", "High", "Low", "Close", "Volume"]]


# ---------------------------------------------------------------------------
# Hovedfunksjon roboten bruker
# ---------------------------------------------------------------------------
def hent_og_oppdater() -> pd.DataFrame:
    """
    Henter ferske kurser og oppdaterer parquet-fila.

    - Første gang (tom fil): henter ~10 år historikk.
    - Deretter: henter bare de siste dagene og legger dem til.
    Til slutt lagres og returneres hele den oppdaterte historikken.
    """
    tickere = les_univers()
    if konfig.BENCHMARK not in tickere:
        tickere = tickere + [konfig.BENCHMARK]

    eksisterende = les_priser()
    forste_gang = eksisterende.empty
    periode = f"{konfig.HISTORIKK_AAR}y" if forste_gang else "1mo"
    print(f"Henter kurser (periode={periode}, {'FØRSTE gang' if forste_gang else 'daglig oppdatering'}).")

    nye = rens(hent_priser(tickere, periode))
    flettet = flett(eksisterende, nye)
    lagre_priser(flettet)
    print(f"Lagret {len(flettet):,} rader for {flettet['Ticker'].nunique()} tickere til {konfig.PRISER_FIL}.")
    return flettet


def hent_live(ticker: str, periode: str = "2y") -> pd.DataFrame:
    """Henter én ticker direkte (brukes av søkefeltet for aksjer utenfor universet)."""
    ticker = ticker.strip().upper()
    df = rens(_last_ned([ticker], periode))
    return serie_for(df, ticker)
