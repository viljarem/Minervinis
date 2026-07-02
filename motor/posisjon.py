"""
posisjon.py – ren matematikk for en long-posisjon (inngang, stop, mål).

Ingen Streamlit eller nettverk her – bare tall inn og tall ut, så det er lett å
teste og gjenbruke. Brukes av «Posisjon & risk/reward»-verktøyet i chartet:
regner hvor mye du risikerer, hvor mye du kan tjene, og forholdet mellom dem
(risk/reward), pluss valgfri posisjonsstørrelse ut fra hvor mange kroner du vil
risikere per handel.
"""
from __future__ import annotations

import math


def nokkeltall(entry, stop, mal, risiko_belop=None) -> dict:
    """Regner risk/reward for en long-handel.

    entry = inngang (kjøpskurs), stop = stopnivå (skal være UNDER inngang),
    mal   = kursmål (skal være OVER inngang). risiko_belop = valgfritt hvor mange
    kroner du vil risikere; da regner vi ut antall aksjer og hva det koster.

    Returnerer en dict med:
      gyldig       – True bare hvis stop < inngang < mål og inngang > 0
      risiko_pct   – prosent ned til stop (positivt tall)
      gevinst_pct  – prosent opp til mål (positivt tall)
      rr           – risk/reward (gevinst delt på risiko i kroner), None hvis ugyldig
      antall       – (kun hvis risiko_belop gitt) antall aksjer å kjøpe
      kostnad      – (kun hvis risiko_belop gitt) omtrentlig kjøpsbeløp
    """
    try:
        entry = float(entry)
        stop = float(stop)
        mal = float(mal)
    except (TypeError, ValueError):
        return {"gyldig": False, "risiko_pct": float("nan"),
                "gevinst_pct": float("nan"), "rr": None}

    risiko_pr_aksje = entry - stop
    gyldig = entry > 0 and stop < entry < mal and risiko_pr_aksje > 0

    risiko_pct = (risiko_pr_aksje / entry * 100) if entry > 0 else float("nan")
    gevinst_pct = ((mal - entry) / entry * 100) if entry > 0 else float("nan")
    rr_verdi = (mal - entry) / risiko_pr_aksje if risiko_pr_aksje > 0 else float("nan")

    ut = {
        "gyldig": bool(gyldig),
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "mal": round(mal, 4),
        "risiko_pct": round(risiko_pct, 1) if math.isfinite(risiko_pct) else float("nan"),
        "gevinst_pct": round(gevinst_pct, 1) if math.isfinite(gevinst_pct) else float("nan"),
        "rr": round(rr_verdi, 2) if math.isfinite(rr_verdi) and rr_verdi > 0 else None,
    }

    if risiko_belop and risiko_pr_aksje > 0:
        try:
            antall = int(float(risiko_belop) // risiko_pr_aksje)
        except (TypeError, ValueError):
            antall = 0
        if antall > 0:
            ut["antall"] = antall
            ut["kostnad"] = round(antall * entry, 0)

    return ut


def forslag_mal(entry, stop, r_multippel: float = 2.0):
    """Standard kursmål = inngang + R_multippel × risiko (avstanden inngang→stop).

    2R betyr at oppsiden er dobbelt så stor som det du risikerer – en vanlig
    Minervini-tommelfingerregel. Returnerer None hvis inn-tallene ikke gir mening.
    """
    try:
        entry = float(entry)
        stop = float(stop)
    except (TypeError, ValueError):
        return None
    if not (stop < entry):
        return None
    return round(entry + r_multippel * (entry - stop), 4)
