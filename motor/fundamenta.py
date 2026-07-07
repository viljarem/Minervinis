"""
fundamenta.py – henter fundamentaltall (inntjening, salg, marginer og
aksjestruktur) for ÉN aksje om gangen fra Yahoo Finance.

Dette er Minervinis «andre bein»: han vil ikke bare ha en pen kursgraf, men også
selskaper som faktisk vokser – helst kvartalsvis inntjening og salg opp ~25 % år
mot år, med marginer som utvider seg. I tillegg liker han aksjer med relativt få
frie aksjer i omløp (lav «free float»), fordi de kan bevege seg raskere når
etterspørselen kommer.

VIKTIG, og litt ærlig:
  • Yahoo har god dekning på store/mellomstore Oslo Børs-navn, men MANGE små
    Growth/Expand-aksjer mangler fundamentaldata helt. Da returnerer vi bare
    {"tilgjengelig": False} – appen viser «ikke tilgjengelig» i stedet for å krasje.
  • Selskaper rapporterer i sin egen valuta (f.eks. EUR/USD) selv om aksjen
    handles i NOK. Prosent og marginer er valuta-nøytrale (trygge). Absolutte
    beløp merkes derfor med rapporteringsvaluta.
  • Tallene kan ligge noen uker etter faktisk kvartalsrapport.

All nettverkskontakt er pakket i try/except. Regnestykkene er skilt ut i små, rene
hjelpefunksjoner uten nettverk, så de er lette å teste.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

# Radnavn kan variere litt mellom selskaper – vi prøver flere varianter i rekkefølge.
_RAD_OMSETNING = ["Total Revenue", "Operating Revenue"]
_RAD_BRUTTO = ["Gross Profit"]
_RAD_DRIFT = ["Operating Income", "Total Operating Income As Reported"]
_RAD_RESULTAT = ["Net Income", "Net Income Common Stockholders",
                 "Net Income From Continuing Operation Net Minority Interest"]


# ---------------------------------------------------------------------------
# Rene regnestykker (ingen nettverk – lette å teste)
# ---------------------------------------------------------------------------
def vekst(ny, gammel) -> float | None:
    """Prosentvis endring fra `gammel` til `ny`. None hvis vi ikke kan regne trygt.

    Vi returnerer None når fjorårstallet er null eller negativt: da blir prosent
    misvisende (f.eks. fra −10 til +5 er ikke «+150 %»). Da viser appen heller de
    rå tallene, som er ærligere.
    """
    try:
        ny = float(ny)
        gammel = float(gammel)
    except (TypeError, ValueError):
        return None
    if pd.isna(ny) or pd.isna(gammel) or gammel <= 0:
        return None
    return round((ny - gammel) / gammel * 100, 1)


def margin(teller, nevner) -> float | None:
    """Margin i prosent = teller / nevner × 100 (f.eks. driftsresultat / omsetning)."""
    try:
        teller = float(teller)
        nevner = float(nevner)
    except (TypeError, ValueError):
        return None
    if pd.isna(teller) or pd.isna(nevner) or nevner == 0:
        return None
    return round(teller / nevner * 100, 1)


def margin_endring(t_ny, n_ny, t_gl, n_gl) -> float | None:
    """Endring i margin (prosentpoeng) fra i fjor til nå. Positivt = utvider seg."""
    m_ny = margin(t_ny, n_ny)
    m_gl = margin(t_gl, n_gl)
    if m_ny is None or m_gl is None:
        return None
    return round(m_ny - m_gl, 1)


# ---------------------------------------------------------------------------
# Hjelpere for å lese resultatregnskapet (kvartalsvis og årlig)
# ---------------------------------------------------------------------------
def _rad_serie(df: pd.DataFrame | None, navn_liste: list[str]) -> pd.Series | None:
    """Første rad som finnes av navnene i lista, som en dato-indeksert serie."""
    if df is None or getattr(df, "empty", True):
        return None
    for navn in navn_liste:
        if navn in df.index:
            return df.loc[navn]
    return None


def _hent_verdi(df: pd.DataFrame | None, navn_liste: list[str], dato) -> float | None:
    """Verdien for en rad på en bestemt kolonne (dato). None hvis den mangler."""
    serie = _rad_serie(df, navn_liste)
    if serie is None or dato is None:
        return None
    try:
        v = serie.get(dato)
        return None if v is None or pd.isna(v) else float(v)
    except Exception:
        return None


def finn_periode_par(df: pd.DataFrame | None, tol_dager: int = 80):
    """Finner (siste_dato, fjorårs_dato) ut fra omsetningskolonnene.

    Kolonnene er periodeslutt-datoer (nyeste kan stå først eller sist). Vi finner
    den nyeste, og deretter den perioden som ligger nærmest 12 måneder tilbake –
    det gir «samme kvartal i fjor» (kvartal) eller «forrige år» (år). Returnerer
    (None, None) hvis vi ikke finner noe brukbart.
    """
    serie = _rad_serie(df, _RAD_OMSETNING)
    if serie is None:
        return None, None
    serie = serie.dropna().sort_index()
    if serie.empty:
        return None, None
    siste = serie.index[-1]
    mal = siste - pd.DateOffset(months=12)
    tidligere = [d for d in serie.index if d < siste]
    if not tidligere:
        return siste, None
    ifjor = min(tidligere, key=lambda d: abs((d - mal).days))
    if abs((ifjor - mal).days) > tol_dager:
        return siste, None          # nærmeste periode er for langt unna 12 mnd
    return siste, ifjor


def _dato_str(dato) -> str | None:
    try:
        return pd.Timestamp(dato).date().isoformat()
    except Exception:
        return None


def bygg_periode(df: pd.DataFrame | None, siste, ifjor) -> dict | None:
    """Bygger ett sett med tall (omsetning, resultat, marginer + endringer) for en periode."""
    if df is None or siste is None:
        return None
    oms = _hent_verdi(df, _RAD_OMSETNING, siste)
    oms_i = _hent_verdi(df, _RAD_OMSETNING, ifjor)
    res = _hent_verdi(df, _RAD_RESULTAT, siste)
    res_i = _hent_verdi(df, _RAD_RESULTAT, ifjor)
    brutto = _hent_verdi(df, _RAD_BRUTTO, siste)
    brutto_i = _hent_verdi(df, _RAD_BRUTTO, ifjor)
    drift = _hent_verdi(df, _RAD_DRIFT, siste)
    drift_i = _hent_verdi(df, _RAD_DRIFT, ifjor)

    return {
        "dato": _dato_str(siste),
        "dato_ifjor": _dato_str(ifjor),
        "omsetning": oms,
        "omsetning_ifjor": oms_i,
        "omsetning_vekst": vekst(oms, oms_i),
        "resultat": res,
        "resultat_ifjor": res_i,
        "resultat_vekst": vekst(res, res_i),
        "brutto_margin": margin(brutto, oms),
        "brutto_margin_endring": margin_endring(brutto, oms, brutto_i, oms_i),
        "drift_margin": margin(drift, oms),
        "drift_margin_endring": margin_endring(drift, oms, drift_i, oms_i),
        "netto_margin": margin(res, oms),
        "netto_margin_endring": margin_endring(res, oms, res_i, oms_i),
    }


def bygg_struktur(info: dict) -> dict:
    """Aksjestruktur fra Yahoos info: utestående, free float, % innsidere/institusjoner."""
    def _tall(navn):
        v = info.get(navn)
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    def _pct(navn):
        v = _tall(navn)
        return None if v is None else round(v * 100, 1)

    utestaende = _tall("sharesOutstanding")
    fri = _tall("floatShares")
    float_pct = None
    if utestaende and fri and utestaende > 0:
        float_pct = round(fri / utestaende * 100, 1)

    return {
        "utestaende": utestaende,
        "float": fri,
        "float_pct": float_pct,
        "innsidere_pct": _pct("heldPercentInsiders"),
        "institusjoner_pct": _pct("heldPercentInstitutions"),
    }


# ---------------------------------------------------------------------------
# Fundamental Minervini-score (rent regnestykke, ingen nettverk)
# ---------------------------------------------------------------------------
def fund_score(fund: dict) -> dict:
    """Fundamental Minervini-score 0–5 basert på vekst og marginer.

    Hvert punkt er ett poeng:
      1. Kvartalsvis salg  ≥ 25 % YoY   (sterk topp-linje)
      2. Kvartalsvis EPS   ≥ 25 % YoY   (sterk bunnlinje)
      3. Marginer ekspanderer (drift→netto som fallback, positivt pp)
      4. Årsvis salg       ≥ 15 % YoY   (varig trend)
      5. Årsvis EPS        ≥ 15 % YoY   (varig inntjening)

    Returnerer {"poeng", "merke", "tilgjengelig", "detaljer"}.
    merke: 🟢 = 4–5 poeng, 🟡 = 2–3, 🔴 = 0–1.
    """
    if not fund.get("tilgjengelig"):
        return {"poeng": None, "merke": "·", "tilgjengelig": False, "detaljer": []}

    kv = fund.get("kvartal") or {}
    aar = fund.get("aar") or {}
    poeng = 0
    detaljer: list[str] = []

    def _ledd(verdi, terskel: float, label: str) -> None:
        nonlocal poeng
        if verdi is None:
            detaljer.append(f"{label} —")
        elif verdi >= terskel:
            poeng += 1
            detaljer.append(f"{label} +{verdi:.0f}% ✅")
        elif verdi >= 0:
            detaljer.append(f"{label} +{verdi:.0f}% —")
        else:
            detaljer.append(f"{label} {verdi:.0f}% ❌")

    _ledd(kv.get("omsetning_vekst"), 25.0, "Q-salg")
    _ledd(kv.get("resultat_vekst"),  25.0, "Q-EPS")

    # Margin-ekspansjon: drift foretrekkes, netto som fallback
    me = kv.get("drift_margin_endring")
    if me is None:
        me = kv.get("netto_margin_endring")
    if me is None:
        detaljer.append("Margin —")
    elif me > 0:
        poeng += 1
        detaljer.append(f"Margin +{me:.1f}pp ✅")
    elif me < 0:
        detaljer.append(f"Margin {me:+.1f}pp —")
    else:
        detaljer.append("Margin 0pp —")

    _ledd(aar.get("omsetning_vekst"), 15.0, "Å-salg")
    _ledd(aar.get("resultat_vekst"),  15.0, "Å-EPS")

    merke = "🟢" if poeng >= 4 else "🟡" if poeng >= 2 else "🔴"
    return {"poeng": poeng, "merke": merke, "tilgjengelig": True, "detaljer": detaljer}


# ---------------------------------------------------------------------------
# Hovedfunksjon (henter fra nettet – alt pakket i try/except)
# ---------------------------------------------------------------------------
def hent_fundamenta(ticker: str) -> dict:
    """Henter fundamentaltall for én ticker. Returnerer alltid en dict.

    {"tilgjengelig": False} betyr at Yahoo ikke har data (typisk små aksjer).
    Ellers: valuta, kvartal (YoY), aar (YoY) og struktur (aksjer/free float).
    """
    tom = {"tilgjengelig": False, "ticker": (ticker or "").strip().upper()}
    ticker = tom["ticker"]
    if not ticker:
        return tom

    try:
        t = yf.Ticker(ticker)
    except Exception:
        return tom

    try:
        info = t.info or {}
    except Exception:
        info = {}

    struktur = bygg_struktur(info)

    kvartal = None
    try:
        q = t.quarterly_income_stmt
        s, i = finn_periode_par(q)
        kvartal = bygg_periode(q, s, i)
    except Exception:
        kvartal = None

    aar = None
    try:
        a = t.income_stmt
        s, i = finn_periode_par(a, tol_dager=120)
        aar = bygg_periode(a, s, i)
    except Exception:
        aar = None

    tilgjengelig = bool(kvartal or aar or struktur.get("utestaende"))
    return {
        "tilgjengelig": tilgjengelig,
        "ticker": ticker,
        "valuta": info.get("financialCurrency") or info.get("currency"),
        "kvartal": kvartal,
        "aar": aar,
        "struktur": struktur,
    }
