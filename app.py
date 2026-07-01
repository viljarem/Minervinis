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
              dager: int = 504) -> go.Figure:
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

        # Stiplet zigzag som binder sammen alle pivotene (historiske + gjeldende),
        # så du ser hvordan pivot/motstanden flytter seg over tid.
        zigzag = [(pd.to_datetime(b["dato"]), float(b["pivot"])) for b in hist]
        if res and res.get("pivot"):
            p_dato = pd.to_datetime(res["bruddato"]) if res.get("bruddato") else full.index[-1]
            zigzag.append((p_dato, float(res["pivot"])))
        zigzag = sorted(zigzag, key=lambda t: t[0])
        # Fjern punkter som ligger rett oppå hverandre (samme dato + pivot)
        renset_zz = []
        for punkt in zigzag:
            if not renset_zz or punkt != renset_zz[-1]:
                renset_zz.append(punkt)
        if len(renset_zz) >= 2:
            fig.add_trace(go.Scatter(
                x=[p[0] for p in renset_zz], y=[p[1] for p in renset_zz],
                mode="lines+markers", name="Pivot-zigzag",
                line=dict(color="rgba(80,80,90,0.9)", width=1.3, dash="dash"),
                marker=dict(size=5, color="rgba(80,80,90,0.9)"),
                hovertemplate="Pivot %{y}<br>%{x|%d.%m.%Y}<extra></extra>",
            ), row=1, col=1)

    if res:
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
    vis["Uke"] = df["mtf_emoji"] if "mtf_emoji" in df else "⚠️"
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
    filt = resultat[resultat["score"] >= min_krit].copy()
    filt = filt[filt["rs"].fillna(0) >= min_rs]
    if kun_ferske:
        filt = filt[filt["status"] == "🟢"]
    if krev_uke:
        filt = filt[filt["mtf_status"] == "bullish"]

    # Standardsortering: nyeste 7/7-dato øverst (aksjer uten dato havner nederst)
    filt["_sortdato"] = pd.to_datetime(filt["dato_7av7"], errors="coerce")
    filt = filt.sort_values("_sortdato", ascending=False, na_position="last").drop(columns="_sortdato")

    st.markdown(f"**{len(filt)} aksjer** oppfyller filtrene. Kolonnene 1–7 = de sju kriteriene.")
    st.dataframe(formater_tabell(filt), use_container_width=True, hide_index=True, height=560)
    st.caption("Sortert etter nyeste 7/7-dato øverst. Tips: klikk på en kolonne-overskrift for å sortere selv.")

# --- Fane 2: Chart ---
with fane2:
    valg = st.selectbox("Velg aksje", resultat["ticker"].tolist())
    kol_a, kol_b = st.columns([3, 2])
    periode = kol_a.radio("Periode", list(PERIODER_VALG.keys()), index=3, horizontal=True)
    vis_perioder = kol_b.checkbox("Marker historikk (7/7, pivoter, brudd)", value=True)
    serie = datamod.serie_for(last_priser(versjon), valg)
    res = screener.analyser_ticker(serie, valg, konfig.PRESETS[preset_navn])
    if res is None:
        st.info("For lite historikk til å tegne chart for denne aksjen.")
    else:
        st.plotly_chart(lag_chart(serie, res, vis_perioder, PERIODER_VALG[periode]),
                        use_container_width=True, config=CHART_CONFIG)
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
                st.plotly_chart(lag_chart(serie, res, vis_perioder=True, dager=PERIODER_VALG[periode3]),
                                use_container_width=True, config=CHART_CONFIG)
                vis_vcp_boks(res)
