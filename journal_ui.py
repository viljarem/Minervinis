"""
journal_ui.py – Streamlit-UI for tradingjournalen (ett sammenhengende dashboard).

Lagring ligger i motor/journal_db.py og matematikk i motor/journal_tall.py.
Denne fila tegner bare. Feiler databasen, viser vi en vennlig melding –
screeneren påvirkes aldri.

Oppbygging etter innlogging (vis_dashboard):
  1. 📊 Oversikt – hvordan går tradingen? (KPI-er, åpne posisjoner, R-kurve)
  2. ⭐ Mine lister  |  📓 Dagbok   (side ved side)
  3. 💼 Trades – loggfør kjøp/salg, se åpne og lukkede handler
Klikker du en ticker hvor som helst → ticker-side med chart, all info og notater.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from motor import journal_db as db
from motor import journal_tall as tall

# ---------------------------------------------------------------------------
# Konsistent fargespråk – ett sted for hele journalen.
#   POS  = positivt/opp (grønn)   NEG = negativt/ned (rød)
#   AKSENT = nøytral handling/kurver (blå)   VARSEL = gul   NOYTRAL = grå
# Bruk disse overalt (tabeller, kort, chart, lister) så alt matcher.
# ---------------------------------------------------------------------------
FARGER = {
    "pos": "#16a34a",      # grønn – gevinst/opp
    "neg": "#dc2626",      # rød – tap/ned
    "aksent": "#3b82f6",   # blå – nøytral aksent/kurver
    "varsel": "#f59e0b",   # gul – advarsel/høy alert
    "noytral": "#6b7280",  # grå – nøytral/parkert
}

# Tre forslag som opprettes FØRSTE gang (du kan omdøpe/slette fritt).
START_LISTER = [
    ("Watchlist", FARGER["aksent"], 0),
    ("High alert", FARGER["varsel"], 1),
    ("Parkert", FARGER["noytral"], 2),
]

# Standard setup-/trigger-valg (fritt i tillegg, så du er ikke låst til disse).
SETUP_VALG = ["VCP", "Breakout", "Flat base", "Cup & handle", "Pullback", "Momentum", "Annet"]
TRIGGER_VALG = ["Volumbrudd", "Pivot", "MA-støtte", "Nyhet", "Annet"]

# Farge per setup til badges (faller tilbake til grå).
SETUP_FARGE = {
    "VCP": "violet", "Breakout": "green", "Flat base": "blue",
    "Cup & handle": "orange", "Pullback": "blue", "Momentum": "red", "Annet": "gray",
}

# Nokler i innstillinger-tabellen (Supabase) for redigerbare tagger.
NOKKEL_SETUP = "setup_valg"
NOKKEL_TRIGGER = "trigger_valg"


def _tagg_liste(lager, nokkel: str, standard: list[str]) -> list[str]:
    """Henter en redigerbar taggliste fra Supabase (cachet i session).

    Faller tilbake til standardlista hvis journalen ikke er koblet til eller
    innstillinger-tabellen ikke finnes ennaa. Da virker alt som foer.
    """
    buf = st.session_state.setdefault("_tagg_cache", {})
    if nokkel in buf:
        return buf[nokkel]
    verdi = standard
    if lager is not None:
        try:
            lagret = lager.hent_innstilling(nokkel, None)
            if isinstance(lagret, list) and lagret:
                verdi = [str(x) for x in lagret]
        except db.JournalFeil:
            verdi = standard
    buf[nokkel] = verdi
    return verdi


def hent_setup_valg(lager=None) -> list[str]:
    return _tagg_liste(lager, NOKKEL_SETUP, SETUP_VALG)


def hent_trigger_valg(lager=None) -> list[str]:
    return _tagg_liste(lager, NOKKEL_TRIGGER, TRIGGER_VALG)


# ---------------------------------------------------------------------------
# Moderne stil – diskret CSS som følger app-temaet (lys/mørk)
# ---------------------------------------------------------------------------
def _injiser_stil() -> None:
    """Kort-look på nøkkeltall, luftigere faner og mykere kanter. Kjøres én gang."""
    if st.session_state.get("_journal_stil"):
        return
    st.session_state["_journal_stil"] = True
    st.markdown("""
        <style>
        /* Nøkkeltall som kort med myk skygge og løft ved hover */
        div[data-testid="stMetric"] {
            background: var(--secondary-background-color);
            border-radius: 14px;
            padding: 16px 18px;
            border: 1px solid rgba(128,128,128,0.15);
            box-shadow: 0 1px 2px rgba(0,0,0,0.06);
            transition: transform .12s ease, box-shadow .12s ease;
        }
        div[data-testid="stMetric"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.10);
        }
        div[data-testid="stMetricLabel"] p {
            font-size: 0.80rem; opacity: 0.75; font-weight: 500;
            text-transform: uppercase; letter-spacing: .03em;
        }
        div[data-testid="stMetricValue"] { font-weight: 700; }
        /* Faner – pill-stil */
        button[data-baseweb="tab"] { font-weight: 600; }
        /* Rammede containere får litt mer luft */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px;
        }
        /* Popover- og primærknapper litt rundere */
        div[data-testid="stPopover"] button, .stButton button, .stFormSubmitButton button {
            border-radius: 10px;
        }
        </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tilkobling og lås
# ---------------------------------------------------------------------------
def _konf():
    return db.les_secrets()


def tilgjengelig() -> bool:
    return _konf() is not None


def innlogget() -> bool:
    return bool(st.session_state.get("journal_ok")) and tilgjengelig()


def sidebar_las() -> None:
    """Passordfelt nederst i menyen. Opplåsing varer til siden lastes på nytt."""
    st.divider()
    st.header("📒 Journal")
    konf = _konf()
    if konf is None:
        st.caption("Databasen er ikke koblet til ennå. Se fanen «Journal».")
        return
    if innlogget():
        st.success("Låst opp.")
        if st.button("Lås journalen", width="stretch"):
            st.session_state["journal_ok"] = False
            st.rerun()
        return
    with st.form("journal_las", clear_on_submit=True):
        pw = st.text_input("Passord", type="password")
        if st.form_submit_button("Lås opp", width="stretch", type="primary"):
            if db.passord_ok(pw, konf["passord"]):
                st.session_state["journal_ok"] = True
                st.rerun()
            else:
                st.error("Feil passord.")


def _lager() -> db.Lager | None:
    if not innlogget():
        return None
    return db.Lager.fra_secrets()


# ---------------------------------------------------------------------------
# Navigasjon: velg en ticker (drill-down)
# ---------------------------------------------------------------------------
def velg_ticker(ticker: str) -> None:
    st.session_state["journal_ticker"] = (ticker or "").strip().upper()


def _lukk_ticker() -> None:
    st.session_state.pop("journal_ticker", None)


# ---------------------------------------------------------------------------
# Følg-knapp (brukes fra hovedlista i app.py)
# ---------------------------------------------------------------------------
def folg_knapp(tickere: list[str], bors: str, *, key: str) -> None:
    """Legger valgte tickere på en liste brukeren velger. Rolig hvis ikke låst opp."""
    if not tickere:
        return
    if not tilgjengelig():
        st.caption("💡 Koble til journalen for å kunne følge aksjer (se fanen «Journal»).")
        return
    if not innlogget():
        st.caption("🔒 Lås opp journalen i menyen til venstre for å følge valgte aksjer.")
        return
    lager = _lager()
    try:
        lister = _sorg_for_startlister(lager)
    except db.JournalFeil as e:
        st.error(str(e))
        return
    navn_til_id = {l["navn"]: l["id"] for l in lister}
    with st.form(f"folg_{key}", clear_on_submit=False):
        c1, c2 = st.columns([2, 1])
        valgt = c1.selectbox(f"Legg {len(tickere)} valgte på liste", list(navn_til_id),
                             key=f"folg_valg_{key}")
        if c2.form_submit_button("＋ Følg", type="primary", width="stretch"):
            nye, fantes = [], []
            try:
                for t in tickere:
                    status = lager.legg_til_aksje(navn_til_id[valgt], t, bors)
                    (nye if status == "ny" else fantes).append(db.normaliser_ticker(t, bors))
            except db.JournalFeil as e:
                st.error(str(e))
                return
            if nye:
                st.success(f"La til på «{valgt}»: " + ", ".join(nye))
            if fantes:
                st.info("Lå allerede på en liste: " + ", ".join(fantes))


# ---------------------------------------------------------------------------
# Live-tall fra screeningen
# ---------------------------------------------------------------------------
def _screening_oppslag(screening) -> dict:
    if screening is None or getattr(screening, "empty", True):
        return {}
    if "ticker" not in screening.columns:
        return {}
    return {r["ticker"]: r.to_dict() for _, r in screening.iterrows()}


def _verdi(kilde: dict, nokkel):
    v = kilde.get(nokkel)
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _til_pivot(avstand) -> str:
    if avstand is None:
        return "—"
    try:
        return f"{float(avstand):+.1f} %"
    except (TypeError, ValueError):
        return "—"


def _naa_kurs(ticker: str, skop: dict) -> float | None:
    return _verdi(skop.get(ticker, {}), "pris")


# ---------------------------------------------------------------------------
# Hjelpere for data
# ---------------------------------------------------------------------------
def _sorg_for_startlister(lager: db.Lager) -> list[dict]:
    lister = lager.hent_lister()
    if lister:
        return lister
    for navn, farge, rekkefolge in START_LISTER:
        try:
            lager.lag_liste(navn, farge, rekkefolge)
        except db.JournalFeil:
            pass
    return lager.hent_lister()


def _beregn_handler(handler: list[dict], delsalg_alle: list[dict], skop: dict,
                    live_kurser: dict | None = None) -> list[dict]:
    """Beriker hver handel med utregnede tall (R, P&L, status osv.).

    `live_kurser` (valgfritt) = {ticker: pris} fra sanntid i åpningstid. Brukes
    som «nå-kurs» for ÅPNE handler når det finnes, så P&L/R blir live. Falles
    tilbake til siste sluttkurs fra skop ellers. Lukkede handler bruker salgs-
    kursene uansett (live rører dem ikke).
    """
    live_kurser = live_kurser or {}
    per_handel: dict[str, list] = {}
    for d in delsalg_alle:
        per_handel.setdefault(d["handel_id"], []).append(d)
    ut = []
    for h in handler:
        ds = per_handel.get(h["id"], [])
        naa = _naa_kurs(h["ticker"], skop)
        live = None
        if h.get("status") == "OPEN":
            lv = live_kurser.get(h["ticker"])
            try:
                if lv is not None and float(lv) > 0:
                    live = float(lv)
            except (TypeError, ValueError):
                live = None
        kurs_naa = live if live is not None else naa
        t = tall.handelstall(
            h.get("kjop_kurs"), h.get("antall"), h.get("stop"),
            delsalg=ds, kjop_dato=h.get("kjop_dato"), kurs_naa=kurs_naa)
        rad = dict(h)
        rad.update(t)
        rad["delsalg"] = ds
        rad["kurs_naa"] = kurs_naa
        rad["er_live"] = live is not None
        if ds:
            datoer = [d.get("salg_dato") for d in ds if d.get("salg_dato")]
            rad["slutt_dato"] = max(datoer) if datoer else None
        ut.append(rad)
    return ut


# ---------------------------------------------------------------------------
# HOVEDINNGANG
# ---------------------------------------------------------------------------
def vis_dashboard(bors_navn: str, screening, vis_ticker_fn=None,
                  datastatus: dict | None = None,
                  live_kurser: dict | None = None,
                  bors_apen: bool = False,
                  parabolsk: dict | None = None) -> None:
    _injiser_stil()
    if not tilgjengelig():
        st.subheader("📒 Journal")
        st.info(
            "Journalen er ikke koblet til databasen ennå. Når det er gjort, får du "
            "ett samlet dashboard med oversikt, lister, dagbok og trades – synlig på "
            "telefon, Mac og PC. Screeneren virker som før uten dette."
        )
        with st.expander("Slik kobler du til (engangsjobb)"):
            st.markdown(
                "1. Kjør SQL-en i `verktoy/journal_supabase.sql` i Supabase.\n"
                "2. Legg inn `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` og "
                "`JOURNAL_PASSORD` i Streamlit Secrets."
            )
        return

    if not innlogget():
        st.subheader("📒 Journal")
        st.info("🔒 Lås opp journalen med passordet i menyen til venstre. "
                "Samme passord på alle enheter.")
        return

    lager = _lager()

    # Er en ticker valgt? Vis ticker-siden i stedet for dashboardet.
    valgt_ticker = st.session_state.get("journal_ticker")
    if valgt_ticker:
        _vis_ticker_side(lager, valgt_ticker, bors_navn, screening, vis_ticker_fn)
        return

    try:
        lister = _sorg_for_startlister(lager)
        alle_aksjer = lager.hent_liste_aksjer()
        notater = lager.hent_notater()
        handler = lager.hent_handler()
        delsalg = lager.hent_delsalg()
    except db.JournalFeil as e:
        st.error(str(e))
        return

    skop = _screening_oppslag(screening)
    beregnet = _beregn_handler(handler, delsalg, skop, live_kurser)

    _vis_datastatus(datastatus)
    if bors_apen and live_kurser:
        st.caption("🔴 **Live** – åpne posisjoner viser sanntids P&L/R "
                   "(≈15 min forsinket) så lenge børsen er åpen.")
    _vis_oversikt(beregnet)
    st.divider()

    kol_lister, kol_dagbok = st.columns([3, 2], gap="large")
    with kol_lister:
        _vis_lister(lager, lister, alle_aksjer, bors_navn, skop, beregnet)
    with kol_dagbok:
        _vis_dagbok(lager, notater)
    st.divider()

    _vis_trades(lager, beregnet, bors_navn, skop, parabolsk)


# ---------------------------------------------------------------------------
# 1) OVERSIKT
# ---------------------------------------------------------------------------
def _vis_datastatus(datastatus: dict | None) -> None:
    """Liten statuslinje som viser hvor ferske kursdataene er (fra screeneren).

    Journalen bruker siste skanning til live Pris/RS/TS. Her ser du med ett blikk
    om de tallene er dagsferske eller gamle, uten å bytte fane.
    """
    if not datastatus or datastatus.get("tom"):
        return
    siste = datastatus.get("siste_dato")
    alder = datastatus.get("alder_dager")
    hentet = datastatus.get("sist_hentet")
    siste_s = f"{siste:%d.%m.%Y}" if siste is not None else "—"
    hentet_s = f"{hentet:%d.%m kl. %H:%M}" if hentet is not None else "—"
    if alder is not None and alder <= 4:
        st.success(f"✅ Kursdata oppdatert – siste handelsdag **{siste_s}** "
                   f"· sist hentet {hentet_s} (norsk tid)")
    else:
        st.warning(f"⚠️ Kursdata er fra **{siste_s}** "
                   f"({alder} dager siden) · sist hentet {hentet_s}. "
                   "Pris/RS/TS i listene kan være utdaterte.")


def _vis_oversikt(beregnet: list[dict]) -> None:
    st.subheader("📊 Oversikt")
    stat = tall.statistikk(beregnet)

    if stat["antall"] == 0:
        st.caption("Ingen handler loggført ennå. Loggfør din første under «💼 Trades» "
                   "så fylles nøkkeltallene inn her automatisk.")
        return

    c = st.columns(4)
    wr = stat["winrate"]
    wr_delta = f"{(wr-0.5)*100:+.0f} pp vs 50 %" if wr is not None else None
    c[0].metric("Winrate", f"{wr*100:.0f} %" if wr is not None else "—",
                delta=wr_delta, border=True,
                help="Andel lukkede handler med gevinst.")
    exp = stat["expectancy_r"]
    c[1].metric("Forventning", f"{exp:+.2f} R" if exp is not None else "—",
                delta=("positiv" if (exp or 0) > 0 else "negativ") if exp is not None else None,
                border=True,
                help="Snitt R per lukket handel. Over 0 = systemet tjener penger.")
    pf = stat["profit_factor"]
    pf_tekst = "∞" if pf == float("inf") else (f"{pf:.2f}" if pf is not None else "—")
    c[2].metric("Profit factor", pf_tekst, border=True,
                help="Brutto gevinst delt på brutto tap. Over 1 = lønnsomt.")
    c[3].metric("Lukket / åpne", f"{stat['lukket']} / {stat['apne']}", border=True)

    c2 = st.columns(4)
    sr = stat["snitt_r"]
    c2[0].metric("Snitt-R", f"{sr:+.2f}" if sr is not None else "—", border=True)
    c2[1].metric("Snitt holdedager", f"{stat['snitt_holdedager']:.0f}"
                 if stat["snitt_holdedager"] is not None else "—", border=True)
    tv = stat["snitt_time_value"]
    c2[2].metric("Time Value", f"{tv:.2f}" if tv is not None else "—", border=True,
                 help="Prosent avkastning per handelsdag (P/D). Høyere = raskere "
                      "penger. F.eks. 10 % på 3 dager = 3.33.")
    c2[3].metric("Realisert P&L", _penger(real := stat["sum_realisert"]), border=True,
                 delta=f"{real:+,.0f}".replace(",", " ") if real else None)

    c3 = st.columns(4)
    ure = stat["urealisert"]
    c3[0].metric("Urealisert", _penger(ure), border=True,
                 delta=f"{ure:+,.0f}".replace(",", " ") if ure else None)

    kurve = tall.kumulativ_r(beregnet)
    if kurve:
        df = pd.DataFrame(kurve)
        df["dato"] = pd.to_datetime(df["dato"])
        df = df.set_index("dato")[["kum_r"]].rename(columns={"kum_r": "Kumulativ R"})
        st.caption("Porteføljekurve – kumulativ R fra lukkede handler:")
        st.area_chart(df, height=220, color=FARGER["aksent"])
    else:
        st.caption("📈 Porteføljekurven tegnes når du har lukket din første handel.")


# ---------------------------------------------------------------------------
# 2a) MINE LISTER
# ---------------------------------------------------------------------------
_AKSJE_KOLONNER = {
    "Pris": st.column_config.NumberColumn("Pris", format="%.2f"),
    "RS": st.column_config.NumberColumn("RS", help="Relativ styrke 1–99 (fra siste skanning)."),
    "TS": st.column_config.NumberColumn("TS", format="%.0f", help="TrendScore 0–100."),
    "Min pivot": st.column_config.NumberColumn("Min pivot", format="%.2f"),
    "Min stop": st.column_config.NumberColumn("Min stop", format="%.2f"),
    "Mål": st.column_config.NumberColumn("Mål", format="%.2f"),
}


def _berik_aksjer(aksjer: list[dict], skop: dict) -> pd.DataFrame:
    rader = []
    for a in aksjer:
        s = skop.get(a["ticker"], {})
        status = _verdi(s, "status") or ""
        tekst = _verdi(s, "statustekst") or ""
        setup = f"{status} {tekst}".strip() or "—"
        score = _verdi(s, "score")
        rader.append({
            "id": a["id"],
            "Ticker": a["ticker"],
            "Pris": _verdi(s, "pris"),
            "Setup": setup,
            "Til pivot": _til_pivot(_verdi(s, "avstand_pivot")),
            "RS": _verdi(s, "rs"),
            "TS": _verdi(s, "trendscore"),
            "Kriterier": f"{int(score)}/7" if score is not None else "—",
            "Min pivot": a.get("pivot"),
            "Min stop": a.get("stop"),
            "Mål": a.get("mal"),
        })
    return pd.DataFrame(rader)


def _vis_lister(lager, lister, alle_aksjer, bors_navn, skop, beregnet=None) -> None:
    st.subheader("⭐ Mine lister")

    per_liste: dict[str, list] = {}
    for a in alle_aksjer:
        per_liste.setdefault(a["liste_id"], []).append(a)

    _administrer_lister(lager, lister)

    # Auto-porteføljer genereres fra handlene dine (ikke egne DB-lister):
    #   💼 Portefølje        = aksjer du har en ÅPEN handel i
    #   📁 Lukket portefølje = aksjer der siste handel er lukket
    beregnet = beregnet or []
    apne_t, lukket_t = _portefolje_tickere(beregnet)

    if not lister and not apne_t and not lukket_t:
        st.info("Du har ingen lister ennå. Lag én over for å komme i gang.")
        return

    auto = [
        ("💼 Portefølje", apne_t, "💼"),
        ("📁 Lukket", lukket_t, "📁"),
    ]
    fane_navn = [f"{l['navn']} ({len(per_liste.get(l['id'], []))})" for l in lister]
    fane_navn += [f"{navn} ({len(ts)})" for navn, ts, _ in auto]

    faner = st.tabs(fane_navn)
    for fane, liste in zip(faner, lister):
        with fane:
            _vis_en_liste(lager, liste, lister, per_liste.get(liste["id"], []),
                          bors_navn, skop)
    for fane, (navn, tickere, ikon) in zip(faner[len(lister):], auto):
        with fane:
            _vis_auto_portefolje(navn, tickere, skop, beregnet,
                                 lukket=(ikon == "📁"))


def _portefolje_tickere(beregnet: list[dict]) -> tuple[list[str], list[str]]:
    """Deler handlene i åpne og lukkede, og gir unike tickere per gruppe.

    En ticker regnes som «i portefølje» hvis den har minst én åpen handel.
    Den havner i «lukket» kun hvis den IKKE har noen åpen handel men har
    minst én lukket – så en ticker aldri står to steder samtidig.
    """
    apne, lukkede = [], []
    for h in beregnet:
        (apne if h.get("status") == "OPEN" else lukkede).append(h)
    apne_t, sett = [], set()
    for h in apne:
        t = h.get("ticker")
        if t and t not in sett:
            sett.add(t); apne_t.append(t)
    lukket_t, sett2 = [], set()
    for h in lukkede:
        t = h.get("ticker")
        if t and t not in sett and t not in sett2:
            sett2.add(t); lukket_t.append(t)
    return apne_t, lukket_t


def _vis_auto_portefolje(navn: str, tickere: list[str], skop: dict,
                         beregnet: list[dict], lukket: bool) -> None:
    """Skrivebeskyttet liste som speiler handlene dine. Oppdateres automatisk."""
    if lukket:
        st.caption("Aksjer der siste handel er lukket. Flyttes hit automatisk "
                   "når du lukker en posisjon.")
    else:
        st.caption("Aksjer du har en åpen posisjon i akkurat nå. Oppdateres "
                   "automatisk når du kjøper og selger.")
    if not tickere:
        st.caption("Ingen aksjer her ennå." if lukket
                   else "Ingen åpne posisjoner. Loggfør et kjøp under «Trades».")
        return

    # Tabell: ticker + litt kontekst fra siste skanning og handel.
    per_ticker: dict[str, list] = {}
    for h in beregnet:
        per_ticker.setdefault(h.get("ticker"), []).append(h)
    rader = []
    for t in tickere:
        s = skop.get(t, {})
        hs = per_ticker.get(t, [])
        rader.append({
            "Ticker": t,
            "Pris": _verdi(s, "pris"),
            "RS": _verdi(s, "rs"),
            "TS": _verdi(s, "trendscore"),
            "Handler": len(hs),
        })
    df = pd.DataFrame(rader)
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Pris": st.column_config.NumberColumn("Pris", format="%.2f"),
        "RS": st.column_config.NumberColumn("RS", help="Relativ styrke 1–99 (fra siste skanning)."),
        "TS": st.column_config.NumberColumn("TS", format="%.0f", help="TrendScore 0–100."),
        "Handler": st.column_config.NumberColumn("Handler", help="Antall handler på denne aksjen."),
    })

    nokkel = "lukket" if lukket else "apne"
    valgt = st.selectbox("Åpne aksje", tickere, key=f"auto_valg_{nokkel}")
    if st.button("🔍 Åpne", key=f"auto_apne_{nokkel}", width="stretch"):
        velg_ticker(valgt)
        st.rerun()


def _administrer_lister(lager, lister) -> None:
    c1, c2 = st.columns(2)
    with c1.popover("＋ Ny liste", width="stretch"):
        with st.form("ny_liste", clear_on_submit=True):
            navn = st.text_input("Navn", placeholder="f.eks. Momentum")
            farge = st.color_picker("Farge", value=FARGER["aksent"])
            if st.form_submit_button("Opprett", type="primary"):
                if not navn.strip():
                    st.warning("Gi listen et navn.")
                else:
                    try:
                        lager.lag_liste(navn, farge, len(lister))
                    except db.JournalFeil as e:
                        st.error(str(e))
                    else:
                        st.rerun()

    with c2.popover("✏️ Endre lister", width="stretch"):
        if not lister:
            st.caption("Ingen lister ennå.")
        for liste in lister:
            st.markdown(f"**{liste['navn']}**")
            r1, r2, r3 = st.columns([3, 1, 1])
            nytt = r1.text_input("Navn", value=liste["navn"],
                                 key=f"omnavn_{liste['id']}", label_visibility="collapsed")
            if r2.button("Lagre", key=f"lagre_{liste['id']}"):
                try:
                    lager.omdop_liste(liste["id"], navn=nytt)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
            if r3.button("🗑", key=f"slett_{liste['id']}", help="Slett listen"):
                st.session_state[f"bekreft_slett_{liste['id']}"] = True
            if st.session_state.get(f"bekreft_slett_{liste['id']}"):
                st.warning(f"Slette «{liste['navn']}» og alle aksjene på den?")
                b1, b2 = st.columns(2)
                if b1.button("Ja, slett", key=f"ja_{liste['id']}", type="primary"):
                    try:
                        lager.slett_liste(liste["id"])
                    except db.JournalFeil as e:
                        st.error(str(e))
                    else:
                        st.session_state.pop(f"bekreft_slett_{liste['id']}", None)
                        st.rerun()
                if b2.button("Avbryt", key=f"nei_{liste['id']}"):
                    st.session_state.pop(f"bekreft_slett_{liste['id']}", None)
                    st.rerun()
            st.divider()


def _vis_en_liste(lager, liste, alle_lister, aksjer, bors_navn, skop) -> None:
    with st.popover("＋ Legg til aksje", width="stretch"):
        with st.form(f"legg_til_{liste['id']}", clear_on_submit=True):
            ticker = st.text_input("Ticker", placeholder="EQNR eller AAPL",
                                   key=f"nyt_{liste['id']}")
            c2, c3, c4 = st.columns(3)
            pivot = c2.number_input("Pivot", min_value=0.0, step=0.1, format="%.2f",
                                    key=f"nyp_{liste['id']}")
            stop = c3.number_input("Stop", min_value=0.0, step=0.1, format="%.2f",
                                   key=f"nys_{liste['id']}")
            mal = c4.number_input("Mål", min_value=0.0, step=0.1, format="%.2f",
                                  key=f"nym_{liste['id']}")
            if st.form_submit_button("Legg til", type="primary"):
                if not ticker.strip():
                    st.warning("Skriv inn en ticker.")
                else:
                    try:
                        status = lager.legg_til_aksje(
                            liste["id"], ticker, bors_navn,
                            pivot=pivot or None, stop=stop or None, mal=mal or None)
                    except db.JournalFeil as e:
                        st.error(str(e))
                    else:
                        if status == "finnes":
                            st.info("Aksjen ligger allerede på denne listen.")
                        else:
                            st.rerun()

    if not aksjer:
        st.caption("Ingen aksjer her ennå. Legg til en over, eller bruk «Følg valgte» "
                   "i hovedlista etter en skanning.")
        return

    df = _berik_aksjer(aksjer, skop)
    st.dataframe(df.drop(columns=["id"]), width="stretch", hide_index=True,
                 column_config=_AKSJE_KOLONNER)
    if not skop:
        st.caption("💡 Skann børsen for å fylle inn Pris, Setup, RS og TrendScore.")

    etikett = {a["ticker"]: a for a in aksjer}
    valgt = st.selectbox("Velg aksje", list(etikett), key=f"velg_{liste['id']}")
    rad = etikett[valgt]
    c1, c2, c3 = st.columns(3)
    if c1.button("🔍 Åpne", key=f"apne_{liste['id']}", width="stretch"):
        velg_ticker(rad["ticker"])
        st.rerun()
    andre = [l for l in alle_lister if l["id"] != liste["id"]]
    if andre:
        with c2.popover("↦ Flytt", width="stretch"):
            mal_liste = st.selectbox("Flytt til", [l["navn"] for l in andre],
                                     key=f"flytt_valg_{liste['id']}")
            if st.button("Flytt", key=f"flytt_{liste['id']}", type="primary"):
                mid = next(l["id"] for l in andre if l["navn"] == mal_liste)
                try:
                    lager.flytt_aksje(rad["id"], mid)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
    if c3.button("🗑 Fjern", key=f"fjern_{liste['id']}", width="stretch"):
        try:
            lager.fjern_aksje(rad["id"])
        except db.JournalFeil as e:
            st.error(str(e))
        else:
            st.rerun()


# ---------------------------------------------------------------------------
# 2b) DAGBOK
# ---------------------------------------------------------------------------
def _vis_dagbok(lager, notater) -> None:
    st.subheader("📓 Dagbok")

    with st.popover("✍️ Nytt notat", width="stretch"):
        _notat_skjema(lager, forhandsvalgt=None, key="dagbok")

    if not notater:
        st.caption("Ingen notater ennå. Skriv ditt første over.")
        return

    tickere = sorted({n["ticker"] for n in notater})
    valgt = st.selectbox("Vis", ["Alle"] + tickere, key="dagbok_filter",
                         label_visibility="collapsed")
    vist = notater if valgt == "Alle" else [n for n in notater if n["ticker"] == valgt]

    with st.container(height=420):
        for n in vist:
            dato = _formater_dato(n.get("opprettet"))
            with st.container(border=True):
                top = st.columns([3, 1, 1])
                top[0].markdown(f"**{n['ticker']}** · {dato}")
                if top[1].button("🔍", key=f"dnd_{n['id']}", help="Åpne aksjen"):
                    velg_ticker(n["ticker"])
                    st.rerun()
                if top[2].button("🗑", key=f"slett_notat_{n['id']}", help="Slett notatet"):
                    try:
                        lager.slett_notat(n["id"])
                    except db.JournalFeil as e:
                        st.error(str(e))
                    else:
                        st.rerun()
                st.write(n.get("tekst") or "")


def _notat_skjema(lager, forhandsvalgt: str | None, key: str) -> None:
    with st.form(f"nytt_notat_{key}", clear_on_submit=True):
        if forhandsvalgt:
            ticker = forhandsvalgt
            st.caption(f"Notat for **{forhandsvalgt}**")
        else:
            ticker = st.text_input(
                "Ticker", placeholder="EQNR.OL eller AAPL",
                help="Skriv tickeren akkurat slik du vil ha den – "
                     "for Oslo-aksjer tar du med .OL selv.")
        tekst = st.text_area("Notat", placeholder="Hva ser du? Hva er planen?", height=100)
        bors = st.session_state.get("bors_navn", "Oslo Børs")
        if st.form_submit_button("Lagre notat", type="primary"):
            if not (ticker or "").strip() or not tekst.strip():
                st.warning("Både ticker og tekst må fylles inn.")
            else:
                try:
                    # Forhaandsvalgt ticker er allerede normalisert; frie notat
                    # lagres akkurat slik de skrives (ingen auto .OL).
                    lager.lag_notat(ticker, bors, tekst,
                                    normaliser=bool(forhandsvalgt))
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()


# ---------------------------------------------------------------------------
# 3) TRADES
# ---------------------------------------------------------------------------
def _penger(x) -> str:
    if x is None:
        return "—"
    return f"{x:+,.0f}".replace(",", " ")


def _farg_tall(df: pd.DataFrame, kolonner: list[str]):
    """Grønn tekst på positive tall, rød på negative – moderne og lettlest."""
    def _stil(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return ""
        if f > 0:
            return f"color: {FARGER['pos']}; font-weight: 600;"
        if f < 0:
            return f"color: {FARGER['neg']}; font-weight: 600;"
        return ""
    finnes = [k for k in kolonner if k in df.columns]
    return df.style.map(_stil, subset=finnes)


def _vis_trades(lager, beregnet, bors_navn, skop, parabolsk=None) -> None:
    st.subheader("💼 Trades")

    v1, v2 = st.columns(2)
    with v1.popover("＋ Loggfør kjøp", width="stretch"):
        _kjop_skjema(lager, bors_navn, forhandsvalgt=None, key="trades")
    with v2.popover("🧮 R/R-kalkulator", width="stretch"):
        _rr_kalkulator(key="trades")

    apne = [h for h in beregnet if h["status"] == "OPEN"]
    lukket = [h for h in beregnet if h["status"] == "CLOSED"]

    st.markdown(f"**Åpne posisjoner ({len(apne)})**")
    if not apne:
        st.caption("Ingen åpne posisjoner. Loggfør et kjøp over.")
    else:
        _kort_apne(lager, apne, skop, parabolsk)

    st.markdown(f"**Lukkede handler ({len(lukket)})**")
    if not lukket:
        st.caption("Ingen lukkede handler ennå.")
    else:
        _tabell_lukket(lukket)
        _slett_lukket(lager, lukket)
        _vis_periode_statistikk(lukket)


# --- R/R-kalkulator ---------------------------------------------------------
def _rr_kalkulator(key: str) -> None:
    """Live risk/reward- og posisjonskalkulator. Oppdaterer seg mens du skriver
    (ligger bevisst UTENFOR et skjema)."""
    st.caption("Regn ut R/R og antall aksjer før du kjøper. Ingenting lagres.")
    c1, c2, c3 = st.columns(3)
    entry = c1.number_input("Inngang", min_value=0.0, step=0.1, format="%.2f", key=f"rr_e_{key}")
    stop = c2.number_input("Stop", min_value=0.0, step=0.1, format="%.2f", key=f"rr_s_{key}")
    mal = c3.number_input("Mål", min_value=0.0, step=0.1, format="%.2f", key=f"rr_m_{key}")
    k1, k2 = st.columns(2)
    kapital = k1.number_input("Kapital", min_value=0.0, step=1000.0, value=100000.0,
                              format="%.0f", key=f"rr_k_{key}")
    risiko_pct = k2.number_input("Risiko %", min_value=0.0, max_value=100.0, step=0.25,
                                 value=1.0, format="%.2f", key=f"rr_r_{key}")

    if entry <= 0 or stop <= 0 or stop >= entry:
        st.info("Fyll inn inngang og en stop som er lavere enn inngangen.")
        return

    risiko_pr_aksje = entry - stop
    rr = (mal - entry) / risiko_pr_aksje if mal > entry else None
    pos = tall.posisjonsstorrelse(entry, stop, kapital, risiko_pct)

    m = st.columns(3)
    m[0].metric("R/R", f"{rr:.2f}" if rr else "—", border=True,
                help="Gevinst mot risiko. 3.0 = tjener 3× det du risikerer.")
    m[1].metric("Antall", f"{pos['antall']:g}" if pos["antall"] else "—", border=True)
    m[2].metric("Risiko", _penger(-pos["risiko_belop"]) if pos["risiko_belop"] else "—",
                border=True)
    m2 = st.columns(3)
    m2[0].metric("Kostnad", f"{pos['kostnad']:,.0f}".replace(",", " ")
                 if pos["kostnad"] else "—", border=True)
    m2[1].metric("Andel av konto", f"{pos['andel_pct']:.1f} %"
                 if pos["andel_pct"] is not None else "—", border=True)
    if mal > entry:
        gevinst = (mal - entry) * pos["antall"]
        m2[2].metric("Gevinst v/mål", _penger(gevinst), border=True)
    if rr is not None and rr < 2:
        st.warning("R/R under 2 – vurder høyere mål eller strammere stop.")


# --- moderne kort for åpne posisjoner ---------------------------------------
def _setup_badge(setup: str | None) -> None:
    if not setup or setup == "—":
        return
    farge = SETUP_FARGE.get(setup, "gray")
    st.badge(setup, color=farge)


def _parabolsk_varsel(pb: dict | None) -> None:
    """Gult "vokt deg / ta gevinst"-flagg når en åpen posisjon har gått parabolsk.

    Dette er Qullamaggies SHORT-oppsett – for oss KUN en observasjon på aksjer vi
    eier, aldri et handelssignal. Viser rådataene bak flagget i en tooltip.
    """
    if not pb:
        return
    biter = []
    if pb.get("opp_pct") is not None:
        biter.append(f"+{pb['opp_pct']:.0f} % på kort tid")
    if pb.get("gronne_rad"):
        biter.append(f"{pb['gronne_rad']} grønne dager på rad")
    if pb.get("over_ema10_pct") is not None:
        biter.append(f"{pb['over_ema10_pct']:.0f} % over EMA10")
    hjelp = ("Parabolsk bevegelse (QM3): " + ", ".join(biter) + ". "
             "Dette er et observasjonsflagg – vurder å ta delgevinst eller "
             "stramme stop. IKKE et kjøpssignal.") if biter else None
    st.badge("Parabolsk – vokt deg", color="orange", icon=":material/warning:")
    if hjelp:
        st.caption(f"⚠️ {hjelp}")


def _fremdrift(kjop, naa, stop, mal) -> tuple[float, str]:
    """Hvor langt fra stop (0) mot mål (1) ligger kursen nå? Returnerer (andel, tekst)."""
    try:
        kjop = float(kjop); naa = float(naa)
    except (TypeError, ValueError):
        return 0.0, ""
    lav = float(stop) if stop else kjop * 0.9
    hoy = float(mal) if mal else kjop * 1.2
    if hoy <= lav:
        return 0.0, ""
    andel = (naa - lav) / (hoy - lav)
    andel = max(0.0, min(1.0, andel))
    return andel, f"Stop {lav:.2f} → Mål {hoy:.2f}"


def _kort_apne(lager, apne, skop, parabolsk=None) -> None:
    parabolsk = parabolsk or {}
    kolonner = st.columns(2, gap="medium")
    for i, h in enumerate(apne):
        with kolonner[i % 2]:
            with st.container(border=True):
                naa = h.get("kurs_naa")
                kjop = h.get("kjop_kurs")
                r = h.get("r")
                pnl = h.get("total_pnl")

                topp = st.columns([2, 1])
                topp[0].markdown(f"### {h['ticker']}")
                with topp[1]:
                    if r is not None:
                        farge = "green" if r >= 0 else "red"
                        st.badge(f"{r:+.2f} R", color=farge, icon=":material/trending_up:")

                _setup_badge(h.get("setup"))
                _parabolsk_varsel(parabolsk.get(h.get("ticker")))

                # Nøkkeltall i tre små kolonner.
                m = st.columns(3)
                m[0].caption("Kjøpt")
                m[0].markdown(f"**{kjop:.2f}**" if kjop else "—")
                m[1].caption("🔴 Nå (live)" if h.get("er_live") else "Nå")
                m[1].markdown(f"**{naa:.2f}**" if naa else "—")
                m[2].caption("P&L")
                if pnl is not None:
                    f = FARGER["pos"] if pnl >= 0 else FARGER["neg"]
                    m[2].markdown(f"<b style='color:{f}'>{pnl:+,.0f}</b>".replace(",", " "),
                                  unsafe_allow_html=True)
                else:
                    m[2].markdown("—")

                # Fremdriftslinje stop → mål.
                if naa:
                    andel, tekst = _fremdrift(kjop, naa, h.get("stop"), h.get("mal"))
                    if tekst:
                        st.progress(andel, text=tekst)

                bunn = st.columns([1, 1, 2])
                dager = h.get("holdedager")
                bunn[0].caption(f"📅 {dager}d" if dager else "📅 —")
                antall = h.get("antall_igjen")
                bunn[1].caption(f"📦 {antall:g}" if antall else "📦 —")
                if bunn[2].button("Håndter ▸", key=f"handter_{h['id']}", width="stretch"):
                    st.session_state["handter_id"] = h["id"]

    # Håndteringspanel for valgt posisjon.
    valgt_id = st.session_state.get("handter_id")
    if valgt_id:
        valgt = next((h for h in apne if h["id"] == valgt_id), None)
        if valgt:
            st.divider()
            _handter_en(lager, valgt, skop)


def _handter_en(lager, h, skop) -> None:
    """Selg, juster stop/mål eller lukk ÉN valgt posisjon."""
    c = st.columns([3, 1])
    c[0].markdown(f"#### Håndter {h['ticker']}")
    if c[1].button("Lukk panel", key=f"lukk_panel_{h['id']}", width="stretch"):
        st.session_state.pop("handter_id", None)
        st.rerun()
    igjen = h.get("antall_igjen") or 0

    if st.button("🔍 Åpne aksjen", key=f"handter_apne_{h['id']}"):
        velg_ticker(h["ticker"])
        st.rerun()

    faner = st.tabs(["Selg", "Juster stop/mål", "Lukk", "Slett"])
    with faner[0]:
        with st.form(f"selg_{h['id']}", clear_on_submit=True):
            st.caption(f"Du har {igjen:g} igjen av {h['ticker']}.")
            s1, s2, s3 = st.columns(3)
            naa = _naa_kurs(h["ticker"], skop)
            salg_kurs = s1.number_input("Salgskurs", min_value=0.0, step=0.1,
                                        value=float(naa) if naa else 0.0, format="%.2f")
            antall = s2.number_input("Antall", min_value=0.0, max_value=float(igjen),
                                     value=float(igjen), step=1.0)
            dato = s3.date_input("Dato", value=date.today())
            arsak = st.text_input("Årsak (valgfritt)", placeholder="Mål nådd, stop, delsalg …")
            if st.form_submit_button("Registrer salg", type="primary"):
                if salg_kurs <= 0 or antall <= 0:
                    st.warning("Fyll inn gyldig kurs og antall.")
                else:
                    try:
                        lager.lag_delsalg(h["id"], str(dato), salg_kurs, antall, arsak)
                        if antall >= igjen - 1e-9:
                            lager.sett_status(h["id"], "CLOSED")
                            st.session_state.pop("handter_id", None)
                    except db.JournalFeil as e:
                        st.error(str(e))
                    else:
                        st.rerun()
    with faner[1]:
        with st.form(f"juster_{h['id']}", clear_on_submit=False):
            j1, j2 = st.columns(2)
            ny_stop = j1.number_input("Ny stop", min_value=0.0, step=0.1,
                                      value=float(h.get("stop") or 0), format="%.2f")
            ny_mal = j2.number_input("Nytt mål", min_value=0.0, step=0.1,
                                     value=float(h.get("mal") or 0), format="%.2f")
            if st.form_submit_button("Lagre stop/mål", type="primary"):
                try:
                    lager.oppdater_handel(h["id"], stop=ny_stop or None, mal=ny_mal or None)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
    with faner[2]:
        with st.form(f"lukk_{h['id']}", clear_on_submit=True):
            st.caption("Lukk hele posisjonen og evaluér.")
            fulgte = st.checkbox("Jeg fulgte planen", value=True)
            evaluering = st.text_area("Evaluering", placeholder="Hva gikk bra/dårlig?", height=80)
            if st.form_submit_button("Lukk posisjon", type="primary"):
                try:
                    naa = _naa_kurs(h["ticker"], skop)
                    if igjen > 0 and naa:
                        lager.lag_delsalg(h["id"], str(date.today()), naa, igjen, "Lukket")
                    lager.oppdater_handel(h["id"], status="CLOSED",
                                          fulgte_plan=fulgte, evaluering=evaluering)
                    st.session_state.pop("handter_id", None)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
    with faner[3]:
        st.caption("Sletter handelen og alle delsalg permanent.")
        bekreft_key = f"bekreft_slett_handel_{h['id']}"
        if not st.session_state.get(bekreft_key):
            if st.button("🗑 Slett handel helt", key=f"slett_handel_{h['id']}"):
                st.session_state[bekreft_key] = True
                st.rerun()
        else:
            st.warning(f"Sikker på at du vil slette hele handelen i {h['ticker']}? "
                       "Dette kan ikke angres.")
            b1, b2 = st.columns(2)
            if b1.button("Ja, slett", key=f"ja_slett_handel_{h['id']}", type="primary"):
                try:
                    lager.slett_handel(h["id"])
                    st.session_state.pop("handter_id", None)
                    st.session_state.pop(bekreft_key, None)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
            if b2.button("Avbryt", key=f"nei_slett_handel_{h['id']}"):
                st.session_state.pop(bekreft_key, None)
                st.rerun()


def _tabell_lukket(lukket) -> None:
    rader = []
    for h in lukket:
        plan = h.get("fulgte_plan")
        rader.append({
            "Ticker": h["ticker"],
            "Kjøpt": _dato_kort(h.get("kjop_dato")),
            "Lukket": _dato_kort(h.get("slutt_dato")),
            "Resultat": "✅" if h.get("vinn") else "❌",
            "R": h.get("r"),
            "P&L": h.get("total_pnl"),
            "%": h.get("pnl_pct"),
            "Dager": h.get("holdedager"),
            "TV": h.get("time_value"),
            "Setup": h.get("setup") or "—",
            "Plan": "✓" if plan else ("✗" if plan is False else "—"),
        })
    df = pd.DataFrame(rader)
    st.dataframe(_farg_tall(df, ["R", "P&L", "%"]), width="stretch", hide_index=True,
                 column_config={
        "R": st.column_config.NumberColumn(format="%.2f"),
        "P&L": st.column_config.NumberColumn(format="%.0f"),
        "%": st.column_config.NumberColumn(format="%.1f %%"),
        "TV": st.column_config.NumberColumn(
            format="%.2f", help="Time Value = prosent avkastning per handelsdag (P/D). Høyere = raskere penger."),
    })


def _slett_lukket(lager, lukket) -> None:
    """Slett en lukket handel som er lagt inn feil (med bekreftelse)."""
    with st.expander("🗑 Slett en lukket handel (lagt inn feil)"):
        st.caption("Velg handelen du vil fjerne permanent. Dette sletter også "
                   "alle delsalg på handelen og kan ikke angres.")
        valg = {
            f"{h['ticker']} · kjøpt {_dato_kort(h.get('kjop_dato'))} · "
            f"lukket {_dato_kort(h.get('slutt_dato'))} "
            f"({(h.get('r') if h.get('r') is not None else 0):+.2f} R)": h["id"]
            for h in lukket
        }
        etikett = st.selectbox("Handel", list(valg), key="slett_lukket_valg")
        valgt_id = valg.get(etikett)
        bekreft_key = f"bekreft_slett_lukket_{valgt_id}"
        if not st.session_state.get(bekreft_key):
            if st.button("🗑 Slett valgt handel", key="slett_lukket_knapp"):
                st.session_state[bekreft_key] = True
                st.rerun()
        else:
            st.warning(f"Sikker på at du vil slette «{etikett}»? Kan ikke angres.")
            b1, b2 = st.columns(2)
            if b1.button("Ja, slett", key="ja_slett_lukket", type="primary"):
                try:
                    lager.slett_handel(valgt_id)
                    st.session_state.pop(bekreft_key, None)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.success("Handelen er slettet.")
                    st.rerun()
            if b2.button("Avbryt", key="nei_slett_lukket"):
                st.session_state.pop(bekreft_key, None)
                st.rerun()


# --- uke/måned-statistikk ---------------------------------------------------
def _periode_nokkel(iso, oppl: str) -> str | None:
    """Gjør en sluttdato om til en periode-etikett (uke eller måned)."""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None
    if oppl == "Måned":
        return d.strftime("%Y-%m")
    iso_aar, iso_uke, _ = d.isocalendar()
    return f"{iso_aar}-U{iso_uke:02d}"


def _vis_periode_statistikk(lukket: list[dict]) -> None:
    """Winrate, R og P&L gruppert per uke eller måned (lukkede handler)."""
    with st.expander("📅 Statistikk per periode"):
        oppl = st.radio("Oppløsning", ["Uke", "Måned"], horizontal=True,
                        key="periode_oppl", label_visibility="collapsed")
        grupper: dict[str, list] = {}
        for h in lukket:
            nk = _periode_nokkel(h.get("slutt_dato"), oppl)
            if nk:
                grupper.setdefault(nk, []).append(h)
        if not grupper:
            st.caption("Ingen lukkede handler med dato ennå.")
            return

        rader = []
        for navn in sorted(grupper, reverse=True):
            st_ = tall.statistikk(grupper[navn])
            wr = st_["winrate"]
            rader.append({
                "Periode": navn,
                "Handler": st_["lukket"],
                "Winrate": f"{wr*100:.0f} %" if wr is not None else "—",
                "Snitt-R": st_["snitt_r"],
                "Sum R": round(sum(h["r"] for h in grupper[navn] if h.get("r") is not None), 2),
                "P&L": st_["sum_realisert"],
            })
        df = pd.DataFrame(rader)
        st.dataframe(_farg_tall(df, ["Snitt-R", "Sum R", "P&L"]),
                     width="stretch", hide_index=True, column_config={
            "Snitt-R": st.column_config.NumberColumn(format="%.2f"),
            "Sum R": st.column_config.NumberColumn(format="%.2f"),
            "P&L": st.column_config.NumberColumn(format="%.0f"),
        })

        # Søyler: sum R per periode (stigende tid for lesbarhet).
        kurve = df[["Periode", "Sum R"]].set_index("Periode").sort_index()
        st.caption("Sum R per periode:")
        st.bar_chart(kurve, height=200, color=FARGER["aksent"])


def _kjop_skjema(lager, bors_navn, forhandsvalgt: str | None, key: str) -> None:
    with st.form(f"kjop_{key}", clear_on_submit=True):
        if forhandsvalgt:
            ticker = forhandsvalgt
            st.caption(f"Loggfør kjøp av **{forhandsvalgt}**")
        else:
            ticker = st.text_input("Ticker", placeholder="EQNR")
        c1, c2, c3 = st.columns(3)
        kjop_dato = c1.date_input("Kjøpsdato", value=date.today())
        kjop_kurs = c2.number_input("Kjøpskurs", min_value=0.0, step=0.1, format="%.2f")
        antall = c3.number_input("Antall", min_value=0.0, step=1.0)
        p1, p2, p3 = st.columns(3)
        pivot = p1.number_input("Pivot", min_value=0.0, step=0.1, format="%.2f")
        stop = p2.number_input("Stop", min_value=0.0, step=0.1, format="%.2f")
        mal = p3.number_input("Mål", min_value=0.0, step=0.1, format="%.2f")
        s1, s2 = st.columns(2)
        setup = s1.selectbox("Setup", hent_setup_valg(lager))
        trigger = s2.selectbox("Trigger", hent_trigger_valg(lager))
        notat = st.text_area("Notat (valgfritt)", height=70)
        if st.form_submit_button("Loggfør kjøp", type="primary"):
            if not (ticker or "").strip() or kjop_kurs <= 0 or antall <= 0:
                st.warning("Ticker, kjøpskurs og antall må fylles inn.")
            elif stop and stop >= kjop_kurs:
                st.warning("Stop må være lavere enn kjøpskursen.")
            else:
                try:
                    lager.lag_handel({
                        "ticker": ticker, "bors": bors_navn,
                        "kjop_dato": str(kjop_dato), "kjop_kurs": kjop_kurs,
                        "antall": antall, "pivot": pivot or None, "stop": stop or None,
                        "mal": mal or None, "setup": setup, "trigger": trigger,
                        "notat": notat,
                    })
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()


# ---------------------------------------------------------------------------
# TICKER-SIDE (drill-down)
# ---------------------------------------------------------------------------
def _bygg_handel_data(lager, ticker, bors_navn) -> dict | None:
    """Henter dine kjøp/salg for aksjen og bygger chart-markører + pos (inngang/stop/mål).

    Markørene får bevisst INGEN layer – da vises de alltid i chartet (ikke skjult
    bak en lag-knapp). Grønn pil opp = kjøp, rød pil ned = salg.
    """
    norm = db.normaliser_ticker(ticker, bors_navn)
    try:
        handler = [h for h in lager.hent_handler() if h.get("ticker") == norm]
        delsalg = lager.hent_delsalg()
    except db.JournalFeil:
        return None
    if not handler:
        return None

    per_handel: dict[str, list] = {}
    for d in delsalg:
        per_handel.setdefault(d["handel_id"], []).append(d)

    markorer = []
    for h in handler:
        if h.get("kjop_dato"):
            kurs = h.get("kjop_kurs")
            markorer.append({
                "time": str(h["kjop_dato"])[:10], "position": "belowBar",
                "color": FARGER["pos"], "shape": "arrowUp",
                "text": f"Kjøp{(' ' + format(kurs, '.2f')) if kurs else ''}",
            })
        for d in per_handel.get(h["id"], []):
            if d.get("salg_dato"):
                sk = d.get("salg_kurs")
                markorer.append({
                    "time": str(d["salg_dato"])[:10], "position": "aboveBar",
                    "color": FARGER["neg"], "shape": "arrowDown",
                    "text": f"Salg{(' ' + format(sk, '.2f')) if sk else ''}",
                })

    # pos = siste åpne handel (eller nyeste) med gyldig stop < inngang < mål.
    pos = None
    apne = [h for h in handler if h.get("status") == "OPEN"] or handler
    for h in sorted(apne, key=lambda x: str(x.get("kjop_dato") or ""), reverse=True):
        try:
            e = float(h.get("kjop_kurs"))
            s = float(h.get("stop")) if h.get("stop") else None
            m = float(h.get("mal")) if h.get("mal") else None
            if s and m and s < e < m:
                pos = {"entry": e, "stop": s, "mal": m}
                break
        except (TypeError, ValueError):
            continue

    if not markorer and not pos:
        return None
    return {"markorer": markorer, "pos": pos}


def _vis_ticker_side(lager, ticker, bors_navn, screening, vis_ticker_fn) -> None:
    c1, c2 = st.columns([1, 5])
    if c1.button("← Tilbake", width="stretch"):
        _lukk_ticker()
        st.rerun()
    c2.subheader(f"📈 {ticker}")

    handel_data = _bygg_handel_data(lager, ticker, bors_navn)
    if handel_data:
        st.caption("📍 Chartet viser dine kjøp/salg (piler) og inngang/stop/mål "
                   "fra handelen din.")

    if vis_ticker_fn is not None:
        try:
            vis_ticker_fn(ticker, kontekst="journal", handel_data=handel_data)
        except TypeError:
            # Eldre signatur uten handel_data – fall tilbake.
            try:
                vis_ticker_fn(ticker, kontekst="journal")
            except Exception as e:
                st.warning(f"Klarte ikke tegne aksjevisningen: {e}")
        except Exception as e:
            st.warning(f"Klarte ikke tegne aksjevisningen: {e}")
    else:
        st.info("Aksjevisningen er ikke tilgjengelig i denne konteksten.")

    st.divider()
    kol1, kol2 = st.columns(2, gap="large")
    with kol1:
        st.markdown("### ✍️ Nytt notat")
        _notat_skjema(lager, forhandsvalgt=ticker, key=f"ts_{ticker}")
    with kol2:
        st.markdown("### 💼 Loggfør kjøp")
        _kjop_skjema(lager, bors_navn, forhandsvalgt=ticker, key=f"ts_{ticker}")

    st.markdown(f"### 📓 Notater for {ticker}")
    try:
        notater = lager.hent_notater(db.normaliser_ticker(ticker, bors_navn))
    except db.JournalFeil as e:
        st.error(str(e))
        notater = []
    if not notater:
        st.caption("Ingen notater for denne aksjen ennå.")
    else:
        for n in notater:
            with st.container(border=True):
                top = st.columns([4, 1])
                top[0].markdown(f"**{_formater_dato(n.get('opprettet'))}**")
                if top[1].button("🗑", key=f"tsnd_{n['id']}", help="Slett"):
                    try:
                        lager.slett_notat(n["id"])
                    except db.JournalFeil as e:
                        st.error(str(e))
                    else:
                        st.rerun()
                st.write(n.get("tekst") or "")


# ---------------------------------------------------------------------------
# Små hjelpere
# ---------------------------------------------------------------------------
def _formater_dato(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return str(iso)[:16]


def _dato_kort(iso) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d.%m.%y")
    except (ValueError, TypeError):
        return str(iso)[:10]


# ---------------------------------------------------------------------------
# INNSTILLINGER (egen fane) – rydder sidebaren og samler valg
# ---------------------------------------------------------------------------
def _rediger_tagger(lager, tittel: str, nokkel: str, standard: list[str]) -> None:
    """Redigerbar taggliste lagret i Supabase (synkes paa tvers av enheter)."""
    valg = hent_setup_valg(lager) if nokkel == NOKKEL_SETUP else hent_trigger_valg(lager)
    st.markdown(f"**{tittel}**")

    def _lagre(ny_liste: list[str]) -> None:
        rene = []
        for t in ny_liste:
            t = (t or "").strip()
            if t and t not in rene:
                rene.append(t)
        try:
            lager.sett_innstilling(nokkel, rene)
        except db.JournalFeil as e:
            st.error(f"Kunne ikke lagre: {e}")
            return
        st.session_state.get("_tagg_cache", {}).pop(nokkel, None)
        st.rerun()

    if valg:
        for i, t in enumerate(valg):
            c1, c2 = st.columns([6, 1])
            c1.write(f"• {t}")
            if c2.button("🗑", key=f"tagdel_{nokkel}_{i}", help=f"Fjern «{t}»"):
                _lagre([x for x in valg if x != t])
    else:
        st.caption("Ingen tagger ennå.")

    with st.form(f"legg_tagg_{nokkel}", clear_on_submit=True):
        c1, c2 = st.columns([4, 1])
        ny = c1.text_input("Ny tag", key=f"ny_tagg_{nokkel}",
                           label_visibility="collapsed", placeholder="Legg til ny …")
        if c2.form_submit_button("＋ Legg til", width="stretch"):
            if (ny or "").strip():
                _lagre(valg + [ny.strip()])

    if valg != standard:
        if st.button("↩︎ Tilbakestill til standard", key=f"nullstill_{nokkel}"):
            _lagre(list(standard))


def vis_innstillinger(bors_navn: str) -> None:
    """Samleside for innstillinger. Rydder sidebaren – alt valgfritt på ett sted."""
    _injiser_stil()
    st.subheader("⚙️ Innstillinger")

    lager = _lager()

    # --- Redigerbare tagger (krever tilkoblet + opplåst journal) ---
    with st.container(border=True):
        st.markdown("### 🏷️ Tagger for handler")
        st.caption("Rediger setup- og trigger-valgene du får når du loggfører kjøp. "
                   "Lagres i databasen, så de er like på telefon, Mac og PC.")
        if not tilgjengelig():
            st.info("Koble til journalen (se fanen «Journal») for å redigere tagger.")
        elif not innlogget():
            st.info("🔒 Lås opp journalen i menyen til venstre for å redigere tagger.")
        else:
            k1, k2 = st.columns(2)
            with k1:
                _rediger_tagger(lager, "Setup", NOKKEL_SETUP, SETUP_VALG)
            with k2:
                _rediger_tagger(lager, "Trigger", NOKKEL_TRIGGER, TRIGGER_VALG)

    # --- Egne tickere (likviditets-/universfil) ---
    with st.container(border=True):
        st.markdown("### 📄 Egne tickere (universfil)")
        st.caption("Dine ekstra tickere i data/univers.txt, i tillegg til den "
                   "auto-hentede børslista. Én ticker per linje (f.eks. AAPL eller NHY.OL).")
        from motor import univers
        try:
            naavaerende = univers.les_manuelle()
        except Exception as e:                       # robusthet – aldri krasj siden
            naavaerende = []
            st.warning(f"Klarte ikke lese universfila: {e}")
        with st.form("egne_tickere", clear_on_submit=False):
            tekst = st.text_area("Tickere", value="\n".join(naavaerende), height=160,
                                 label_visibility="collapsed")
            if st.form_submit_button("💾 Lagre tickere", type="primary"):
                linjer = [l.strip() for l in (tekst or "").splitlines()]
                try:
                    lagret = univers.skriv_manuelle(linjer)
                except Exception as e:
                    st.error(f"Kunne ikke lagre: {e}")
                else:
                    st.success(f"Lagret {len(lagret)} tickere. "
                               "De er med ved neste skanning.")
        st.caption("ℹ️ Endringen gjelder lokalt og tas med i neste skanning. "
                   "På nettutgaven (Streamlit Cloud) nullstilles fila ved ny oppstart – "
                   "der styrer roboten universet.")

    # --- Generelt / status ---
    with st.container(border=True):
        st.markdown("### 🧭 Generelt")
        st.write(f"Valgt børs: **{bors_navn}**")
        konf = _konf()
        if konf is None:
            st.caption("Journal-database: ikke koblet til.")
        elif innlogget():
            st.caption("Journal-database: ✅ tilkoblet og låst opp.")
        else:
            st.caption("Journal-database: tilkoblet (lås opp i menyen for full tilgang).")

