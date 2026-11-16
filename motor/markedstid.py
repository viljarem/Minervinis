"""
markedstid.py – er børsen åpen akkurat nå?

Brukes til å vise LIVE P&L/R i journalen automatisk i åpningstid, og falle
tilbake til siste sluttkurs utenom. Ren funksjon uten nett/IO, så den er lett
å teste. Helligdager tas ikke hensyn til (de færreste; live-kurs faller uansett
tilbake til sluttkurs hvis Yahoo ikke gir ferske tall).

Åpningstider (lokal børstid):
  * Oslo Børs:  09:00–16:20 (Europe/Oslo), mandag–fredag.
  * S&P 500:    09:30–16:00 (America/New_York), mandag–fredag.
"""
from __future__ import annotations

import pandas as pd

# kind → (tidssone, åpne (t, m), stenge (t, m))
_APNINGSTID = {
    "oslo":  ("Europe/Oslo",        (9, 0),  (16, 20)),
    "sp500": ("America/New_York",   (9, 30), (16, 0)),
}


def bors_apen(kind: str, naa: pd.Timestamp | None = None) -> bool:
    """True hvis børsen (kind='oslo'/'sp500') er åpen på tidspunktet `naa`.

    `naa` kan være tz-aware eller naiv (tolkes da som børsens lokaltid). Lar vi
    den stå tom, brukes nåtid. Ukjent kind → False (trygt: ingen live).
    """
    spec = _APNINGSTID.get(kind)
    if spec is None:
        return False
    tz, (ah, am), (sh, sm) = spec
    if naa is None:
        naa = pd.Timestamp.now(tz=tz)
    else:
        naa = pd.Timestamp(naa)
        naa = naa.tz_convert(tz) if naa.tzinfo is not None else naa.tz_localize(tz)
    if naa.weekday() >= 5:               # lør/søn
        return False
    minutter = naa.hour * 60 + naa.minute
    return (ah * 60 + am) <= minutter <= (sh * 60 + sm)
