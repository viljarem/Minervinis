"""
data.py – henter kurser fra Yahoo Finance (biblioteket yfinance), renser dem og
lagrer alt i én parquet-fil.

Parquet er bare et komprimert tabell-format – tenk på det som et Excel-ark som er
raskt for datamaskinen å lese og skrive.

Dataene lagres i "langt format": én rad per (dato, ticker), med kolonnene
Open/High/Low/Close/Volume. Det gjør det enkelt å legge til nye dager senere.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

from . import konfig, univers

KOLONNER = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# Univers (lista over tickere)
# ---------------------------------------------------------------------------
def les_univers(bors: "konfig.Bors" = konfig.OSLO_BORS, oppdater: bool = False) -> list[str]:
    """
    Henter hele tickerlista for én børs.
    oppdater=True henter fersk liste fra nett; False bruker lagret cache.
    """
    return univers.hent_alle_tickere(bors, oppdater=oppdater)


# ---------------------------------------------------------------------------
# Nedlasting fra Yahoo
# ---------------------------------------------------------------------------
def _til_langt_format(rå: pd.DataFrame, tickere: list[str]) -> pd.DataFrame:
    """Gjør Yahoo sitt "brede" format om til langt format (én rad per dato+ticker)."""
    rammer = []
    if isinstance(rå.columns, pd.MultiIndex):
        tilgjengelige = set(rå.columns.get_level_values(0))
        for t in tickere:
            if t not in tilgjengelige:
                continue
            del_ = rå[t].copy()
            del_["Ticker"] = t
            rammer.append(del_)
    else:
        # yfinance returnerer flatt format når man ber om bare én ticker
        del_ = rå.copy()
        del_["Ticker"] = tickere[0]
        rammer.append(del_)

    if not rammer:
        return pd.DataFrame(columns=KOLONNER)

    ut = pd.concat(rammer).reset_index()
    if "Datetime" in ut.columns:
        ut = ut.rename(columns={"Datetime": "Date"})
    for kol in ["Open", "High", "Low", "Close", "Volume"]:
        if kol not in ut.columns:
            ut[kol] = np.nan
    return ut[KOLONNER]


def _last_ned(tickere: list[str], periode: str) -> pd.DataFrame:
    """Laster ned én bunt med tickere. Prøver på nytt (med økende ventetid) ved feil."""
    for forsok in range(4):
        try:
            rå = yf.download(
                tickers=tickere,
                period=periode,
                auto_adjust=True,      # justerer for utbytte og splitt
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if rå is None or len(rå) == 0:
                return pd.DataFrame(columns=KOLONNER)
            return _til_langt_format(rå, tickere)
        except Exception as feil:  # noqa: BLE001 – vi vil fange alt og prøve igjen
            ventetid = 5 * (forsok + 1)
            print(f"   Yahoo feilet ({feil}). Prøver igjen om {ventetid}s ...")
            time.sleep(ventetid)
    print("   Ga opp denne bunten etter flere forsøk.")
    return pd.DataFrame(columns=KOLONNER)


def hent_priser(tickere: list[str], periode: str, buntstorrelse: int = 40) -> pd.DataFrame:
    """Henter kurser for mange tickere, i mindre bunter så Yahoo ikke overbelastes."""
    deler = []
    for i in range(0, len(tickere), buntstorrelse):
        bunt = tickere[i:i + buntstorrelse]
        print(f"   Henter {i + 1}-{i + len(bunt)} av {len(tickere)} ...")
        del_ = _last_ned(bunt, periode)
        if not del_.empty:
            deler.append(del_)
        time.sleep(1)  # liten pause av høflighet mot Yahoo
    if not deler:
        return pd.DataFrame(columns=KOLONNER)
    return pd.concat(deler, ignore_index=True)


# ---------------------------------------------------------------------------
# Rensing
# ---------------------------------------------------------------------------
def rens(df: pd.DataFrame) -> pd.DataFrame:
    """Fjerner ugyldige rader og retter åpenbare feil i OHLC (Open/High/Low/Close)."""
    if df.empty:
        return df
    df = df.dropna(subset=["Close"]).copy()
    df = df[df["Close"] > 0]
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    # High skal være høyest og Low lavest av de fire prisene:
    ohlc = df[["Open", "High", "Low", "Close"]]
    df["High"] = ohlc.max(axis=1)
    df["Low"] = ohlc.min(axis=1)
    df["Volume"] = df["Volume"].fillna(0)
    return df


# ---------------------------------------------------------------------------
# Lagring, lesing og fletting av parquet-fila
# ---------------------------------------------------------------------------
def les_priser(sti: str = konfig.PRISER_FIL) -> pd.DataFrame:
    """Leser hele kurshistorikken fra fil (tom tabell hvis fila ikke finnes ennå)."""
    if os.path.exists(sti):
        df = pd.read_parquet(sti)
        df["Date"] = pd.to_datetime(df["Date"])
        return df
    return pd.DataFrame(columns=KOLONNER)


def lagre_priser(df: pd.DataFrame, sti: str = konfig.PRISER_FIL) -> None:
    """Lagrer hele kurshistorikken til fil."""
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    df.to_parquet(sti, index=False)


def skriv_oppdateringstid(sti: str = konfig.SIST_OPPDATERT_FIL) -> None:
    """Lagrer NÅR roboten sist hentet data – i NORSK tid – i en liten metadatafil.

    Dette er den pålitelige «Sist hentet»-tiden. (Vi kan ikke stole på selve
    fil-tidene på serveren, for Streamlit Cloud skriver ny fil-tid hver gang den
    henter koden på nytt – altså ved utrulling, ikke når roboten faktisk kjørte.)
    """
    tid = pd.Timestamp.now(tz="Europe/Oslo")
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump({"sist_oppdatert": tid.isoformat()}, f)


def les_oppdateringstid(sti: str = konfig.SIST_OPPDATERT_FIL) -> pd.Timestamp | None:
    """Leser tidspunktet roboten sist hentet data (tidssone-bevisst). None hvis mangler."""
    try:
        if os.path.exists(sti):
            with open(sti, encoding="utf-8") as f:
                raw = json.load(f)
            return pd.Timestamp(raw["sist_oppdatert"])
    except Exception:
        return None
    return None


def flett(gammel: pd.DataFrame, ny: pd.DataFrame) -> pd.DataFrame:
    """Slår sammen gammel historikk med nye dager. Nyeste tall vinner ved dublett."""
    if gammel.empty:
        return ny.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    if ny.empty:
        return gammel
    alt = pd.concat([gammel, ny], ignore_index=True)
    alt["Date"] = pd.to_datetime(alt["Date"])
    alt = alt.sort_values(["Ticker", "Date"])
    alt = alt.drop_duplicates(subset=["Ticker", "Date"], keep="last")
    return alt.reset_index(drop=True)


def flett_flere(deler: list[pd.DataFrame]) -> pd.DataFrame:
    """Fletter flere tabeller til én. Ved dublett (samme ticker+dato) vinner den siste."""
    reelle = [d for d in deler if d is not None and not d.empty]
    if not reelle:
        return pd.DataFrame(columns=KOLONNER)
    alt = pd.concat(reelle, ignore_index=True)
    alt["Date"] = pd.to_datetime(alt["Date"])
    alt = alt.sort_values(["Ticker", "Date"])
    alt = alt.drop_duplicates(subset=["Ticker", "Date"], keep="last")
    return alt.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Hent én tickers historikk som en pen tidsserie
# ---------------------------------------------------------------------------
def serie_for(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Plukker ut én tickers rader, sortert etter dato med dato som indeks."""
    d = df[df["Ticker"] == ticker].copy()
    if d.empty:
        return d
    d["Date"] = pd.to_datetime(d["Date"])
    d = d.sort_values("Date").set_index("Date")
    return d[["Open", "High", "Low", "Close", "Volume"]]


# ---------------------------------------------------------------------------
# Hovedfunksjon roboten bruker
# ---------------------------------------------------------------------------
def hent_og_oppdater(bors: "konfig.Bors" = konfig.OSLO_BORS) -> pd.DataFrame:
    """
    Henter ferske kurser og oppdaterer parquet-fila for én børs.

    Skiller mellom to grupper, slik at systemet er selvreparerende:
      - NYE tickere (som ikke finnes i fila ennå) -> full ~10 års historikk.
        Dette gjelder både første kjøring OG når det noteres nye selskaper,
        eller når du legger til egne tickere.
      - KJENTE tickere (som allerede har data) -> bare de siste dagene (1 mnd).

    Til slutt lagres og returneres hele den oppdaterte historikken for børsen.
    """
    tickere = les_univers(bors, oppdater=True)
    if bors.benchmark and bors.benchmark not in tickere:
        tickere = tickere + [bors.benchmark]

    eksisterende = les_priser(bors.priser_fil)
    kjente = set(eksisterende["Ticker"].unique()) if not eksisterende.empty else set()
    nye_tickere = [t for t in tickere if t not in kjente]
    kjente_tickere = [t for t in tickere if t in kjente]

    deler = [eksisterende] if not eksisterende.empty else []

    if nye_tickere:
        print(f"Henter FULL historikk ({konfig.HISTORIKK_AAR}y) for {len(nye_tickere)} nye tickere ...")
        deler.append(rens(hent_priser(nye_tickere, f"{konfig.HISTORIKK_AAR}y")))

    if kjente_tickere:
        print(f"Henter siste dager (1mo) for {len(kjente_tickere)} kjente tickere ...")
        deler.append(rens(hent_priser(kjente_tickere, "1mo")))

    flettet = deler[0] if len(deler) == 1 else flett_flere(deler)
    lagre_priser(flettet, bors.priser_fil)
    skriv_oppdateringstid(bors.sist_oppdatert_fil)
    print(f"Lagret {len(flettet):,} rader for {flettet['Ticker'].nunique()} tickere til {bors.priser_fil}.")
    return flettet


def hent_live(ticker: str, periode: str = "2y") -> pd.DataFrame:
    """Henter én ticker direkte (brukes av søkefeltet for aksjer utenfor universet)."""
    ticker = ticker.strip().upper()
    df = rens(_last_ned([ticker], periode))
    return serie_for(df, ticker)


# ---------------------------------------------------------------------------
# Live-kurser + projisert relativt volum (KUN til visning – rører aldri fila)
# ---------------------------------------------------------------------------
# Typisk andel av en dags volum som er handlet innen et gitt klokkeslett på Oslo
# Børs. Volum er U-formet – tyngst rundt åpning (09:00) og mot slutten (~16:25) –
# så en rett linje ville bommet. Tallene er anslag, men fanger formen godt nok.
# Minutter fra 09:00  ->  andel av dagsvolum (0–1).
_VOLUMKURVE_MIN = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390, 420, 445]
_VOLUMKURVE_AND = [0.0, 0.12, 0.21, 0.29, 0.36, 0.42, 0.48, 0.54,
                   0.60, 0.66, 0.72, 0.78, 0.84, 0.90, 0.95, 1.0]


def dagsandel(naa) -> float:
    """Typisk andel (0–1) av dagens volum som er handlet innen tidspunktet `naa`.

    Brukes til å projisere dagens volum-så-langt til et helt døgn, slik at «live»
    relativt volum blir meningsfullt også tidlig på dagen (da rått volum ellers
    alltid ser lavt ut). Utenfor børstid returneres 1.0 (økta er komplett).
    `naa` er en tidssone-bevisst Timestamp i norsk tid.
    """
    aapen = naa.replace(hour=9, minute=0, second=0, microsecond=0)
    minutter = (naa - aapen).total_seconds() / 60.0
    if minutter <= 0 or minutter >= _VOLUMKURVE_MIN[-1]:
        return 1.0
    return float(np.interp(minutter, _VOLUMKURVE_MIN, _VOLUMKURVE_AND))


def live_rvol(volum, snitt50, naa) -> float:
    """Projisert relativt volum for inneværende dag, målt mot 50-dagers snittvolum.

    1,0 = på vei mot et helt normalt dagsvolum · 2,0 = dobbelt så travelt som
    normalt. Vi deler dagens volum-så-langt på den TYPISKE andelen som pleier å
    være handlet på dette klokkeslettet (se dagsandel), så tallet ikke blir
    kunstig lavt om morgenen. Fortsatt et anslag – mest presist utover dagen.
    Returnerer NaN når vi mangler tall.
    """
    try:
        volum = float(volum)
        snitt50 = float(snitt50)
    except (TypeError, ValueError):
        return float("nan")
    if pd.isna(volum) or pd.isna(snitt50) or snitt50 <= 0 or volum <= 0:
        return float("nan")
    andel = max(dagsandel(naa), 0.05)          # gulv så vi ikke deler på ~0 ved åpning
    return (volum / andel) / snitt50


def hent_sanntid(tickere: list[str]) -> dict[str, dict]:
    """Henter DAGENS siste kurs OG volum (Yahoo, ca. 15 min forsinket) – KUN til visning.

    VIKTIG: dette er helt adskilt fra kurshistorikken. Funksjonen rører ALDRI
    parquet-fila og lagrer ingenting – den returnerer bare
    {ticker: {"pris": .., "volum": ..}} som appen kan vise ved siden av. Slik kan
    vi se hvem som nærmer seg pivot – og om det er volum på gang – intradag, uten
    fare for at OHLC-dataene vi screener på blir feil.

    Alle feil svelges (tom dict), så en treg eller nede Yahoo aldri kan krasje
    siden eller påvirke screeningen.
    """
    tickere = [t for t in tickere if t]
    if not tickere:
        return {}
    try:
        rå = yf.download(
            tickers=tickere,
            period="1d",            # kun dagens bar (lett) – oppdateres gjennom dagen
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception:
        return {}
    if rå is None or len(rå) == 0:
        return {}

    def _siste(serie) -> float:
        s = serie.dropna()
        return float(s.iloc[-1]) if not s.empty else float("nan")

    ut: dict[str, dict] = {}
    try:
        if isinstance(rå.columns, pd.MultiIndex):
            tilgjengelige = set(rå.columns.get_level_values(0))
            for t in tickere:
                if t not in tilgjengelige or "Close" not in rå[t].columns:
                    continue
                kol = rå[t]
                pris = _siste(kol["Close"])
                if pd.isna(pris):
                    continue
                volum = _siste(kol["Volume"]) if "Volume" in kol.columns else float("nan")
                ut[t] = {"pris": pris, "volum": volum}
        else:
            # yfinance gir flatt format når det bare er én ticker
            pris = _siste(rå["Close"]) if "Close" in rå.columns else float("nan")
            if not pd.isna(pris):
                volum = _siste(rå["Volume"]) if "Volume" in rå.columns else float("nan")
                ut[tickere[0]] = {"pris": pris, "volum": volum}
    except Exception:
        return {}
    return ut

