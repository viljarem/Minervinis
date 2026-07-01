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
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

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
CHART_CONFIG = {
    "scrollZoom": True,          # zoom med musehjul
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}

# Hvor mange handelsdager hver "Periode"-knapp viser ved åpning (og skalerer etter)
PERIODER_VALG = {"3 mnd": 63, "6 mnd": 126, "1 år": 252, "2 år": 504,
                 "3 år": 756, "5 år": 1260, "Alt": 100_000}


def lag_chart(serie: pd.DataFrame, res: dict | None, vis_perioder: bool,
              dager: int = 504, vis_7av7: bool = False) -> go.Figure:
    """Candlestick + MA50/150/200 + 52u høy/lav + pivot/stop + volum.

    HELE historikken legges i figuren, men chartet åpner på de siste `dager`
    dagene (via x-aksens område). Da kan du dra/panorere bakover og faktisk se
    eldre kurs – samtidig som y-aksen og volumet er skalert til startvinduet.
    """
    full = indikatorer.legg_til_indikatorer(serie)
    if full.empty:
        return go.Figure()
    n = len(full)
    dager = min(dager, n)
    synlig = full.iloc[-dager:]          # det som vises ved åpning (styrer skalering)
    d = full                             # alt ligger i figuren (så panorering funker)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.76, 0.24], subplot_titles=("", "Volum"),
    )

    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="Kurs", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350",
    ), row=1, col=1)

    # Glidende snitt – MA50 er tykkest (viktigst for Minervini-kjøpet)
    for navn, farge, bredde in (("SMA50", "#2196f3", 2.2),
                                ("SMA150", "#ff9800", 1.3),
                                ("SMA200", "#9c27b0", 1.3)):
        fig.add_trace(go.Scatter(x=d.index, y=d[navn], name=navn,
                                 line=dict(color=farge, width=bredde)), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d["High_52w"], name="52u høy",
                             line=dict(color="#bdbdbd", width=1, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["Low_52w"], name="52u lav",
                             line=dict(color="#bdbdbd", width=1, dash="dot")), row=1, col=1)

    # Volum – grønt på opp-dager, rødt på ned-dager
    opp = (d["Close"] >= d["Open"]).to_numpy()
    vol_farger = np.where(opp, "rgba(38,166,154,0.55)", "rgba(239,83,80,0.55)")
    fig.add_trace(go.Bar(x=d.index, y=d["Volume"], name="Volum",
                         marker_color=vol_farger, marker_line_width=0,
                         showlegend=False), row=2, col=1)

    # 50-dagers snittvolum – viser når volumet er over/under det normale
    vol_snitt = d["Volume"].rolling(50, min_periods=10).mean()
    fig.add_trace(go.Scatter(x=d.index, y=vol_snitt, name="Volum SMA50",
                             line=dict(color="#3949ab", width=1.4),
                             hoverinfo="skip"), row=2, col=1)

    if vis_perioder:
        # Historiske 7/7-perioder (lys grønn skygge)
        if res:
            for start, slutt in res.get("perioder", []):
                fig.add_vrect(x0=start, x1=slutt, fillcolor="green",
                              opacity=0.06, line_width=0, row=1, col=1)
        # Historiske volumbrudd: kort pivotlinje + trekant der kursen brøt motstand.
        # Pakket i try/except så et enkelt chart aldri kan krasje hele appen.
        try:
            finn_hist = getattr(vcp, "historiske_brudd", None)
            hist = finn_hist(serie) if finn_hist else []
        except Exception:
            hist = []
        if hist:
            seg_x, seg_y, mk_x, mk_y = [], [], [], []
            for b in hist:
                seg_x += [b["base_start"], b["dato"], None]
                seg_y += [b["pivot"], b["pivot"], None]
                mk_x.append(b["dato"])
                mk_y.append(b["pivot"])
            fig.add_trace(go.Scatter(x=seg_x, y=seg_y, mode="lines", name="Hist. pivot",
                                     line=dict(color="rgba(255,193,7,0.75)", width=1.4),
                                     hoverinfo="skip"), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=mk_x, y=mk_y, mode="markers", name="Hist. brudd",
                marker=dict(symbol="triangle-up", size=9, color="rgba(255,193,7,0.95)",
                            line=dict(color="black", width=0.5)),
                hovertemplate="Hist. brudd %{x|%d.%m.%Y}<br>pivot %{y}<extra></extra>",
            ), row=1, col=1)

    # 7/7 av/på-markører: grønn trekant der aksjen BLE 7/7, rødt kryss der den
    # MISTET ett av de sju kriteriene (dagen etter at en 7/7-periode tok slutt).
    if vis_7av7 and res:
        paa_x, paa_y, av_x, av_y = [], [], [], []
        for start, slutt in res.get("perioder", []):
            s_ts, e_ts = pd.Timestamp(start), pd.Timestamp(slutt)
            if s_ts in full.index:
                paa_x.append(s_ts)
                paa_y.append(float(full.loc[s_ts, "Low"]))
            if e_ts in full.index:
                pos = full.index.get_loc(e_ts)
                if isinstance(pos, int) and pos + 1 < len(full):
                    tap = full.index[pos + 1]
                    av_x.append(tap)
                    av_y.append(float(full.loc[tap, "High"]))
        if paa_x:
            fig.add_trace(go.Scatter(
                x=paa_x, y=paa_y, mode="markers", name="Ble 7/7",
                marker=dict(symbol="triangle-up", size=13, color="#2e7d32",
                            line=dict(color="black", width=0.6)),
                hovertemplate="Ble 7/7 %{x|%d.%m.%Y}<extra></extra>",
            ), row=1, col=1)
        if av_x:
            fig.add_trace(go.Scatter(
                x=av_x, y=av_y, mode="markers", name="Mistet 1 av 7",
                marker=dict(symbol="x", size=11, color="#c62828",
                            line=dict(color="black", width=0.6)),
                hovertemplate="Mistet 1 av 7 %{x|%d.%m.%Y}<extra></extra>",
            ), row=1, col=1)

    if res:
        # Gul stiplet zigzag gjennom VCP-kontraksjonene (topp→bunn→topp ...),
        # så du ser hvordan aksjen strammer seg sammen mot pivot.
        vcp_pkt = res.get("vcp_punkter") or []
        if len(vcp_pkt) >= 2:
            fig.add_trace(go.Scatter(
                x=[p["dato"] for p in vcp_pkt], y=[p["pris"] for p in vcp_pkt],
                mode="lines+markers", name="VCP-kontraksjoner",
                line=dict(color="gold", width=1.6, dash="dash"),
                marker=dict(size=5, color="gold"),
                hovertemplate="VCP %{y}<br>%{x|%d.%m.%Y}<extra></extra>",
            ), row=1, col=1)
        # Gjeldende pivotlinje (gull)
        if res.get("pivot"):
            fig.add_hline(y=res["pivot"], line=dict(color="gold", width=2),
                          annotation_text=f"Pivot {res['pivot']}", annotation_position="top left",
                          row=1, col=1)
        # Stop-nivå (rød stiplet)
        if res.get("stop"):
            fig.add_hline(y=res["stop"], line=dict(color="#ef5350", width=1, dash="dash"),
                          annotation_text=f"Stop {res['stop']}", annotation_position="bottom left",
                          row=1, col=1)
        # Markør der kursen brøt gjeldende pivot
        if res.get("bruddato") and res.get("pivot"):
            fig.add_trace(go.Scatter(
                x=[res["bruddato"]], y=[res["pivot"]], mode="markers",
                marker=dict(symbol="triangle-up", size=15, color="gold",
                            line=dict(color="black", width=1)),
                name="Brudd nå",
            ), row=1, col=1)

    # Skaler y-aksen til startvinduet (ta med gjeldende pivot/stop i ramma)
    lav = float(synlig["Low"].min())
    hoy = float(synlig["High"].max())
    for niva in ((res or {}).get("pivot"), (res or {}).get("stop")):
        if niva is not None and np.isfinite(niva):
            lav, hoy = min(lav, float(niva)), max(hoy, float(niva))
    pad = (hoy - lav) * 0.06 or hoy * 0.02
    fig.update_yaxes(range=[lav - pad, hoy + pad], row=1, col=1)

    # Klipp de høyeste volumtoppene i vinduet så normalvolum blir synlig
    vol_tak = float(np.nanpercentile(synlig["Volume"], 95)) * 1.35
    if vol_tak > 0:
        fig.update_yaxes(range=[0, vol_tak], row=2, col=1)

    # Åpne på startvinduet, men la hele historikken være tilgjengelig å dra til
    x0 = synlig.index[0]
    x1 = full.index[-1] + pd.Timedelta(days=5)
    fig.update_xaxes(range=[x0, x1])
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])  # skjul helger
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1,
                     spikecolor="#bbbbbb", spikedash="dot")

    fig.update_layout(
        height=680, template="plotly_white", dragmode="pan", bargap=0.1,
        xaxis_rangeslider_visible=False, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


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
        if vis_hist:
            try:
                finn_hist = getattr(vcp, "historiske_brudd", None)
                for b in (finn_hist(serie) if finn_hist else []):
                    dato = pd.Timestamp(b["dato"]).strftime("%Y-%m-%d")
                    if dato in t_sett:
                        markorer.append({"time": dato, "position": "belowBar",
                                         "color": "#f6c343", "shape": "circle", "text": "brudd"})
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

        # Volum + 50-dagers snittvolum (delt overlay-skala i bunnen)
        serier.append({"type": "Histogram", "data": volum,
                       "options": {"priceFormat": {"type": "volume"}, "priceScaleId": "vol"},
                       "priceScale": {"scaleMargins": {"top": 0.78, "bottom": 0}}})
        d["_volsnitt"] = d["Volume"].rolling(50, min_periods=10).mean()
        serier.append(linje("_volsnitt", "#3949ab", 1, skala="vol"))

        # Pivot (gull) og stop (rød stiplet) som flate linjer
        if res and res.get("pivot"):
            serier.append({"type": "Line",
                           "data": [{"time": ti, "value": res["pivot"]} for ti in t],
                           "options": {"color": "#f6c343", "lineWidth": 2, "lineStyle": 0,
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

fane1, fane2, fane3, fane4 = st.tabs(["📋 Hovedliste", "📊 Chart", "🔎 Søk", "🧪 Chart 2.0 (test)"])

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
    valg = st.selectbox("Velg aksje", resultat["ticker"].tolist())
    kol_a, kol_b = st.columns([3, 2])
    periode = kol_a.radio("Periode", list(PERIODER_VALG.keys()), index=3, horizontal=True)
    vis_perioder = kol_b.checkbox("Marker historikk (7/7, pivoter, brudd)", value=True)
    vis_7av7 = kol_b.checkbox("Vis 7/7-treff (grønn = ble 7/7, rød = mistet ett)", value=False)
    serie = datamod.serie_for(last_priser(versjon), valg)
    res = screener.analyser_ticker(serie, valg, konfig.PRESETS[preset_navn])
    if res is None:
        st.info("For lite historikk til å tegne chart for denne aksjen.")
    else:
        st.plotly_chart(lag_chart(serie, res, vis_perioder, PERIODER_VALG[periode], vis_7av7),
                        width="stretch", config=CHART_CONFIG)
        st.caption("💡 Dra sidelengs for å se eldre kurs, rull med musehjulet for å zoome, "
                   "dobbeltklikk for å nullstille. Bruk periode-knappene for perfekt skalering. "
                   "Gule trekanter = historiske volumbrudd gjennom motstand.")
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
                vis_7av7_3 = st.checkbox("Vis 7/7-treff (grønn = ble 7/7, rød = mistet ett)",
                                         value=False, key="vis7_sok")
                st.plotly_chart(lag_chart(serie, res, vis_perioder=True,
                                          dager=PERIODER_VALG[periode3], vis_7av7=vis_7av7_3),
                                width="stretch", config=CHART_CONFIG)
                vis_vcp_boks(res)

# --- Fane 4: Chart 2.0 (test) ---
with fane4:
    st.markdown(
        "🧪 **Testversjon** av chartet med TradingViews motor (*lightweight-charts*). "
        "Prøv gjerne: **dra sidelengs**, **rull musehjulet** for å zoome, og – det du ønsket – "
        "**dra loddrett på prisaksen** (tallene til høyre) for å strekke/skalere høyden. "
        "Y-aksen følger automatisk når du panorerer. Si ifra om dette føles bedre enn dagens chart."
    )
    if not HAR_LWC:
        st.warning("Chart-komponenten er ikke lastet i dette miljøet ennå (kommer ved neste utrulling).")
    else:
        valg4 = st.selectbox("Velg aksje", resultat["ticker"].tolist(), key="valg_lwc")
        periode4 = st.radio("Periode", list(PERIODER_VALG.keys()), index=3, horizontal=True,
                            key="periode_lwc")
        with st.popover("⚙️ Tilpass chartet"):
            st.caption("Huk av hva du vil se. Færre lag = renere bilde.")
            vis_ma4 = st.checkbox("Glidende snitt (MA50/150/200)", value=True, key="lwc_ma")
            vis_52u4 = st.checkbox("52-ukers høy/lav (grå stiplet)", value=True, key="lwc_52u")
            vis_vcp4 = st.checkbox("VCP-kontraksjoner (gul zigzag)", value=True, key="lwc_vcp")
            vis_7av74 = st.checkbox("7/7-markører (ble/mistet)", value=True, key="lwc_7av7")
            vis_hist4 = st.checkbox("Historiske volumbrudd", value=False, key="lwc_hist")
        serie4 = datamod.serie_for(last_priser(versjon), valg4)
        res4 = screener.analyser_ticker(serie4, valg4, konfig.PRESETS[preset_navn])
        if res4 is None:
            st.info("For lite historikk til å tegne chart for denne aksjen.")
        else:
            spec = lag_chart_lwc(serie4, res4, PERIODER_VALG[periode4],
                                 vis_ma=vis_ma4, vis_52u=vis_52u4, vis_vcp=vis_vcp4,
                                 vis_7av7=vis_7av74, vis_hist=vis_hist4)
            if spec is None:
                st.info("Klarte ikke bygge chartet for denne aksjen.")
            else:
                noekkel = f"lwc_{valg4}_{periode4}_{vis_ma4}{vis_52u4}{vis_vcp4}{vis_7av74}{vis_hist4}"
                renderLightweightCharts(spec, key=noekkel)
                st.caption("🟡 Gull = pivot (kjøpsnivå) · 🔴 stiplet rød = stop · 🟢 pil opp = ble 7/7 · "
                           "🔴 pil ned = mistet 7/7. Blå = MA50, oransje = MA150, lilla = MA200, "
                           "blå strek i volum = 50-dagers snittvolum.")
                vis_vcp_boks(res4)
