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

from motor import konfig, data as datamod, indikatorer, minervini, screener, univers, vcp

# TradingViews lightweight-charts (testfane). Pakket i try/except så appen aldri
# krasjer om komponenten ikke er installert i miljøet (f.eks. rett etter utrulling).
try:
    from streamlit_lightweight_charts import renderLightweightCharts
    HAR_LWC = True
except Exception:
    HAR_LWC = False

st.set_page_config(page_title="Minervini-screener · Oslo Børs", layout="wide")


# ---------------------------------------------------------------------------
# Data-innlasting (bufres/caches så siden blir rask)
# ---------------------------------------------------------------------------
def data_versjon() -> float:
    """Endres når datafila oppdateres – brukes til å friske opp bufferet."""
    return os.path.getmtime(konfig.PRISER_FIL) if os.path.exists(konfig.PRISER_FIL) else 0.0


@st.cache_data(show_spinner=False)
def last_priser(versjon: float) -> pd.DataFrame:
    return datamod.les_priser()


@st.cache_data(show_spinner="Kjører screening for hele Oslo Børs ...")
def kjor_screening(preset_navn: str, versjon: float) -> pd.DataFrame:
    priser = datamod.les_priser()
    return screener.screen(priser, konfig.PRESETS[preset_navn])


@st.cache_data(show_spinner=False)
def data_status(versjon: float) -> dict:
    """Regner ut datadekning: siste handelsdag, antall aksjer med data, universstørrelse."""
    priser = datamod.les_priser()
    if priser.empty:
        return {"tom": True}
    i_data = set(priser["Ticker"].unique())
    aksjer_data = len([t for t in i_data if t != konfig.BENCHMARK])
    univ = set(univers.les_cache()) | set(univers.les_manuelle())
    aksjer_univ = len(univ) if univ else aksjer_data
    siste_dato = pd.to_datetime(priser["Date"]).max()
    alder = (pd.Timestamp.now().normalize() - siste_dato.normalize()).days
    return {
        "tom": False,
        "siste_dato": siste_dato,
        "aksjer_data": aksjer_data,
        "aksjer_univ": aksjer_univ,
        "alder_dager": alder,
        "fil_tid": pd.to_datetime(versjon, unit="s"),
    }


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
# Hvor mange handelsdager hver "Periode"-knapp viser ved åpning (og skalerer etter)
PERIODER_VALG = {"3 mnd": 63, "6 mnd": 126, "1 år": 252, "2 år": 504,
                 "3 år": 756, "5 år": 1260, "Alt": 100_000}


def vis_vcp_boks(res: dict) -> None:
    """Viser VCP-detaljer under chartet."""
    st.markdown(f"**Setup-status:** {res['status']} {res['statustekst']}")
    st.markdown(f"**Ukentlig trend:** {res.get('mtf_emoji', '⚠️')} {res.get('mtf_tekst', '–')}")
    kol = st.columns(4)
    kol[0].metric("Pivot (kjøp)", "—" if res["pivot"] is None else f"{res['pivot']}")
    kol[1].metric("Stop", "—" if res["stop"] is None else f"{res['stop']}")
    kol[2].metric("Avstand til pivot", "—" if res["avstand_pivot"] is None else f"{res['avstand_pivot']} %")
    kol[3].metric("Kvalitetsscore", f"{res['kvalitet']}/100")

    kol2 = st.columns(4)
    kol2[0].metric("Antall kontraksjoner", res["antall_kontr"])
    kontr = ", ".join(f"{x} %" for x in res["kontraksjoner"]) if res["kontraksjoner"] else "—"
    kol2[1].metric("Dybder", kontr)
    kol2[2].metric("Volumuttørking", "Ja ✅" if res["volumuttorking"] else "Nei")
    kol2[3].metric("RS-avkastning (rå)", "—" if pd.isna(res["rs_avkastning"]) else f"{res['rs_avkastning'] * 100:.0f} %")


# ---------------------------------------------------------------------------
# Chart 2.0 (test) – TradingViews lightweight-charts
# ---------------------------------------------------------------------------
def lag_chart_lwc(serie: pd.DataFrame, res: dict | None, dager: int = 504, *,
                  vis_ma: bool = True, vis_52u: bool = True, vis_vcp: bool = True,
                  vis_7av7: bool = True, vis_hist: bool = False) -> list | None:
    """Bygger data-spesifikasjonen for lightweight-charts.

    Tar med alt det gamle Plotly-chartet hadde: candles, MA50/150/200, 52-ukers
    høy/lav, volum + volum-SMA50, pivot/stop, VCP-kontraksjonene (zigzag),
    7/7-markører (ble/mistet), historiske volumbrudd og «brudd nå». Hvert lag kan
    slås av/på. Returnerer lista renderLightweightCharts venter, eller None.
    Pakket i try/except så testfanen aldri kan krasje appen.
    """
    try:
        full = indikatorer.legg_til_indikatorer(serie)
        if full.empty:
            return None
        d = full.iloc[-min(dager, len(full)):].copy()
        t = list(d.index.strftime("%Y-%m-%d"))
        t_sett = set(t)

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
                    pos = t.index(slutt)
                    if pos + 1 < len(t):
                        markorer.append({"time": t[pos + 1], "position": "aboveBar",
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
                             "wickDownColor": "#ef5350"}}
        if rene:
            hoved["markers"] = rene

        serier = [hoved]

        # Glidende snitt
        if vis_ma:
            serier += [linje("SMA50", "#2196f3", 2),
                       linje("SMA150", "#ff9800", 1),
                       linje("SMA200", "#9c27b0", 1)]

        # 52-ukers høy/lav (grå stiplede referanselinjer – kriterium 6 og 7)
        if vis_52u:
            serier += [linje("High_52w", "#9e9e9e", 1, stil=1),
                       linje("Low_52w", "#9e9e9e", 1, stil=1)]

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

        # Volum + 50-dagers snittvolum (delt overlay-skala i bunnen)
        serier.append({"type": "Histogram", "data": volum,
                       "options": {"priceFormat": {"type": "volume"}, "priceScaleId": "vol"},
                       "priceScale": {"scaleMargins": {"top": 0.78, "bottom": 0}}})
        d["_volsnitt"] = d["Volume"].rolling(50, min_periods=10).mean()
        serier.append(linje("_volsnitt", "#3949ab", 1, skala="vol"))

        # Pivot (gull) og stop (rød stiplet) som flate linjer. Aktiv pivot er
        # bevisst TYKKEST og solid, så den skiller seg klart fra de svakere,
        # stiplede historiske pivotlinjene.
        if res and res.get("pivot"):
            serier.append({"type": "Line",
                           "data": [{"time": ti, "value": res["pivot"]} for ti in t],
                           "options": {"color": "#f6c343", "lineWidth": 3, "lineStyle": 0,
                                       "priceLineVisible": False, "lastValueVisible": True,
                                       "title": "Pivot"}})
        if res and res.get("stop"):
            serier.append({"type": "Line",
                           "data": [{"time": ti, "value": res["stop"]} for ti in t],
                           "options": {"color": "#ef5350", "lineWidth": 1, "lineStyle": 2,
                                       "priceLineVisible": False, "lastValueVisible": True,
                                       "title": "Stop"}})

        chart_options = {
            "height": 620,
            "layout": {"background": {"type": "solid", "color": "white"},
                       "textColor": "#333333"},
            "grid": {"vertLines": {"color": "rgba(197,203,206,0.35)"},
                     "horzLines": {"color": "rgba(197,203,206,0.35)"}},
            "rightPriceScale": {"scaleMargins": {"top": 0.06, "bottom": 0.26},
                                "borderVisible": False},
            "timeScale": {"borderVisible": False, "rightOffset": 4},
            "crosshair": {"mode": 0},
        }
        return [{"chart": chart_options, "series": serier}]
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


def formater_tabell(df: pd.DataFrame) -> pd.DataFrame:
    vis = pd.DataFrame()
    vis["Ticker"] = df["ticker"]
    vis["Pris"] = df["pris"]
    vis["Setup"] = df["status"] + " " + df["statustekst"]
    vis["Til pivot"] = df["avstand_pivot"].map(_til_pivot_tekst)
    vis["Kriterie 1-7"] = df["score"].astype(str) + "/7"
    vis["RVol"] = df["rel_volum"] if "rel_volum" in df.columns else np.nan
    vis["RS"] = df["rs"]
    vis["Uke"] = df["mtf_emoji"] if "mtf_emoji" in df else "⚠️"
    return vis


def stil_hovedtabell(vis: pd.DataFrame):
    """Fargelegger tabellen: grønn bakgrunn på fulle 7/7 og på høyt relativt volum.

    Sterk grønn = toppnivå (7/7 eller bruddvolum ≥ 1,4×), lys grønn = nesten der
    (6/7 eller volum over snittet). Returnerer en pandas Styler som st.dataframe
    tegner med farger – column_config styrer fortsatt format og hjelpetekster.
    """
    sterk, lys = "background-color:#b7e4c7;font-weight:600", "background-color:#eaf7ec"

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

    styler = vis.style
    if "Kriterie 1-7" in vis.columns:
        styler = styler.map(_krit, subset=["Kriterie 1-7"])
    if "RVol" in vis.columns:
        styler = styler.map(_rvol, subset=["RVol"])
    return styler


# Hjelpetekster på kolonneoverskriftene (så vi kan forenkle uten å miste info).
TABELL_HJELP = {
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
    "RS": st.column_config.NumberColumn(
        "RS", help="Relativ styrke 1–99 (99 = sterkest momentum i universet)."),
    "Uke": st.column_config.TextColumn(
        "Uke", help="Ukentlig (høyere tidsramme) trend: ✅ bekreftet opp, ⚠️ blandet, ❌ nedtrend."),
}


# ---------------------------------------------------------------------------
# Selve siden
# ---------------------------------------------------------------------------
st.title("📈 Minervini-screener · Oslo Børs")

versjon = data_versjon()
if versjon == 0:
    st.warning(
        "Fant ingen kursdata ennå. Kjør roboten én gang (se README, «Test roboten») "
        "så fylles data/priser.parquet, og siden viser resultater automatisk."
    )
    st.stop()

# --- Visuell bekreftelse på datastatus (øverst, alltid synlig) ---
_status = data_status(versjon)
if not _status["tom"]:
    _dekning = _status["aksjer_data"] / _status["aksjer_univ"] if _status["aksjer_univ"] else 0
    if _status["alder_dager"] <= 4:
        st.success(
            f"✅ **Data oppdatert** – siste handelsdag **{_status['siste_dato']:%d.%m.%Y}**. "
            f"Roboten henter automatisk hver hverdag kl. 19 (norsk tid)."
        )
    else:
        st.warning(
            f"⚠️ Nyeste data er fra **{_status['siste_dato']:%d.%m.%Y}** "
            f"({_status['alder_dager']} dager siden). Roboten kjører hver hverdag kl. 19 (norsk tid)."
        )
    _k1, _k2, _k3 = st.columns(3)
    _k1.metric("📅 Siste handelsdag", f"{_status['siste_dato']:%d.%m.%Y}")
    _k2.metric("🏦 Aksjer med data", f"{_status['aksjer_data']} / {_status['aksjer_univ']}",
               help="Antall Oslo Børs-aksjer vi har kurshistorikk på, av hele universet.")
    _k3.metric("🕔 Sist hentet", f"{_status['fil_tid']:%d.%m kl. %H:%M}")
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
Den leter automatisk gjennom hele Oslo Børs etter aksjer som er i en sterk
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
- 📋 **Hovedliste** – alle treff, sortert med nyeste 7/7 øverst.
- 📊 **Chart** – tegn en aksje med MA-linjer, pivot, stop, volum og historikk.
- 🔎 **Søk** – slå opp hvilken som helst ticker (også utenfor Oslo Børs, live fra Yahoo).

*Dette er et analyseverktøy, ikke en kjøpsanbefaling. Ta alltid egne vurderinger.*
        """
    )

# --- Sidefelt: filtre ---
with st.sidebar:
    st.header("Filtre")
    preset_navn = st.selectbox("Oppsett (preset)", list(konfig.PRESETS.keys()))
    min_krit = st.slider("Minimum antall kriterier", 0, 7, konfig.PRESETS[preset_navn].krev_antall)
    min_rs = st.slider("Minimum RS-rating", 0, 99, 0)
    kun_ferske = st.checkbox("Vis kun ferske brudd (🟢)", value=False)
    krev_uke = st.checkbox("Krev ukentlig bekreftelse (✅)", value=False,
                           help="Vis kun aksjer der også den ukentlige trenden peker opp.")
    st.caption(f"Sist oppdatert: {pd.to_datetime(versjon, unit='s'):%d.%m.%Y %H:%M}")

resultat = kjor_screening(preset_navn, versjon)
if resultat.empty:
    st.info("Screeningen ga ingen treff ennå. Har roboten fått hentet nok historikk?")
    st.stop()

fane1, fane2, fane3 = st.tabs(["📋 Hovedliste", "📊 Chart", "🔎 Søk"])

# --- Fane 1: Hovedliste ---
with fane1:
    # Ferske brudd (🟢) vises ALLTID – selv om de har færre enn valgt antall kriterier,
    # så du aldri går glipp av et akkurat utløst kjøpssignal.
    filt = resultat[(resultat["score"] >= min_krit) | (resultat["status"] == "🟢")].copy()
    filt = filt[filt["rs"].fillna(0) >= min_rs]
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

    st.markdown(
        f"**{len(filt)} aksjer** – sortert med de mest handlbare øverst: ferske brudd (🟢) "
        f"først, så de som er nærmest et brudd. Ferske brudd vises alltid, også under {min_krit}/7."
    )
    st.dataframe(stil_hovedtabell(formater_tabell(filt)), width="stretch", hide_index=True,
                 height=560, column_config=TABELL_HJELP)
    st.caption("Øverst = skjer nå / nærmest brudd. **Til pivot**: negativt = mangler så mange % "
               "på brudd, positivt = over pivot. **Grønt** = 7/7 eller bruddvolum (≥1,4×). "
               "Tips: klikk en kolonne-overskrift for å sortere selv.")

# --- Fane 2: Chart ---
with fane2:
    if not HAR_LWC:
        st.warning("Chart-komponenten er ikke lastet i dette miljøet ennå (kommer ved neste utrulling).")
    else:
        valg = st.selectbox("Velg aksje", resultat["ticker"].tolist())
        periode = st.radio("Periode", list(PERIODER_VALG.keys()), index=3, horizontal=True,
                           key="periode_chart")
        with st.popover("⚙️ Tilpass chartet"):
            st.caption("Huk av hva du vil se. Færre lag = renere bilde.")
            vis_ma = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="chart_ma")
            vis_52u = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="chart_52u")
            vis_vcp = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=True, key="chart_vcp")
            vis_7av7 = st.checkbox("7/7-markører (ble/mistet)", value=True, key="chart_7av7")
            vis_hist = st.checkbox("Historiske volumbrudd", value=False, key="chart_hist")
        serie = datamod.serie_for(last_priser(versjon), valg)
        res = screener.analyser_ticker(serie, valg, konfig.PRESETS[preset_navn])
        if res is None:
            st.info("For lite historikk til å tegne chart for denne aksjen.")
        else:
            spec = lag_chart_lwc(serie, res, PERIODER_VALG[periode],
                                 vis_ma=vis_ma, vis_52u=vis_52u, vis_vcp=vis_vcp,
                                 vis_7av7=vis_7av7, vis_hist=vis_hist)
            if spec is None:
                st.info("Klarte ikke bygge chartet for denne aksjen.")
            else:
                noekkel = f"chart_{valg}_{periode}_{vis_ma}{vis_52u}{vis_vcp}{vis_7av7}{vis_hist}"
                renderLightweightCharts(spec, key=noekkel)
                st.caption("💡 Dra sidelengs, rull musehjulet for å zoome, dra loddrett på "
                           "prisaksen for å strekke høyden. 🟡 **Kraftig gull = aktiv pivot** · "
                           "🔴 stiplet rød = stop · 🟢/🔴 pil = ble/mistet 7/7. Svake stiplede "
                           "gull-streker = historiske brudd (ubiased).")
                vis_vcp_boks(res)

# --- Fane 3: Søk ---
with fane3:
    st.markdown("Slå opp **hvilken som helst** ticker. Er den ikke i universet, hentes den live fra Yahoo.")
    sok = st.text_input("Ticker (f.eks. EQNR.OL, AAPL, NVDA)", value="").strip().upper()
    if sok:
        priser = last_priser(versjon)
        if sok in priser["Ticker"].values:
            serie = datamod.serie_for(priser, sok)
        else:
            with st.spinner(f"Henter {sok} live ..."):
                serie = datamod.hent_live(sok)
        if serie is None or serie.empty:
            st.error(f"Fant ingen data for «{sok}». Sjekk at tickeren er riktig skrevet.")
        else:
            res = screener.analyser_ticker(serie, sok, konfig.PRESETS[preset_navn])
            if res is None:
                st.info("For lite historikk (trenger ~200 handelsdager) til full analyse.")
            else:
                st.subheader(f"{sok} · {res['score']}/7 · {res['status']} {res['statustekst']}")
                periode3 = st.radio("Periode", list(PERIODER_VALG.keys()), index=3,
                                    horizontal=True, key="periode_sok")
                with st.popover("⚙️ Tilpass chartet"):
                    st.caption("Huk av hva du vil se. Færre lag = renere bilde.")
                    vis_ma3 = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="sok_ma")
                    vis_52u3 = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="sok_52u")
                    vis_vcp3 = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=True, key="sok_vcp")
                    vis_7av7_3 = st.checkbox("7/7-markører (ble/mistet)", value=True, key="sok_7av7")
                    vis_hist3 = st.checkbox("Historiske volumbrudd", value=False, key="sok_hist")
                if not HAR_LWC:
                    st.warning("Chart-komponenten er ikke lastet i dette miljøet ennå.")
                else:
                    spec3 = lag_chart_lwc(serie, res, PERIODER_VALG[periode3],
                                          vis_ma=vis_ma3, vis_52u=vis_52u3, vis_vcp=vis_vcp3,
                                          vis_7av7=vis_7av7_3, vis_hist=vis_hist3)
                    if spec3 is not None:
                        renderLightweightCharts(
                            spec3,
                            key=f"sok_{sok}_{periode3}_{vis_ma3}{vis_52u3}{vis_vcp3}{vis_7av7_3}{vis_hist3}")
                vis_vcp_boks(res)
