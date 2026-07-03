"""
vcp.py – Volatility Contraction Pattern ("innsnevrings-mønster").

Idé (Minervini): før et mulig utbrudd strammer kursen seg gjerne inn i stadig
mindre svingninger – som en fjær som trykkes sammen. Vi leter etter en slik
"base", finner PIVOT (kjøpsnivået = toppen av den strammeste innsnevringen) og
STOP (bunnen av basen), og vurderer om det har skjedd et brudd opp gjennom pivot.

Alle tallgrenser hentes fra konfig.py, så de er lette å justere.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import konfig


def _tomt_resultat() -> dict:
    """Returneres når vi ikke finner et gyldig VCP-mønster."""
    return {
        "har_vcp": False,
        "pivot": np.nan,
        "stop": np.nan,
        "avstand": np.nan,        # hvor langt under pivot kursen er (positivt = under)
        "kontraksjoner": [],       # liste med dybder i prosent
        "antall": 0,
        "punkter": [],             # svingpunkter (topp/bunn) til chartet
        "volumuttorking": False,
        "volum_ratio": np.nan,
        "kvalitet": 0,
        "gyldig": False,
    }


def _svingpunkter(hoy: np.ndarray, lav: np.ndarray, vindu: int):
    """
    Finner lokale topper og bunner. Et punkt er en topp hvis High der er høyest
    innenfor +/- 'vindu' dager, og en bunn hvis Low der er lavest.
    """
    n = len(hoy)
    topper, bunner = [], []
    for i in range(vindu, n - vindu):
        if hoy[i] == hoy[i - vindu:i + vindu + 1].max():
            topper.append(i)
        if lav[i] == lav[i - vindu:i + vindu + 1].min():
            bunner.append(i)
    return topper, bunner


def _alternerende(hoy: np.ndarray, lav: np.ndarray, topper: list, bunner: list) -> list:
    """Fletter topper/bunner til en ren vekslende topp→bunn→topp-sekvens.

    Når to like typer følger etter hverandre, beholdes den mest ekstreme (høyeste
    High / laveste Low). Da unngår vi falske, grunne kontraksjoner og får en mer
    presis pivot. Returnerer liste av (type, indeks) der type ∈ {"topp", "bunn"}.
    """
    alle = [("topp", i) for i in topper] + [("bunn", i) for i in bunner]
    alle.sort(key=lambda x: x[1])
    renset: list = []
    for typ, idx in alle:
        if renset and renset[-1][0] == typ:
            _, forrige = renset[-1]
            if typ == "topp" and hoy[idx] > hoy[forrige]:
                renset[-1] = (typ, idx)
            elif typ == "bunn" and lav[idx] < lav[forrige]:
                renset[-1] = (typ, idx)
        else:
            renset.append((typ, idx))
    return renset


def _bygg_kontraksjoner(hoy: np.ndarray, lav: np.ndarray, sekvens: list) -> list:
    """Bygger kontraksjoner (topp→påfølgende bunn) fra en vekslende sekvens.

    Hver kontraksjon = fall fra en lokal topp (High) ned til neste lokale bunn (Low),
    målt i prosent – klassisk Minervini peak-to-trough.
    """
    kontr = []
    for k in range(len(sekvens) - 1):
        typ, idx = sekvens[k]
        neste_typ, neste_idx = sekvens[k + 1]
        if typ != "topp" or neste_typ != "bunn":
            continue
        topp = float(hoy[idx])
        bunn = float(lav[neste_idx])
        if topp <= 0:
            continue
        kontr.append({"topp_i": idx, "topp": topp, "bunn_i": neste_idx,
                      "bunn": bunn, "dyp": (topp - bunn) / topp})
    return kontr


def finn_vcp(df: pd.DataFrame) -> dict:
    """Analyserer de siste ~120 dagene og returnerer VCP-detaljer (se _tomt_resultat)."""
    d = df.dropna(subset=["Close"]).copy()
    if len(d) < konfig.VCP_MIN_DAGER:
        return _tomt_resultat()

    base = d.iloc[-konfig.VCP_LOOKBACK:] if len(d) > konfig.VCP_LOOKBACK else d
    hoy = base["High"].to_numpy()
    lav = base["Low"].to_numpy()
    close = base["Close"].to_numpy()
    vol = base["Volume"].to_numpy()

    topper, bunner = _svingpunkter(hoy, lav, konfig.VCP_SVING_VINDU)
    if len(topper) < konfig.VCP_MIN_KONTR or not bunner:
        return _tomt_resultat()

    # Flett topper/bunner til en ren vekslende topp→bunn→topp-sekvens, og bygg
    # kontraksjoner (topp→neste bunn). Fjern småstøy under terskelen.
    sekvens = _alternerende(hoy, lav, topper, bunner)
    kontr = [k for k in _bygg_kontraksjoner(hoy, lav, sekvens)
             if k["dyp"] >= konfig.VCP_STOY_GRENSE]
    if len(kontr) < konfig.VCP_MIN_KONTR:
        return _tomt_resultat()

    # Behold den nyeste serien der hver tidligere kontraksjon er dypere enn den
    # neste (med litt toleranse) – altså stadig strammere innsnevring.
    serie = [kontr[-1]]
    for i in range(len(kontr) - 2, -1, -1):
        tidligere, nyere = kontr[i], serie[0]
        if tidligere["dyp"] >= nyere["dyp"] / konfig.VCP_TOLERANSE:
            serie.insert(0, tidligere)
        else:
            break
    serie = serie[-konfig.VCP_MAKS_KONTR:]

    if len(serie) < konfig.VCP_MIN_KONTR:
        return _tomt_resultat()
    if serie[0]["dyp"] > konfig.VCP_FORSTE_MAKS:      # dypeste for dyp
        return _tomt_resultat()
    if serie[-1]["dyp"] > konfig.VCP_SISTE_MAKS:      # siste ikke stram nok
        return _tomt_resultat()

    pivot = float(serie[-1]["topp"])
    start_i = serie[0]["topp_i"]
    stop = float(lav[start_i:].min())
    siste_close = float(close[-1])
    avstand = (pivot - siste_close) / pivot   # positiv = under pivot

    # Volumuttørking: mindre volum i andre halvdel av basen enn i første.
    basevol = vol[start_i:]
    m = len(basevol) // 2
    if m > 0 and basevol[:m].mean() > 0:
        v1, v2 = basevol[:m].mean(), basevol[m:].mean()
        volum_ratio = float(v2 / v1)
        uttorking = v2 < v1
    else:
        volum_ratio, uttorking = np.nan, False

    kvalitet = _kvalitetsscore(serie, uttorking, avstand)
    gyldig = avstand <= konfig.VCP_MAKS_UNDER_PIVOT   # maks 12 % under pivot = "klar"

    # Svingpunktene i kontraksjonsserien (topp→bunn→topp ...) til chartet.
    sving = {}
    for k in serie:
        sving[k["topp_i"]] = float(k["topp"])
        sving[k["bunn_i"]] = float(k["bunn"])
    punkter = [
        {"dato": pd.Timestamp(base.index[i]).date().isoformat(), "pris": round(pris, 4)}
        for i, pris in sorted(sving.items())
    ]

    return {
        "har_vcp": True,
        "pivot": pivot,
        "stop": stop,
        "avstand": float(avstand),
        "kontraksjoner": [round(k["dyp"] * 100, 1) for k in serie],
        "antall": len(serie),
        "punkter": punkter,
        "volumuttorking": bool(uttorking),
        "volum_ratio": volum_ratio,
        "kvalitet": kvalitet,
        "gyldig": bool(gyldig),
    }


def _kvalitetsscore(serie: list, uttorking: bool, avstand: float) -> int:
    """Kvalitetsscore 0–100: flere kontraksjoner, volumuttørking, stram siste og nær pivot = høyere."""
    score = 0.0
    score += min(len(serie), 4) / 4 * 30                                   # opptil 30: antall kontraksjoner
    score += 25 if uttorking else 0                                        # 25: volumuttørking
    stramhet = max(0.0, (konfig.VCP_SISTE_MAKS - serie[-1]["dyp"]) / konfig.VCP_SISTE_MAKS)
    score += stramhet * 25                                                 # opptil 25: stram siste kontraksjon
    naerhet = max(0.0, 1 - max(avstand, 0) / konfig.VCP_MAKS_UNDER_PIVOT)
    score += naerhet * 20                                                  # opptil 20: nær pivot
    return int(round(min(100, max(0, score))))


def bruddstatus(df: pd.DataFrame, pivot: float) -> dict:
    """
    Vurderer om kursen har brutt opp gjennom pivot, og hvor "ferskt"/sterkt bruddet er.

    Statuser:
      🟢 Bekreftet brudd     – krysset opp <= 5 dager siden på høyt volum
      🟡 Brudd uten volum    – krysset, men uten volumbekreftelse
      🔵 Forlenget           – godt over pivot / for lenge siden (ikke jag)
      ⚪ Klar, venter        – fortsatt under pivot
    """
    resultat = {"emoji": "⚪", "tekst": "Ingen pivot", "bruddindeks": None, "bruddato": None}
    if pivot is None or (isinstance(pivot, float) and np.isnan(pivot)):
        return resultat

    d = df.dropna(subset=["Close"])
    close = d["Close"].to_numpy()
    vol = d["Volume"].to_numpy()
    # Snittvolum av de FORUTGÅENDE dagene (shift 1 = ekskluder dagen selv),
    # slik at et brudd måles mot normalvolumet før selve bruddet.
    snitt50 = d["Volume"].rolling(50, min_periods=10).mean().shift(1).to_numpy()
    n = len(close)
    siste = close[-1]

    if siste < pivot:
        resultat.update(emoji="⚪", tekst="Klar, venter på brudd")
        return resultat

    # Finn siste dag kursen krysset OPP gjennom pivot.
    kryss = None
    for i in range(n - 1, 0, -1):
        if close[i] >= pivot and close[i - 1] < pivot:
            kryss = i
            break

    if kryss is None:
        resultat.update(emoji="🔵", tekst="Forlenget (over pivot)")
        return resultat

    dager_siden = (n - 1) - kryss
    resultat["bruddindeks"] = int(kryss)
    resultat["bruddato"] = d.index[kryss]

    if siste > pivot * (1 + konfig.BRUDD_FORLENGET) or dager_siden > konfig.BRUDD_FERSK_DAGER:
        resultat.update(emoji="🔵", tekst=f"Forlenget ({dager_siden} d siden brudd)")
        return resultat

    snitt = snitt50[kryss]
    volum_ok = (not np.isnan(snitt)) and vol[kryss] >= konfig.BRUDD_VOLUM_FAKTOR * snitt
    if volum_ok:
        resultat.update(emoji="🟢", tekst=f"Bekreftet brudd ({dager_siden} d siden)")
    else:
        resultat.update(emoji="🟡", tekst=f"Brudd uten volum ({dager_siden} d siden)")
    return resultat


def _desimaler(pris: float) -> int:
    """Passe antall desimaler ut fra kursnivå (så pivot vises pent)."""
    if pris >= 100:
        return 1
    if pris >= 1:
        return 2
    return 3


def historiske_brudd(df: pd.DataFrame, vindu: int | None = None) -> list:
    """Finner TIDLIGERE volumbekreftede utbrudd gjennom motstand.

    Et utbrudd = dagen kursen lukker over den forutgående N-dagers toppen
    (motstanden), på volum >= BRUDD_VOLUM_FAKTOR x snittet av de forutgående
    50 dagene. For hvert utbrudd får vi datoen, pivot-nivået (motstanden som
    ble brutt) og hvor "basen" startet – slik at chartet kan tegne en kort
    pivotlinje fram til bruddet.

    Returnerer liste av {dato, base_start, pivot, pris}, eldste først.
    """
    vindu = vindu or konfig.HIST_BRUDD_VINDU
    d = df.dropna(subset=["Close"])
    if len(d) < vindu + 55:
        return []

    close = d["Close"]
    motstand = d["High"].rolling(vindu).max().shift(1)
    snittvol = d["Volume"].rolling(50, min_periods=10).mean().shift(1)
    kryss = (close > motstand) & (close.shift(1) <= motstand.shift(1))
    volum_ok = d["Volume"] >= konfig.BRUDD_VOLUM_FAKTOR * snittvol
    er_brudd = (kryss & volum_ok).to_numpy()

    idx = d.index
    motstand_v = motstand.to_numpy()
    close_v = close.to_numpy()

    resultater: list = []
    sist = -10 ** 9
    for i in range(len(d)):
        if not er_brudd[i] or (i - sist) < vindu:
            continue
        niva = motstand_v[i]
        if not np.isfinite(niva):
            continue
        base_i = max(0, i - vindu)
        resultater.append({
            "dato": idx[i],
            "base_start": idx[base_i],
            "pivot": round(float(niva), _desimaler(float(niva))),
            "pris": float(close_v[i]),
        })
        sist = i
    return resultater


def ferskt_brudd(df: pd.DataFrame) -> dict | None:
    """Fanger et NYLIG volumbrudd gjennom motstand – uavhengig av VCP-mønster.

    Minervini: et gyldig kjøpssignal er kursen som bryter opp gjennom motstand
    på høyt volum, SELV om vi ikke rakk å se en perfekt VCP-innsnevring først.
    (Etter et brudd "forsvinner" ofte VCP-basen, og da mister vi ellers signalet.)

    Bruker historiske_brudd() og returnerer det SISTE bruddet hvis det er ferskt
    (<= BRUDD_FERSK_DAGER handelsdager siden) og kursen ikke er blitt forlenget.
    Returnerer en status-dict på samme form som bruddstatus(), eller None.
    """
    brudd = historiske_brudd(df)
    if not brudd:
        return None

    d = df.dropna(subset=["Close"])
    b = brudd[-1]
    try:
        pos = d.index.get_loc(b["dato"])
    except KeyError:
        return None

    dager_siden = (len(d) - 1) - int(pos)
    if dager_siden > konfig.BRUDD_FERSK_DAGER:
        return None                      # for lenge siden – ikke ferskt lenger

    pivot = float(b["pivot"])
    siste_close = float(d["Close"].iloc[-1])
    if siste_close > pivot * (1 + konfig.BRUDD_FORLENGET):
        return None                      # blitt forlenget – ikke jag

    # Stop = laveste Low i basen fram til bruddet
    base = d.loc[b["base_start"]:b["dato"]]
    stop = float(base["Low"].min()) if not base.empty else np.nan

    return {
        "emoji": "🟢",
        "tekst": f"Bekreftet brudd ({dager_siden} d siden)",
        "bruddindeks": int(pos),
        "bruddato": b["dato"],
        "pivot": pivot,
        "stop": round(stop, _desimaler(stop)) if np.isfinite(stop) else np.nan,
        "kilde": "motstand",
    }


# ---------------------------------------------------------------------------
# Volum rundt bruddet (RVol-signatur) + volumforløp til lista
# ---------------------------------------------------------------------------
def _rvol_kolonne(df: pd.DataFrame) -> pd.Series:
    """Relativt volum per dag: dagens volum / snittet av de 50 FORUTGÅENDE dagene.

    1,0 = helt normalt, >1 = mer handel enn vanlig. Samme definisjon som ellers
    i appen (shift(1) så dagen selv ikke er med i snittet den måles mot).
    """
    d = df.dropna(subset=["Close"])
    snitt50 = d["Volume"].rolling(50, min_periods=10).mean().shift(1)
    rvol = d["Volume"] / snitt50
    return rvol.replace([np.inf, -np.inf], np.nan)


def volum_signatur(df: pd.DataFrame, bruddato, dager_for: int = 2,
                   dager_etter: int = 2) -> list[dict]:
    """Relativt volum for dagene rundt et brudd: dag −dager_for … +dager_etter.

    Minervini vil se at volumet TØRKER INN i basen og så EKSPLODERER på selve
    bruddet (dag 0). Returnerer en liste [{offset, dato, rvol, er_brudd}] – ett
    element per dag som faktisk finnes. Dager som ikke er kommet ennå (framtid
    for et ferskt brudd) utelates rett og slett. Tom liste hvis ingen bruddato.
    """
    if bruddato is None:
        return []
    d = df.dropna(subset=["Close"])
    try:
        pos = int(d.index.get_loc(pd.Timestamp(bruddato)))
    except (KeyError, TypeError):
        return []
    rvol = _rvol_kolonne(df)
    ut: list[dict] = []
    for off in range(-dager_for, dager_etter + 1):
        i = pos + off
        if i < 0 or i >= len(d):
            continue
        rv = rvol.iloc[i]
        ut.append({
            "offset": off,
            "dato": pd.Timestamp(d.index[i]).date().isoformat(),
            "rvol": None if pd.isna(rv) else round(float(rv), 2),
            "er_brudd": off == 0,
        })
    return ut


def rvol_serie(df: pd.DataFrame, dager: int = 10) -> list[float]:
    """Relativt volum for de siste `dager` dagene (til mini-sparklinen i lista).

    Viser volumforløpet – inntørking så sprut – på hver rad. NaN der snittet ennå
    ikke kan regnes (helt i starten av historikken).
    """
    rvol = _rvol_kolonne(df).iloc[-dager:]
    return [None if pd.isna(x) else round(float(x), 2) for x in rvol.tolist()]


