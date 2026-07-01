"""
screener.py – "dirigenten" som bruker alle de andre modulene.

Den:
  1. Går gjennom hver aksje og regner indikatorer, kriterier og VCP.
  2. Regner RS-rating (relativ styrke) på tvers av hele universet (1–99).
  3. Bruker likviditetsfilter (fjern aksjer det handles for lite i).
  4. Lager "dagens liste" og kan sammenligne den mot forrige kjøring (til e-post).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from . import konfig, data as datamod, indikatorer, minervini, vcp
from .konfig import Preset


# ---------------------------------------------------------------------------
# Analyse av ÉN aksje
# ---------------------------------------------------------------------------
def analyser_ticker(serie: pd.DataFrame, ticker: str, preset: Preset = konfig.STANDARD) -> dict | None:
    """Regner alt vi trenger om én aksje. Returnerer None hvis for kort historikk."""
    if serie is None or len(serie) < konfig.MIN_HANDELSDAGER:
        return None

    d = indikatorer.legg_til_indikatorer(serie)
    if d["SMA200"].isna().all():
        return None

    k = minervini.kriterie_kolonner(d, preset)
    siste = k.iloc[-1]
    kv_dato, volumstotte = minervini.kvalifiseringsdato(d, k, preset.krev_antall)

    v = vcp.finn_vcp(d)
    brudd = vcp.bruddstatus(d, v["pivot"])
    mtf = indikatorer.multi_timeframe(d)

    pris = float(d["Close"].iloc[-1])
    dagsomsetning = float((d["Close"] * d["Volume"]).rolling(konfig.OMSETNING_VINDU).mean().iloc[-1])

    # Utvikling siden aksjen gikk inn i full trend (i prosent)
    utvikling = np.nan
    if kv_dato is not None:
        try:
            utvikling = (pris / float(d["Close"].loc[kv_dato]) - 1) * 100
        except (KeyError, TypeError):
            utvikling = np.nan

    perioder = minervini.historiske_perioder(minervini.full_trend(k, preset.krev_antall))

    return {
        "ticker": ticker,
        "pris": round(pris, 2),
        "score": int(siste["score"]),
        "k1": bool(siste["k1"]), "k2": bool(siste["k2"]), "k3": bool(siste["k3"]),
        "k4": bool(siste["k4"]), "k5": bool(siste["k5"]), "k6": bool(siste["k6"]),
        "k7": bool(siste["k7"]),
        "dato_7av7": None if kv_dato is None else pd.Timestamp(kv_dato).date().isoformat(),
        "volumstotte": bool(volumstotte),
        "utvikling_siden": None if pd.isna(utvikling) else round(float(utvikling), 1),
        "status": brudd["emoji"],
        "statustekst": brudd["tekst"],
        "bruddato": None if brudd["bruddato"] is None else pd.Timestamp(brudd["bruddato"]).date().isoformat(),
        "pivot": None if pd.isna(v["pivot"]) else round(v["pivot"], 2),
        "stop": None if pd.isna(v["stop"]) else round(v["stop"], 2),
        "avstand_pivot": None if pd.isna(v["avstand"]) else round(v["avstand"] * 100, 1),
        "antall_kontr": v["antall"],
        "kontraksjoner": v["kontraksjoner"],
        "volumuttorking": v["volumuttorking"],
        "kvalitet": v["kvalitet"],
        "vcp_gyldig": v["gyldig"],
        "mtf_status": mtf["status"],
        "mtf_emoji": mtf["emoji"],
        "mtf_tekst": mtf["tekst"],
        "rs_avkastning": indikatorer.rs_avkastning(d["Close"]),
        "dagsomsetning": dagsomsetning,
        "perioder": [(pd.Timestamp(a).date().isoformat(), pd.Timestamp(b).date().isoformat()) for a, b in perioder],
    }


# ---------------------------------------------------------------------------
# Screening av HELE universet
# ---------------------------------------------------------------------------
def _persentil(serie: pd.Series) -> pd.Series:
    """Rangerer verdiene til en skala 1–99 (99 = sterkest)."""
    rang = serie.rank(pct=True)
    return (rang * 98 + 1).round()


def screen(priser: pd.DataFrame, preset: Preset = konfig.STANDARD) -> pd.DataFrame:
    """Kjører analysen for alle tickere i prisdataene og returnerer én stor tabell."""
    if priser is None or priser.empty:
        return pd.DataFrame()

    tickere = [t for t in sorted(priser["Ticker"].unique()) if t != konfig.BENCHMARK]
    rader = []
    for t in tickere:
        res = analyser_ticker(datamod.serie_for(priser, t), t, preset)
        if res is not None:
            rader.append(res)

    df = pd.DataFrame(rader)
    if df.empty:
        return df

    # Likviditetsfilter
    df = df[df["dagsomsetning"] >= konfig.MIN_DAGSOMSETNING].copy()
    if df.empty:
        return df

    # RS-rating (1–99) på tvers av universet
    df["rs"] = _persentil(df["rs_avkastning"])
    df["rs"] = df["rs"].astype("Int64")

    # Oppfyller valgt preset? (evt. med RS-krav)
    df["oppfyller"] = df["score"] >= preset.krev_antall
    if preset.krev_rs:
        df["oppfyller"] = df["oppfyller"] & (df["rs"] >= konfig.RS_MIN)

    df = df.sort_values(["oppfyller", "score", "rs"], ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Dagens liste (JSON) + sammenligning mot forrige kjøring
# ---------------------------------------------------------------------------
def til_dagens_liste(df: pd.DataFrame) -> dict:
    """Lager en liten oppsummering (én rad per aksje) som lagres og sammenlignes senere."""
    liste = {}
    for _, r in df.iterrows():
        liste[r["ticker"]] = {
            "score": int(r["score"]),
            "oppfyller": bool(r["oppfyller"]),
            "status": r["status"],
            "pris": float(r["pris"]),
            "rs": int(r["rs"]) if pd.notna(r["rs"]) else None,
            "pivot": None if r["pivot"] is None else float(r["pivot"]),
        }
    return liste


def lagre_liste(liste: dict, sti: str = konfig.SISTE_LISTE_FIL) -> None:
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, indent=2)


def les_forrige_liste(sti: str = konfig.SISTE_LISTE_FIL) -> dict:
    if os.path.exists(sti):
        with open(sti, encoding="utf-8") as f:
            return json.load(f)
    return {}


def sammenlign(forrige: dict, naa: dict) -> dict:
    """
    Finner endringer mellom to lister:
      - nye:          aksjer som NÅ oppfyller trenden (men ikke gjorde det før)
      - falt_ut:      aksjer som oppfylte før, men ikke lenger
      - ferske_brudd: aksjer som NÅ har grønt (🟢) brudd (men ikke hadde det før)
    """
    nye = [t for t, v in naa.items() if v.get("oppfyller") and not forrige.get(t, {}).get("oppfyller")]
    falt_ut = [t for t, v in forrige.items() if v.get("oppfyller") and not naa.get(t, {}).get("oppfyller")]
    ferske_brudd = [t for t, v in naa.items() if v.get("status") == "🟢" and forrige.get(t, {}).get("status") != "🟢"]
    return {"nye": sorted(nye), "falt_ut": sorted(falt_ut), "ferske_brudd": sorted(ferske_brudd)}
