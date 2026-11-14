"""
journal_tall.py – all matematikken bak tradingjournalen.

Rene funksjoner: tall inn, tall ut. Ingen database, ingen Streamlit, ingen
nettverk – så alt er lett å teste og kan ikke krasje appen. Lagringen (Supabase)
og skjemaene (Streamlit) ligger i egne filer.

Hovedbegreper:
  R          – resultat målt i «hvor mange ganger den opprinnelige risikoen».
               +2R betyr at du tjente dobbelt så mye som du risikerte. R er
               valutanøytralt, så Oslo (kr) og USA ($) kan sammenlignes direkte.
  Risiko     – (kjøpskurs − stop) × antall. Det du kunne tapt hvis stop traff.
  Time Value – R per handelsdag posisjonen var åpen. Måler hvor effektivt
               kapitalen jobbet, ikke bare hvor mye den tjente.
  Heat       – samlet åpen risiko akkurat nå, i prosent av kontoen. Hvor mye du
               kan tape hvis ALLE åpne stop treffer samtidig.
"""
from __future__ import annotations

import math
from datetime import date, datetime


# ---------------------------------------------------------------------------
# Små hjelpere
# ---------------------------------------------------------------------------
def _tall(verdi):
    """Gjør verdi om til float, eller None hvis det ikke går (tom, tekst, NaN)."""
    if verdi is None or verdi == "":
        return None
    try:
        t = float(verdi)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(t) else t


def _dato(verdi):
    """Godtar date, datetime eller ISO-tekst ('2026-11-14'). None hvis umulig."""
    if verdi is None or verdi == "":
        return None
    if isinstance(verdi, datetime):
        return verdi.date()
    if isinstance(verdi, date):
        return verdi
    try:
        return date.fromisoformat(str(verdi)[:10])
    except ValueError:
        return None


def handelsdager(fra, til) -> int | None:
    """Antall handelsdager (man–fre) mellom to datoer, inklusiv begge ender.

    Helger teller ikke (børsen er stengt). Helligdager er ikke trukket fra –
    det er en bevisst forenkling som holder for Time Value. Returnerer minst 1
    for en handel åpnet og lukket samme dag, og None ved ugyldige datoer.
    """
    f, t = _dato(fra), _dato(til)
    if f is None or t is None or t < f:
        return None
    dager = 0
    steg = f
    while steg <= t:
        if steg.weekday() < 5:          # 0=mandag ... 4=fredag
            dager += 1
        steg = date.fromordinal(steg.toordinal() + 1)
    return max(dager, 1)


# ---------------------------------------------------------------------------
# Én handel (med støtte for delsalg og trailing)
# ---------------------------------------------------------------------------
def handelstall(kjop_kurs, antall, stop, *, delsalg=None, kjop_dato=None,
                kurs_naa=None, i_dag=None) -> dict:
    """Regner alt for ÉN handel – åpen eller lukket, hel eller delvis solgt.

    delsalg = liste med {'salg_kurs', 'antall', 'salg_dato'} (kan være tom/None).
    kurs_naa brukes til å verdsette det som fortsatt er åpent (urealisert).
    i_dag lar testene fryse «dagens dato»; ellers brukes date.today().

    Returnerer bl.a.:
      status        – 'OPEN' så lenge noe gjenstår, ellers 'CLOSED'
      antall_solgt / antall_igjen
      realisert_pnl – kroner/dollar tatt hjem fra delsalg
      urealisert_pnl– verdi av resten mot kurs_naa (None hvis ukjent)
      total_pnl     – realisert + urealisert
      pnl_pct       – snittavkastning i prosent (vektet på antall)
      risiko        – opprinnelig risiko i kr/$ ((kjøp − stop) × antall)
      r             – total_pnl / risiko (None uten gyldig stop)
      holdedager    – handelsdager til siste salg (lukket) eller til i dag (åpen)
      time_value    – pnl_pct / holdedager (prosent avkastning per handelsdag,
                      P/D: f.eks. 10 % på 3 dager = 3.33. Høyere = raskere penger)
      vinn          – True/False for en LUKKET handel, ellers None
    """
    kjop = _tall(kjop_kurs)
    ant = _tall(antall)
    stop_v = _tall(stop)
    naa = _tall(kurs_naa)
    idag = _dato(i_dag) or date.today()

    linjer = []
    for d in (delsalg or []):
        k = _tall(d.get("salg_kurs"))
        a = _tall(d.get("antall"))
        if k is not None and a is not None and a > 0:
            linjer.append({"salg_kurs": k, "antall": a, "salg_dato": d.get("salg_dato")})

    ut = {
        "status": "OPEN", "antall_solgt": 0.0, "antall_igjen": ant or 0.0,
        "realisert_pnl": None, "urealisert_pnl": None, "total_pnl": None,
        "pnl_pct": None, "risiko": None, "r": None,
        "holdedager": None, "time_value": None, "vinn": None,
    }
    if not kjop or kjop <= 0 or not ant or ant <= 0:
        return ut

    solgt = sum(l["antall"] for l in linjer)
    solgt = min(solgt, ant)                       # aldri selg mer enn du har
    igjen = max(ant - solgt, 0.0)
    lukket = igjen <= 1e-9 and solgt > 0
    ut["antall_solgt"] = round(solgt, 6)
    ut["antall_igjen"] = round(igjen, 6)
    ut["status"] = "CLOSED" if lukket else "OPEN"

    realisert = sum((l["salg_kurs"] - kjop) * l["antall"] for l in linjer)
    ut["realisert_pnl"] = round(realisert, 4)

    urealisert = None
    if igjen > 0 and naa is not None:
        urealisert = (naa - kjop) * igjen
        ut["urealisert_pnl"] = round(urealisert, 4)

    total = realisert + (urealisert or 0.0)
    # total_pnl gir bare mening hvis vi kan verdsette ALT (lukket, eller åpen med kurs)
    if lukket or urealisert is not None:
        ut["total_pnl"] = round(total, 4)
        # Vektet snittavkastning i prosent av innkjøpt beløp som er «avgjort».
        avgjort_antall = solgt + (igjen if urealisert is not None else 0.0)
        if avgjort_antall > 0:
            ut["pnl_pct"] = round(total / (kjop * avgjort_antall) * 100, 2)

    if stop_v is not None and stop_v < kjop:
        risiko = (kjop - stop_v) * ant
        ut["risiko"] = round(risiko, 4)
        if risiko > 0 and ut["total_pnl"] is not None:
            ut["r"] = round(total / risiko, 3)

    sluttdato = None
    if lukket:
        datoer = [_dato(l.get("salg_dato")) for l in linjer]
        datoer = [d for d in datoer if d is not None]
        sluttdato = max(datoer) if datoer else None
    hd = handelsdager(kjop_dato, sluttdato or idag) if kjop_dato else None
    ut["holdedager"] = hd
    if hd and ut["pnl_pct"] is not None:
        ut["time_value"] = round(ut["pnl_pct"] / hd, 4)

    if lukket:
        ut["vinn"] = total > 0

    return ut


# ---------------------------------------------------------------------------
# Posisjonsstørrelse og risiko
# ---------------------------------------------------------------------------
def posisjonsstorrelse(entry, stop, kapital, risiko_pct) -> dict:
    """Hvor mange aksjer skal jeg kjøpe for å risikere X % av kontoen?

    risiko_pct = 1.0 betyr «risiker 1 % av kapitalen hvis stop treffer».
    Returnerer antall (rundet ned), kronebeløpet du faktisk risikerer, hva
    posisjonen koster, og hvor stor andel av kontoen den legger beslag på.
    """
    e, s = _tall(entry), _tall(stop)
    kap, pct = _tall(kapital), _tall(risiko_pct)
    tom = {"antall": 0, "risiko_belop": None, "kostnad": None, "andel_pct": None}
    if not e or e <= 0 or s is None or s >= e or not kap or kap <= 0 or pct is None or pct <= 0:
        return tom
    risiko_belop = kap * pct / 100
    pr_aksje = e - s
    antall = int(risiko_belop // pr_aksje)
    if antall <= 0:
        return tom
    kostnad = antall * e
    return {
        "antall": antall,
        "risiko_belop": round(antall * pr_aksje, 2),
        "kostnad": round(kostnad, 2),
        "andel_pct": round(kostnad / kap * 100, 1),
    }


def heat(apne_handler, kapital) -> dict:
    """Samlet åpen risiko akkurat nå: hva taper jeg hvis ALLE stop treffer?

    apne_handler = liste med {'kjop_kurs','antall','stop'} (eller handelstall-dict
    med 'risiko'). Risiko regnes på det som fortsatt er ÅPENT i hver handel.
    Returnerer sum i kr/$ og som prosent av kontoen.
    """
    kap = _tall(kapital)
    sum_risiko = 0.0
    for h in apne_handler or []:
        r = _tall(h.get("risiko"))
        if r is None:
            kjop = _tall(h.get("kjop_kurs"))
            stop = _tall(h.get("stop"))
            ant = _tall(h.get("antall_igjen")) or _tall(h.get("antall"))
            if kjop and stop is not None and stop < kjop and ant:
                r = (kjop - stop) * ant
        if r and r > 0:
            sum_risiko += r
    return {
        "risiko_belop": round(sum_risiko, 2),
        "risiko_pct": round(sum_risiko / kap * 100, 2) if kap and kap > 0 else None,
    }


def atr_stop(entry, atr, multippel: float = 2.0) -> float | None:
    """Volatilitetsbasert stop: inngang − multippel × ATR (Minervini-stil).

    ATR = gjennomsnittlig dagsutslag. Et vanlig valg er 1.5–3 × ATR under
    inngang, så stoppen puster med aksjens normale støy. None ved tull-input.
    """
    e, a = _tall(entry), _tall(atr)
    if not e or e <= 0 or a is None or a <= 0:
        return None
    stop = e - multippel * a
    return round(stop, 4) if stop > 0 else None


# ---------------------------------------------------------------------------
# Statistikk over mange handler
# ---------------------------------------------------------------------------
def statistikk(handler) -> dict:
    """Nøkkeltall over en liste ferdig-utregnede handelstall-dicter.

    Winrate, expectancy og profit factor regnes BARE på lukkede handler.
    Åpne handler telles for seg (antall + urealisert).
    """
    lukket = [h for h in handler if h.get("status") == "CLOSED" and h.get("vinn") is not None]
    apne = [h for h in handler if h.get("status") != "CLOSED"]

    vinnere = [h for h in lukket if h["vinn"]]
    tapere = [h for h in lukket if not h["vinn"]]

    r_alle = [h["r"] for h in lukket if h.get("r") is not None]
    r_vinn = [h["r"] for h in vinnere if h.get("r") is not None]
    r_tap = [h["r"] for h in tapere if h.get("r") is not None]

    pnl_vinn = [h["total_pnl"] for h in vinnere if h.get("total_pnl") is not None]
    pnl_tap = [h["total_pnl"] for h in tapere if h.get("total_pnl") is not None]

    pct_alle = [h["pnl_pct"] for h in lukket if h.get("pnl_pct") is not None]
    hold = [h["holdedager"] for h in lukket if h.get("holdedager") is not None]
    tv = [h["time_value"] for h in lukket if h.get("time_value") is not None]

    sum_realisert = sum(h["total_pnl"] for h in lukket if h.get("total_pnl") is not None)
    urealisert = sum(h["urealisert_pnl"] for h in apne if h.get("urealisert_pnl") is not None)

    brutto_vinn = sum(pnl_vinn)
    brutto_tap = abs(sum(pnl_tap))
    winrate = (len(vinnere) / len(lukket)) if lukket else None

    # Expectancy i R: snitt-R per lukket handel. Enkelt og ærlig.
    expectancy = (sum(r_alle) / len(r_alle)) if r_alle else None

    # Profit factor: brutto gevinst / brutto tap. >1 = tjener penger.
    if brutto_tap > 0:
        profit_factor = round(brutto_vinn / brutto_tap, 2)
    elif brutto_vinn > 0:
        profit_factor = math.inf          # bare vinnere, ingen tap ennå
    else:
        profit_factor = None

    def _snitt(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "antall": len(handler),
        "lukket": len(lukket),
        "apne": len(apne),
        "vinnere": len(vinnere),
        "tapere": len(tapere),
        "winrate": round(winrate, 4) if winrate is not None else None,
        "expectancy_r": round(expectancy, 3) if expectancy is not None else None,
        "profit_factor": profit_factor,
        "snitt_r": _snitt(r_alle),
        "snitt_r_vinn": _snitt(r_vinn),
        "snitt_r_tap": _snitt(r_tap),
        "snitt_pct": _snitt(pct_alle),
        "beste_pct": round(max(pct_alle), 2) if pct_alle else None,
        "verste_pct": round(min(pct_alle), 2) if pct_alle else None,
        "snitt_holdedager": _snitt(hold),
        "snitt_time_value": _snitt(tv),
        "sum_realisert": round(sum_realisert, 2),
        "urealisert": round(urealisert, 2) if apne else 0.0,
    }


def statistikk_per(handler, nokkel: str = "setup") -> list[dict]:
    """Samme nøkkeltall, gruppert på f.eks. 'setup', 'kilde' eller en tag."""
    grupper: dict[str, list] = {}
    for h in handler:
        grupper.setdefault(h.get(nokkel) or "Uten", []).append(h)
    ut = []
    for navn, rader in grupper.items():
        rad = statistikk(rader)
        rad["gruppe"] = navn
        ut.append(rad)
    ut.sort(key=lambda x: (-x["lukket"], -(x["expectancy_r"] or -99), x["gruppe"]))
    return ut


def kumulativ_r(handler) -> list[dict]:
    """Bygger porteføljekurven: kumulativ R over tid fra LUKKEDE handler.

    Sorteres på sluttdato (holdedager finnes, men vi trenger datoen – den sendes
    med som 'slutt_dato' på hver handel). Returnerer [{dato, r, kum_r}] stigende.
    """
    lukket = [h for h in handler
              if h.get("status") == "CLOSED" and h.get("r") is not None
              and h.get("slutt_dato")]
    lukket.sort(key=lambda h: _dato(h["slutt_dato"]) or date.min)
    kurve, kum = [], 0.0
    for h in lukket:
        kum += h["r"]
        kurve.append({"dato": _dato(h["slutt_dato"]),
                      "r": round(h["r"], 3), "kum_r": round(kum, 3)})
    return kurve
