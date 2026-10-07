"""
sektor.py – sektor-/bransjestyrke (O'Neils «ledere i ledende grupper»).

O'Neil var tydelig på at ~halvparten av en aksjes bevegelse skyldes gruppen
(sektoren) den tilhører. Du vil eie den STERKESTE aksjen i den STERKESTE sektoren
– ikke en sterk aksje i en død sektor. Denne modulen rangerer sektorene etter
samlet relativ styrke, og finner lederne innen hver.

Alt her er rene regnestykker (ingen Streamlit, ingen nettverk), så det er lett å
teste. Selve sektor-etiketten (hvilken bransje en ticker tilhører) hentes andre
steder (Yahoo) og sendes inn som et enkelt oppslag {ticker: sektor}.

Sektorstyrke bygger KUN på data vi allerede har – RS-rating (relativ styrke mot
universet) og Minervini-score (antall av de 7 kriteriene oppfylt). Ingen
oppfunne vekter: sektor-RS er MEDIAN av medlemmenes RS (robust mot utliggere),
og re-rangeres så til en ren 1–99-skala på tvers av sektorene.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

UKJENT = "Ukjent"            # bøtte for aksjer uten kjent sektor (små Growth-navn)
_MIN_MEDLEMMER = 2           # en «sektor» trenger minst så mange for en meningsfull median


def _rangér_1_99(serie: pd.Series) -> pd.Series:
    """Persentil-rangering til 1–99 (99 = sterkest), som RS-ratingen ellers."""
    if serie.empty:
        return serie
    if len(serie) == 1:
        # Én enkelt verdi kan ikke rangeres mot andre – gi den midtfeltet (50).
        return pd.Series([50.0], index=serie.index)
    rang = serie.rank(pct=True)
    return (rang * 98 + 1).round()


def sektor_oversikt(df: pd.DataFrame, sektorer: dict[str, str],
                    rs_min: int = 70, trend_min: int = 7,
                    inkluder_ukjent: bool = False) -> pd.DataFrame:
    """Bygger en rangert oversikt over sektorene ut fra en screening-tabell.

    df         – screening-resultat med minst kolonnene «ticker», «rs», «score».
    sektorer   – oppslag {ticker: sektornavn}. Mangler en ticker, havner den i
                 «Ukjent»-bøtta.
    rs_min     – terskel for å telles som «sterk» aksje (default 70, som Minervini).
    trend_min  – Minervini-score som regnes som «full opptrend» (default 7/7).
    inkluder_ukjent – ta med «Ukjent»-bøtta i rangeringen? Default False (den er
                 en blandingspose og sier lite om én bransje).

    Returnerer en DataFrame, sterkeste sektor øverst, med kolonnene:
      sektor, antall, sektor_rs (1–99), rs_median, rs_snitt, antall_sterke,
      andel_sterke (%), antall_trend, andel_trend (%).
    Tom ramme hvis df er tom eller mangler nødvendige kolonner.
    """
    if df is None or df.empty or not {"ticker", "rs"}.issubset(df.columns):
        return pd.DataFrame()

    d = df.copy()
    d["sektor"] = d["ticker"].map(lambda t: sektorer.get(t) or UKJENT)
    d["rs"] = pd.to_numeric(d["rs"], errors="coerce")
    if "score" not in d.columns:
        d["score"] = np.nan
    d["score"] = pd.to_numeric(d["score"], errors="coerce")

    rader = []
    for sektor, g in d.groupby("sektor"):
        rs = g["rs"].dropna()
        if len(rs) < _MIN_MEDLEMMER:
            continue
        antall = int(len(g))
        antall_sterke = int((rs >= rs_min).sum())
        antall_trend = int((g["score"] >= trend_min).sum())
        rader.append({
            "sektor": sektor,
            "antall": antall,
            "rs_median": round(float(rs.median()), 1),
            "rs_snitt": round(float(rs.mean()), 1),
            "antall_sterke": antall_sterke,
            "andel_sterke": round(antall_sterke / antall * 100, 0),
            "antall_trend": antall_trend,
            "andel_trend": round(antall_trend / antall * 100, 0),
        })

    ut = pd.DataFrame(rader)
    if ut.empty:
        return ut

    if not inkluder_ukjent:
        ut = ut[ut["sektor"] != UKJENT]
        if ut.empty:
            return ut

    # Sektor-RS: re-rangér medianene til en ren 1–99-skala på tvers av sektorene.
    ut["sektor_rs"] = _rangér_1_99(ut["rs_median"]).astype(int)
    ut = ut.sort_values(["sektor_rs", "rs_median"], ascending=False,
                        kind="mergesort").reset_index(drop=True)

    # Pen kolonnerekkefølge.
    kol = ["sektor", "sektor_rs", "antall", "rs_median", "rs_snitt",
           "antall_sterke", "andel_sterke", "antall_trend", "andel_trend"]
    return ut[kol]


def vinnere_i_sektor(df: pd.DataFrame, sektorer: dict[str, str], sektor: str,
                     antall: int = 10) -> pd.DataFrame:
    """De sterkeste aksjene i ÉN sektor – «lederne i gruppen».

    Sorterer medlemmene i valgt sektor på RS (høyest først), så Minervini-score,
    og returnerer de `antall` øverste. Beholder alle originalkolonnene fra df, så
    kalleren kan vise akkurat de feltene den vil.
    """
    if df is None or df.empty or "ticker" not in df.columns:
        return pd.DataFrame()
    d = df.copy()
    d["_sektor"] = d["ticker"].map(lambda t: sektorer.get(t) or UKJENT)
    g = d[d["_sektor"] == sektor].drop(columns=["_sektor"])
    if g.empty:
        return g
    sorter_på = [k for k in ["rs", "score"] if k in g.columns]
    if sorter_på:
        for k in sorter_på:
            g[k] = pd.to_numeric(g[k], errors="coerce")
        g = g.sort_values(sorter_på, ascending=False, kind="mergesort")
    return g.head(antall).reset_index(drop=True)


def sektor_historikk(rs_bred: pd.DataFrame, sektorer: dict[str, str],
                     min_medlemmer: int = 2, glatting: int = 0) -> pd.DataFrame:
    """Median RS per sektor PER DAG – sektorstyrke langs en tidslinje.

    rs_bred    – bred RS-tabell (datoer × ticker) slik rs_rating_historikk gir:
                 hver celle er aksjens RS-rating (1–99) den dagen.
    sektorer   – oppslag {ticker: sektornavn}. Tickere uten kjent sektor hoppes
                 over (de forurenser ikke en bransjelinje).
    min_medlemmer – en sektor trenger minst så mange tickere for en robust median.
    glatting   – valgfritt glidende snitt (antall dager) for å dempe dag-til-dag-
                 støy. 0/1 = ingen glatting.

    Returnerer en bred tabell (datoer × sektor) med median RS per dag, så den er
    lett å smelte til langt format for en fler-linjers tidslinje. Tom ramme hvis
    input mangler. Siden RS allerede er tverrsnitt (rangert mot universet hver
    dag), er medianen direkte sammenlignbar over tid: en linje som klatrer =
    sektoren tar ledelsen, en som faller = den taper styrke.
    """
    if rs_bred is None or getattr(rs_bred, "empty", True) or not sektorer:
        return pd.DataFrame()

    # Grupper de tilgjengelige kolonnene (tickere) på sektor.
    medlemmer: dict[str, list[str]] = {}
    for t in rs_bred.columns:
        s = sektorer.get(t)
        if s:
            medlemmer.setdefault(s, []).append(t)

    data = {}
    for s, tickere in medlemmer.items():
        if len(tickere) < min_medlemmer:
            continue
        data[s] = rs_bred[tickere].median(axis=1)

    if not data:
        return pd.DataFrame()
    ut = pd.DataFrame(data).sort_index()
    if glatting and glatting > 1:
        ut = ut.rolling(glatting, min_periods=1).mean()
    return ut.round(1)

