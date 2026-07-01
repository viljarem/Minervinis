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
# Hovedfunksjon: den komplette lista
# ---------------------------------------------------------------------------
def hent_alle_tickere(oppdater: bool = True) -> list[str]:
    """
    Returnerer hele universet = (Oslo Børs) + (dine manuelle ekstra).

    oppdater=True  -> hent fersk liste fra Euronext og lagre den som cache.
    oppdater=False -> bruk den sist lagrede cache-lista (rask, uten nett).
    """
    oslo: list[str] = []
    if oppdater:
        print("Henter fersk Oslo Børs-liste fra Euronext ...")
        oslo = hent_fra_euronext()

    if oslo:
        _skriv_fil(
            konfig.OSLOBORS_CACHE_FIL, oslo,
            "# Oslo Børs-tickere hentet AUTOMATISK fra Euronext.\n"
            "# Denne fila oppdateres av roboten – rediger den ikke for hånd.\n"
            "# Vil du legge til egne aksjer? Bruk data/univers.txt i stedet.",
        )
        print(f"   Lagret {len(oslo)} Oslo Børs-tickere til {konfig.OSLOBORS_CACHE_FIL}.")
    else:
        oslo = les_cache()  # fallback til siste kjente komplette liste
        if oslo:
            print(f"   Bruker lagret Oslo Børs-liste ({len(oslo)} tickere) som fallback.")

    manuelle = les_manuelle()
    if manuelle:
        print(f"   + {len(manuelle)} manuelle ekstra tickere fra {konfig.UNIVERS_FIL}.")

    return sorted(set(oslo) | set(manuelle))
