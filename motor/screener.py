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
    pivot_vis, stop_vis = v["pivot"], v["stop"]

    # Fallback: fanger ferske volumbrudd gjennom motstand selv når VCP-motoren
    # ikke fant en pivot (typisk RETT ETTER et brudd, da basen "forsvinner").
    if pd.isna(v["pivot"]):
        fersk = vcp.ferskt_brudd(d)
        if fersk:
            brudd = fersk
            pivot_vis, stop_vis = fersk["pivot"], fersk["stop"]

    mtf = indikatorer.multi_timeframe(d)

    # Golden cross-status (SMA50 vs SMA200): siste golden cross + om vi er over nå.
    gc = indikatorer.golden_cross_status(d)

    pris = float(d["Close"].iloc[-1])
    dagsomsetning = float((d["Close"] * d["Volume"]).rolling(konfig.OMSETNING_VINDU).mean().iloc[-1])

    # Relativt volum (RVol): siste dags volum delt på 50-dagers snittvolum (før i dag).
    # 1,0 = helt normalt, >1 = mer handel enn vanlig. Et ekte brudd skjer typisk
    # på >1,4 (samme terskel som bruddlogikken bruker).
    vol_snitt50 = d["Volume"].rolling(50, min_periods=10).mean().shift(1).iloc[-1]
    rel_volum = float(d["Volume"].iloc[-1] / vol_snitt50) if vol_snitt50 and vol_snitt50 > 0 else np.nan
    # Rent 50-dagers snittvolum (uten shift) – baseline for LIVE relativt volum i appen.
    snitt_vol_50 = d["Volume"].rolling(50, min_periods=10).mean().iloc[-1]
    # Volumsignatur rundt bruddet: relativt volum dag −2 … +2 (0 = selve bruddagen).
    # Tom liste hvis aksjen ikke har brutt pivot ennå. Minervini vil se volumet tørke
    # inn i basen og eksplodere på bruddet – dette gjør det synlig.
    volum_signatur = vcp.volum_signatur(d, brudd.get("bruddato"))
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
        "pivot": None if pd.isna(pivot_vis) else round(pivot_vis, 2),
        "stop": None if pd.isna(stop_vis) else round(stop_vis, 2),
        # Avstand til den VISTE pivoten i prosent (positiv = under pivot). Regnes fra
        # pivot_vis – ikke v["avstand"] – slik at den også gjelder ferske brudd som kom
        # via ferskt_brudd-fallbacken (der VCP-motoren ikke fant noen pivot selv).
        "avstand_pivot": None if pd.isna(pivot_vis) else round((float(pivot_vis) - pris) / float(pivot_vis) * 100, 1),
        "antall_kontr": v["antall"],
        "kontraksjoner": v["kontraksjoner"],
        "vcp_punkter": v.get("punkter", []),
        "volumuttorking": v["volumuttorking"],
        "kvalitet": v["kvalitet"],
        "vcp_gyldig": v["gyldig"],
        "mtf_status": mtf["status"],
        "mtf_emoji": mtf["emoji"],
        "mtf_tekst": mtf["tekst"],
        "golden_cross_dato": None if gc["dato"] is None else pd.Timestamp(gc["dato"]).date().isoformat(),
        "golden_cross_dager": gc["dager_siden"],
        "golden_cross_over": gc["over"],
        "rs_avkastning": indikatorer.rs_avkastning(d["Close"]),
        "dagsomsetning": dagsomsetning,
        "rel_volum": None if pd.isna(rel_volum) else round(rel_volum, 2),
        "volum_signatur": volum_signatur,
        "snittvolum50": None if pd.isna(snitt_vol_50) else round(float(snitt_vol_50), 0),
        "perioder": [(pd.Timestamp(a).date().isoformat(), pd.Timestamp(b).date().isoformat()) for a, b in perioder],
    }


# ---------------------------------------------------------------------------
# Sortering av hovedlista ("hvem skal jeg følge med på?")
# ---------------------------------------------------------------------------
# Rekkefølge på status – mest handlbart øverst:
#   🟢 ferskt brudd  → 🟡 brudd uten volum → ⚪ klar/venter → 🔵 forlenget.
# ⚪ uten pivot ("Ingen pivot") er ikke handlbart og havner helt nederst (rang 5).
STATUS_RANG = {"🟢": 0, "🟡": 1, "⚪": 2, "🔵": 3}


def sorter_hovedliste(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sorterer lista slik at det mest handlbare ligger øverst – uten noen oppfunne
    vekter, bare to objektive akser i rekkefølge:
      1. STATUS (🟢 → 🟡 → ⚪ klar → 🔵 forlenget → ⚪ uten pivot nederst)
      2. NÆRHET til pivot (minst absolutt avstand i prosent øverst innen hver gruppe)

    Altså: det som skjer nå først, deretter det som er tettest på å skje.
    """
    if df.empty:
        return df
    d = df.copy()
    har_pivot = d["pivot"].notna()
    d["_rang"] = d["status"].map(STATUS_RANG).fillna(4).astype(int)
    d.loc[~har_pivot, "_rang"] = 5                      # ⚪ "Ingen pivot" helt nederst
    d["_naer"] = d["avstand_pivot"].abs()
    d.loc[~har_pivot, "_naer"] = float("inf")           # uten pivot: uendelig langt bak
    d = d.sort_values(["_rang", "_naer"], ascending=[True, True], kind="mergesort")
    return d.drop(columns=["_rang", "_naer"])


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

    # Hold ALLE børsers benchmark-indekser (OSEBX.OL, ^GSPC ...) utenfor selve
    # screeningen – de er referanser, ikke aksjer man kan kjøpe.
    benchmarks = {b.benchmark for b in konfig.BORSER.values() if b.benchmark}
    benchmarks.add(konfig.BENCHMARK)
    tickere = [t for t in sorted(priser["Ticker"].unique()) if t not in benchmarks]
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
# Golden cross-screener (SELVSTENDIG – IKKE Minervini-template)
# ---------------------------------------------------------------------------
# Denne screeneren leter kun etter forholdet mellom SMA50 og SMA200. Den bryr
# seg ikke om Minervinis 7 kriterier, VCP, pivot e.l. – den svarer på ett enkelt
# spørsmål: «hvem har nettopp fått (eller er i ferd med å få) et golden cross?»
GC_FERSK = "✨"       # golden cross bekreftet nylig (fersk)
GC_ETABLERT = "✅"    # golden cross for lenge siden, fortsatt over
GC_VENTER = "⏳"      # SMA50 rett under SMA200 og nærmer seg = venter på kryss


def analyser_golden_cross(serie: pd.DataFrame, ticker: str) -> dict | None:
    """Vurderer én aksje KUN ut fra SMA50/SMA200-forholdet (golden cross).

    Returnerer en dict hvis aksjen er relevant (nylig/etablert golden cross ELLER
    rett under og nærmer seg et kryss), ellers None. Ingen Minervini-logikk her.
    """
    if serie is None or len(serie) < konfig.MIN_HANDELSDAGER:
        return None
    d = indikatorer.legg_til_indikatorer(serie)
    if d["SMA200"].isna().all():
        return None
    s50 = d["SMA50"].iloc[-1]
    s200 = d["SMA200"].iloc[-1]
    if pd.isna(s50) or pd.isna(s200) or s200 <= 0:
        return None

    pris = float(d["Close"].iloc[-1])
    gap_pct = float((s50 - s200) / s200 * 100)      # + = SMA50 over, − = under
    gc = indikatorer.golden_cross_status(d)

    # Gapet N dager tilbake – brukes til å se om SMA50 nærmer seg SMA200 nedenfra.
    n = konfig.GOLDEN_CROSS_KONVERGENS_DAGER
    gap_for = np.nan
    if len(d) > n:
        s50_f, s200_f = d["SMA50"].iloc[-1 - n], d["SMA200"].iloc[-1 - n]
        if pd.notna(s50_f) and pd.notna(s200_f) and s200_f > 0:
            gap_for = float((s50_f - s200_f) / s200_f * 100)

    status = None
    if gc["over"]:
        # SMA50 ligger over SMA200 akkurat nå = aktivt golden cross.
        if gc["dager_siden"] is not None and gc["dager_siden"] <= konfig.GOLDEN_CROSS_FERSK_DAGER:
            status = GC_FERSK
        else:
            status = GC_ETABLERT
    else:
        # SMA50 under SMA200: er vi nær OG på vei opp mot et kryss?
        naer = -konfig.GOLDEN_CROSS_NAER_PROSENT * 100   # f.eks. −3.0 %
        krymper = pd.notna(gap_for) and gap_pct > gap_for   # gapet er mindre negativt nå
        if naer <= gap_pct < 0 and krymper:
            status = GC_VENTER

    if status is None:
        return None

    dagsomsetning = float((d["Close"] * d["Volume"]).rolling(konfig.OMSETNING_VINDU).mean().iloc[-1])
    return {
        "ticker": ticker,
        "pris": round(pris, 2),
        "gc_status": status,
        "gap_pct": round(gap_pct, 2),
        "golden_cross_dato": None if gc["dato"] is None else pd.Timestamp(gc["dato"]).date().isoformat(),
        "golden_cross_dager": gc["dager_siden"],
        "sma50": round(float(s50), 2),
        "sma200": round(float(s200), 2),
        "dagsomsetning": dagsomsetning,
        "rs_avkastning": indikatorer.rs_avkastning(d["Close"]),
    }


# Sorteringsrekkefølge: ferske kryss først, så de som venter (nærmest), så etablerte.
_GC_RANG = {GC_FERSK: 0, GC_VENTER: 1, GC_ETABLERT: 2}


def screen_golden_cross(priser: pd.DataFrame) -> pd.DataFrame:
    """Skanner HELE universet for golden cross (bekreftet + ventende). Egen tabell.

    Helt uavhengig av Minervini-screeningen. Bruker samme likviditetsfilter og
    RS-rating (relativ styrke i universet), men ingen av de 7 kriteriene.
    """
    if priser is None or priser.empty:
        return pd.DataFrame()

    benchmarks = {b.benchmark for b in konfig.BORSER.values() if b.benchmark}
    benchmarks.add(konfig.BENCHMARK)
    tickere = [t for t in sorted(priser["Ticker"].unique()) if t not in benchmarks]
    rader = []
    for t in tickere:
        res = analyser_golden_cross(datamod.serie_for(priser, t), t)
        if res is not None:
            rader.append(res)

    df = pd.DataFrame(rader)
    if df.empty:
        return df

    df = df[df["dagsomsetning"] >= konfig.MIN_DAGSOMSETNING].copy()
    if df.empty:
        return df

    df["rs"] = _persentil(df["rs_avkastning"])
    df["rs"] = df["rs"].astype("Int64")

    # Ferske kryss øverst, så ventende (nærmest kryss først = minst negativt gap),
    # så etablerte. Innen hver gruppe: ferske nærmest krysset, ventende nærmest 0.
    df["_rang"] = df["gc_status"].map(_GC_RANG).fillna(3).astype(int)
    df["_naer"] = df["gap_pct"].abs()
    df = (df.sort_values(["_rang", "_naer"], ascending=[True, True], kind="mergesort")
            .drop(columns=["_rang", "_naer"])
            .reset_index(drop=True))
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
