"""
qullamaggie.py – Qullamaggies BREAKOUT-oppsett (setup-variant, INGEN score).

Samme filosofi som minervini.py: hvert kriterium passerer/feiler (True/False),
slik at alt er transparent og etterprøvbart. I tillegg regner vi "avstand til
utbrudd" (pivot) – som Minervinis avstand til pivot – så du ser hvilke
markedsledere som står på KANTEN av neste trinn (du ligger foran markedet).

Validert mot ekte data 16.11 (se todos.txt): finner ekte ledere, få falske.

De 7 kriteriene (QM1 Breakout):
  qk1  Momentum-leder   – topp X % på 3M i universet (settes av screener).
  qk2  Reelt byks       – minst QM_BYKS_MIN % lav→høy siste ~3 mnd.
  qk3  Surfer EMA       – Close ≥ EMA20 og EMA10 > EMA20 > EMA50.
  qk4  Høyere bunner    – siste halvdel av basen har ≥ bunn som første halvdel.
  qk5  Stram base       – range/ADR under QM_STRAM_MAKS (kontraksjon).
  qk6  Nok bevegelse    – ADR% ≥ QM_ADR_MIN.
  qk7  Tight stop       – stop (dagens low) ≤ ADR% (R/R-mekanikken intakt).

qk1 settes på tvers av universet (momentum-persentil) i screeneren, resten er
rent per-aksje. nøkkeltall() returnerer alle rådata + pivot/stop/avstand.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import konfig, indikatorer

# qk1 (momentum-leder) avgjøres på tvers av universet, derfor ikke her.
QM_KRITERIE_KOLONNER = ["qk1", "qk2", "qk3", "qk4", "qk5", "qk6", "qk7"]

QM_KRITERIE_TEKST = {
    "qk1": "Momentum-leder (topp 3M)",
    "qk2": "Reelt byks siste 3 mnd",
    "qk3": "Surfer stigende EMA10/20/50",
    "qk4": "Høyere bunner i basen",
    "qk5": "Stram base (range/ADR)",
    "qk6": "Nok bevegelse (ADR%)",
    "qk7": "Tight stop (≤ ADR%)",
}


def nokkeltall(d: pd.DataFrame) -> dict | None:
    """Regner alle Qullamaggie-størrelser for SISTE dag. None hvis for kort.

    Returnerer rådata (etterprøvbart) + kriterier qk2–qk7 (qk1 settes i
    screeneren). Alt i prosent der naturlig.
    """
    if d is None or len(d) < konfig.QM_MIN_DAGER:
        return None
    c = d["Close"]
    pris = float(c.iloc[-1])
    if pris <= 0:
        return None

    e10 = indikatorer.ema(c, 10).iloc[-1]
    e20 = indikatorer.ema(c, 20).iloc[-1]
    e50 = indikatorer.ema(c, 50).iloc[-1]
    adr = indikatorer.adr_prosent(d, konfig.QM_ADR_VINDU)
    mom = indikatorer.momentum(c, konfig.QM_MOM_PERIODER)

    # Reelt byks siste ~3 mnd (lav → høy i vinduet)
    bvindu = c.tail(konfig.QM_BYKS_VINDU)
    byks = (float(bvindu.max()) / float(bvindu.min()) - 1.0) * 100.0 if float(bvindu.min()) > 0 else np.nan

    # Konsolidering (base): pivot = toppen (motstand), stramhet = range/ADR
    base = d.tail(konfig.QM_BASE_VINDU)
    pivot = float(base["High"].max())
    base_lav = float(base["Low"].min())
    range_pct = (pivot / base_lav - 1.0) * 100.0 if base_lav > 0 else np.nan
    tightness = range_pct / adr if adr and adr > 0 else np.nan
    avstand_pivot = (pivot / pris - 1.0) * 100.0  # hvor langt UNDER pivot (positiv = under)

    # Høyere bunner: min i siste halvdel ≥ min i første halvdel av basen
    halv = konfig.QM_BASE_VINDU // 2
    h1 = float(base["Low"].iloc[:halv].min())
    h2 = float(base["Low"].iloc[halv:].min())
    hoyere_bunner = bool(h2 >= h1)

    # Stop = DAGENS low (Qullamaggie), bredde i %
    dag_lav = float(d["Low"].iloc[-1])
    stop_bredde = (pris / dag_lav - 1.0) * 100.0 if dag_lav > 0 else np.nan

    # Trend-struktur: surfer stigende EMA
    surfer = bool(
        pd.notna(e10) and pd.notna(e20) and pd.notna(e50)
        and pris >= e20 and e10 > e20 > e50
    )

    # Kriterier (qk1 = momentum-leder settes i screeneren på tvers av universet)
    qk2 = bool(pd.notna(byks) and byks >= konfig.QM_BYKS_MIN)
    qk3 = surfer
    qk4 = hoyere_bunner
    qk5 = bool(pd.notna(tightness) and tightness < konfig.QM_STRAM_MAKS)
    qk6 = bool(pd.notna(adr) and adr >= konfig.QM_ADR_MIN)
    qk7 = bool(pd.notna(stop_bredde) and pd.notna(adr) and stop_bredde <= adr)

    return {
        "pris": pris,
        "adr_pct": adr,
        "mom": mom,
        "mom_3m": mom.get(f"m{konfig.QM_MOM_PERIODER[1]}", np.nan),
        "byks_pct": byks,
        "pivot": pivot,
        "avstand_pivot_pct": avstand_pivot,
        "range_pct": range_pct,
        "tightness": tightness,
        "hoyere_bunner": hoyere_bunner,
        "stop": dag_lav,
        "stop_bredde_pct": stop_bredde,
        "ema10": float(e10) if pd.notna(e10) else np.nan,
        "ema20": float(e20) if pd.notna(e20) else np.nan,
        "ema50": float(e50) if pd.notna(e50) else np.nan,
        "qk2": qk2, "qk3": qk3, "qk4": qk4, "qk5": qk5, "qk6": qk6, "qk7": qk7,
    }


def antall_oppfylt(n: dict, inkluder_qk1: bool = True) -> int:
    """Teller hvor mange qk-kriterier som er True i et nøkkeltall-dict."""
    kol = QM_KRITERIE_KOLONNER if inkluder_qk1 else QM_KRITERIE_KOLONNER[1:]
    return int(sum(1 for k in kol if n.get(k)))


def er_gyldig_setup(n: dict) -> bool:
    """True når ALLE 7 qk-kriterier er oppfylt (inkl. qk1 fra screeneren)."""
    return all(bool(n.get(k)) for k in QM_KRITERIE_KOLONNER)


# ---------------------------------------------------------------------------
# Episodic Pivot (EP, QM2) – nyhets-/resultatgap
# ---------------------------------------------------------------------------
# Qullamaggies EP: en aksje gapper opp 10 %+ på stort volum (typisk resultat/
# nyhet) – ofte starten på en lang bevegelse. Edge er størst når aksjen IKKE
# allerede har gått mye (overraskelse). Vi dekker det teknisk (gap + volum +
# "ikke strukket"); fundamentale vekst-tall kan legges på senere.
EP_KRITERIE_KOLONNER = ["ek1", "ek2", "ek3"]

EP_KRITERIE_TEKST = {
    "ek1": "Gap opp ≥ 10 %",
    "ek2": "Stort volum (≥ 2x snitt)",
    "ek3": "Ikke allerede strukket",
}


def finn_ep(d: pd.DataFrame) -> dict | None:
    """Finner nyeste EP (gap-up på stort volum) de siste EP_FERSK_DAGER. None ellers.

    Ser bakover fra siste dag: for hver dag regnes gap% (dagens open mot forrige
    close) og volum mot 50-dagers snitt (før gap-dagen). Returnerer nøkkeltall
    for det nyeste kvalifiserende gapet, inkl. kriteriene ek1–ek3.
    """
    if d is None or len(d) < konfig.EP_MIN_DAGER:
        return None

    snitt50 = d["Volume"].rolling(50, min_periods=20).mean().shift(1)
    c = d["Close"]
    pris = float(c.iloc[-1])
    if pris <= 0:
        return None

    n = len(d)
    sok = min(konfig.EP_FERSK_DAGER, n - 1)
    for tilbake in range(sok):
        i = n - 1 - tilbake
        if i < 1:
            break
        forrige_close = float(c.iloc[i - 1])
        aapning = float(d["Open"].iloc[i])
        if forrige_close <= 0:
            continue
        gap = (aapning / forrige_close - 1.0) * 100.0
        vol = float(d["Volume"].iloc[i])
        vsnitt = float(snitt50.iloc[i]) if pd.notna(snitt50.iloc[i]) else np.nan
        vol_x = vol / vsnitt if vsnitt and vsnitt > 0 else np.nan

        # "Ikke allerede strukket": avkastning de 6 mnd FØR gapet (fram til dagen før).
        før = c.iloc[:i]
        strukket = np.nan
        if len(før) > 126:
            base = float(før.iloc[-127])
            if base > 0:
                strukket = (float(før.iloc[-1]) / base - 1.0) * 100.0

        ek1 = bool(gap >= konfig.EP_GAP_MIN)
        ek2 = bool(pd.notna(vol_x) and vol_x >= konfig.EP_VOLUM_FAKTOR)
        ek3 = bool(pd.isna(strukket) or strukket <= konfig.EP_IKKE_STRUKKET)

        if ek1:  # et reelt gap – rapporter nyeste slike (selv om volum/strukket svikter)
            gapdag = d.index[i]
            dag_lav = float(d["Low"].iloc[i])
            siden = (pris / float(c.iloc[i]) - 1.0) * 100.0 if float(c.iloc[i]) > 0 else np.nan
            return {
                "gap_dato": gapdag,
                "gap_pct": gap,
                "volum_x": vol_x,
                "strukket_6m": strukket,
                "dager_siden": int(tilbake),
                "pris": pris,
                "gap_close": float(c.iloc[i]),
                "stop": dag_lav,
                "siden_gap_pct": siden,
                "ek1": ek1, "ek2": ek2, "ek3": ek3,
            }
    return None


# ---------------------------------------------------------------------------
# Parabolsk (QM3) – KUN et observasjonsflagg på aksjer du allerede EIER
# ---------------------------------------------------------------------------
# Qullamaggie bruker parabolske bevegelser som SHORT-oppsett. Vi handler ikke
# short, så for oss er dette aldri et kjøpssignal – det er et "vokt deg / vurder
# å ta gevinst"-varsel på åpne posisjoner: aksjen har gått parabolsk (rask,
# bratt oppgang, mange grønne dager på rad, strukket langt over EMA10) og kan
# stå foran en skarp korreksjon. Alt er rådata, ingen score.
PB_KRITERIE_KOLONNER = ["pb1", "pb2", "pb3"]

PB_KRITERIE_TEKST = {
    "pb1": "Rask, bratt oppgang (vindu)",
    "pb2": "Mange grønne dager på rad",
    "pb3": "Strukket langt over EMA10",
}


def er_parabolsk(d: pd.DataFrame) -> dict | None:
    """Vurderer om SISTE dag ser parabolsk ut. None hvis for kort historikk.

    Returnerer rådata + kriteriene pb1–pb3 og et samlet `parabolsk`-flagg.
    Flagget slår til når oppgangen er rask (pb1) OG minst ett av de to andre
    tegnene er til stede (mange grønne dager på rad eller strukket over EMA10).
    Dette er et OBSERVASJONSFLAGG for aksjer du eier – aldri et kjøpssignal.
    """
    if d is None or len(d) < konfig.PB_MIN_DAGER:
        return None
    c = d["Close"]
    pris = float(c.iloc[-1])
    if pris <= 0:
        return None

    # Rask oppgang: % opp over de siste PB_VINDU dagene (lav i vinduet → nå).
    vindu = c.tail(konfig.PB_VINDU + 1)
    start = float(vindu.min())
    opp = (pris / start - 1.0) * 100.0 if start > 0 else np.nan

    # Grønne dager på rad (siste dager der close > forrige close).
    diff = c.diff()
    gronne = 0
    for v in reversed(diff.tolist()):
        if pd.notna(v) and v > 0:
            gronne += 1
        else:
            break

    # Strukket: hvor langt over EMA10 close ligger nå.
    e10 = indikatorer.ema(c, 10).iloc[-1]
    over_ema10 = (pris / float(e10) - 1.0) * 100.0 if pd.notna(e10) and float(e10) > 0 else np.nan

    pb1 = bool(pd.notna(opp) and opp >= konfig.PB_OPP_MIN)
    pb2 = bool(gronne >= konfig.PB_GRONNE_MIN)
    pb3 = bool(pd.notna(over_ema10) and over_ema10 >= konfig.PB_OVER_EMA10)

    parabolsk = bool(pb1 and (pb2 or pb3))

    return {
        "pris": pris,
        "opp_pct": opp,
        "gronne_rad": int(gronne),
        "over_ema10_pct": over_ema10,
        "ema10": float(e10) if pd.notna(e10) else np.nan,
        "parabolsk": parabolsk,
        "pb1": pb1, "pb2": pb2, "pb3": pb3,
    }

