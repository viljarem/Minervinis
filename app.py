"""
app.py – selve nettsiden (Streamlit).

Dette er "visnings"-delen. All den tunge logikken ligger i motor/-mappa, så denne
fila handler bare om å vise fram resultatene og tegne chart.

Kjøre lokalt på egen PC:   streamlit run app.py
På nett:                   Streamlit Community Cloud kjører denne fila for deg.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import streamlit as st

from motor import konfig, data as datamod, fundamenta, indikatorer, minervini, posisjon, screener, sektor, univers, vcp

# TradingViews lightweight-charts (testfane). Pakket i try/except så appen aldri
# krasjer om komponenten ikke er installert i miljøet (f.eks. rett etter utrulling).
try:
    from streamlit_lightweight_charts import renderLightweightCharts
    HAR_LWC = True
except Exception:
    HAR_LWC = False

st.set_page_config(page_title="Screener", layout="wide")


def _er_morkt() -> bool:
    """True hvis appen står i mørkt tema.

    Leser brukerens FAKTISKE valgte tema (også når det byttes i ⋮-menyen), via
    st.context.theme. Faller trygt tilbake til lyst tema hvis noe skulle mangle.
    """
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Data-innlasting (bufres/caches så siden blir rask)
# ---------------------------------------------------------------------------
def data_versjon(bors: "konfig.Bors" = konfig.OSLO_BORS) -> float:
    """Endres når datafila for valgt børs oppdateres – frisker opp bufferet."""
    sti = bors.priser_fil
    return os.path.getmtime(sti) if os.path.exists(sti) else 0.0


@st.cache_data(show_spinner=False)
def last_priser(bors_navn: str, versjon: float) -> pd.DataFrame:
    return datamod.les_priser(konfig.BORSER[bors_navn].priser_fil)


@st.cache_data(show_spinner="Kjører screening for hele børsen ...")
def kjor_screening(bors_navn: str, preset_navn: str, versjon: float) -> pd.DataFrame:
    priser = datamod.les_priser(konfig.BORSER[bors_navn].priser_fil)
    return screener.screen(priser, konfig.PRESETS[preset_navn])


@st.cache_data(show_spinner="Søker etter golden cross i hele børsen ...")
def kjor_golden_cross(bors_navn: str, versjon: float) -> pd.DataFrame:
    priser = datamod.les_priser(konfig.BORSER[bors_navn].priser_fil)
    return screener.screen_golden_cross(priser)


@st.cache_data(show_spinner="Leter etter nye noteringer ...")
def kjor_nye_ipoer(bors_navn: str, versjon: float) -> pd.DataFrame:
    """Ferske noteringer (for kort historikk til full analyse).

    getattr-fallback som for RS-historikken: hvis Streamlit Cloud ennå kjører en
    gammel, bufret screener-modul, returner tom ramme i stedet for å krasje.
    """
    _fn = getattr(screener, "screen_nye_ipoer", None)
    if _fn is None:
        return pd.DataFrame()
    priser = datamod.les_priser(konfig.BORSER[bors_navn].priser_fil)
    return _fn(priser)


@st.cache_data(show_spinner=False)
def rs_rating_historikk(bors_navn: str, versjon: float) -> pd.DataFrame:
    """RS-rating (1–99) per dag for hele universet – bred tabell (Date × Ticker).

    getattr-fallback: hvis Streamlit Cloud ennå kjører en gammel, bufret utgave av
    screener-modulen (kan skje det første minuttet etter utrulling), mangler
    funksjonen. Da returnerer vi en tom ramme i stedet for å krasje appen –
    RS-over-tid-laget blir bare borte til den nye modulen er lastet.
    """
    _fn = getattr(screener, "rs_rating_historikk", None)
    if _fn is None:
        return pd.DataFrame()
    priser = datamod.les_priser(konfig.BORSER[bors_navn].priser_fil)
    return _fn(priser)


def kjor_screening_retrospektiv(bors_navn: str, preset_navn: str, dato: pd.Timestamp, versjon: float) -> pd.DataFrame:
    """Kjør screening på data slik det var på en historisk dato (uten look-ahead bias).
    
    Slicer opp priser til og med valgt dato, kjører screening, returnerer resultater.
    """
    priser = datamod.les_priser(konfig.BORSER[bors_navn].priser_fil)
    if priser.empty:
        return pd.DataFrame()
    
    # Konverter dato til timestamp hvis det ikke er det allerede
    if isinstance(dato, pd.Timestamp):
        dato_ts = dato
    else:
        dato_ts = pd.Timestamp(dato)
    
    # Filtrer priser til og med valgt dato
    priser_op_til_dato = priser[pd.to_datetime(priser["Date"]) <= dato_ts].copy()
    if priser_op_til_dato.empty:
        return pd.DataFrame()
    
    return screener.screen(priser_op_til_dato, konfig.PRESETS[preset_navn])


@st.cache_data(show_spinner=False)
def data_status(bors_navn: str, versjon: float) -> dict:
    """Datadekning for én børs: siste handelsdag, antall aksjer med data, universstørrelse."""
    bors = konfig.BORSER[bors_navn]
    priser = datamod.les_priser(bors.priser_fil)
    if priser.empty:
        return {"tom": True}
    benchmarks = {b.benchmark for b in konfig.BORSER.values() if b.benchmark}
    i_data = set(priser["Ticker"].unique())
    univ = set(univers.les_cache(bors.univers_cache_fil))
    if bors.bruk_manuelle:
        univ |= set(univers.les_manuelle())
    univ = {t for t in univ if t not in benchmarks}
    # Dekning = hvor mange av DAGENS univers vi faktisk har kurshistorikk på.
    # (Prisfila kan også inneholde avnoterte tickere som ikke lenger er i universet;
    # de skal ikke blåse opp tallet, derfor snitter vi mot universet.)
    aksjer_univ = len(univ) if univ else len([t for t in i_data if t not in benchmarks])
    aksjer_data = len(univ & i_data) if univ else aksjer_univ
    siste_dato = pd.to_datetime(priser["Date"]).max()
    naa_oslo = pd.Timestamp.now(tz="Europe/Oslo").normalize().tz_localize(None)
    alder = (naa_oslo - siste_dato.normalize()).days
    # «Sist hentet»: robotens EGEN loggede tid (norsk tid) er fasit. Vi kan ikke stole
    # på filas endringstid på serveren – Streamlit Cloud skriver ny fil-tid hver gang
    # den henter koden (ved utrulling), ikke når roboten faktisk kjørte. Faller tilbake
    # til fil-tida (tolket som UTC og vist i norsk tid) hvis metadata mangler.
    sist_hentet = datamod.les_oppdateringstid(bors.sist_oppdatert_fil)
    if sist_hentet is None:
        sist_hentet = pd.Timestamp(versjon, unit="s", tz="UTC").tz_convert("Europe/Oslo")
    return {
        "tom": False,
        "siste_dato": siste_dato,
        "aksjer_data": aksjer_data,
        "aksjer_univ": aksjer_univ,
        "alder_dager": alder,
        "sist_hentet": sist_hentet,
    }


@st.cache_data(ttl=120, show_spinner="Henter live-kurser (≈15 min forsinket) ...")
def hent_live_priser(tickere: tuple[str, ...]) -> dict:
    """Cachet innpakning av datamod.hent_sanntid – oppdateres automatisk ~hvert 2. min.

    Helt adskilt fra kurshistorikken: dette lagres ALDRI til fil og kan aldri
    påvirke tallene vi screener på.
    """
    return datamod.hent_sanntid(list(tickere))


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
# Hvor mange handelsdager hver "Periode"-knapp viser ved åpning (og skalerer etter)
PERIODER_VALG = {"3 mnd": 63, "6 mnd": 126, "1 år": 252, "2 år": 504,
                 "3 år": 756, "5 år": 1260, "Alt": 100_000}


def vis_vcp_boks(res: dict) -> None:
    """Viser VCP-detaljer under chartet som én pen, skalerbar tabell."""
    st.markdown(f"**Setup-status:** {res['status']} {res['statustekst']}")
    st.markdown(f"**Ukentlig trend:** {res.get('mtf_emoji', '⚠️')} {res.get('mtf_tekst', '–')}")

    kontr = ", ".join(f"{x} %" for x in res["kontraksjoner"]) if res["kontraksjoner"] else "—"
    rader = [
        ("Pivot (kjøp)", "—" if res["pivot"] is None else f"{res['pivot']}"),
        ("Stop", "—" if res["stop"] is None else f"{res['stop']}"),
        ("Avstand til pivot", "—" if res["avstand_pivot"] is None else f"{res['avstand_pivot']} %"),
        ("Kvalitetsscore", f"{res['kvalitet']}/100"),
        ("Antall kontraksjoner", str(res["antall_kontr"])),
        ("Dybder", kontr),
        ("Volumuttørking", "Ja ✅" if res["volumuttorking"] else "Nei"),
        ("RS-avkastning (rå)", "—" if pd.isna(res["rs_avkastning"]) else f"{res['rs_avkastning'] * 100:.0f} %"),
    ]

    kropp = "".join(
        f'<tr style="background:{"#eef4ee" if i % 2 else "#ffffff"};">'
        f'<td style="padding:3px 12px;border-bottom:1px solid #e2e8e2;">{navn}</td>'
        f'<td style="padding:3px 12px;border-bottom:1px solid #e2e8e2;'
        f'text-align:right;font-weight:600;font-variant-numeric:tabular-nums;">{verdi}</td>'
        f'</tr>'
        for i, (navn, verdi) in enumerate(rader)
    )
    st.markdown(
        '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;color:#1f2937;'
        'line-height:1.25;border:1px solid #cdddcd;border-radius:8px;overflow:hidden;">'
        '<thead><tr style="background:#5b8a5b;color:#ffffff;">'
        '<th style="text-align:left;padding:4px 12px;font-weight:600;">Nøkkeltall</th>'
        '<th style="text-align:right;padding:4px 12px;font-weight:600;">Verdi</th>'
        f'</tr></thead><tbody>{kropp}</tbody></table>',
        unsafe_allow_html=True,
    )

    # Volumsignatur rundt bruddet (dag −2 … +2). Bruddagen (0) farges grønn hvis
    # den kom på høyt volum (≥ trigger), ellers gul – akkurat det Minervini vil se.
    sig = res.get("volum_signatur") or []
    if sig:
        trigger = konfig.BRUDD_VOLUM_FAKTOR
        chips = []
        for e in sig:
            off, rv, er_brudd = e["offset"], e["rvol"], e["er_brudd"]
            lab = "0" if off == 0 else f"{off:+d}"
            if rv is None:
                inn, bg, col = f"{lab}: –", "#eef2f7", "#94a3b8"
            else:
                komma = f"{rv:.1f}".replace(".", ",")
                paa_volum = er_brudd and rv >= trigger
                inn = f"{lab}: {komma}×" + (" ✅" if paa_volum else "")
                if er_brudd:
                    bg, col = ("#b7e4c7", "#14532d") if rv >= trigger else ("#fde68a", "#78350f")
                else:
                    bg, col = "#eef4ee", "#1f2937"
            chips.append(
                f'<span style="display:inline-block;padding:2px 9px;margin:2px;border-radius:6px;'
                f'background:{bg};color:{col};font-weight:600;font-variant-numeric:tabular-nums;'
                f'font-size:0.8rem;">{inn}</span>'
            )
        trig_txt = f"{trigger:.1f}".replace(".", ",")
        st.markdown(
            '<div style="margin:10px 0 2px;font-size:0.82rem;color:#4b5563;">'
            '📊 <b>Volum rundt bruddet</b> — × mot 50-dagers snitt · 0 = bruddagen '
            f'(grønn = brudd på høyt volum ≥ {trig_txt}×):</div>'
            '<div>' + "".join(chips) + '</div>',
            unsafe_allow_html=True,
        )
    elif res.get("pivot") is not None:
        st.caption("📊 Volumsignatur rundt bruddet vises så snart aksjen faktisk bryter opp gjennom pivot.")


# ---------------------------------------------------------------------------
# Fundamentale tall (vekst, marginer, aksjestruktur) – hentes på forespørsel
# ---------------------------------------------------------------------------
@st.cache_data(ttl=43200, show_spinner=False)   # caches i 12 timer per ticker
def hent_fundamenta_cached(ticker: str) -> dict:
    """Bufret innpakning – henter fundamentaltall bare én gang per aksje per 12 t."""
    return fundamenta.hent_fundamenta(ticker)


@st.cache_data(ttl=86400, show_spinner=False)   # sektor endrer seg sjelden – 24 t
def hent_sektor_cached(ticker: str) -> dict:
    """Bufret, lettvekts sektor-henting (kun t.info). {ticker, sektor, industri}."""
    _fn = getattr(fundamenta, "hent_sektor", None)
    if _fn is None:
        return {"ticker": ticker, "sektor": None, "industri": None}
    return _fn(ticker)


@st.cache_data(ttl=86400, show_spinner=False)   # aksjer utestående endrer seg sjelden
def hent_aksjeinfo_cached(ticker: str) -> dict:
    """Bufret, lettvekts aksjer-utestående + sektor (KUN t.info – 1 nettkall).

    Egen, lett sti for Shares/MCAP-kolonnene, så de IKKE blir avhengige av den tunge
    hent_fundamenta (som laster to resultatregnskap og rate-limites lett ved bulk).
    getattr-fallback om Streamlit Cloud kjører en eldre, bufret modulversjon.
    """
    _fn = getattr(fundamenta, "hent_aksjeinfo", None)
    if _fn is None:
        return {"ticker": ticker, "utestaende": None, "sektor": None, "industri": None}
    return _fn(ticker)


@st.cache_data(show_spinner=False)
def sektor_oppslag(bors_navn: str, tickers: tuple[str, ...]) -> dict[str, str]:
    """Henter sektor for alle tickere og returnerer et {ticker: sektor}-oppslag.

    Cachet på (børs, ticker-sett), så den kjøres bare én gang per universe-utvalg.
    Tickere uten kjent sektor hos Yahoo utelates (de havner i «Ukjent»-bøtta i
    sektor-modulen). Viser en progressbar første gang siden det er mange nettkall;
    etterpå er hver ticker 24 t-cachet, så det går momentant.
    """
    oppslag: dict[str, str] = {}
    if not tickers:
        return oppslag
    _bar = st.progress(0.0, text="Henter sektorer fra Yahoo (første gang) ...")
    n = len(tickers)
    for i, t in enumerate(tickers, start=1):
        try:
            s = hent_sektor_cached(t).get("sektor")
            if s:
                oppslag[t] = s
        except Exception:
            pass
        if i % 5 == 0 or i == n:
            _bar.progress(i / n, text=f"Henter sektorer ... {i}/{n}")
    _bar.empty()
    return oppslag


def prefetch_fund_scores(tickers: list[str]) -> None:
    """Pre-henter fundamental scores for alle tickers og lagrer i session_state.
    
    Gjør det mulig å vise Fund-kolonnen i tabellen immediately. Kjøres asynkront
    så tabellen vises før alle scores er hentet.
    """
    if not tickers:
        return
    
    scores = st.session_state.get("fund_scores", {})
    
    # Hent scores for alle tickers som ikke allerede er cached
    for ticker in tickers:
        if ticker not in scores:
            try:
                fund = hent_fundamenta_cached(ticker)
                score = fundamenta.fund_score(fund)
                scores[ticker] = score
                st.session_state["fund_scores"] = scores
            except Exception:
                # Hvis henting feiler, skip denne aksjen – formater_tabell håndterer det
                pass


def get_shares_and_mcap(ticker: str) -> tuple[float | None, float | None]:
    """Returnerer (shares_outstanding, market_cap_in_native_currency) for ticker.
    
    Market cap beregnes som shares × pris (nåværende pris fra screening-data).
    """
    try:
        fund = hent_fundamenta_cached(ticker)
        struktur = fund.get("struktur", {})
        shares = struktur.get("utestaende")
        # Market cap = shares × current price (motta pris som parameter ville vært bedre,
        # men vi har det ikke lett tilgjengelig her). Returnerer bare shares for nå.
        return shares, None
    except Exception:
        return None, None


def beregn_kursutvikling_siden_dato(priser_df: pd.DataFrame, ticker: str, dato: pd.Timestamp, 
                                     pris_pa_dato: float) -> dict:
    """Beregn kursutvikling siden en historisk dato.
    
    Returnerer:
      - pct_change: % endring fra pris_pa_dato til siste pris
      - peak_high_pct: høyeste pris som % over pris_pa_dato
      - peak_low_pct: laveste pris som % under pris_pa_dato
      - siste_pris: siste sluttkurs
    """
    try:
        serie = datamod.serie_for(priser_df, ticker)
        if serie is None or serie.empty or "Close" not in serie.columns:
            return {"pct_change": None, "peak_high_pct": None, "peak_low_pct": None, "siste_pris": None}

        # Vi må regne på sluttkurs-serien (én verdi per dag), ikke hele OHLC-tabellen.
        close = pd.to_numeric(serie["Close"], errors="coerce").dropna()
        if close.empty:
            return {"pct_change": None, "peak_high_pct": None, "peak_low_pct": None, "siste_pris": None}

        # Etter valgt dato (uten look-ahead i selve screeningen).
        fra_dato = pd.Timestamp(dato)
        framover = close[close.index > fra_dato]
        if framover.empty:
            return {"pct_change": None, "peak_high_pct": None, "peak_low_pct": None, "siste_pris": None}

        basis = pd.to_numeric(pd.Series([pris_pa_dato]), errors="coerce").iloc[0]
        if pd.isna(basis) or basis <= 0:
            return {"pct_change": None, "peak_high_pct": None, "peak_low_pct": None, "siste_pris": None}

        siste = float(framover.iloc[-1])
        hoeyeste = float(framover.max())
        laveste = float(framover.min())

        return {
            "pct_change": (siste - basis) / basis * 100,
            "peak_high_pct": (hoeyeste - basis) / basis * 100,
            "peak_low_pct": (laveste - basis) / basis * 100,
            "siste_pris": siste,
        }
    except Exception:
        return {"pct_change": None, "peak_high_pct": None, "peak_low_pct": None, "siste_pris": None}


def _golden_cross_tekst(dager, over) -> str:
    """Kompakt golden cross-status til tabellen.

    Krever at vi fortsatt er i golden-cross-tilstand (SMA50 over SMA200) – et
    kryss som allerede har reversert (whipsaw) regnes ikke som gyldig.
    ✨ = nylig bekreftet golden cross (≤ GOLDEN_CROSS_FERSK_DAGER dager siden).
    ✅ = i golden-cross-tilstand, men krysset for lenge siden.
    «—» = SMA50 under SMA200 (ingen aktiv golden cross) eller mangler data.
    """
    if not bool(over):
        return "—"
    try:
        d = int(dager)
    except (TypeError, ValueError):
        return "✅"
    if d <= konfig.GOLDEN_CROSS_FERSK_DAGER:
        return f"✨ {d}d"
    return f"✅ {d}d"


def _stor_tall(x) -> str:
    """Store tall pent på norsk: 2489187863 → '2,49 mrd', 272700000 → '272,7 mill'."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(x):
        return "—"
    a = abs(x)
    if a >= 1e9:
        s = f"{x / 1e9:.2f} mrd"
    elif a >= 1e6:
        s = f"{x / 1e6:.1f} mill"
    elif a >= 1e3:
        s = f"{x / 1e3:.1f} k"
    else:
        s = f"{x:.0f}"
    return s.replace(".", ",")


def _belop(x, valuta) -> str:
    """Beløp med rapporteringsvaluta bak (valuta kan mangle)."""
    t = _stor_tall(x)
    if t == "—":
        return t
    return f"{t} {valuta}" if valuta else t


def _vekst_farge(pct) -> str:
    """Cellefarge for vekst: ≥25 % kraftig grønn, 15–25 % lys grønn, negativ svak rød."""
    if pct is None or pd.isna(pct):
        return ""
    if pct >= 25:
        return "#4e8a4e"      # kraftig grønn – Minervini-standard
    if pct >= 15:
        return "#cfe6cf"      # lys grønn – bra for Oslo Børs
    if pct < 0:
        return "#f3d9d9"      # svak rød – negativ vekst
    return ""


def _pp_farge(pp) -> str:
    """Cellefarge for margin-endring: utvider seg (grønn) / krymper (rød)."""
    if pp is None or pd.isna(pp):
        return ""
    if pp > 0:
        return "#cfe6cf"
    if pp < 0:
        return "#f3d9d9"
    return ""


def _celle(txt: str, bg: str = "", venstre: bool = False, sterk: bool = False) -> str:
    align = "left" if venstre else "right"
    hvit = "color:#ffffff;font-weight:600;" if sterk else ""
    b = f"background:{bg};" if bg else ""
    return (f'<td style="padding:3px 10px;border-bottom:1px solid #e2e8e2;'
            f'text-align:{align};font-variant-numeric:tabular-nums;{b}{hvit}">{txt}</td>')


def _pct_txt(pct) -> str:
    return "—" if pct is None or pd.isna(pct) else f"{pct:+.1f} %"


def _pp_txt(pp) -> str:
    return "—" if pp is None or pd.isna(pp) else f"{pp:+.1f} pp"


def _margin_txt(m) -> str:
    return "—" if m is None or pd.isna(m) else f"{m:.1f} %"


def _kvartal_navn(iso) -> str:
    try:
        t = pd.Timestamp(iso)
        return f"Q{(t.month - 1) // 3 + 1} {t.year}"
    except Exception:
        return "—"


def _aar_navn(iso) -> str:
    try:
        return str(pd.Timestamp(iso).year)
    except Exception:
        return "—"


def _fund_tabell(overskrifter: list[str], rader_html: str) -> str:
    """Bygger en grønn HTML-tabell med gitt topprad og ferdig kropp."""
    celler = "".join(
        f'<th style="text-align:{"left" if i == 0 else "right"};padding:5px 10px;'
        f'font-weight:600;">{h}</th>' for i, h in enumerate(overskrifter))
    return ('<table style="width:100%;border-collapse:collapse;font-size:0.82rem;color:#1f2937;'
            'line-height:1.25;border:1px solid #cdddcd;border-radius:8px;overflow:hidden;">'
            f'<thead><tr style="background:#5b8a5b;color:#ffffff;">{celler}</tr></thead>'
            f'<tbody>{rader_html}</tbody></table>')


def _navn_celle(t: str) -> str:
    return f'<td style="padding:3px 10px;border-bottom:1px solid #e2e8e2;">{t}</td>'


def _tegn_fundamenta(fund: dict) -> None:
    """Tegner de to fundamenttabellene (vekst/marginer + aksjestruktur)."""
    valuta = fund.get("valuta")
    kv = fund.get("kvartal") or {}
    aar = fund.get("aar") or {}

    def belop_rad(tittel, nokkel):
        kv_v = _belop(kv.get(nokkel), valuta)
        aar_v = _belop(aar.get(nokkel), valuta)
        kv_p = kv.get(f"{nokkel}_vekst")
        aar_p = aar.get(f"{nokkel}_vekst")
        return ("<tr>" + _navn_celle("&nbsp;&nbsp;" + tittel)
                + _celle(kv_v)
                + _celle(_pct_txt(kv_p), _vekst_farge(kv_p), sterk=(kv_p is not None and kv_p >= 25))
                + _celle(aar_v)
                + _celle(_pct_txt(aar_p), _vekst_farge(aar_p), sterk=(aar_p is not None and aar_p >= 25))
                + "</tr>")

    def margin_rad(tittel, nokkel):
        kv_e = kv.get(f"{nokkel}_endring")
        aar_e = aar.get(f"{nokkel}_endring")
        return ("<tr>" + _navn_celle("&nbsp;&nbsp;" + tittel)
                + _celle(_margin_txt(kv.get(nokkel)))
                + _celle(_pp_txt(kv_e), _pp_farge(kv_e))
                + _celle(_margin_txt(aar.get(nokkel)))
                + _celle(_pp_txt(aar_e), _pp_farge(aar_e))
                + "</tr>")

    def seksjon_rad(navn, kol1, kol2):
        """Seksjons-skille som samtidig forklarer de to kolonnene under."""
        liten = ('padding:4px 10px;text-align:right;font-size:0.7rem;'
                 'font-weight:400;color:#557055;border-bottom:1px solid #cdddcd;')
        return (f'<tr style="background:#dcebdc;">'
                f'<td style="padding:4px 10px;font-weight:700;'
                f'border-bottom:1px solid #cdddcd;">{navn}</td>'
                f'<td style="{liten}">{kol1}</td><td style="{liten}">{kol2}</td>'
                f'<td style="{liten}">{kol1}</td><td style="{liten}">{kol2}</td></tr>')

    kropp = (seksjon_rad("📈 Vekst", "Beløp", "vs i fjor")
             + belop_rad("Omsetning", "omsetning")
             + belop_rad("Resultat", "resultat")
             + seksjon_rad("📊 Marginer", "Nivå", "endring")
             + margin_rad("Bruttomargin", "brutto_margin")
             + margin_rad("Driftsmargin", "drift_margin")
             + margin_rad("Nettomargin", "netto_margin"))

    kv_p = _kvartal_navn(kv.get("dato")); kv_pi = _kvartal_navn(kv.get("dato_ifjor"))
    aar_p = _aar_navn(aar.get("dato")); aar_pi = _aar_navn(aar.get("dato_ifjor"))
    kant = "border-left:1px solid rgba(255,255,255,0.35);"
    topphode = (
        '<thead><tr style="background:#5b8a5b;color:#ffffff;">'
        '<th style="text-align:left;padding:6px 10px;">Vekst &amp; marginer</th>'
        f'<th colspan="2" style="text-align:center;padding:6px 10px;{kant}">Siste kvartal'
        f'<br><span style="font-weight:400;font-size:0.7rem;">{kv_p} vs {kv_pi}</span></th>'
        f'<th colspan="2" style="text-align:center;padding:6px 10px;{kant}">Siste år'
        f'<br><span style="font-weight:400;font-size:0.7rem;">{aar_p} vs {aar_pi}</span></th>'
        '</tr></thead>'
    )
    tabell = ('<table style="width:100%;border-collapse:collapse;font-size:0.82rem;color:#1f2937;'
              'line-height:1.25;border:1px solid #cdddcd;border-radius:8px;overflow:hidden;">'
              + topphode + f'<tbody>{kropp}</tbody></table>')
    st.markdown(tabell, unsafe_allow_html=True)

    val_txt = f" Beløp vises i {valuta}." if valuta else ""
    st.caption("Slik leser du den: **Beløp/Nivå** = tallet nå · **vs i fjor** = endring mot "
               "samme periode året før. 🟩 vekst ≥ 25 % · 🟢 15–25 % · 🟥 negativ. "
               f"Marginer måles i prosentpoeng (pp).{val_txt}")

    # --- Vekst-trend over flere perioder (akselererer veksten?) ---
    oms_serie = fund.get("vekst_oms_serie") or []
    eps_serie = fund.get("vekst_eps_serie") or []
    akse = fund.get("akselerasjon")
    basis = fund.get("akse_basis", "kvartal")
    periode_ord = "kvartaler" if basis == "kvartal" else "år"
    if len(oms_serie) >= 2 or len(eps_serie) >= 2:
        def _spor(serie):
            return " → ".join(f"{v:+.0f}%" for _, v in serie) if serie else "—"
        linjer = []
        if akse:
            linjer.append(f"{akse['merke']} **{akse['tekst']}**")
        linjer.append(f"YoY-salg siste {periode_ord}: {_spor(oms_serie)}")
        if len(eps_serie) >= 2:
            linjer.append(f"YoY-resultat: {_spor(eps_serie)}")
        st.caption("📈 **Vekst-trend** — "
                   + "  ·  ".join(linjer)
                   + ".  🚀 = stigende vekstrate (Minervinis favoritt) · ➡️ stabil · 🐢 avtagende.")


    # --- Tabell 2: Aksjestruktur ---
    s = fund.get("struktur") or {}
    fri_txt = _stor_tall(s.get("float"))
    if s.get("float_pct") is not None:
        fri_txt += f" ({s['float_pct']:.1f} % av totalen)"
    struktur_rader = [
        ("Utestående aksjer", _stor_tall(s.get("utestaende"))),
        ("Fritt omsettelige (free float)", fri_txt),
        ("Eid av innsidere", "—" if s.get("innsidere_pct") is None else f"{s['innsidere_pct']:.1f} %"),
        ("Eid av institusjoner", "—" if s.get("institusjoner_pct") is None else f"{s['institusjoner_pct']:.1f} %"),
    ]
    kropp2 = "".join(
        f'<tr style="background:{"#eef4ee" if i % 2 else "#ffffff"};">'
        + _navn_celle(navn)
        + f'<td style="padding:3px 10px;border-bottom:1px solid #e2e8e2;text-align:right;'
          f'font-weight:600;font-variant-numeric:tabular-nums;">{verdi}</td></tr>'
        for i, (navn, verdi) in enumerate(struktur_rader))
    st.markdown(_fund_tabell(["Aksjestruktur", "Verdi"], kropp2), unsafe_allow_html=True)
    st.caption("Lav free float = få frie aksjer i omløp – kan gi raskere kursbevegelser "
               "(Minervini liker det). Tallene er Yahoos anslag; eksakt topp-50-liste finnes "
               "ikke gratis automatisk.")


def _vis_fund_merke(score: dict, ticker: str) -> None:
    """Viser fundamental Minervini-score som én kompakt linje under chartet."""
    if not score.get("tilgjengelig"):
        st.caption(f"📊 Fundamental: ingen Yahoo-data for **{ticker}** (vanlig for mindre aksjer)")
        return
    p, m = score["poeng"], score["merke"]
    detaljer = " · ".join(score["detaljer"])
    label = "Sterk ✅" if p >= 4 else "Godkjent" if p >= 2 else "Svak"
    st.caption(f"📊 **Fundamental Minervini-score:** {m} **{p}/5** ({label}) — {detaljer}")


def _vis_vekst_trend(fund: dict) -> None:
    """Viser om YoY-veksten akselererer – Minervinis favoritt-signal.

    En vekstrate som STIGER kvartal for kvartal (f.eks. +18 % → +25 % → +40 % YoY)
    er langt sterkere enn flat vekst. Vises som én kompakt linje med spor over de
    siste kvartalene. Stille hvis Yahoo mangler nok historikk (typisk små aksjer).
    """
    akse = (fund or {}).get("akselerasjon")
    serie = (fund or {}).get("vekst_oms_serie") or []
    if not akse or len(serie) < 2:
        return
    basis = (fund or {}).get("akse_basis", "kvartal")
    periode_ord = "siste kvartaler" if basis == "kvartal" else "siste år"
    spor = " → ".join(f"{v:+.0f}%" for _, v in serie)
    st.caption(f"{akse['merke']} **Vekst-trend (salg YoY):** {akse['tekst']}  ·  {periode_ord}: {spor}")


def fundamenta_seksjon(ticker: str, nokkel: str) -> None:
    """Henter alltid fundamental score (cached, rask etter første gang) og viser merke.
    Scoren lagres i session_state så tabellen kan vise Fund-kolonnen gradvis.
    Detaljert tabell bak toggle for de som vil dykke dypere.
    """
    fund = hent_fundamenta_cached(ticker)
    score = fundamenta.fund_score(fund)
    st.session_state.setdefault("fund_scores", {})[ticker] = score
    _vis_fund_merke(score, ticker)
    _vis_vekst_trend(fund)
    vis = st.toggle("📊 Vis detaljerte fundamentale tall (vekst, marginer, aksjestruktur)",
                    value=False, key=f"fund_{nokkel}")
    if not vis:
        return
    if not fund.get("tilgjengelig"):
        st.info(f"Yahoo har ingen fundamentaldata for {ticker}. Det er vanlig for mindre "
                "aksjer på Euronext Growth/Expand.")
        return
    _tegn_fundamenta(fund)


def _kr(x) -> str:
    """Kroner med mellomrom som tusenskille (norsk stil): 12345 → '12 345'."""
    try:
        return f"{float(x):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _pos_defaults(res: dict) -> tuple[float, float, float]:
    """Default for inngang + faste prosentnivåer (5 % stop, 10 % mål)."""
    piv = res.get("pivot")
    entry_def = float(piv) if piv else float(res.get("pris") or 0.0)
    stop_pct_def = 5.0
    mal_pct_def = 10.0
    return round(entry_def, 2), stop_pct_def, mal_pct_def


def _init_posisjon_state(res: dict, nokkel: str) -> None:
    """Legger inn førsteverdier i session_state for posisjonsverktøyet."""
    entry_def, stop_pct_def, mal_pct_def = _pos_defaults(res)
    st.session_state.setdefault(f"pos_e_{nokkel}", entry_def)
    st.session_state.setdefault(f"pos_sp_{nokkel}", stop_pct_def)
    st.session_state.setdefault(f"pos_mp_{nokkel}", mal_pct_def)
    st.session_state.setdefault(f"pos_n_{nokkel}", 0)
    st.session_state.setdefault(f"pos_p_{nokkel}", False)


def _posisjon_fra_state(nokkel: str) -> tuple[dict | None, str]:
    """Henter aktiv posisjon (entry/stop/mål i kr) ut fra prosent-input i state."""
    try:
        entry_v = float(st.session_state.get(f"pos_e_{nokkel}", 0.0))
        stop_pct_v = float(st.session_state.get(f"pos_sp_{nokkel}", 0.0))
        mal_pct_v = float(st.session_state.get(f"pos_mp_{nokkel}", 0.0))
    except (TypeError, ValueError):
        return None, ""

    if not st.session_state.get(f"pos_p_{nokkel}", True):
        return None, ""
    if not (entry_v > 0 and stop_pct_v > 0 and mal_pct_v > 0):
        return None, ""

    stop_v = round(entry_v * (1 - stop_pct_v / 100), 4)
    mal_v = round(entry_v * (1 + mal_pct_v / 100), 4)
    if not (0 < stop_v < entry_v < mal_v):
        return None, ""

    pos = {"entry": entry_v, "stop": stop_v, "mal": mal_v}
    suffix = f"_pos{entry_v:.2f}_{stop_pct_v:.1f}_{mal_pct_v:.1f}"
    return pos, suffix


def posisjon_verktoy(res: dict, nokkel: str, valuta: str = "kr") -> None:
    """Kalkulator for long-posisjon med prosent-input og beløp som output."""
    _init_posisjon_state(res, nokkel)

    with st.expander("📐 Posisjon & risk/reward"):
        entry_def, stop_pct_def, mal_pct_def = _pos_defaults(res)
        h1, h2 = st.columns([1, 3])
        if h1.button("Reset til standard", key=f"pos_reset_{nokkel}"):
            st.session_state[f"pos_e_{nokkel}"] = entry_def
            st.session_state[f"pos_sp_{nokkel}"] = stop_pct_def
            st.session_state[f"pos_mp_{nokkel}"] = mal_pct_def
            st.session_state[f"pos_n_{nokkel}"] = 0
            st.rerun()
        h2.caption("Standard = pivot som inngang, 5 % stop og 10 % mål.")

        c1, c2, c3, c4 = st.columns(4)
        entry_v = c1.number_input(f"Inngang ({valuta})", min_value=0.0,
                                  value=float(st.session_state[f"pos_e_{nokkel}"]),
                                  step=0.1, format="%.2f", key=f"pos_e_{nokkel}")
        stop_pct_v = c2.number_input("Stop (%)", min_value=0.1,
                                     value=float(st.session_state[f"pos_sp_{nokkel}"]),
                                     step=0.1, format="%.1f", key=f"pos_sp_{nokkel}")
        mal_pct_v = c3.number_input("Mål (%)", min_value=0.1,
                                    value=float(st.session_state[f"pos_mp_{nokkel}"]),
                                    step=0.1, format="%.1f", key=f"pos_mp_{nokkel}")
        antall_v = int(c4.number_input("Antall aksjer", min_value=0,
                                       value=int(st.session_state[f"pos_n_{nokkel}"]),
                                       step=10, key=f"pos_n_{nokkel}"))

        stop_v = round(entry_v * (1 - stop_pct_v / 100), 4) if entry_v > 0 else 0.0
        mal_v = round(entry_v * (1 + mal_pct_v / 100), 4) if entry_v > 0 else 0.0
        nt = posisjon.nokkeltall(entry_v, stop_v, mal_v)

        if nt["gyldig"]:
            tap_pr_aksje = max(0.0, entry_v - stop_v)
            gev_pr_aksje = max(0.0, mal_v - entry_v)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Stopkurs", f"{stop_v:.2f} {valuta}", f"−{stop_pct_v:.1f} %")
            m2.metric("Målkurs", f"{mal_v:.2f} {valuta}", f"+{mal_pct_v:.1f} %")
            m3.metric("Tap pr aksje", f"{tap_pr_aksje:.2f} {valuta}")
            m4.metric("Gevinst pr aksje", f"{gev_pr_aksje:.2f} {valuta}")

            m5, m6 = st.columns(2)
            m5.metric("Risk/reward", f"{nt['rr']:.2f} : 1" if nt["rr"] else "—")
            m6.metric("Total innsats", f"{_kr(entry_v * antall_v)} {valuta}" if antall_v > 0 else "—")

            if antall_v > 0:
                totalt_tap = tap_pr_aksje * antall_v
                total_gevinst = gev_pr_aksje * antall_v
                st.caption(f"💸 Stop-tap ved **{antall_v} aksjer**: ca. **{_kr(totalt_tap)} {valuta}** · "
                           f"🎯 potensiell gevinst: **{_kr(total_gevinst)} {valuta}**.")

            if nt["rr"] and nt["rr"] >= 2:
                st.caption(f"✅ Risk/reward {nt['rr']:.2f} : 1 – oppsiden er {nt['rr']:.1f}× risikoen.")
            elif nt["rr"]:
                st.caption(f"⚠️ Risk/reward {nt['rr']:.2f} : 1 – Minervini liker helst minst 2 : 1.")
        else:
            st.caption("Ugyldig oppsett – bruk positive prosentverdier og inngang over 0.")

        st.checkbox("Tegn posisjonen i chartet", value=False, key=f"pos_p_{nokkel}")


# ---------------------------------------------------------------------------
# Chart 2.0 (test) – TradingViews lightweight-charts
# ---------------------------------------------------------------------------
def lag_chart_lwc(serie: pd.DataFrame, res: dict | None, dager: int = 504, *,
                  vis_ma: bool = True, vis_52u: bool = True, vis_vcp: bool = True,
                  vis_7av7: bool = True, vis_hist: bool = False, vis_golden: bool = False,
                  vis_rs_rating: bool = False, rs_rating: pd.Series | None = None,
                  vis_indeks: bool = False, indeks: pd.DataFrame | None = None,
                  indeks_navn: str = "indeks",
                  ukentlig: bool = False, hoyde: int = 620, pos: dict | None = None,
                  morkt: bool = False, tittel: str = "",
                  vis_eps: bool = False, eps_bars: list | None = None,
                  oms_bars: list | None = None, graf_basis: str = "kvartal",
                  graf_valuta: str = "") -> list | None:
    """Bygger data-spesifikasjonen for lightweight-charts.

    Tar med alt det gamle Plotly-chartet hadde: candles, MA50/150/200, 52-ukers
    høy/lav, volum + volum-SMA50, pivot/stop, VCP-kontraksjonene (zigzag),
    7/7-markører (ble/mistet), historiske volumbrudd og «brudd nå». Hvert lag kan
    slås av/på. Returnerer lista renderLightweightCharts venter, eller None.
    Pakket i try/except så testfanen aldri kan krasje appen.

    ukentlig=True resampler til UKEDATA før indikatorene regnes – da blir SMA50
    = 50 uker, volum-snittet SMA10 (10 uker), osv. De daglige analyse-artefaktene
    (VCP-punkter, 7/7-markører, historiske brudd) vises kun i dagsvisning siden
    datoene deres ikke faller på ukeslutt; pivot/stop (prisnivåer) vises i begge.
    """
    try:
        if ukentlig:
            uke = indikatorer.til_ukedata(serie)
            if uke.empty or len(uke) < 30:
                return None
            full = indikatorer.legg_til_indikatorer(uke)
            vindu = max(dager // 5, 30)          # omtrent samme tidsspenn som dagsvisning
            vol_vindu = 10                        # SMA10 på volum i ukevisning
        else:
            full = indikatorer.legg_til_indikatorer(serie)
            vindu = dager
            vol_vindu = 50
        if full.empty:
            return None
        d = full.iloc[-min(vindu, len(full)):].copy()
        t = list(d.index.strftime("%Y-%m-%d"))
        t_sett = set(t)

        # Valider long-posisjonen (inngang/stop/mål) hvis den er sendt inn.
        posn = None
        if pos:
            try:
                _e = float(pos.get("entry")); _s = float(pos.get("stop")); _m = float(pos.get("mal"))
                if _e > 0 and _s < _e < _m:
                    posn = {"entry": _e, "stop": _s, "mal": _m}
            except (TypeError, ValueError):
                posn = None

        def linje(kol, farge, bredde, stil=0, skala=None):
            data = [{"time": ti, "value": round(float(v), 4)}
                    for ti, v in zip(t, d[kol]) if pd.notna(v)]
            opts = {"color": farge, "lineWidth": bredde, "lineStyle": stil,
                    "priceLineVisible": False, "lastValueVisible": False}
            s = {"type": "Line", "data": data, "options": opts}
            if skala is not None:
                s["options"]["priceScaleId"] = skala
            return s

        candles = [{"time": ti, "open": float(o), "high": float(h),
                    "low": float(lo), "close": float(c)}
                   for ti, o, h, lo, c in zip(t, d["Open"], d["High"], d["Low"], d["Close"])]

        opp = (d["Close"] >= d["Open"]).to_numpy()
        volum = [{"time": ti, "value": float(v),
                  "color": "rgba(38,166,154,0.5)" if up else "rgba(239,83,80,0.5)"}
                 for ti, v, up in zip(t, d["Volume"], opp)]

        # --- Samle ALLE markører i én liste (LWC tillater kun én per serie) ---
        markorer = []
        if vis_7av7 and res:
            for start, slutt in res.get("perioder", [])[-12:]:
                if start in t_sett:
                    markorer.append({"time": start, "position": "belowBar",
                                     "color": "#2e7d32", "shape": "arrowUp", "text": "7/7"})
                # «Mistet ett» = dagen etter at perioden sluttet
                if slutt in t_sett:
                    idx = t.index(slutt)
                    if idx + 1 < len(t):
                        markorer.append({"time": t[idx + 1], "position": "aboveBar",
                                         "color": "#c62828", "shape": "arrowDown", "text": "×"})
        hist_segmenter = []   # (start, brudd, niva) for korte historiske pivotstreker
        if vis_hist:
            try:
                finn_hist = getattr(vcp, "historiske_brudd", None)
                for b in (finn_hist(serie) if finn_hist else []):
                    dato = pd.Timestamp(b["dato"]).strftime("%Y-%m-%d")
                    if dato in t_sett:
                        markorer.append({"time": dato, "position": "belowBar",
                                         "color": "#f6c343", "shape": "circle", "text": "brudd"})
                        start = pd.Timestamp(b["base_start"]).strftime("%Y-%m-%d")
                        if start not in t_sett:
                            start = t[0]          # klipp basen til venstre kant av vinduet
                        if start < dato:          # trenger to ulike datoer for en strek
                            hist_segmenter.append((start, dato, float(b["pivot"])))
            except Exception:
                pass
        if res and res.get("bruddato"):
            bd = pd.Timestamp(res["bruddato"]).strftime("%Y-%m-%d")
            if bd in t_sett:
                markorer.append({"time": bd, "position": "belowBar",
                                 "color": "#f6c343", "shape": "arrowUp", "text": "BRUDD"})
        # Golden/death cross (SMA50 krysser SMA200): historiske signal som markører.
        if vis_golden:
            try:
                for h in indikatorer.golden_cross_hendelser(full):
                    dato = pd.Timestamp(h["dato"]).strftime("%Y-%m-%d")
                    if dato not in t_sett:
                        continue
                    if h["type"] == "golden":
                        markorer.append({"time": dato, "position": "belowBar",
                                         "color": "#fbc02d", "shape": "arrowUp", "text": "GC"})
                    else:
                        markorer.append({"time": dato, "position": "aboveBar",
                                         "color": "#78909c", "shape": "arrowDown", "text": "DC"})
            except Exception:
                pass
        # Fjern duplikater (samme tid+form) og sorter stigende på tid (LWC-krav)
        sett = set()
        rene = []
        for m in sorted(markorer, key=lambda x: x["time"]):
            nk = (m["time"], m["shape"], m["position"])
            if nk not in sett:
                sett.add(nk)
                rene.append(m)

        hoved = {"type": "Candlestick", "data": candles,
                 "options": {"upColor": "#26a69a", "downColor": "#ef5350",
                             "borderVisible": False, "wickUpColor": "#26a69a",
                             "wickDownColor": "#ef5350",
                             # Siste kurs som alltid-synlig etikett til høyre.
                             "lastValueVisible": True, "priceLineVisible": True,
                             "priceLineWidth": 1, "priceLineStyle": 2,
                             "priceLineColor": "#787b86"}}
        if rene:
            hoved["markers"] = rene

        # Risk/reward-soner (long): grønn gevinstsone inngang→mål, rød risikosone
        # inngang→stop. Lagt BAK candlene (svak farge) så de blir bakteppe, som
        # TradingViews «Long Position»-verktøy. Baseline fyller mellom en flat linje
        # og «baseValue» (= inngangen).
        zone_serier = []
        if posn:
            gjennomsiktig = "rgba(0,0,0,0)"
            zone_serier = [
                {"type": "Baseline",
                 "data": [{"time": ti, "value": posn["mal"]} for ti in t],
                 "options": {"baseValue": {"type": "price", "price": posn["entry"]},
                             "topLineColor": gjennomsiktig,
                             "topFillColor1": "rgba(38,166,154,0.22)",
                             "topFillColor2": "rgba(38,166,154,0.22)",
                             "bottomLineColor": gjennomsiktig,
                             "bottomFillColor1": gjennomsiktig, "bottomFillColor2": gjennomsiktig,
                             "priceLineVisible": False, "lastValueVisible": False}},
                {"type": "Baseline",
                 "data": [{"time": ti, "value": posn["stop"]} for ti in t],
                 "options": {"baseValue": {"type": "price", "price": posn["entry"]},
                             "topLineColor": gjennomsiktig,
                             "topFillColor1": gjennomsiktig, "topFillColor2": gjennomsiktig,
                             "bottomLineColor": gjennomsiktig,
                             "bottomFillColor1": "rgba(239,83,80,0.22)",
                             "bottomFillColor2": "rgba(239,83,80,0.22)",
                             "priceLineVisible": False, "lastValueVisible": False}},
            ]

        serier = [*zone_serier, hoved]

        # Glidende snitt
        if vis_ma:
            serier += [linje("SMA50", "#2196f3", 2),
                       linje("SMA150", "#ff9800", 1),
                       linje("SMA200", "#9c27b0", 1)]

        # 52-ukers høy/lav (grå stiplede referanselinjer – kriterium 6 og 7)
        if vis_52u:
            serier += [linje("High_52w", "#9e9e9e", 1, stil=1),
                       linje("Low_52w", "#9e9e9e", 1, stil=1)]

        # Indeks-overlay: indekslinjen (OSEBX.OL / ^GSPC) lagt OPPÅ hovedchartet,
        # skalert slik at den starter på SAMME pris som aksjen i venstre kant.
        # Da ser du direkte om aksjen holdt seg når indeksen dyppet: faller den grå
        # indekslinjen mens candlene står støtt, har aksjen vært sterkere.
        if vis_indeks and indeks is not None and not indeks.empty:
            try:
                idx_kilde = indikatorer.til_ukedata(indeks) if ukentlig else indeks
                idx_align = idx_kilde["Close"].reindex(d.index).ffill().bfill()
                gyldige = idx_align.dropna()
                if not gyldige.empty and float(gyldige.iloc[0]) > 0:
                    basis = float(gyldige.iloc[0])
                    startpris = float(d["Close"].iloc[0])
                    rebas = idx_align / basis * startpris
                    idx_data = [{"time": ti, "value": round(float(v), 4)}
                                for ti, v in zip(t, rebas) if pd.notna(v)]
                    serier.append({"type": "Line", "data": idx_data,
                                   "options": {"color": "#607d8b", "lineWidth": 2,
                                               "lineStyle": 0, "priceLineVisible": False,
                                               "lastValueVisible": False,
                                               "title": f"{indeks_navn}"}})
            except Exception:
                pass

        # VCP-kontraksjoner (gul stiplet zigzag topp→bunn→topp mot pivot)
        if vis_vcp and res:
            pkt = [{"time": pd.Timestamp(p["dato"]).strftime("%Y-%m-%d"),
                    "value": float(p["pris"])}
                   for p in (res.get("vcp_punkter") or [])
                   if pd.Timestamp(p["dato"]).strftime("%Y-%m-%d") in t_sett]
            if len(pkt) >= 2:
                serier.append({"type": "Line", "data": pkt,
                               "options": {"color": "#e0b000", "lineWidth": 2, "lineStyle": 2,
                                           "priceLineVisible": False, "lastValueVisible": False,
                                           "pointMarkersVisible": True}})
                # «Pågår»-strek: tynn, lys, prikket linje fra siste bekreftede
                # svingpunkt fram til dagens kurs. Tentativ – det aller siste
                # svinget er ikke bekreftet ennå (svingpunkt trenger ~1 uke), men
                # dette viser at «fjæra» fortsatt strammer seg helt til i dag.
                siste = pkt[-1]
                sluttpris = round(float(d["Close"].iloc[-1]), 4)
                if siste["time"] < t[-1]:
                    serier.append({"type": "Line",
                                   "data": [siste, {"time": t[-1], "value": sluttpris}],
                                   "options": {"color": "rgba(224,176,0,0.5)", "lineWidth": 1,
                                               "lineStyle": 1, "priceLineVisible": False,
                                               "lastValueVisible": False}})

        # Historiske pivotlinjer: kort gull strek langs motstanden fram til hvert
        # brudd. UBIASED / point-in-time – motstanden er høyeste High i de
        # FORUTGÅENDE dagene (shift 1), så streken er nøyaktig det du kunne sett
        # i sanntid, uten å kikke framover.
        for start, slutt, niva in hist_segmenter:
            serier.append({"type": "Line",
                           "data": [{"time": start, "value": niva},
                                    {"time": slutt, "value": niva}],
                           "options": {"color": "rgba(246,195,67,0.5)", "lineWidth": 1,
                                       "lineStyle": 2, "priceLineVisible": False,
                                       "lastValueVisible": False}})

        # Volum + snittvolum (delt overlay-skala i bunnen). Vindu følger tidsrammen:
        # 50-dagers snitt i dagsvisning, 10-ukers (SMA10) i ukevisning.
        serier.append({"type": "Histogram", "data": volum,
                       "options": {"priceFormat": {"type": "volume"}, "priceScaleId": "vol"},
                       "priceScale": {"scaleMargins": {"top": 0.78, "bottom": 0}}})
        d["_volsnitt"] = d["Volume"].rolling(vol_vindu, min_periods=max(2, vol_vindu // 5)).mean()
        serier.append(linje("_volsnitt", "#3949ab", 1, skala="vol"))

        # Pivot (gull) og stop (rød stiplet) som flate linjer. Aktiv pivot er
        # bevisst TYKKEST og solid, så den skiller seg klart fra de svakere,
        # stiplede historiske pivotlinjene. Skjules når posisjonsverktøyet er på
        # (da tegner vi inngang/stop/mål i stedet, så det ikke blir dobbelt opp).
        if res and res.get("pivot") and not posn:
            serier.append({"type": "Line",
                           "data": [{"time": ti, "value": res["pivot"]} for ti in t],
                           "options": {"color": "#f6c343", "lineWidth": 3, "lineStyle": 0,
                                       "priceLineVisible": False, "lastValueVisible": True,
                                       "title": "Pivot"}})
        if res and res.get("stop") and not posn:
            serier.append({"type": "Line",
                           "data": [{"time": ti, "value": res["stop"]} for ti in t],
                           "options": {"color": "#ef5350", "lineWidth": 1, "lineStyle": 2,
                                       "priceLineVisible": False, "lastValueVisible": True,
                                       "title": "Stop"}})

        # Posisjon (long): inngang (blå solid), stop (rød stiplet) og mål (grønn
        # stiplet) som tydelige nivålinjer med pris-etikett til høyre.
        if posn:
            for verdi, farge, bredde, stil, tittel in [
                (posn["entry"], "#1e88e5", 2, 0, "Inngang"),
                (posn["stop"], "#ef5350", 1, 2, "Stop"),
                (posn["mal"], "#26a69a", 1, 2, "Mål"),
            ]:
                serier.append({"type": "Line",
                               "data": [{"time": ti, "value": verdi} for ti in t],
                               "options": {"color": farge, "lineWidth": bredde, "lineStyle": stil,
                                           "priceLineVisible": False, "lastValueVisible": True,
                                           "title": tittel}})

        # Farger som følger app-temaet: mørk bakgrunn + lys tekst i dark mode,
        # ellers hvitt med mørk tekst. Candle-, MA- og pivotfargene funker i begge.
        if morkt:
            bg, tekstfarge, grid = "#131722", "#d1d4dc", "rgba(120,123,134,0.22)"
        else:
            bg, tekstfarge, grid = "white", "#333333", "rgba(197,203,206,0.35)"
        chart_options = {
            "height": hoyde,
            "layout": {"background": {"type": "solid", "color": bg},
                       "textColor": tekstfarge},
            "grid": {"vertLines": {"color": grid},
                     "horzLines": {"color": grid}},
            "rightPriceScale": {"scaleMargins": {"top": 0.06, "bottom": 0.26},
                                "borderVisible": False},
            "timeScale": {"borderVisible": False, "rightOffset": 4},
            "crosshair": {"mode": 0},
        }
        # Vannmerke: svak ticker-tekst bak chartet, så du alltid ser hvilken aksje
        # det gjelder – nyttig når flere charts tegnes under hverandre i tabellene.
        if tittel:
            vm_tekst = f"{tittel} \u00b7 uke" if ukentlig else tittel
            chart_options["watermark"] = {
                "visible": True, "text": vm_tekst,
                "fontSize": 34, "lineHeight": 34,
                "color": "rgba(160,160,160,0.12)" if not morkt else "rgba(200,200,200,0.10)",
                "horzAlign": "center", "vertAlign": "top",
            }
        charts = [{"chart": chart_options, "series": serier}]

        # --- RS-rating over tid (1–99) som egen delgraf ---
        # Samme skanne-tall, men beregnet for HVER dag bakover: aksjens relative
        # styrke mot hele universet. Baseline ved 70 (Minervinis terskel):
        # grønt over 70 = blant de sterkeste, rødt under. Høyre kant = dagens
        # RS-rating (samme tall som i tabellen).
        if vis_rs_rating and rs_rating is not None and not rs_rating.empty:
            try:
                rs_j = rs_rating.reindex(d.index).dropna()
                rs_data = [{"time": ti.strftime("%Y-%m-%d"), "value": round(float(v), 0)}
                           for ti, v in rs_j.items() if pd.notna(v)]
                if len(rs_data) >= 2:
                    rs_serie = [{
                        "type": "Baseline", "data": rs_data,
                        "options": {
                            "baseValue": {"type": "price", "price": konfig.RS_MIN},
                            "topLineColor": "#26a69a", "bottomLineColor": "#ef5350",
                            "topFillColor1": "rgba(38,166,154,0.28)",
                            "topFillColor2": "rgba(38,166,154,0.05)",
                            "bottomFillColor1": "rgba(239,83,80,0.05)",
                            "bottomFillColor2": "rgba(239,83,80,0.28)",
                            "lineWidth": 2, "priceLineVisible": False,
                            "lastValueVisible": True, "title": "RS-rating"},
                    }]
                    rs_chart = {
                        "height": 150,
                        "layout": {"background": {"type": "solid", "color": bg},
                                   "textColor": tekstfarge},
                        "grid": {"vertLines": {"color": grid},
                                 "horzLines": {"color": grid}},
                        "rightPriceScale": {"scaleMargins": {"top": 0.12, "bottom": 0.12},
                                            "borderVisible": False},
                        "timeScale": {"borderVisible": False, "rightOffset": 4},
                        "crosshair": {"mode": 0},
                    }
                    charts.append({"chart": rs_chart, "series": rs_serie})
            except Exception:
                pass

        # --- Omsetning + resultat (EPS) som egen delgraf ---
        # Søyler = kvartalsvis (eller årlig) resultat/netto (grønn ved overskudd,
        # rød ved underskudd) + omsetning som linje. Lar deg SE om bunnlinjen vokser
        # – Minervinis «andre bein». Fundamentaldata ligger på rapportdatoer, så vi
        # snapper hver verdi til nærmeste handelsdag i chartets vindu.
        if vis_eps and (eps_bars or oms_bars):
            try:
                def _snap(dato_iso):
                    # Nærmeste chart-dato (handelsdag) ≤ rapportdatoen, ellers første.
                    kand = [ti for ti in t if ti <= dato_iso]
                    return kand[-1] if kand else (t[0] if t else None)

                farge_opp = "rgba(38,166,154,0.7)"
                farge_ned = "rgba(239,83,80,0.7)"
                eps_data = []
                for dato_iso, verdi in (eps_bars or []):
                    ti = _snap(dato_iso)
                    if ti is None:
                        continue
                    eps_data.append({"time": ti, "value": round(float(verdi), 2),
                                     "color": farge_opp if verdi >= 0 else farge_ned})
                # Dedup på tid (LWC krever unike, stigende tider).
                sett_t, eps_rene = set(), []
                for pkt in sorted(eps_data, key=lambda x: x["time"]):
                    if pkt["time"] not in sett_t:
                        sett_t.add(pkt["time"])
                        eps_rene.append(pkt)

                oms_data = []
                for dato_iso, verdi in (oms_bars or []):
                    ti = _snap(dato_iso)
                    if ti is None:
                        continue
                    oms_data.append({"time": ti, "value": round(float(verdi), 2)})
                sett_o, oms_rene = set(), []
                for pkt in sorted(oms_data, key=lambda x: x["time"]):
                    if pkt["time"] not in sett_o:
                        sett_o.add(pkt["time"])
                        oms_rene.append(pkt)

                eps_serier = []
                if eps_rene:
                    eps_serier.append({
                        "type": "Histogram", "data": eps_rene,
                        "options": {"priceFormat": {"type": "volume"},
                                    "priceLineVisible": False, "lastValueVisible": True,
                                    "title": "Resultat"}})
                if oms_rene:
                    eps_serier.append({
                        "type": "Line", "data": oms_rene,
                        "options": {"color": "#42a5f5", "lineWidth": 2, "lineStyle": 0,
                                    "priceFormat": {"type": "volume"},
                                    "priceLineVisible": False, "lastValueVisible": True,
                                    "pointMarkersVisible": True, "title": "Omsetning"}})
                if eps_serier:
                    eps_chart = {
                        "height": 170,
                        "layout": {"background": {"type": "solid", "color": bg},
                                   "textColor": tekstfarge},
                        "grid": {"vertLines": {"color": grid},
                                 "horzLines": {"color": grid}},
                        "rightPriceScale": {"scaleMargins": {"top": 0.12, "bottom": 0.08},
                                            "borderVisible": False},
                        "timeScale": {"borderVisible": False, "rightOffset": 4},
                        "crosshair": {"mode": 0},
                    }
                    charts.append({"chart": eps_chart, "series": eps_serier})
            except Exception:
                pass
        return charts
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Hovedtabell
# ---------------------------------------------------------------------------
def _til_pivot_tekst(avstand_pivot) -> str:
    """Fortegnstall for hvor langt kursen er fra pivot (kjøpsnivået).

    avstand_pivot er positiv NÅR kursen er UNDER pivot. Vi snur fortegnet så det
    leses som avkastning: negativt = mangler så mange % på brudd, positivt = over
    pivot (allerede brutt). Ingen ord – bare tallet.
    """
    if pd.isna(avstand_pivot):
        return "—"
    return f"{-avstand_pivot:+.1f} %"


def _pivot_tall(tekst) -> float:
    """Henter tallet ut av en 'Til pivot'-tekst ('+1.1 %' → 1.1). NaN ved '—'."""
    if not isinstance(tekst, str) or tekst.strip() == "—":
        return float("nan")
    try:
        return float(tekst.replace("%", "").replace("+", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return float("nan")


def _live_verdi(v):
    """Plukker (pris, volum) ut av én live-oppføring, uansett format.

    Tåler både det nye formatet {"pris": .., "volum": ..} OG et gammelt/bufret
    format der verdien bare var prisen (float). Sistnevnte kan henge igjen i
    Streamlit Cloud sin cache rett etter en utrulling – da vil vi ikke krasje,
    bare vise pris uten live-volum. Ukjent/tomt gir (None, None).
    """
    if isinstance(v, dict):
        return v.get("pris"), v.get("volum")
    if isinstance(v, (int, float)):
        return float(v), None
    return None, None


def _signatur_kort(sig) -> str:
    """Kompakt volumsignatur til hovedlista: fem RVol-tall for dag −2 … +2.

    Midterste tall (indeks 2) = selve bruddagen. «–» = dag mangler (framtid for et
    ferskt brudd, eller før datastart), «—» = aksjen har ikke brutt pivot ennå.
    """
    if not isinstance(sig, list) or not sig:
        return "—"
    etter_offset = {e["offset"]: e["rvol"] for e in sig}
    biter = []
    for off in (-2, -1, 0, 1, 2):
        rv = etter_offset.get(off)
        biter.append("–" if rv is None else f"{rv:.1f}".replace(".", ","))
    return " ".join(biter)


def formater_tabell(df: pd.DataFrame, live: dict | None = None, naa_oslo=None, retrospektiv_dato: pd.Timestamp | None = None) -> pd.DataFrame:
    vis = pd.DataFrame()
    vis["Ticker"] = df["ticker"]
    vis["Pris"] = df["pris"]
    vis["Setup"] = df["status"] + " " + df["statustekst"]
    vis["Til pivot"] = df["avstand_pivot"].map(_til_pivot_tekst)
    if live:
        # Live-kurs og -volum per ticker. Vi bygger lister eksplisitt (i stedet for
        # .map med lambda) så det er robust mot både nytt/gammelt cache-format og
        # PyArrow-baserte kolonner. Tomt → NaN, så regnestykkene tåler hull.
        pris_liste, vol_liste = [], []
        for t in df["ticker"]:
            p, vol = _live_verdi(live.get(t))
            pris_liste.append(p)
            vol_liste.append(vol)
        pris_live = pd.to_numeric(pd.Series(pris_liste, index=df.index), errors="coerce")
        # Live avstand til pivot: samme fortegn-konvensjon som avstand_pivot
        # (positiv = under pivot), regnet fra DAGENS kurs mot lagret pivot.
        live_avst = (df["pivot"] - pris_live) / df["pivot"] * 100
        vis["Live"] = pris_live
        vis["Til pivot (live)"] = live_avst.map(_til_pivot_tekst)
        if naa_oslo is not None and "snittvolum50" in df.columns:
            vis["RVol (live)"] = [datamod.live_rvol(v, s, naa_oslo)
                                  for v, s in zip(vol_liste, df["snittvolum50"])]
    vis["Kriterie 1-7"] = df["score"].astype(str) + "/7"
    vis["RVol"] = df["rel_volum"] if "rel_volum" in df.columns else np.nan
    vis["Vol snitt50"] = (df["snittvolum50"].map(_stor_tall)
                          if "snittvolum50" in df.columns else "—")
    vis["Likviditet"] = (df["dagsomsetning"].map(_stor_tall)
                         if "dagsomsetning" in df.columns else "—")
    vis["Volum ±2"] = (df["volum_signatur"].map(_signatur_kort)
                       if "volum_signatur" in df.columns else "—")
    vis["RS"] = df["rs"]
    vis["Fra 52u høy"] = (df["pct_fra_52h"].map(lambda p: f"{p:+.1f}%" if pd.notna(p) else "—")
                          if "pct_fra_52h" in df.columns else "—")
    vis["Over 52u lav"] = (df["pct_over_52l"].map(lambda p: f"{p:+.0f}%" if pd.notna(p) else "—")
                           if "pct_over_52l" in df.columns else "—")
    if "golden_cross_dager" in df.columns:
        vis["GC"] = [_golden_cross_tekst(dg, ov)
                     for dg, ov in zip(df["golden_cross_dager"],
                                       df.get("golden_cross_over", [False] * len(df)))]
    scores = st.session_state.get("fund_scores", {})
    vis["Fund"] = df["ticker"].map(
        lambda t: (
            f"{scores[t]['merke']} {scores[t]['poeng']}/5"
            if t in scores and scores[t].get("tilgjengelig")
            else ("·" if t in scores else "")
        )
    )
    
    # Shares og MCAP: hentes via en LETTVEKTS, info-only sti (hent_aksjeinfo_cached)
    # som KUN kaller t.info. Det gjør kolonnene uavhengige av den tunge hent_fundamenta
    # (to resultatregnskap per ticker) som Yahoo rate-limiter lett ved bulk – det var
    # grunnen til at kolonnene ble tomme. Vi cacher IKKE None i session_state.
    shares_liste = []
    mcap_liste = []
    for t, pris in zip(df["ticker"], df["pris"]):
        sh = None
        try:
            sh = (hent_aksjeinfo_cached(t) or {}).get("utestaende")
        except Exception:
            sh = None
        shares_liste.append(_stor_tall(sh) if sh else "—")
        # MCAP = shares × pris (i native valuta)
        if sh and pris and sh > 0:
            mcap_liste.append(_stor_tall(sh * pris))
        else:
            mcap_liste.append("—")

    vis["Shares"] = shares_liste
    vis["MCAP"] = mcap_liste
    
    # Hvis bruker velger retrospektiv dato: legg til kursutvikling siden den dato
    if retrospektiv_dato is not None:
        priser_alle = last_priser(st.session_state.get("bors_navn", "Oslo Børs"), data_versjon(konfig.BORSER[st.session_state.get("bors_navn", "Oslo Børs")]))
        endre_liste = []
        peak_high_liste = []
        peak_low_liste = []
        for ticker, pris_pa_dato in zip(df["ticker"], df["pris"]):
            res = beregn_kursutvikling_siden_dato(priser_alle, ticker, retrospektiv_dato, pris_pa_dato)
            pct = res.get("pct_change")
            # Sjekk om det er et tall (float/int) som kan formateres
            try:
                endre_liste.append(f"{float(pct):+.1f}%" if isinstance(pct, (int, float)) and pct is not None else "—")
            except (TypeError, ValueError):
                endre_liste.append("—")
            
            ph = res.get("peak_high_pct")
            try:
                peak_high_liste.append(f"{float(ph):+.1f}%" if isinstance(ph, (int, float)) and ph is not None else "—")
            except (TypeError, ValueError):
                peak_high_liste.append("—")
            
            pl = res.get("peak_low_pct")
            try:
                peak_low_liste.append(f"{float(pl):+.1f}%" if isinstance(pl, (int, float)) and pl is not None else "—")
            except (TypeError, ValueError):
                peak_low_liste.append("—")
        
        vis["Endring %"] = endre_liste
        vis["Peak High %"] = peak_high_liste
        vis["Peak Low %"] = peak_low_liste
    
    vis["Uke"] = df["mtf_emoji"] if "mtf_emoji" in df else "⚠️"
    return vis


def stil_hovedtabell(vis: pd.DataFrame):
    """Fargelegger tabellen: grønn bakgrunn på fulle 7/7 og på høyt relativt volum.

    Sterk grønn = toppnivå (7/7 eller bruddvolum ≥ 1,4×), lys grønn = nesten der
    (6/7 eller volum over snittet). Returnerer en pandas Styler som st.dataframe
    tegner med farger – column_config styrer fortsatt format og hjelpetekster.
    """
    # Fargepalett som tilpasser seg tema. I mørkt tema er standard-teksten lys,
    # så vi må bruke MØRKE bakgrunner (ellers blir lys tekst på lys grønn uleselig).
    # I lyst tema beholder vi de luftige pastellfargene som før.
    if _er_morkt():
        sterk = "background-color:#1b5e20;color:#eaffea;font-weight:600"
        lys = "background-color:#2f4733;color:#eaffea"
        gul = "background-color:#5c4d12;color:#fff4c2"
        rod = "background-color:#5c2020;color:#ffd6d6"
    else:
        sterk = "background-color:#b7e4c7;color:#14321f;font-weight:600"
        lys = "background-color:#eaf7ec;color:#14321f"
        gul = "background-color:#fef9c3;color:#3f3a10"
        rod = "background-color:#fee2e2;color:#4a1414"

    def _krit(v):
        if v == "7/7":
            return sterk
        if v == "6/7":
            return lys
        return ""

    def _rvol(v):
        if pd.isna(v):
            return ""
        if v >= konfig.BRUDD_VOLUM_FAKTOR:
            return sterk
        if v >= 1.0:
            return lys
        return ""

    def _live(v):
        x = _pivot_tall(v)
        if pd.isna(x):
            return ""
        if x >= 0:            # dagens kurs er PÅ eller over pivot = bryter nå
            return sterk
        if x >= -2:           # innen 2 % under pivot = nærmer seg
            return lys
        return ""

    def _rvol_live(v):
        if pd.isna(v):
            return ""
        if v >= konfig.BRUDD_VOLUM_FAKTOR:
            return sterk
        if v >= 1.0:
            return lys
        return ""

    def _volsig(v):
        # Farger hele cellen etter bruddagen (midterste av de fem tallene).
        if not isinstance(v, str):
            return ""
        deler = v.split(" ")
        if len(deler) != 5:
            return ""
        try:
            x = float(deler[2].replace(",", "."))
        except ValueError:
            return ""
        if x >= konfig.BRUDD_VOLUM_FAKTOR:
            return sterk
        if x >= 1.0:
            return lys
        return ""

    def _fund_style(v):
        if not isinstance(v, str) or not v or v == "·":
            return ""
        if v.startswith("🟢"):
            return lys
        if v.startswith("🟡"):
            return gul
        if v.startswith("🔴"):
            return rod
        return ""

    styler = vis.style
    if "Kriterie 1-7" in vis.columns:
        styler = styler.map(_krit, subset=["Kriterie 1-7"])
    if "RVol" in vis.columns:
        styler = styler.map(_rvol, subset=["RVol"])
    if "Volum ±2" in vis.columns:
        styler = styler.map(_volsig, subset=["Volum ±2"])
    if "Fund" in vis.columns:
        styler = styler.map(_fund_style, subset=["Fund"])
    if "Til pivot (live)" in vis.columns:
        styler = styler.map(_live, subset=["Til pivot (live)"])
    if "RVol (live)" in vis.columns:
        styler = styler.map(_rvol_live, subset=["RVol (live)"])
    return styler


# Hjelpetekster på kolonneoverskriftene (så vi kan forenkle uten å miste info).
TABELL_HJELP = {
    "Pris": st.column_config.NumberColumn(
        "Pris", format="%.2f", help="Siste sluttkurs (NOK)."),
    "Live": st.column_config.NumberColumn(
        "Live", format="%.2f", help="Dagens kurs akkurat nå (Yahoo, ca. 15 min forsinket). "
        "Vises bare når «Live-kurser» er huket av i menyen til venstre."),
    "Til pivot (live)": st.column_config.TextColumn(
        "Til pivot (live)", help="Hvor langt DAGENS kurs er fra pivot. Negativt = mangler så "
        "mange % på brudd akkurat nå. Grønn = bryter eller nærmer seg pivot live."),
    "RVol (live)": st.column_config.NumberColumn(
        "RVol (live)", format="%.1f×",
        help="Rå live-faktor: dagens volum så langt delt på 50-dagers snitt – INGEN "
        "klokkeslett-justering. 0,1 = 10 % av et normalt dagsvolum omsatt hittil, 1,0 = "
        "allerede et helt dagsvolum. Tidlig på dagen er tallet naturlig lavt – vurder selv "
        "hvor langt på dagen vi er. Grønn ≥ 1,4×."),
    "Setup": st.column_config.TextColumn(
        "Setup", help="🟢 ferskt brudd (følg nå) · 🟡 brudd uten volum · "
        "⚪ klar/venter på brudd · 🔵 forlenget (for sent å jage)."),
    "Til pivot": st.column_config.TextColumn(
        "Til pivot", help="Hvor langt kursen er fra kjøpsnivået (pivot). "
        "Negativt = mangler så mange % på brudd. Positivt = allerede over pivot."),
    "Kriterie 1-7": st.column_config.TextColumn(
        "Kriterie 1-7", help="Hvor mange av Minervinis 7 trend-kriterier som er oppfylt akkurat nå. "
        "Grønn = 7/7 (full trend), lys grønn = 6/7."),
    "RVol": st.column_config.NumberColumn(
        "RVol", format="%.1f×",
        help="Relativt volum: siste dags volum delt på 50-dagers snitt. 1,0 = normalt. "
        "Grønn ≥ 1,4× = bruddvolum (Minervini vil se høyt volum når kursen bryter ut)."),
    "Vol snitt50": st.column_config.TextColumn(
        "Vol snitt50", help="50-dagers gjennomsnittlig dagsvolum (antall aksjer handlet per dag). "
        "Dette er baseline som både RVol og RVol (live) måles mot."),
    "Likviditet": st.column_config.TextColumn(
        "Likviditet", help="Gjennomsnittlig daglig omsetning i KRONER siste 20 dager (kurs × volum). "
        "Minervini unngår illikvide aksjer – høyere tall = lettere å kjøpe og selge uten å flytte "
        "kursen. Basisgulvet er allerede 500k; skru opp minstekravet i menyen til venstre for kun "
        "svært likvide aksjer."),
    "Volum ±2": st.column_config.TextColumn(
        "Volum ±2", help="Relativt volum rundt bruddet: dag −2, −1, 0 (brudd), +1, +2 mot "
        "50-dagers snitt. Minervini vil se volumet tørke inn før og eksplodere på bruddet. "
        "Midterste tall = bruddagen; grønn celle = bruddet kom på høyt volum (≥ 1,4×). "
        "«–» = dag mangler ennå, «—» = ikke brutt pivot ennå."),
    "RS": st.column_config.NumberColumn(
        "RS", help="Relativ styrke 1–99 (99 = sterkest momentum i universet)."),
    "Fra 52u høy": st.column_config.TextColumn(
        "Fra 52u høy", help="Hvor langt under 52-ukers høyeste kurs aksjen er (negativt = under "
        "toppen). Minervini vil se kursen innen 25 % av toppen (kriterium 7)."),
    "Over 52u lav": st.column_config.TextColumn(
        "Over 52u lav", help="Hvor langt over 52-ukers laveste kurs aksjen er. Minervini vil se "
        "minst 30 % over bunnen (kriterium 6)."),
    "GC": st.column_config.TextColumn(
        "GC", help="Golden cross (SMA50 over SMA200): ✨ = nylig bekreftet (krysset opp ≤ "
        "25 handelsdager siden), ✅ = i golden-cross-tilstand men krysset for lengre siden, "
        "«—» = SMA50 ligger under SMA200. Tallet = handelsdager siden siste golden cross."),
    "Fund": st.column_config.TextColumn(
        "Fund",
        help="Fundamental Minervini-score 0–5: 🟢 4–5 = sterk vekst ✅, 🟡 2–3 = godkjent, "
             "🔴 0–1 = svak. Kriterier: kvartalsvis salg ≥25 % + EPS ≥25 % + marginer opp + "
             "årsvis salg ≥15 % + EPS ≥15 %. Hentes når du åpner et chart (caches i 12 t). "
             "Tom = ikke sjekket ennå · '·' = ingen Yahoo-data (vanlig for små Oslo-aksjer)."),
    "Shares": st.column_config.TextColumn(
        "Shares", help="Antall aksjer utestående (millioner). Yahoo-data."),
    "MCAP": st.column_config.TextColumn(
        "MCAP", help="Estimert markedsverdi (native valuta). Beregnet som shares × siste sluttkurs."),
    "Uke": st.column_config.TextColumn(
        "Uke", help="Ukentlig (høyere tidsramme) trend: ✅ bekreftet opp, ⚠️ blandet, ❌ nedtrend."),
    "Endring %": st.column_config.TextColumn(
        "Endring %", help="Kursendring % siden analyseringsdatoen (kun ved retrospektiv analyse)."),
    "Peak High %": st.column_config.TextColumn(
        "Peak High %", help="Høyeste pris % over analyseringsdatoen siden da (kun ved retrospektiv analyse)."),
    "Peak Low %": st.column_config.TextColumn(
        "Peak Low %", help="Laveste pris % under analyseringsdatoen siden da (kun ved retrospektiv analyse)."),
}


# ---------------------------------------------------------------------------
# Selve siden
# ---------------------------------------------------------------------------
# Børs-velger + skann-knapp (sidefelt, helt øverst). Selve skanningen – som søker
# gjennom HELE børsen – skjer bare når du trykker knappen, ikke automatisk.
with st.sidebar:
    st.header("Marked")
    bors_navn = st.selectbox(
        "Børs", list(konfig.BORSER.keys()),
        help="Bytt børs. Hver børs har egne kursdata og sin egen RS-rating.")
    BORS = konfig.BORSER[bors_navn]
    VALUTA = BORS.valuta
    if st.button(f"🔍 Skann {BORS.navn}", type="primary", width="stretch",
                 help="Søk gjennom hele børsen. Hva det søkes etter styres av «Oppsett» "
                      "under Filtre (Minervini-template eller golden cross)."):
        st.session_state["skannet_bors"] = bors_navn
    st.divider()

skannet_na = st.session_state.get("skannet_bors") == bors_navn
st.session_state["bors_navn"] = bors_navn

st.title("📈 Screener")
st.caption(f"Marked: **{BORS.navn}** · valuta {BORS.valuta_navn}")

versjon = data_versjon(BORS)
if versjon == 0:
    st.warning(
        f"Fant ingen kursdata for **{BORS.navn}** ennå. Kjør roboten én gang "
        f"(se README, «Test roboten»), så fylles {BORS.priser_fil} og lista dukker opp. "
        f"Du kan bytte børs i menyen til venstre."
    )
    st.stop()

# --- Visuell bekreftelse på datastatus (øverst, alltid synlig) ---
_status = data_status(bors_navn, versjon)
if not _status["tom"]:
    _dekning = _status["aksjer_data"] / _status["aksjer_univ"] if _status["aksjer_univ"] else 0
    if _status["alder_dager"] <= 4:
        st.success(
            f"✅ **Data oppdatert** – siste handelsdag **{_status['siste_dato']:%d.%m.%Y}**. "
            f"Roboten henter automatisk hver hverdag kl. 17 (norsk tid), like etter børsslutt."
        )
    else:
        st.warning(
            f"⚠️ Nyeste data er fra **{_status['siste_dato']:%d.%m.%Y}** "
            f"({_status['alder_dager']} dager siden). Roboten kjører hver hverdag kl. 17 (norsk tid)."
        )
    _k1, _k2, _k3 = st.columns(3)
    _k1.metric("📅 Siste handelsdag", f"{_status['siste_dato']:%d.%m.%Y}",
               help="Dagen kursene i lista gjelder for – siste børsdag med ferdige sluttkurser.")
    _k2.metric("🏦 Aksjer med data", f"{_status['aksjer_data']} / {_status['aksjer_univ']}",
               help="Antall aksjer på denne børsen vi har kurshistorikk på, av hele universet.")
    _k3.metric("🕔 Sist hentet", f"{_status['sist_hentet']:%d.%m kl. %H:%M}",
               help="Da roboten sist lastet ned kurser fra Yahoo (norsk tid). Samme dag som siste "
                    "handelsdag på hverdager – kan være dagen før i helger/helligdager.")
    if _dekning < 0.9:
        st.info(
            f"ℹ️ Vi har foreløpig data på {_status['aksjer_data']} av {_status['aksjer_univ']} aksjer "
            f"({_dekning:.0%}). Nye tickere får full historikk automatisk ved neste robotkjøring."
        )
    st.divider()

# --- "Slik funker det" – kort forklaring, foldet sammen som standard ---
with st.expander("ℹ️ Slik funker screeneren (klikk for å lese)"):
    st.markdown(
        """
**Hva gjør denne siden?**  
Den leter automatisk gjennom hele børsen du har valgt etter aksjer som er i en sterk
opptrend og er i ferd med å ta **utbrudd** – altså bryte opp gjennom en motstand
på høyt volum. Metoden bygger på **Mark Minervinis** «trend template».

**De 7 kriteriene (kolonnen «Kriterie 1-7»)**  
Aksjen får ett poeng for hvert punkt. 7 av 7 = perfekt opptrend:
1. Kursen er **over** både MA150 og MA200 (glidende snitt for 150 og 200 dager).
2. MA150 ligger **over** MA200.
3. MA200 **peker oppover**.
4. MA50 ligger over MA150, og MA150 over MA200.
5. Kursen er **over** MA50.
6. Kursen er minst **30 %** over 52-ukers **bunn**.
7. Kursen er innen **25 %** av 52-ukers **topp**.

I tillegg krever oppsettet en god **RS-rating** (relativ styrke mot markedet).

**Fargene (status)**  
- 🟢 **Ferskt brudd** – aksjen brøt nettopp opp gjennom pivot på høyt volum. Mest interessant.
- 🟡 **Nær brudd** – ligger og presser rett under pivot. Følg med.
- 🔵 **I base** – bygger en sammentrekning (VCP), men er ikke klar ennå.
- ⚪ **Ingen pivot** – ingen tydelig utbruddskant akkurat nå.

**Pivot og stop**  
**Pivot** er kanten aksjen må bryte for å gi kjøpssignal. **Stop** er et forslag til
hvor du kutter tapet hvis bruddet feiler. Begge tegnes inn på chartet.

**De tre fanene**  
- 📋 **Hovedliste** – alle treff, sortert med de mest handlbare øverst. **Huk av rader** for å tegne chart rett under lista.
- 📊 **Chart** – tegn én aksje med MA-linjer, pivot, stop, volum og historikk.
- 🔎 **Søk** – slå opp hvilken som helst ticker (også utenfor børsen du har valgt, live fra Yahoo).

**Live-kurser (valgfritt)**  
Huker du av «🔴 Live-kurser» til venstre, vises dagens intradag-kurs (≈15 min forsinket)
ved siden av lista, så du ser hvem som nærmer seg pivot akkurat nå. Dette er kun til
visning og rører **aldri** kursdataene screeningen bygger på.

*Dette er et analyseverktøy, ikke en kjøpsanbefaling. Ta alltid egne vurderinger.*
        """
    )

# --- Sidefelt: filtre ---
GOLDEN_VALG = "✨ Golden Cross"
IPO_VALG = "🆕 Nye IPO-er"
with st.sidebar:
    st.header("Filtre")
    preset_navn = st.selectbox(
        "Oppsett", list(konfig.PRESETS.keys()) + [GOLDEN_VALG, IPO_VALG],
        help="Velg hva skanningen skal lete etter: Minervini-template (standard), "
             "golden cross (SMA50 over SMA200 + aksjer som venter på kryss), eller "
             "nye IPO-er (ferske noteringer med for kort historikk til full analyse).")
    er_golden = preset_navn == GOLDEN_VALG
    er_ipo = preset_navn == IPO_VALG
    # Trygt preset-navn for Minervini-analyser (chart/søk) også i golden-/ipo-modus.
    aktiv_preset_navn = konfig.STANDARD.navn if (er_golden or er_ipo) else preset_navn

    # Standardverdier så variablene finnes uansett modus.
    bruker_dato = None
    min_krit = konfig.STANDARD.krev_antall
    min_rs = 0
    min_oms_mill = 0.5
    kun_ferske = False
    krev_uke = False
    del_opp = False

    if er_golden:
        st.caption("✨ **Golden cross-modus** – leter etter SMA50 over SMA200 (bekreftet) "
                   "og aksjer rett under som nærmer seg et kryss. Minervini-filtrene under "
                   "er skrudd av i denne modusen.")
    elif er_ipo:
        st.caption("🆕 **Nye IPO-er** – ferske noteringer som ennå har for kort historikk "
                   f"(< {konfig.MIN_HANDELSDAGER} handelsdager) til full Minervini-analyse. "
                   "Her ser du hva som er på vei inn i universet og hvor mange dager til de "
                   "kvalifiserer. Minervini-filtrene under er skrudd av.")
    else:
        # Datovelger for retrospektiv screening (valgfritt)
        bruker_dato = st.date_input(
            "📅 Analyser en historisk dato",
            value=None,
            help="La stå tom for nåværende data. Velg en dato for å se hva screeningen fant "
                 "den dagen, med kursutvikling siden da.",
            max_value=pd.Timestamp.now()
        )

        min_krit = st.slider("Minimum antall kriterier", 0, 7, konfig.PRESETS[preset_navn].krev_antall)
        min_rs = st.slider("Minimum RS-rating", 0, 99, 0)
        min_oms_mill = st.slider(
            "Min. likviditet (mill./dag)", 0.5, 50.0, 0.5, 0.5,
            help="Snitt daglig omsetning (kurs × volum) siste 20 dager, i millioner kroner. "
                 "0,5 = ingen ekstra filtrering (basisgulvet er allerede 500k). Skru opp for kun "
                 "svært likvide aksjer som er lette å handle uten å flytte kursen.")
        kun_ferske = st.checkbox("Vis kun ferske brudd (🟢)", value=False)
        krev_uke = st.checkbox("Krev ukentlig bekreftelse (✅)", value=False,
                               help="Vis kun aksjer der også den ukentlige trenden peker opp.")
        del_opp = st.checkbox("📑 Del opp i tabeller per setup", value=True,
                              help="Vis fire separate tabeller – én for hver setup-status "
                                   "(🟢 bekreftet brudd · 🟡 brudd uten volum · ⚪ klar/venter · "
                                   "🔵 forlenget) – i stedet for én samlet liste.")
    st.divider()
    vis_live = st.checkbox("🔴 Live-kurser (≈15 min forsinket)", value=False,
                           help="Viser dagens intradag-kurs OG rått relativt volum (volum så langt "
                                "mot 50-dagers snitt) ved siden av lista, så du ser hvem som nærmer "
                                "seg pivot – og om det er volum på gang – akkurat nå. Rører ALDRI "
                                "dataene vi screener på.")
    _sh = _status.get("sist_hentet")
    if _sh is not None:
        st.caption(f"🕔 Sist hentet: {_sh:%d.%m.%Y kl. %H:%M} (norsk tid)")

# Hva skal skanningen lete etter? Styres av «Oppsett»-dropdownen.
if er_golden:
    gc_resultat = kjor_golden_cross(bors_navn, versjon) if skannet_na else None
    resultat = None
    ipo_resultat = None
elif er_ipo:
    ipo_resultat = kjor_nye_ipoer(bors_navn, versjon) if skannet_na else None
    gc_resultat = None
    resultat = None
else:
    gc_resultat = None
    ipo_resultat = None
    if bruker_dato:
        resultat = kjor_screening_retrospektiv(bors_navn, preset_navn, pd.Timestamp(bruker_dato), versjon)
    else:
        resultat = kjor_screening(bors_navn, preset_navn, versjon) if skannet_na else None

fane1, fane2, fane3, fane4 = st.tabs(["📋 Hovedliste", "📊 Chart", "🔎 Søk", "🌡️ Markedshelse"])

# Følg app-temaet i chartet (mørk bakgrunn i dark mode). Legges i chart-nøklene
# lenger nede så bildet tegnes på nytt når du bytter tema.
MORKT = _er_morkt()
TEMA = "d" if MORKT else "l"


# ---------------------------------------------------------------------------
# Golden cross-visning (brukes i Hovedliste-fanen når «✨ Golden Cross» er valgt)
# ---------------------------------------------------------------------------
def _formater_golden_cross_tabell(df: pd.DataFrame) -> pd.DataFrame:
    """Bygger visningstabellen for golden cross-screeneren."""
    vis = pd.DataFrame()
    vis["Ticker"] = df["ticker"]
    vis["Status"] = df["gc_status"].map({
        "✨": "✨ Fersk kryss", "✅": "✅ Etablert", "⏳": "⏳ Venter på kryss"})
    vis["Pris"] = df["pris"]
    vis["Gap SMA50-200"] = df["gap_pct"].map(
        lambda g: f"{g:+.1f}%" if pd.notna(g) else "—")
    # For ⏳ "venter" er krysset ikke skjedd ennå – da gir "dager siden" ingen mening.
    vis["Dager siden"] = [
        (f"{int(d)}d" if (pd.notna(d) and s != "⏳") else "—")
        for d, s in zip(df["golden_cross_dager"], df["gc_status"])
    ]
    vis["SMA50"] = df["sma50"]
    vis["SMA200"] = df["sma200"]
    vis["Fra 52u høy"] = df["pct_fra_52h"].map(
        lambda p: f"{p:+.1f}%" if pd.notna(p) else "—") if "pct_fra_52h" in df.columns else "—"
    vis["Over 52u lav"] = df["pct_over_52l"].map(
        lambda p: f"{p:+.0f}%" if pd.notna(p) else "—") if "pct_over_52l" in df.columns else "—"
    vis["RS"] = df["rs"]
    return vis


GC_TABELL_HJELP = {
    "Pris": st.column_config.NumberColumn("Pris", format="%.2f", help="Siste sluttkurs."),
    "SMA50": st.column_config.NumberColumn("SMA50", format="%.2f", help="50-dagers glidende snitt."),
    "SMA200": st.column_config.NumberColumn("SMA200", format="%.2f", help="200-dagers glidende snitt."),
    "Gap SMA50-200": st.column_config.TextColumn(
        "Gap SMA50-200", help="Hvor langt SMA50 er over (+) eller under (−) SMA200, i prosent. "
        "Positivt = golden cross aktivt. Negativt (men nær 0) = venter på kryss."),
    "Dager siden": st.column_config.TextColumn(
        "Dager siden", help="Handelsdager siden siste golden cross (SMA50 krysset opp over SMA200)."),
    "Status": st.column_config.TextColumn(
        "Status", help="✨ Fersk = krysset ≤ 25 dager siden · ✅ Etablert = over, men eldre kryss · "
        "⏳ Venter = SMA50 rett under SMA200 og nærmer seg et kryss."),
    "Fra 52u høy": st.column_config.TextColumn(
        "Fra 52u høy", help="Hvor langt under 52-ukers høyeste kurs aksjen er (negativt = under toppen)."),
    "Over 52u lav": st.column_config.TextColumn(
        "Over 52u lav", help="Hvor langt over 52-ukers laveste kurs aksjen er."),
    "RS": st.column_config.NumberColumn("RS", help="Relativ styrke 1–99 (99 = sterkest i universet)."),
}


def vis_golden_cross(gc_resultat):
    """Rendrer golden cross-tabellen + chart i Hovedliste-fanen (golden-modus)."""
    st.markdown("### ✨ Golden Cross-screener")
    st.caption("Leter etter aksjer der SMA50 har krysset opp over SMA200 (golden cross), "
               "pluss de som ligger rett under og nærmer seg et kryss. **Uavhengig av "
               "Minervini-templaten.**")
    if gc_resultat is None:
        st.info(f"Trykk **🔍 Skann {BORS.navn}** i menyen til venstre for å søke gjennom hele "
                "børsen etter golden cross. (Ingenting skannes automatisk – du velger når.)")
        return
    if gc_resultat.empty:
        st.info("Fant ingen golden cross (eller aksjer nær et kryss) akkurat nå.")
        return
    _antall = {
        "fersk": int((gc_resultat["gc_status"] == "✨").sum()),
        "venter": int((gc_resultat["gc_status"] == "⏳").sum()),
        "etablert": int((gc_resultat["gc_status"] == "✅").sum()),
    }
    st.markdown(
        f"**{len(gc_resultat)} treff** – ✨ {_antall['fersk']} ferske kryss · "
        f"⏳ {_antall['venter']} venter på kryss · ✅ {_antall['etablert']} etablerte. "
        "Sortert med ferske kryss øverst, så de som er nærmest et kryss."
    )
    _gc_tab = st.dataframe(
        _formater_golden_cross_tabell(gc_resultat),
        width="stretch", hide_index=True, height=560, column_config=GC_TABELL_HJELP,
        on_select="rerun", selection_mode="multi-row", key="golden_cross_tabell",
    )
    st.caption("💡 **Huk av én eller flere rader** for å tegne chart med golden cross-markører under.")

    _gc_rader = list(getattr(_gc_tab.selection, "rows", []) or [])
    _gc_valgte = [gc_resultat.iloc[i]["ticker"] for i in _gc_rader if i < len(gc_resultat)]
    if not _gc_valgte:
        st.caption("Ingen rader valgt ennå – huk av i tabellen over for å tegne chart her.")
        return
    st.divider()
    _maks = 15
    if len(_gc_valgte) > _maks:
        st.info(f"Viser de {_maks} første av {len(_gc_valgte)} valgte (for fartens skyld).")
        _gc_valgte = _gc_valgte[:_maks]
    st.subheader(f"📊 Chart for {len(_gc_valgte)} valgte")
    _gc_priser = last_priser(bors_navn, versjon)
    _gcc1, _gcc2 = st.columns([3, 1])
    with _gcc1:
        _gc_periode = st.radio("Periode (chart)", list(PERIODER_VALG.keys()), index=3,
                               horizontal=True, key="gc_periode")
    with _gcc2:
        _gc_tidsramme = st.radio("Tidsramme", ["Dag", "Uke"], horizontal=True, key="gc_tf",
                                 help="Uke = ukentlige barer (SMA50 = 50 uker, volum SMA10).")
    _gc_ukentlig = _gc_tidsramme == "Uke"
    with st.popover("⚙️ Tilpass chartene"):
        st.caption("Gjelder alle golden cross-chartene. Krysset vises som standard – det er jo poenget.")
        _gc_ma = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="gc_ma")
        _gc_52u = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="gc_52u")
        _gc_vcp = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=False, key="gc_vcp")
        _gc_7av7 = st.checkbox("7/7-markører (ble/mistet)", value=False, key="gc_7av7")
        _gc_hist = st.checkbox("Historiske volumbrudd", value=False, key="gc_hist")
        _gc_golden_v = st.checkbox("Golden cross (SMA50×SMA200)", value=True, key="gc_golden")
        _gc_indeks = st.checkbox(f"📉 Indeks-overlay ({BORS.benchmark})", value=False, key="gc_indeks",
                                 help="Legger indeksen oppå chartet, skalert til å starte likt med aksjen.")
        _gc_rs_rating = st.checkbox("📈 RS-rating over tid (1–99)", value=False, key="gc_rs_rating",
                                    help="Egen rute under chartet. Relativ styrke mot universet over tid.")
    _gc_rs_mat = rs_rating_historikk(bors_navn, versjon) if _gc_rs_rating else None
    _gc_indeks_serie = (datamod.serie_for(_gc_priser, BORS.benchmark) if _gc_indeks else None)
    for _tk in _gc_valgte:
        _s = datamod.serie_for(_gc_priser, _tk)
        _r = screener.analyser_ticker(_s, _tk, konfig.PRESETS[aktiv_preset_navn])
        st.markdown(f"**{_tk}**")
        if HAR_LWC:
            _rs_serie_gc = None
            if _gc_rs_mat is not None and _tk in _gc_rs_mat.columns:
                _rs_serie_gc = _gc_rs_mat[_tk].dropna()
            _spec = lag_chart_lwc(_s, _r, PERIODER_VALG[_gc_periode],
                                  vis_ma=_gc_ma, vis_52u=_gc_52u, vis_vcp=_gc_vcp,
                                  vis_7av7=_gc_7av7, vis_hist=_gc_hist, vis_golden=_gc_golden_v,
                                  vis_rs_rating=_gc_rs_rating, rs_rating=_rs_serie_gc,
                                  vis_indeks=_gc_indeks, indeks=_gc_indeks_serie,
                                  indeks_navn=BORS.benchmark, ukentlig=_gc_ukentlig,
                                  hoyde=460, morkt=MORKT, tittel=_tk)
            if _spec:
                renderLightweightCharts(_spec, key=f"gc_{_tk}_{_gc_periode}_{_gc_tidsramme}_{TEMA}")
        else:
            st.caption("Chart-komponenten er ikke lastet i dette miljøet ennå.")


def vis_nye_ipoer(ipo_resultat):
    """Viser ferske noteringer (for kort historikk til full Minervini-analyse).

    Tabell øverst med nøkkeltall (alder, dager igjen til kvalifisering, utvikling),
    og chart for radene brukeren huker av. Chartene bruker lag_chart_lwc uten de
    Minervini-lagene som krever lang historikk – candles, volum og MA så langt det
    rekker holder for en fersk notering.
    """
    st.subheader(f"🆕 Nye noteringer på {BORS.navn}")
    if ipo_resultat is None:
        st.info(f"Trykk **🔍 Skann {BORS.navn}** i menyen til venstre for å lete etter ferske "
                "noteringer. (Ingenting skannes automatisk – du velger når.)")
        return
    if ipo_resultat.empty:
        st.info(f"Fant ingen ferske noteringer akkurat nå – ingen aksjer med mellom "
                f"{getattr(konfig, 'IPO_MIN_DAGER', 20)} og {konfig.MIN_HANDELSDAGER} "
                "handelsdagers historikk i universet.")
        return
    st.caption(
        f"**{len(ipo_resultat)} ferske noteringer** med mindre enn {konfig.MIN_HANDELSDAGER} "
        "handelsdager – for kort til full Minervini-analyse. «Dager igjen» = handelsdager til "
        "aksjen kvalifiserer for den vanlige screeningen. Nyest øverst."
    )

    _vis = pd.DataFrame()
    _vis["Ticker"] = ipo_resultat["ticker"]
    _vis["Pris"] = ipo_resultat["pris"]
    _vis["Notert"] = ipo_resultat["forste_dato"]
    _vis["Handelsdager"] = ipo_resultat["antall_dager"]
    _vis["Dager igjen"] = ipo_resultat["dager_igjen"]
    _vis["Siden start"] = ipo_resultat["utvikling_pct"].map(
        lambda p: f"{p:+.1f}%" if pd.notna(p) else "—")
    _vis["Fra topp"] = ipo_resultat["fra_topp_pct"].map(
        lambda p: f"{p:+.1f}%" if pd.notna(p) else "—")

    _tab = st.dataframe(
        _vis, width="stretch", hide_index=True, height=440,
        on_select="rerun", selection_mode="multi-row", key="ipo_tabell",
    )
    st.caption("💡 **Huk av én eller flere rader** for å tegne chart av det som finnes av historikk.")

    _rader = list(getattr(_tab.selection, "rows", []) or [])
    _valgte = [ipo_resultat.iloc[i]["ticker"] for i in _rader if i < len(ipo_resultat)]
    if not _valgte:
        st.caption("Ingen rader valgt ennå – huk av i tabellen over for å tegne chart her.")
        return
    st.divider()
    _maks = 15
    if len(_valgte) > _maks:
        st.info(f"Viser de {_maks} første av {len(_valgte)} valgte.")
        _valgte = _valgte[:_maks]
    st.subheader(f"📊 Chart for {len(_valgte)} valgte")
    _ipo_priser = last_priser(bors_navn, versjon)
    for _tk in _valgte:
        _s = datamod.serie_for(_ipo_priser, _tk)
        st.markdown(f"**{_tk}**")
        if HAR_LWC:
            # Fersk notering: ingen pivot/VCP/7-7 (krever lang historikk). Vis bare
            # candles + volum + MA så langt det rekker, med hele historikken.
            _dager = len(_s.dropna(subset=["Close"])) if _s is not None else 0
            _spec = lag_chart_lwc(_s, None, max(_dager, 30),
                                  vis_ma=True, vis_52u=False, vis_vcp=False,
                                  vis_7av7=False, vis_hist=False, vis_golden=False,
                                  hoyde=420, morkt=MORKT, tittel=_tk)
            if _spec:
                renderLightweightCharts(_spec, key=f"ipo_{_tk}_{TEMA}")
            else:
                st.caption("For lite historikk til å tegne chart ennå.")
        else:
            st.caption("Chart-komponenten er ikke lastet i dette miljøet ennå.")


# --- Fane 1: Hovedliste ---
with fane1:
    if er_golden:
        vis_golden_cross(gc_resultat)
    elif er_ipo:
        vis_nye_ipoer(ipo_resultat)
    elif resultat is None:
        st.info(f"Trykk **🔍 Skann {BORS.navn}** i menyen til venstre for å søke gjennom hele "
                "børsen etter Minervini-treff. (Ingenting skannes automatisk – du velger når.)")
    elif resultat.empty:
        st.info("Screeningen ga ingen treff ennå. Har roboten fått hentet nok historikk?")
    else:
        # Ferske brudd (🟢) vises ALLTID – selv om de har færre enn valgt antall kriterier,
        # så du aldri går glipp av et akkurat utløst kjøpssignal.
        filt = resultat[(resultat["score"] >= min_krit) | (resultat["status"] == "🟢")].copy()
        filt = filt[filt["rs"].fillna(0) >= min_rs]
        if min_oms_mill > 0.5 and "dagsomsetning" in filt.columns:
            filt = filt[filt["dagsomsetning"].fillna(0) >= min_oms_mill * 1e6]
        if kun_ferske:
            filt = filt[filt["status"] == "🟢"]
        if krev_uke:
            filt = filt[filt["mtf_status"] == "bullish"]

        # Standardsortering: mest handlbart øverst – status (🟢→🟡→⚪ klar→🔵 forlenget),
        # deretter nærhet til pivot. Ren, objektiv rekkefølge (ingen oppfunne vekter).
        # getattr-fallback så appen ikke krasjer om Streamlit Cloud kjører en gammel,
        # bufret utgave av screener-modulen (kan skje det første minuttet etter utrulling).
        _sorter = getattr(screener, "sorter_hovedliste", None)
        if _sorter is not None:
            filt = _sorter(filt)
        elif not filt.empty:
            _har_pivot = filt["pivot"].notna()
            filt = filt.assign(
                _rang=filt["status"].map({"🟢": 0, "🟡": 1, "⚪": 2, "🔵": 3}).fillna(4).astype(int),
                _naer=filt["avstand_pivot"].abs(),
            )
            filt.loc[~_har_pivot, "_rang"] = 5
            filt.loc[~_har_pivot, "_naer"] = float("inf")
            filt = (filt.sort_values(["_rang", "_naer"], kind="mergesort")
                        .drop(columns=["_rang", "_naer"]))

        # Pre-hent fundamental scores for alle tickers i resultatet,
        # så Fund-kolonnen kan vises immediately i tabellen.
        prefetch_fund_scores(filt["ticker"].tolist())
        
        # Live-kurser (valgfritt): hentes helt adskilt og påvirker ALDRI screening-dataene.
        live_priser = {}
        naa_oslo = pd.Timestamp.now(tz="Europe/Oslo")
        if vis_live and not filt.empty:
            live_priser = hent_live_priser(tuple(filt["ticker"].head(80).tolist()))

        # Lastes én gang her, så hver tabell-gruppe kan tegne chart uten å laste på nytt.
        _priser_alle_hl = last_priser(bors_navn, versjon)

        # Felles chart-innstillinger for alle tabell-chartene (samme som Chart-fanen).
        _ch1, _ch2 = st.columns([3, 1])
        with _ch1:
            _hl_periode = st.radio("Periode (chart)", list(PERIODER_VALG.keys()), index=3,
                                   horizontal=True, key="hl_periode")
        with _ch2:
            _hl_tidsramme = st.radio("Tidsramme", ["Dag", "Uke"], horizontal=True, key="hl_tf",
                                     help="Uke = ukentlige barer (SMA50 = 50 uker, volum SMA10).")
        _hl_ukentlig = _hl_tidsramme == "Uke"
        with st.popover("⚙️ Tilpass tabell-chartene"):
            st.caption("Gjelder alle chartene som tegnes når du huker av rader. Færre lag = renere bilde.")
            _hl_ma = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="hl_ma")
            _hl_52u = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="hl_52u")
            _hl_vcp = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=True, key="hl_vcp")
            _hl_7av7 = st.checkbox("7/7-markører (ble/mistet)", value=True, key="hl_7av7")
            _hl_hist = st.checkbox("Historiske volumbrudd", value=False, key="hl_hist")
            _hl_golden = st.checkbox("Golden cross (SMA50×SMA200)", value=False, key="hl_golden")
            _hl_indeks = st.checkbox(f"📉 Indeks-overlay ({BORS.benchmark})", value=False,
                                     key="hl_indeks",
                                     help="Legger indeksen oppå chartet, skalert til å starte likt "
                                          "med aksjen. Faller indekslinjen mens candlene står støtt, "
                                          "holdt aksjen seg sterkere enn markedet.")
            _hl_rs_rating = st.checkbox("📈 RS-rating over tid (1–99)", value=False,
                                        key="hl_rs_rating",
                                        help="Egen rute under hvert chart. Viser hvordan skanne-tallet "
                                             "(relativ styrke mot universet) har beveget seg. "
                                             "Grønt over 70 = blant de sterkeste, rødt under.")
        # Tunge data hentes kun når lagene faktisk er på.
        _hl_rs_mat = rs_rating_historikk(bors_navn, versjon) if _hl_rs_rating else None
        _hl_indeks_serie = (datamod.serie_for(_priser_alle_hl, BORS.benchmark)
                            if _hl_indeks else None)

        def _vis_gruppe_tabell(df_gruppe, nokkel):
            """Rendrer én tabell + chart for radene brukeren huker av.

            Brukes både for den samlede lista (nokkel='alle') og for hver av de fire
            setup-gruppene når «Del opp i tabeller per setup» er huket av. `nokkel` gjør
            dataframe- og chart-nøklene unike så Streamlit ikke blander gruppene.
            """
            if df_gruppe.empty:
                st.caption("Ingen aksjer i denne gruppen akkurat nå.")
                return
            _tab = st.dataframe(
                stil_hovedtabell(formater_tabell(df_gruppe, live_priser or None, naa_oslo,
                                 retrospektiv_dato=pd.Timestamp(bruker_dato) if bruker_dato else None)),
                width="stretch", hide_index=True, height=560, column_config=TABELL_HJELP,
                on_select="rerun", selection_mode="multi-row", key=f"hovedliste_tabell_{nokkel}",
            )
            _rader = list(getattr(_tab.selection, "rows", []) or [])
            _valgte = [df_gruppe.iloc[i]["ticker"] for i in _rader if i < len(df_gruppe)]
            if not _valgte:
                st.caption("Ingen rader valgt ennå – huk av i tabellen over for å tegne chart her.")
                return
            st.divider()
            _maks = 15
            if len(_valgte) > _maks:
                st.info(f"Viser de {_maks} første av {len(_valgte)} valgte (for fartens skyld).")
                _valgte = _valgte[:_maks]
            st.subheader(f"📊 Chart for {len(_valgte)} valgte")
            for _tk in _valgte:
                _s = datamod.serie_for(_priser_alle_hl, _tk)
                _r = screener.analyser_ticker(_s, _tk, konfig.PRESETS[aktiv_preset_navn])
                _lp, _ = _live_verdi(live_priser.get(_tk))
                _live_txt = f" · 🔴 live ≈ {_lp:.2f}" if _lp is not None else ""
                if _r is None:
                    st.markdown(f"**{_tk}**")
                    st.caption("For lite historikk til å tegne chart.")
                    continue
                st.markdown(f"**{_tk}** — {_r['status']} {_r['statustekst']}{_live_txt}")
                if HAR_LWC:
                    _rs_serie_hl = None
                    if _hl_rs_mat is not None and _tk in _hl_rs_mat.columns:
                        _rs_serie_hl = _hl_rs_mat[_tk].dropna()
                    _spec = lag_chart_lwc(_s, _r, PERIODER_VALG[_hl_periode],
                                          vis_ma=_hl_ma, vis_52u=_hl_52u, vis_vcp=_hl_vcp,
                                          vis_7av7=_hl_7av7, vis_hist=_hl_hist, vis_golden=_hl_golden,
                                          vis_rs_rating=_hl_rs_rating, rs_rating=_rs_serie_hl,
                                          vis_indeks=_hl_indeks, indeks=_hl_indeks_serie,
                                          indeks_navn=BORS.benchmark, ukentlig=_hl_ukentlig,
                                          hoyde=460, morkt=MORKT, tittel=_tk)
                    if _spec:
                        renderLightweightCharts(_spec, key=f"hl_{nokkel}_{_tk}_{_hl_periode}_{_hl_tidsramme}_{TEMA}")

        if del_opp:
            # Fire separate tabeller – én per setup-status, i handlbar rekkefølge.
            st.markdown(f"**{len(filt)} aksjer** – delt opp i fire tabeller per setup-status.")
            _NOKKEL = {"🟢": "gronn", "🟡": "gul", "⚪": "klar", "🔵": "blaa"}
            _grupper = [
                ("🟢", "Bekreftet brudd", "krysset pivot på høyt volum – følg nå"),
                ("🟡", "Brudd uten volum", "krysset pivot, men mangler volumbekreftelse"),
                ("⚪", "Klar / venter", "bygger base under pivot – venter på brudd"),
                ("🔵", "Forlenget", "for langt over pivot / for lenge siden – ikke jag"),
            ]
            for _emoji, _tittel, _forkl in _grupper:
                _gr = filt[filt["status"] == _emoji]
                st.markdown(f"### {_emoji} {_tittel} ({len(_gr)})")
                st.caption(_forkl)
                _vis_gruppe_tabell(_gr, nokkel=_NOKKEL[_emoji])
                st.divider()
        else:
            st.markdown(
                f"**{len(filt)} aksjer** – sortert med de mest handlbare øverst: ferske brudd (🟢) "
                f"først, så de som er nærmest et brudd. Ferske brudd vises alltid, også under {min_krit}/7."
            )
            _vis_gruppe_tabell(filt, nokkel="alle")
            st.caption("Øverst = skjer nå / nærmest brudd. **Til pivot**: negativt = mangler så mange % "
                       "på brudd, positivt = over pivot. **Grønt** = 7/7 eller bruddvolum (≥1,4×). "
                       "💡 **Huk av én eller flere rader** (venstre kant) for å se chartene nederst.")

# --- Fane 2: Chart ---
with fane2:
    if not HAR_LWC:
        st.warning("Chart-komponenten er ikke lastet i dette miljøet ennå (kommer ved neste utrulling).")
    elif resultat is None:
        st.info(f"Trykk **🔍 Skann {BORS.navn}** i menyen til venstre for å velge blant treffene her.")
    elif resultat.empty:
        st.info("Ingen treff å velge mellom ennå.")
    else:
        valg = st.selectbox("Velg aksje", resultat["ticker"].tolist())
        _c1, _c2 = st.columns([3, 1])
        with _c1:
            periode = st.radio("Periode", list(PERIODER_VALG.keys()), index=3, horizontal=True,
                               key="periode_chart")
        with _c2:
            tidsramme = st.radio("Tidsramme", ["Dag", "Uke"], horizontal=True, key="tf_chart",
                                 help="Uke = ukentlige barer. Da blir SMA50 = 50 uker og "
                                      "volumsnittet SMA10 (10 uker).")
        ukentlig = tidsramme == "Uke"
        with st.popover("⚙️ Tilpass chartet"):
            st.caption("Huk av hva du vil se. Færre lag = renere bilde.")
            vis_ma = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="chart_ma")
            vis_52u = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="chart_52u")
            vis_vcp = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=True, key="chart_vcp")
            vis_7av7 = st.checkbox("7/7-markører (ble/mistet)", value=True, key="chart_7av7")
            vis_hist = st.checkbox("Historiske volumbrudd", value=False, key="chart_hist")
            vis_golden = st.checkbox("Golden cross (SMA50×SMA200)", value=False, key="chart_golden")
            vis_indeks = st.checkbox(f"📉 Indeks-overlay ({BORS.benchmark})", value=False,
                                     key="chart_indeks",
                                     help="Legger indeksen OPPÅ chartet, skalert til å starte likt "
                                          "med aksjen. Faller indekslinjen mens candlene står støtt, "
                                          "holdt aksjen seg sterkere enn markedet.")
            vis_rs_rating = st.checkbox("📈 RS-rating over tid (1–99)", value=False,
                                        key="chart_rs_rating",
                                        help="Egen rute under chartet. Viser hvordan skanne-tallet "
                                             "(IBD-vektet relativ styrke mot hele universet) har beveget seg. "
                                             "Persentil mot DETTE universet, ikke globalt IBD-tall. "
                                             "Grønt over 70 = blant de sterkeste, rødt under. "
                                             "Høyre kant = dagens RS-rating.")
            vis_eps = st.checkbox("💰 Omsetning/resultat (EPS)", value=False,
                                  key="chart_eps",
                                  help="Egen rute under chartet med kvartalsvis (eller årlig) "
                                       "omsetning (blå linje) og resultat/bunnlinje (søyler – grønn "
                                       "overskudd, rød underskudd). Minervinis «andre bein»: vokser "
                                       "inntjeningen? Hentes fra Yahoo (små aksjer kan mangle data).")
        serie = datamod.serie_for(last_priser(bors_navn, versjon), valg)
        res = screener.analyser_ticker(serie, valg, konfig.PRESETS[aktiv_preset_navn])
        if res is None:
            st.info("For lite historikk til å tegne chart for denne aksjen.")
        else:
            # RS-rating (1–99) fra skanningen for nettopp denne aksjen.
            _rs_rad = resultat[resultat["ticker"] == valg]
            if not _rs_rad.empty and pd.notna(_rs_rad.iloc[0].get("rs")):
                _rsv = int(_rs_rad.iloc[0]["rs"])
                _cR, _ = st.columns([1, 3])
                _cR.metric("RS-rating", f"{_rsv}/99",
                           help="IBD-vektet relativ styrke (40 % siste 3 mnd + 20 % hver "
                                "av 6/9/12 mnd), rangert som persentil mot alle aksjene i "
                                f"DETTE universet ({BORS.navn}) – ikke mot hele verdensmarkedet "
                                "slik IBD-tallet i avisen er. 70+ = sterkere enn 70 % av "
                                "aksjene her. Huk av «RS-rating over tid» i ⚙️ for forløpet.")
            _init_posisjon_state(res, f"chart_{valg}")
            pos, pos_suffix = _posisjon_fra_state(f"chart_{valg}")
            _rs_serie = None
            if vis_rs_rating:
                _rs_mat = rs_rating_historikk(bors_navn, versjon)
                if valg in _rs_mat.columns:
                    _rs_serie = _rs_mat[valg].dropna()
            _indeks = datamod.serie_for(last_priser(bors_navn, versjon), BORS.benchmark) if vis_indeks else None
            _eps_bars = _oms_bars = None
            _graf_basis = "kvartal"
            _graf_valuta = ""
            if vis_eps:
                _f = hent_fundamenta_cached(valg)
                _eps_bars = _f.get("eps_verdier")
                _oms_bars = _f.get("oms_verdier")
                _graf_basis = _f.get("graf_basis", "kvartal")
                _graf_valuta = _f.get("valuta") or ""
            spec = lag_chart_lwc(serie, res, PERIODER_VALG[periode],
                                 vis_ma=vis_ma, vis_52u=vis_52u, vis_vcp=vis_vcp,
                                 vis_7av7=vis_7av7, vis_hist=vis_hist, vis_golden=vis_golden,
                                 vis_rs_rating=vis_rs_rating, rs_rating=_rs_serie,
                                 vis_indeks=vis_indeks, indeks=_indeks, indeks_navn=BORS.benchmark,
                                 ukentlig=ukentlig, pos=pos, morkt=MORKT, tittel=valg,
                                 vis_eps=vis_eps, eps_bars=_eps_bars, oms_bars=_oms_bars,
                                 graf_basis=_graf_basis, graf_valuta=_graf_valuta)
            if spec is None:
                st.info("Klarte ikke bygge chartet for denne aksjen.")
            else:
                noekkel = f"chart_{valg}_{periode}_{tidsramme}_{vis_ma}{vis_52u}{vis_vcp}{vis_7av7}{vis_hist}{vis_golden}{vis_rs_rating}{vis_indeks}{vis_eps}{pos_suffix}_{TEMA}"
                renderLightweightCharts(spec, key=noekkel)
                st.caption("💡 Dra sidelengs, rull musehjulet for å zoome, dra loddrett på "
                           "prisaksen for å strekke høyden. 🟡 **Kraftig gull = aktiv pivot** · "
                           "🔴 stiplet rød = stop · 🟢/🔴 pil = ble/mistet 7/7. Svake stiplede "
                           "gull-streker = historiske brudd (ubiased).")
                if vis_eps:
                    _basis_ord = "kvartalsvis" if _graf_basis == "kvartal" else "årlig"
                    _val = f" ({_graf_valuta})" if _graf_valuta else ""
                    st.caption(f"💰 Nederste rute: {_basis_ord} **omsetning** (blå linje) og "
                               f"**resultat**{_val} (søyler – grønn overskudd, rød underskudd). "
                               "Snappet til nærmeste handelsdag. Tom = Yahoo mangler regnskap.")
                vis_vcp_boks(res)
                fundamenta_seksjon(valg, f"chart_{valg}")
                st.divider()
                posisjon_verktoy(res, f"chart_{valg}", VALUTA)

# --- Fane 3: Søk ---
with fane3:
    st.markdown("Slå opp **hvilken som helst** ticker. Er den ikke i universet, hentes den live fra Yahoo.")
    sok = st.text_input("Ticker (f.eks. EQNR.OL, AAPL, NVDA)", value="").strip().upper()
    if sok:
        priser = last_priser(bors_navn, versjon)
        if sok in priser["Ticker"].values:
            serie = datamod.serie_for(priser, sok)
        else:
            with st.spinner(f"Henter {sok} live ..."):
                serie = datamod.hent_live(sok)
        if serie is None or serie.empty:
            st.error(f"Fant ingen data for «{sok}». Sjekk at tickeren er riktig skrevet.")
        else:
            res = screener.analyser_ticker(serie, sok, konfig.PRESETS[aktiv_preset_navn])
            if res is None:
                st.info("For lite historikk (trenger ~200 handelsdager) til full analyse.")
            else:
                st.subheader(f"{sok} · {res['score']}/7 · {res['status']} {res['statustekst']}")
                _s1, _s2 = st.columns([3, 1])
                with _s1:
                    periode3 = st.radio("Periode", list(PERIODER_VALG.keys()), index=3,
                                        horizontal=True, key="periode_sok")
                with _s2:
                    tidsramme3 = st.radio("Tidsramme", ["Dag", "Uke"], horizontal=True, key="tf_sok",
                                          help="Uke = ukentlige barer (SMA50 = 50 uker, volum SMA10).")
                ukentlig3 = tidsramme3 == "Uke"
                with st.popover("⚙️ Tilpass chartet"):
                    st.caption("Huk av hva du vil se. Færre lag = renere bilde.")
                    vis_ma3 = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="sok_ma")
                    vis_52u3 = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="sok_52u")
                    vis_vcp3 = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=True, key="sok_vcp")
                    vis_7av7_3 = st.checkbox("7/7-markører (ble/mistet)", value=True, key="sok_7av7")
                    vis_hist3 = st.checkbox("Historiske volumbrudd", value=False, key="sok_hist")
                    vis_golden3 = st.checkbox("Golden cross (SMA50×SMA200)", value=False, key="sok_golden")
                    vis_indeks3 = st.checkbox(f"📉 Indeks-overlay ({BORS.benchmark})", value=False,
                                              key="sok_indeks",
                                              help="Legger indeksen oppå chartet, skalert til å starte "
                                                   "likt. Ser du om aksjen holdt seg når indeksen falt.")
                    vis_rs_rating3 = st.checkbox("📈 RS-rating over tid (1–99)", value=False,
                                                 key="sok_rs_rating",
                                                 help="Egen rute under chartet. Hvordan skanne-tallet "
                                                      "(relativ styrke mot universet) har beveget seg. "
                                                      "Kun for aksjer i universet. Grønt over 70 = sterk.")
                if not HAR_LWC:
                    st.warning("Chart-komponenten er ikke lastet i dette miljøet ennå.")
                else:
                    _init_posisjon_state(res, f"sok_{sok}")
                    pos3, pos_suffix3 = _posisjon_fra_state(f"sok_{sok}")
                    _rs_serie3 = None
                    if vis_rs_rating3:
                        _rs_mat3 = rs_rating_historikk(bors_navn, versjon)
                        if sok in _rs_mat3.columns:
                            _rs_serie3 = _rs_mat3[sok].dropna()
                    _indeks3 = datamod.serie_for(last_priser(bors_navn, versjon), BORS.benchmark) if vis_indeks3 else None
                    spec3 = lag_chart_lwc(serie, res, PERIODER_VALG[periode3],
                                          vis_ma=vis_ma3, vis_52u=vis_52u3, vis_vcp=vis_vcp3,
                                          vis_7av7=vis_7av7_3, vis_hist=vis_hist3, vis_golden=vis_golden3,
                                          vis_rs_rating=vis_rs_rating3, rs_rating=_rs_serie3,
                                          vis_indeks=vis_indeks3, indeks=_indeks3, indeks_navn=BORS.benchmark,
                                          ukentlig=ukentlig3, pos=pos3, morkt=MORKT, tittel=sok)
                    if spec3 is not None:
                        renderLightweightCharts(
                            spec3,
                            key=f"sok_{sok}_{periode3}_{tidsramme3}_{vis_ma3}{vis_52u3}{vis_vcp3}{vis_7av7_3}{vis_hist3}{vis_golden3}{vis_rs_rating3}{vis_indeks3}{pos_suffix3}_{TEMA}")
                vis_vcp_boks(res)
                fundamenta_seksjon(sok, f"sok_{sok}")
                st.divider()
                posisjon_verktoy(res, f"sok_{sok}", VALUTA)


# --- Fane 4: Markedshelse (sektorstyrke) ---
with fane4:
    st.subheader(f"🌡️ Markedshelse – sektorstyrke på {BORS.navn}")
    st.markdown(
        "O'Neil: *~halvparten av en aksjes bevegelse skyldes gruppen den tilhører.* "
        "Du vil eie den **sterkeste aksjen i den sterkeste sektoren** – ikke en sterk "
        "aksje i en død sektor. Her rangeres sektorene etter samlet relativ styrke, "
        "og du kan bore ned til **lederne** i hver."
    )

    # Sektor-oversikten bygger på RS + score for HELE universet. Bruk en standard
    # Minervini-screening (cachet) uansett hvilken modus «Oppsett» står i, så fanen
    # alltid har noe å vise etter en skanning.
    if not skannet_na:
        st.info(f"Trykk **🔍 Skann {BORS.navn}** i menyen til venstre først – så regner "
                "jeg sektorstyrken ut fra relativ styrke i hele universet.")
    else:
        _mh = kjor_screening(bors_navn, konfig.STANDARD.navn, versjon)
        if _mh is None or _mh.empty or "rs" not in _mh.columns:
            st.info("Fant ikke nok data til å regne sektorstyrke ennå.")
        else:
            st.caption(
                "💡 Sektor hentes fra Yahoo første gang (tar litt tid for hele børsen), "
                "deretter er det bufret i et døgn. Små Growth/Expand-aksjer uten "
                "sektordata hos Yahoo holdes utenfor rangeringen."
            )
            _hent = st.button("🏭 Hent / oppdater sektorstyrke", key="mh_hent")
            if _hent or st.session_state.get("mh_vist"):
                st.session_state["mh_vist"] = True
                _tickere = tuple(sorted(_mh["ticker"].dropna().astype(str).tolist()))
                _oppslag = sektor_oppslag(bors_navn, _tickere)
                if not _oppslag:
                    st.warning("Yahoo ga ingen sektordata for dette universet akkurat nå. "
                               "Prøv igjen senere.")
                else:
                    _ov = sektor.sektor_oversikt(_mh, _oppslag)
                    if _ov.empty:
                        st.info("For få aksjer med kjent sektor til en meningsfull rangering ennå.")
                    else:
                        _dekning = len(_oppslag)
                        st.caption(f"Sektor funnet for **{_dekning}** av {len(_tickere)} aksjer · "
                                   f"**{len(_ov)}** sektorer rangert.")

                        # --- Heatmap: horisontale barer farget etter sektor-RS ---
                        import altair as alt
                        _kilde = _ov.rename(columns={
                            "sektor": "Sektor", "sektor_rs": "Sektor-RS",
                            "antall": "Antall", "andel_sterke": "Andel sterke",
                            "andel_trend": "Andel i trend"})
                        _chart = (
                            alt.Chart(_kilde)
                            .mark_bar(cornerRadiusEnd=4)
                            .encode(
                                x=alt.X("Sektor-RS:Q", title="Sektor-RS (1–99)",
                                        scale=alt.Scale(domain=[0, 100])),
                                y=alt.Y("Sektor:N", sort="-x", title=None),
                                color=alt.Color("Sektor-RS:Q",
                                                scale=alt.Scale(scheme="redyellowgreen",
                                                                domain=[0, 100]),
                                                legend=None),
                                tooltip=["Sektor", "Sektor-RS", "Antall",
                                         "Andel sterke", "Andel i trend"],
                            )
                            .properties(height=max(220, 34 * len(_ov)))
                        )
                        st.altair_chart(_chart, use_container_width=True)

                        # --- Full tabell med nøkkeltall ---
                        _vis = _ov.copy()
                        _vis = _vis.rename(columns={
                            "sektor": "Sektor", "sektor_rs": "Sektor-RS", "antall": "Antall",
                            "rs_median": "RS median", "rs_snitt": "RS snitt",
                            "antall_sterke": "Sterke (RS≥70)", "andel_sterke": "Andel sterke %",
                            "antall_trend": "I trend (7/7)", "andel_trend": "Andel trend %"})
                        st.dataframe(_vis, width="stretch", hide_index=True,
                                     key="mh_sektor_tabell")

                        # --- Tidslinje: sektorstyrke historisk (hvem har ledet?) ---
                        st.divider()
                        st.markdown("### 📈 Sektorstyrke over tid")
                        st.caption(
                            "Median RS-rating per sektor for hver dag bakover – ser du "
                            "**rotasjonen**: en linje som klatrer tar ledelsen, en som "
                            "faller taper styrke. Velg hvilke sektorer du vil følge."
                        )
                        _rs_mat = rs_rating_historikk(bors_navn, versjon)
                        _hist = sektor.sektor_historikk(_rs_mat, _oppslag, glatting=10) \
                            if (_rs_mat is not None and not _rs_mat.empty) else pd.DataFrame()
                        if _hist.empty:
                            st.caption("Ikke nok RS-historikk til en tidslinje ennå.")
                        else:
                            _c1, _c2 = st.columns([3, 1])
                            with _c1:
                                # Standard: de 5 sterkeste sektorene nå (fra rangeringen).
                                _standard = _ov["sektor"].head(5).tolist()
                                _valgte_sekt = st.multiselect(
                                    "Sektorer å vise", list(_hist.columns),
                                    default=[s for s in _standard if s in _hist.columns],
                                    key="mh_tidslinje_sektorer")
                            with _c2:
                                _mnd = st.radio("Periode", ["1 år", "2 år", "Alt"],
                                                index=1, key="mh_tidslinje_periode")
                            if _valgte_sekt:
                                _h = _hist[_valgte_sekt].copy()
                                if _mnd != "Alt":
                                    _dager = 252 if _mnd == "1 år" else 504
                                    _h = _h.iloc[-_dager:]
                                _lang = (_h.reset_index()
                                         .melt(id_vars=_h.index.name or "index",
                                               var_name="Sektor", value_name="RS"))
                                _tidkol = _h.index.name or "index"
                                _lang = _lang.rename(columns={_tidkol: "Dato"})
                                _lang["Dato"] = pd.to_datetime(_lang["Dato"])
                                import altair as alt
                                _linje = (
                                    alt.Chart(_lang)
                                    .mark_line(interpolate="monotone")
                                    .encode(
                                        x=alt.X("Dato:T", title=None),
                                        y=alt.Y("RS:Q", title="Median RS",
                                                scale=alt.Scale(domain=[0, 100])),
                                        color=alt.Color("Sektor:N", title="Sektor"),
                                        tooltip=["Dato:T", "Sektor:N",
                                                 alt.Tooltip("RS:Q", format=".0f")],
                                    )
                                    .properties(height=340)
                                )
                                # Referanselinje ved 50 (midt på universet).
                                _ref = (alt.Chart(pd.DataFrame({"y": [50]}))
                                        .mark_rule(strokeDash=[4, 4], color="#9e9e9e")
                                        .encode(y="y:Q"))
                                st.altair_chart(_ref + _linje, use_container_width=True)
                                st.caption("Stiplet grå linje = 50 (midt på universet). "
                                           "Over = sterkere enn snittaksjen, under = svakere. "
                                           "Linjene er 10-dagers glattet for å dempe støy.")

                        st.divider()
                        # --- Drill-down: lederne i valgt sektor ---
                        st.markdown("### 🎯 Finn lederne i en sektor")
                        _valgt_sektor = st.selectbox(
                            "Velg sektor", _ov["sektor"].tolist(), key="mh_valgt_sektor",
                            help="Topp-sektoren er valgt som standard. Her ser du de sterkeste "
                                 "aksjene (høyest RS, så flest Minervini-kriterier) i gruppen.")
                        _vinnere = sektor.vinnere_i_sektor(_mh, _oppslag, _valgt_sektor, antall=10)
                        if _vinnere.empty:
                            st.caption("Ingen aksjer med data i denne sektoren akkurat nå.")
                        else:
                            _vt = pd.DataFrame()
                            _vt["Ticker"] = _vinnere["ticker"]
                            if "pris" in _vinnere.columns:
                                _vt["Pris"] = _vinnere["pris"]
                            _vt["RS"] = _vinnere["rs"]
                            if "score" in _vinnere.columns:
                                _vt["Kriterier"] = _vinnere["score"].map(
                                    lambda s: f"{int(s)}/7" if pd.notna(s) else "—")
                            if "status" in _vinnere.columns:
                                _vt["Status"] = _vinnere["status"]
                            if "pct_fra_52h" in _vinnere.columns:
                                _vt["Fra 52u høy"] = _vinnere["pct_fra_52h"].map(
                                    lambda p: f"{p:+.1f}%" if pd.notna(p) else "—")
                            _lt = st.dataframe(
                                _vt, width="stretch", hide_index=True, height=360,
                                on_select="rerun", selection_mode="multi-row",
                                key="mh_vinnere_tabell")
                            st.caption("💡 **Huk av rader** for å tegne chart av lederne.")

                            _mh_rader = list(getattr(_lt.selection, "rows", []) or [])
                            _mh_valgte = [_vinnere.iloc[i]["ticker"]
                                          for i in _mh_rader if i < len(_vinnere)]
                            if _mh_valgte and HAR_LWC:
                                st.divider()
                                _mh_priser = last_priser(bors_navn, versjon)
                                for _tk in _mh_valgte[:10]:
                                    _s = datamod.serie_for(_mh_priser, _tk)
                                    _r = screener.analyser_ticker(
                                        _s, _tk, konfig.PRESETS[aktiv_preset_navn])
                                    st.markdown(f"**{_tk}**")
                                    _spec = lag_chart_lwc(_s, _r, PERIODER_VALG["2 år"],
                                                          hoyde=420, morkt=MORKT, tittel=_tk)
                                    if _spec:
                                        renderLightweightCharts(_spec, key=f"mh_{_tk}_{TEMA}")
