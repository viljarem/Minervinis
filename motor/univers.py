"""
univers.py – bestemmer HVILKE aksjer appen følger.

Oslo Børs (alle tre lister – Oslo Børs, Euronext Expand og Euronext Growth)
hentes AUTOMATISK fra Euronext. Slik fanger vi hele børsen uten en manuell liste,
og nye selskaper kommer med av seg selv når de noteres.

I tillegg kan du legge inn EGNE ekstra tickere i data/univers.txt (f.eks.
utenlandske aksjer). Den endelige lista er summen av begge.

Robusthet: klarer ikke Euronext å svare, faller vi tilbake til den sist lagrede
lista (data/univers_oslobors.txt), som roboten committer til GitHub hver dag.
"""
from __future__ import annotations

import io
import os
import time

import pandas as pd
from curl_cffi import requests

from . import konfig

_NETTLESER = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://live.euronext.com/en/products/equities/list",
}


# ---------------------------------------------------------------------------
# Hjelpere for å lese/skrive tickerlister (én ticker per linje)
# ---------------------------------------------------------------------------
def _les_fil(sti: str) -> list[str]:
    if not os.path.exists(sti):
        return []
    ut: list[str] = []
    with open(sti, encoding="utf-8") as f:
        for linje in f:
            t = linje.strip().upper()
            if t and not t.startswith("#"):
                ut.append(t)
    return ut


def _skriv_fil(sti: str, tickere: list[str], overskrift: str) -> None:
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        f.write(overskrift.rstrip() + "\n\n")
        for t in tickere:
            f.write(t + "\n")


def les_manuelle(sti: str = konfig.UNIVERS_FIL) -> list[str]:
    """Leser DINE egne ekstra tickere fra data/univers.txt."""
    return _les_fil(sti)


def les_cache(sti: str = konfig.OSLOBORS_CACHE_FIL) -> list[str]:
    """Leser den sist lagrede Oslo Børs-lista (fallback hvis Euronext er nede)."""
    return _les_fil(sti)


# ---------------------------------------------------------------------------
# Henting fra Euronext
# ---------------------------------------------------------------------------
def _hent_mic(mic: str, suffiks: str) -> list[str]:
    """Henter alle tickere for én Euronext-liste (MIC-kode) som en CSV-nedlasting."""
    url = f"https://live.euronext.com/en/pd_es/data/stocks/download?mics={mic}"
    r = requests.get(url, headers=_NETTLESER, impersonate="chrome", timeout=30)
    r.raise_for_status()
    linjer = r.text.replace("\ufeff", "").splitlines()
    start = next(i for i, l in enumerate(linjer) if "ISIN;Symbol" in l)
    df = pd.read_csv(io.StringIO("\n".join(linjer[start:])), sep=";", engine="python")
    # Behold bare ekte aksjerader (gyldig 12-tegns ISIN) med et symbol
    df = df[df["ISIN"].astype(str).str.len() == 12].dropna(subset=["Symbol"])
    symboler = df["Symbol"].astype(str).str.strip()
    return [s + suffiks for s in symboler if s and s.lower() != "nan"]


def hent_fra_euronext() -> list[str]:
    """
    Henter hele Oslo Børs (alle markedene i konfig.EURONEXT_MARKEDER).
    Prøver på nytt ved feil. Returnerer tom liste hvis alt feiler.
    """
    alle: list[str] = []
    for mic, suffiks in konfig.EURONEXT_MARKEDER.items():
        for forsok in range(3):
            try:
                fikk = _hent_mic(mic, suffiks)
                alle += fikk
                print(f"   Euronext {mic}: {len(fikk)} tickere.")
                break
            except Exception as feil:  # noqa: BLE001
                ventetid = 3 * (forsok + 1)
                print(f"   Euronext {mic} feilet ({feil}). Prøver igjen om {ventetid}s ...")
                time.sleep(ventetid)
    return sorted(set(alle))


# ---------------------------------------------------------------------------
# Henting fra Wikipedia (S&P 500)
# ---------------------------------------------------------------------------
def hent_sp500_fra_wikipedia() -> list[str]:
    """Henter S&P 500-symbolene fra Wikipedia. Tom liste hvis noe feiler.

    Vi leser symbolene rett ut av HTML-en med et enkelt mønster (regex) i stedet
    for et tungt tabell-bibliotek – da slipper vi en ekstra avhengighet. Hvert
    symbol lenker til en NYSE- eller NASDAQ-kursside, og der står tickeren.
    Yahoo vil ha bindestrek der Wikipedia bruker punktum (BRK.B → BRK-B).
    """
    import re

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    for forsok in range(3):
        try:
            r = requests.get(url, headers=_NETTLESER, impersonate="chrome", timeout=30)
            r.raise_for_status()
            nyse = re.findall(r'quote/X[A-Z]+:([A-Z][A-Z.\-]*)"', r.text)
            nasdaq = re.findall(r'nasdaq\.com/market-activity/stocks/([a-z][a-z.\-]*)"',
                                r.text, re.I)
            symboler = sorted(set(s.upper().replace(".", "-") for s in (nyse + nasdaq)))
            if len(symboler) >= 400:          # sanity: S&P 500 skal ha ~500
                print(f"   Wikipedia S&P 500: {len(symboler)} tickere.")
                return symboler
            print(f"   Wikipedia ga bare {len(symboler)} symboler – prøver igjen ...")
        except Exception as feil:  # noqa: BLE001
            ventetid = 3 * (forsok + 1)
            print(f"   Wikipedia feilet ({feil}). Prøver igjen om {ventetid}s ...")
            time.sleep(ventetid)
    return []



# ---------------------------------------------------------------------------
# Hovedfunksjon: den komplette lista
# ---------------------------------------------------------------------------
def hent_alle_tickere(bors: "konfig.Bors" = konfig.OSLO_BORS, oppdater: bool = True) -> list[str]:
    """
    Returnerer hele universet for én børs.

    Oslo Børs = (Euronext-lista) + (dine manuelle ekstra fra univers.txt).
    S&P 500   = (Wikipedia-lista).  Begge lagres til børsens egen cache-fil.

    oppdater=True  -> hent fersk liste fra nett og lagre den som cache.
    oppdater=False -> bruk den sist lagrede cache-lista (rask, uten nett).
    """
    ferske: list[str] = []
    if oppdater:
        if bors.kind == "sp500":
            print("Henter fersk S&P 500-liste fra Wikipedia ...")
            ferske = hent_sp500_fra_wikipedia()
        else:
            print("Henter fersk Oslo Børs-liste fra Euronext ...")
            ferske = hent_fra_euronext()

    if ferske:
        # Fjern kjente "problem-tickere" (konfig.UTELUKK_TICKERE) FØR vi lagrer,
        # slik at selve cache-fila alltid er ren.
        ferske = [t for t in ferske if t not in konfig.UTELUKK_TICKERE]
        _skriv_fil(
            bors.univers_cache_fil, ferske,
            f"# {bors.navn}-tickere hentet AUTOMATISK.\n"
            "# Denne fila oppdateres av roboten – rediger den ikke for hånd.\n"
            "# Vil du legge til egne aksjer? Bruk data/univers.txt i stedet.",
        )
        print(f"   Lagret {len(ferske)} tickere til {bors.univers_cache_fil}.")
    else:
        ferske = les_cache(bors.univers_cache_fil)   # fallback til siste kjente liste
        if ferske:
            print(f"   Bruker lagret {bors.navn}-liste ({len(ferske)} tickere) som fallback.")

    alle = set(ferske)
    if bors.bruk_manuelle:
        manuelle = les_manuelle()
        if manuelle:
            print(f"   + {len(manuelle)} manuelle ekstra tickere fra {konfig.UNIVERS_FIL}.")
            alle |= set(manuelle)

    # Utelukk igjen på det endelige settet (dekker cache-fallback og manuelle).
    return sorted(alle - konfig.UTELUKK_TICKERE)
