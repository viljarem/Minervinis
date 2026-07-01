"""
app.py – selve nettsiden (Streamlit).

Dette er "visnings"-delen. All den tunge logikken ligger i motor/-mappa, så denne
fila handler bare om å vise fram resultatene og tegne chart.

Kjøre lokalt på egen PC:   streamlit run app.py
På nett:                   Streamlit Community Cloud kjører denne fila for deg.
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from motor import konfig, data as datamod, indikatorer, minervini, screener, univers

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
def lag_chart(serie: pd.DataFrame, res: dict | None, vis_perioder: bool) -> go.Figure:
    """Tegner candlestick + glidende snitt + 52u høy/lav + pivot + bruddmarkør."""
    d = indikatorer.legg_til_indikatorer(serie).iloc[-400:]  # vis ~1,5 år

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.78, 0.22], subplot_titles=("", "Volum"),
    )

    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="Kurs", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)

    farger = {"SMA50": "#2196f3", "SMA150": "#ff9800", "SMA200": "#9c27b0"}
    for navn, farge in farger.items():
        fig.add_trace(go.Scatter(x=d.index, y=d[navn], name=navn,
                                  line=dict(color=farge, width=1.3)), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d["High_52w"], name="52u høy",
                             line=dict(color="#9e9e9e", width=1, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["Low_52w"], name="52u lav",
                             line=dict(color="#9e9e9e", width=1, dash="dot")), row=1, col=1)

    # Volum nederst
    fig.add_trace(go.Bar(x=d.index, y=d["Volume"], name="Volum",
                         marker_color="rgba(120,120,120,0.5)"), row=2, col=1)

    if res:
        # Historiske 7/7-perioder (lys grønn skygge)
        if vis_perioder:
            for start, slutt in res.get("perioder", []):
                fig.add_vrect(x0=start, x1=slutt, fillcolor="green",
                              opacity=0.07, line_width=0, row=1, col=1)
        # Gull pivotlinje
        if res.get("pivot"):
            fig.add_hline(y=res["pivot"], line=dict(color="gold", width=2),
                          annotation_text=f"Pivot {res['pivot']}", annotation_position="top left",
                          row=1, col=1)
        # Stop-nivå (rød stiplet)
        if res.get("stop"):
            fig.add_hline(y=res["stop"], line=dict(color="#ef5350", width=1, dash="dash"),
                          annotation_text=f"Stop {res['stop']}", annotation_position="bottom left",
                          row=1, col=1)
        # Markør der kursen brøt pivot
        if res.get("bruddato") and res.get("pivot"):
            fig.add_trace(go.Scatter(
                x=[res["bruddato"]], y=[res["pivot"]], mode="markers",
                marker=dict(symbol="triangle-up", size=15, color="gold",
                            line=dict(color="black", width=1)),
                name="Brudd",
            ), row=1, col=1)

    fig.update_layout(
        height=620, xaxis_rangeslider_visible=False, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def vis_vcp_boks(res: dict) -> None:
    """Viser VCP-detaljer under chartet."""
    st.markdown(f"**Setup-status:** {res['status']} {res['statustekst']}")
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
# Hovedtabell
# ---------------------------------------------------------------------------
KRIT = [("k1", "1"), ("k2", "2"), ("k3", "3"), ("k4", "4"), ("k5", "5"), ("k6", "6"), ("k7", "7")]


def formater_tabell(df: pd.DataFrame) -> pd.DataFrame:
    vis = pd.DataFrame()
    vis["Ticker"] = df["ticker"]
    vis["Pris"] = df["pris"]
    vis["RS"] = df["rs"]
    vis["Score"] = df["score"].astype(str) + "/7"
    vis["Dato 7/7"] = df["dato_7av7"].fillna("—")
    vis["Setup"] = df["status"] + " " + df["statustekst"]
    vis["Utv. siden 7/7"] = df["utvikling_siden"].map(lambda x: "—" if pd.isna(x) else f"{x:+.1f} %")
    vis["Pivot"] = df["pivot"]
    vis["Kvalitet"] = df["kvalitet"]
    for kol, navn in KRIT:
        vis[navn] = df[kol].map(lambda b: "✅" if b else "❌")
    return vis


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
            f"Roboten henter automatisk hver hverdag."
        )
    else:
        st.warning(
            f"⚠️ Nyeste data er fra **{_status['siste_dato']:%d.%m.%Y}** "
            f"({_status['alder_dager']} dager siden). Roboten kjører hver hverdag ca. kl. 18–19."
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

# --- Sidefelt: filtre ---
with st.sidebar:
    st.header("Filtre")
    preset_navn = st.selectbox("Oppsett (preset)", list(konfig.PRESETS.keys()))
    min_krit = st.slider("Minimum antall kriterier", 0, 7, konfig.PRESETS[preset_navn].krev_antall)
    min_rs = st.slider("Minimum RS-rating", 0, 99, 0)
    kun_ferske = st.checkbox("Vis kun ferske brudd (🟢)", value=False)
    st.caption(f"Sist oppdatert: {pd.to_datetime(versjon, unit='s'):%d.%m.%Y %H:%M}")

resultat = kjor_screening(preset_navn, versjon)
if resultat.empty:
    st.info("Screeningen ga ingen treff ennå. Har roboten fått hentet nok historikk?")
    st.stop()

fane1, fane2, fane3 = st.tabs(["📋 Hovedliste", "📊 Chart", "🔎 Søk"])

# --- Fane 1: Hovedliste ---
with fane1:
    filt = resultat[resultat["score"] >= min_krit].copy()
    filt = filt[filt["rs"].fillna(0) >= min_rs]
    if kun_ferske:
        filt = filt[filt["status"] == "🟢"]

    st.markdown(f"**{len(filt)} aksjer** oppfyller filtrene. Kolonnene 1–7 = de sju kriteriene.")
    st.dataframe(formater_tabell(filt), use_container_width=True, hide_index=True, height=560)
    st.caption("Tips: klikk på en kolonne-overskrift for å sortere.")

# --- Fane 2: Chart ---
with fane2:
    valg = st.selectbox("Velg aksje", resultat["ticker"].tolist())
    vis_perioder = st.checkbox("Marker historiske 7/7-perioder", value=True)
    serie = datamod.serie_for(last_priser(versjon), valg)
    res = screener.analyser_ticker(serie, valg, konfig.PRESETS[preset_navn])
    if res is None:
        st.info("For lite historikk til å tegne chart for denne aksjen.")
    else:
        st.plotly_chart(lag_chart(serie, res, vis_perioder), use_container_width=True)
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
                st.plotly_chart(lag_chart(serie, res, vis_perioder=True), use_container_width=True)
                vis_vcp_boks(res)
