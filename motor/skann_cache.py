"""
skann_cache.py – deler ferdige skann-resultater via Supabase.

Hele poenget: appen skal slippe å regne skanningen på nytt ved kald oppstart,
og alle enheter (telefon, Mac, PC) skal se samme ferske resultat. Roboten eller
den første som skanner lagrer resultatet; alle andre leser det ferdige.

VIKTIG – trygghet:
  * ALT her er pakket i try/except. Feiler databasen eller mangler secrets,
    returnerer vi stille None / False. Screeneren merker ingenting og kjører
    som før (regner selv). Denne modulen kan ALDRI velte appen.
  * Dette er bare screener-resultater (offentlig info), så cachen er IKKE låst
    bak journal-passordet. Den bruker Supabase-nøkkelen direkte.
  * Lagrer en DataFrame som JSON-liste av rader. Leser den tilbake til DataFrame.
"""
from __future__ import annotations

import pandas as pd

from . import journal_db as db


# ---------------------------------------------------------------------------
# Hjelpere
# ---------------------------------------------------------------------------
def tilgjengelig() -> bool:
    """True hvis Supabase er konfigurert (secrets finnes). Ellers False."""
    try:
        return db.les_secrets() is not None
    except Exception:
        return False


def _lager() -> "db.Lager | None":
    try:
        return db.Lager.fra_secrets()
    except Exception:
        return None


def _dato_str(datadato) -> str | None:
    """Gjør datadato om til 'YYYY-MM-DD'. None hvis den ikke lar seg tolke."""
    if datadato is None:
        return None
    try:
        return pd.Timestamp(datadato).strftime("%Y-%m-%d")
    except Exception:
        return None


def _df_til_rader(df: pd.DataFrame) -> list[dict]:
    """DataFrame → liste av JSON-trygge dict-er (NaN/Timestamp håndtert)."""
    if df is None or getattr(df, "empty", True):
        return []
    try:
        # to_json håndterer NaN (→ null) og datoer trygt; parse tilbake til Python.
        import json
        return json.loads(df.to_json(orient="records", date_format="iso"))
    except Exception:
        return []


def _rader_til_df(rader) -> pd.DataFrame:
    try:
        if not rader:
            return pd.DataFrame()
        return pd.DataFrame(rader)
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Lagre / lese
# ---------------------------------------------------------------------------
def lagre(bors: str, oppsett: str, datadato, df: pd.DataFrame) -> bool:
    """Lagrer (upsert) et ferdig skann-resultat. Returnerer True ved suksess.

    Stille False hvis noe feiler – skanningen selv påvirkes aldri.
    """
    dato = _dato_str(datadato)
    if not dato or not bors or not oppsett:
        return False
    lager = _lager()
    if lager is None:
        return False
    rader = _df_til_rader(df)
    body = {
        "eier": db.EIER, "bors": bors, "oppsett": oppsett, "datadato": dato,
        "antall": len(rader), "rader": rader,
    }
    try:
        lager._kall("POST", "/rest/v1/skann_cache", body,
                    prefer="resolution=merge-duplicates,return=minimal")
        return True
    except Exception:
        return False


def hent(bors: str, oppsett: str, datadato) -> pd.DataFrame | None:
    """Leser ferdig skann-resultat for (bors, oppsett, datadato).

    Returnerer en DataFrame hvis cachen finnes, ellers None (da regner appen selv).
    """
    dato = _dato_str(datadato)
    if not dato or not bors or not oppsett:
        return None
    lager = _lager()
    if lager is None:
        return None
    try:
        import urllib.parse as _up
        sti = ("/rest/v1/skann_cache?select=rader"
               f"&bors=eq.{_up.quote(bors)}"
               f"&oppsett=eq.{_up.quote(oppsett)}"
               f"&datadato=eq.{dato}&limit=1")
        svar = lager._kall("GET", sti)
    except Exception:
        return None
    if not svar:
        return None
    return _rader_til_df(svar[0].get("rader"))


def hent_siste(bors: str, oppsett: str) -> tuple[pd.DataFrame, str] | None:
    """Leser det NYESTE lagrede resultatet for (bors, oppsett), uansett dato.

    Returnerer (DataFrame, datadato-streng) eller None. Nyttig når vi vil vise
    siste kjente skann selv om datagrunnlaget skulle være litt eldre.
    """
    if not bors or not oppsett:
        return None
    lager = _lager()
    if lager is None:
        return None
    try:
        import urllib.parse as _up
        sti = ("/rest/v1/skann_cache?select=rader,datadato"
               f"&bors=eq.{_up.quote(bors)}"
               f"&oppsett=eq.{_up.quote(oppsett)}"
               "&order=datadato.desc&limit=1")
        svar = lager._kall("GET", sti)
    except Exception:
        return None
    if not svar:
        return None
    df = _rader_til_df(svar[0].get("rader"))
    return df, str(svar[0].get("datadato"))
