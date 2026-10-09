"""
aksjeinfo.py – henter og lagrer aksjer utestående + sektor/industri for HELE
universet, slik at nettsiden kan LESE tallene fra fil i stedet for å spørre Yahoo
ved hver visning.

Hvorfor dette trengs:
  Yahoo rate-limiter delte skyserver-IP-er (som Streamlit Community Cloud) hardt.
  Da nettsiden prøvde å hente shares/MCAP for ~280 aksjer ved render, fikk bare
  de første par aksjene svar – resten ble tomme. Lokalt (ren hjemme-IP) gikk det
  fint, derfor «virket det lokalt, men ikke online».

Løsningen er den SAMME som for kursene: natt-roboten henter én gang i ro og mak
(med små pauser mellom hvert kall), lagrer til en JSON-fil som committes til
GitHub, og nettsiden leser bare fila. Null Yahoo-kall ved visning = ingen
rate-limiting.

Filformat (JSON):
    {
      "EQNR.OL": {"utestaende": 2980000000.0, "sektor": "Energy", "industri": "Oil & Gas"},
      ...
    }

Henting er tålmodig og idempotent:
  • Eksisterende fil leses først – aksjer vi allerede har beholdes hvis et nytt
    forsøk feiler (vi mister ALDRI gode tall på en dårlig nettverksdag).
  • Små pauser + noen få forsøk per ticker holder oss under rate-limit-grensa.
"""
from __future__ import annotations

import json
import os
import time

from . import fundamenta


def last(sti: str) -> dict[str, dict]:
    """Leser aksjeinfo-fila. Tom dict hvis fila ikke finnes eller er ugyldig."""
    if not sti or not os.path.exists(sti):
        return {}
    try:
        with open(sti, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _hent_en(ticker: str, forsok: int = 3, pause: float = 1.0) -> dict | None:
    """Henter aksjeinfo for ÉN ticker med noen få forsøk. None hvis alt feiler."""
    for n in range(forsok):
        try:
            info = fundamenta.hent_aksjeinfo(ticker) or {}
            if info.get("utestaende") or info.get("sektor") or info.get("industri"):
                return {
                    "utestaende": info.get("utestaende"),
                    "sektor": info.get("sektor"),
                    "industri": info.get("industri"),
                }
        except Exception:
            pass
        if n < forsok - 1:
            time.sleep(pause * (n + 1))   # økende ventetid mellom forsøk
    return None


def oppdater(sti: str, tickere: list[str], pause: float = 0.4) -> dict[str, dict]:
    """Henter aksjeinfo for alle tickere og lagrer til `sti`. Returnerer fullt oppslag.

    Beholder eksisterende verdier hvis et nytt forsøk feiler, så en dårlig
    nettverksdag aldri tømmer gode tall. Liten pause mellom hvert kall holder oss
    under Yahoos rate-limit.
    """
    data = last(sti)
    tickere = [str(t).strip().upper() for t in (tickere or []) if str(t).strip()]
    totalt = len(tickere)

    for i, t in enumerate(tickere, 1):
        ny = _hent_en(t)
        if ny is not None:
            data[t] = ny          # overskriv kun med et gyldig svar
        if i % 25 == 0 or i == totalt:
            print(f"   aksjeinfo: {i}/{totalt} hentet …")
            _lagre(sti, data)     # lagre underveis – delvis fremgang går aldri tapt
        time.sleep(pause)

    _lagre(sti, data)
    return data


def _lagre(sti: str, data: dict) -> None:
    """Skriver aksjeinfo-fila (lager mappa om nødvendig)."""
    mappe = os.path.dirname(sti)
    if mappe:
        os.makedirs(mappe, exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=True)
