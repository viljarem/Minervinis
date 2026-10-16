"""
trendscore.py – regner ut TrendScore (0–100) per handelsdag for én aksje.

TrendScore måler hvor sterk og sunn en opptrend er. Jo høyere tall, jo sterkere
trend. Resultatet er en tidsserie (én score per dag) som kan tegnes som en kurve
under priskartet, og den siste verdien brukes til å rangere aksjer mot hverandre.

Scoren blandes av fire byggeklosser, hver skalert til sin egen 0–100-skala og så
vektet sammen (se konfig.TRENDSCORE_VEKTER):

  1. Momentum (40 %)      – 12-mnd-avkastning MINUS siste måned (fjerner støy).
  2. Relativ styrke (25 %) – meravkastning mot markedsindeksen (3 mnd).
  3. Trendstruktur (20 %)  – glidende snitt på rekke + stigende topper/bunner.
  4. ADX (15 %)            – trendstyrke (uansett retning), 14-dagers Wilder-ADX.

TrendScore = 0.40·Momentum + 0.25·RelStyrke + 0.20·Struktur + 0.15·ADX, klippet
til 0–100. I tillegg lagres to ja/nei-flagg per dag: om kursen ligger over
200-dagers snittet, og om ADX er minst 20 («ekte» trend).

Alle funksjonene er rene (ingen nettverk) og regner på handelsdager, ikke
kalenderdager. De første ~252 dagene mangler full score fordi de lange snittene og
12-mnd-momentumet ikke er klare ennå.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import konfig, indikatorer


def _skaler(verdi, lav, hoy):
    """Lineær 0–100-skala: `lav` → 0, `hoy` → 100, klippet til [0, 100].

    Virker på både skalarer og pandas-serier. NaN bevares.
    """
    andel = (verdi - lav) / (hoy - lav)
    if isinstance(andel, pd.Series):
        return (andel * 100).clip(0, 100)
    if andel != andel:            # NaN
        return float("nan")
    return float(min(100.0, max(0.0, andel * 100)))


# ---------------------------------------------------------------------------
# Byggekloss 1 – Momentum (40 %)
# ---------------------------------------------------------------------------
def momentum_serie(close: pd.Series) -> pd.Series:
    """0–100 per dag. 12-mnd-avkastning minus siste måneds avkastning.

    Den siste måneden er ofte «støy»; ved å trekke den fra fanger vi den mer varige
    trenden. Skalaen er lineær: −20 % → 0 poeng, +60 % → 100 poeng.
    """
    ret_12m = close / close.shift(konfig.TS_MOM_12M) - 1.0
    ret_1m = close / close.shift(konfig.TS_MOM_1M) - 1.0
    raa = ret_12m - ret_1m
    return _skaler(raa, konfig.TS_MOM_LAV, konfig.TS_MOM_HOY)


# ---------------------------------------------------------------------------
# Byggekloss 2 – Relativ styrke (25 %)
# ---------------------------------------------------------------------------
def rel_styrke_serie(close: pd.Series, indeks_close: pd.Series | None = None) -> pd.Series:
    """0–100 per dag. Aksjens 3-mnd-avkastning minus markedets, rundt 50 = likt.

    0 % forskjell → 50 poeng, +20 % bedre enn markedet → 100, −20 % → 0. Uten
    markedsindeks settes den til nøytrale 50 (for dagene aksjen har nok historikk).
    """
    aksje_ret = close / close.shift(konfig.TS_RS_3M) - 1.0
    if indeks_close is None or indeks_close.empty:
        return pd.Series(np.where(aksje_ret.notna(), 50.0, np.nan), index=close.index)

    indeks_just = indeks_close.reindex(close.index).ffill()
    indeks_ret = indeks_just / indeks_just.shift(konfig.TS_RS_3M) - 1.0
    mer = aksje_ret - indeks_ret
    # 50 = likt; ±TS_RS_SPENN strekker symmetrisk til 0..100.
    return _skaler(mer, -konfig.TS_RS_SPENN, konfig.TS_RS_SPENN)


# ---------------------------------------------------------------------------
# Byggekloss 3 – Trendstruktur (20 %)
# ---------------------------------------------------------------------------
def struktur_serie(d: pd.DataFrame) -> pd.Series:
    """0–100 per dag. Tre deler: snitt på rekke (A) + stigende topper (B) + bunner (C).

    A (0–40): kurs > SMA50 (15), kurs > SMA200 (10), SMA50 > SMA200 (10),
              SMA50 stigende vs for 20 dager siden (5).
    B (0–30): del de siste tre ~månedsbolkene opp; midt-bolk høyere topp enn eldst
              (15), nyeste høyere topp enn midt (15).
    C (0–30): samme tre bolker, men laveste kurs: midt høyere bunn enn eldst (15),
              nyeste høyere bunn enn midt (15).
    """
    close = d["Close"]
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    # Del A – glidende snitt på rekke (maks 40).
    a = (
        (close > sma50).astype(float) * 15
        + (close > sma200).astype(float) * 10
        + (sma50 > sma200).astype(float) * 10
        + (sma50 > sma50.shift(konfig.TS_SMA_HELNING_DAGER)).astype(float) * 5
    )

    # Tre ~månedsbolker: nyeste = siste N dager, midt = N før det, eldst = N før det.
    n = konfig.TS_BLOKK_DAGER
    hoy = d["High"]
    lav = d["Low"]
    ny_topp = hoy.rolling(n).max()
    midt_topp = ny_topp.shift(n)
    eldst_topp = ny_topp.shift(2 * n)
    ny_bunn = lav.rolling(n).min()
    midt_bunn = ny_bunn.shift(n)
    eldst_bunn = ny_bunn.shift(2 * n)

    # Del B – stigende topper (maks 30).
    b = (
        (midt_topp > eldst_topp).astype(float) * 15
        + (ny_topp > midt_topp).astype(float) * 15
    )
    # Del C – stigende bunner (maks 30).
    c = (
        (midt_bunn > eldst_bunn).astype(float) * 15
        + (ny_bunn > midt_bunn).astype(float) * 15
    )

    total = (a + b + c).clip(0, 100)
    # Ugyldig før SMA200 og de tre bolkene finnes.
    gyldig = sma200.notna() & eldst_topp.notna() & eldst_bunn.notna()
    return total.where(gyldig)


# ---------------------------------------------------------------------------
# Byggekloss 4 – ADX / trendstyrke (15 %)
# ---------------------------------------------------------------------------
def adx_serie(d: pd.DataFrame) -> pd.Series:
    """0–100 per dag. 14-dagers Wilder-ADX skalert: ADX 10 → 0, ADX 50 → 100."""
    raa = indikatorer.adx(d, konfig.ADX_PERIODE)
    return _skaler(raa, konfig.TS_ADX_LAV, konfig.TS_ADX_HOY)


# ---------------------------------------------------------------------------
# Sammensatt TrendScore
# ---------------------------------------------------------------------------
def trendscore_serie(serie: pd.DataFrame, indeks: pd.DataFrame | None = None) -> pd.DataFrame:
    """Full TrendScore-tidsserie for én aksje.

    Returnerer en DataFrame indeksert på dato med kolonnene:
      • score         – 0–100 (NaN de første ~252 dagene)
      • momentum, rel_styrke, struktur, adx – de fire delscorene (0–100)
      • over_sma200   – bool, om kursen ligger over 200-dagers snittet
      • adx_ok        – bool, om rå ADX er ≥ 20 («ekte» trend)
    Tom DataFrame hvis input mangler eller er for kort.
    """
    if serie is None or serie.empty or "Close" not in serie.columns:
        return pd.DataFrame()

    d = serie.copy()
    close = d["Close"]
    indeks_close = indeks["Close"] if (indeks is not None and not indeks.empty
                                       and "Close" in indeks.columns) else None

    mom = momentum_serie(close)
    rs = rel_styrke_serie(close, indeks_close)
    struktur = struktur_serie(d)
    adx_sk = adx_serie(d)

    v = konfig.TRENDSCORE_VEKTER
    score = (v["momentum"] * mom + v["rel_styrke"] * rs
             + v["struktur"] * struktur + v["adx"] * adx_sk).clip(0, 100)
    # Full score bare når ALLE komponentene finnes.
    gyldig = mom.notna() & rs.notna() & struktur.notna() & adx_sk.notna()
    score = score.where(gyldig)

    sma200 = close.rolling(200).mean()
    raa_adx = indikatorer.adx(d, konfig.ADX_PERIODE)

    return pd.DataFrame({
        "score": score,
        "momentum": mom,
        "rel_styrke": rs,
        "struktur": struktur,
        "adx": adx_sk,
        "over_sma200": close > sma200,
        "adx_ok": raa_adx >= konfig.TS_ADX_EKTE,
    }, index=d.index)


def siste_trendscore(serie: pd.DataFrame, indeks: pd.DataFrame | None = None) -> dict | None:
    """Siste gyldige TrendScore for én aksje. None hvis for kort historikk.

    Returnerer {"score", "momentum", "rel_styrke", "struktur", "adx",
    "over_sma200", "adx_ok", "dato"} for den nyeste dagen med full score.
    """
    df = trendscore_serie(serie, indeks)
    if df.empty:
        return None
    gyldige = df[df["score"].notna()]
    if gyldige.empty:
        return None
    rad = gyldige.iloc[-1]
    return {
        "score": round(float(rad["score"]), 1),
        "momentum": round(float(rad["momentum"]), 1),
        "rel_styrke": round(float(rad["rel_styrke"]), 1),
        "struktur": round(float(rad["struktur"]), 1),
        "adx": round(float(rad["adx"]), 1),
        "over_sma200": bool(rad["over_sma200"]),
        "adx_ok": bool(rad["adx_ok"]),
        "dato": gyldige.index[-1],
    }
