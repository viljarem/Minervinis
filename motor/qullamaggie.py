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
