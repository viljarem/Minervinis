"""
journal_ui.py – Streamlit-UI for tradingjournalen.

Denne fila tegner skjema og tabeller. All lagring ligger i motor/journal_db.py
og all matematikk i motor/journal_tall.py. Feiler databasen, viser vi en vennlig
melding – screeneren påvirkes aldri.

Nå inneholder den (steg 3b):
  * passordlås i sidebaren
  * fanen «Mine lister» (opprett/omdøp/slett lister, flytt/fjern aksjer,
    live-kolonner fra screeningen, dagbok per aksje)
  * følg-knapp som hovedlista kan kalle for å legge valgte aksjer på en liste
Handler, dashboard og chart-piler kommer i senere steg.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from motor import journal_db as db

# Tre forslag som opprettes FØRSTE gang (du kan omdøpe/slette fritt).
START_LISTER = [
    ("Watchlist", "#3b82f6", 0),
    ("High alert", "#f59e0b", 1),
    ("Parkert", "#6b7280", 2),
]


# ---------------------------------------------------------------------------
# Tilkobling og lås
# ---------------------------------------------------------------------------
def _konf():
    return db.les_secrets()


def tilgjengelig() -> bool:
    """True hvis secrets finnes (databasen er satt opp)."""
    return _konf() is not None


def innlogget() -> bool:
    return bool(st.session_state.get("journal_ok")) and tilgjengelig()


def sidebar_las() -> None:
    """Passordfelt nederst i menyen. Opplåsing varer til siden lastes på nytt."""
    st.divider()
    st.header("📒 Journal")
    konf = _konf()
    if konf is None:
        st.caption("Databasen er ikke koblet til ennå. Se fanen «Mine lister».")
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


def _krev_tilgang() -> db.Lager | None:
    """Viser forklaring og returnerer lageret, eller None hvis vi skal stoppe."""
    if not tilgjengelig():
        st.info(
            "Journalen er ikke koblet til databasen ennå. Når det er gjort, kan du "
            "følge aksjer, skrive dagbok og loggføre handler – og se det samme på "
            "telefon, Mac og PC. Screeneren virker som før uten dette."
        )
        with st.expander("Slik kobler du til (engangsjobb)"):
            st.markdown(
                "1. Kjør SQL-en i `verktoy/journal_supabase.sql` i Supabase.\n"
                "2. Legg inn `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` og "
                "`JOURNAL_PASSORD` i Streamlit Secrets (se `.streamlit/"
                "secrets.toml.example`)."
            )
        return None
    if not innlogget():
        st.info("🔒 Lås opp journalen med passordet i menyen til venstre. "
                "Samme passord på alle enheter.")
        return None
    return _lager()


def _sorg_for_startlister(lager: db.Lager) -> list[dict]:
    """Henter lister; oppretter tre forslag hvis brukeren ikke har noen ennå."""
    lister = lager.hent_lister()
    if lister:
        return lister
    for navn, farge, rekkefolge in START_LISTER:
        try:
            lager.lag_liste(navn, farge, rekkefolge)
        except db.JournalFeil:
            pass
    return lager.hent_lister()


# ---------------------------------------------------------------------------
# Følg-knapp (brukes fra hovedlista i app.py)
# ---------------------------------------------------------------------------
def folg_knapp(tickere: list[str], bors: str, *, key: str) -> None:
    """Legger valgte tickere på en liste brukeren velger. Rolig hvis ikke låst opp."""
    if not tickere:
        return
    if not tilgjengelig():
        st.caption("💡 Koble til journalen for å kunne følge aksjer (se fanen «Mine lister»).")
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


def _berik_aksjer(aksjer: list[dict], screening) -> pd.DataFrame:
    treff = _screening_oppslag(screening)
    rader = []
    for a in aksjer:
        s = treff.get(a["ticker"], {})
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


_AKSJE_KOLONNER = {
    "Pris": st.column_config.NumberColumn("Pris", format="%.2f"),
    "RS": st.column_config.NumberColumn("RS", help="Relativ styrke 1–99 (fra siste skanning)."),
    "TS": st.column_config.NumberColumn("TS", format="%.0f", help="TrendScore 0–100."),
    "Min pivot": st.column_config.NumberColumn("Min pivot", format="%.2f"),
    "Min stop": st.column_config.NumberColumn("Min stop", format="%.2f"),
    "Mål": st.column_config.NumberColumn("Mål", format="%.2f"),
}


# ---------------------------------------------------------------------------
# Fanen «Mine lister»
# ---------------------------------------------------------------------------
def vis_mine_lister(bors_navn: str, screening) -> None:
    st.subheader("⭐ Mine lister")
    st.caption(
        "Du lagrer tickeren og hvilken liste den ligger på. Pris, setup, RS og "
        "TrendScore hentes på nytt fra siste skanning – de fryser ikke fast."
    )
    lager = _krev_tilgang()
    if lager is None:
        return

    try:
        lister = _sorg_for_startlister(lager)
        alle_aksjer = lager.hent_liste_aksjer()
    except db.JournalFeil as e:
        st.error(str(e))
        return

    # Aksjer gruppert per liste-id.
    per_liste: dict[str, list] = {}
    for a in alle_aksjer:
        per_liste.setdefault(a["liste_id"], []).append(a)

    _administrer_lister(lager, lister)
    st.divider()

    if not lister:
        st.info("Du har ingen lister ennå. Lag én over for å komme i gang.")
        return

    # Én fane per liste, så det blir oversiktlig på mobil.
    faner = st.tabs([f"{l['navn']} ({len(per_liste.get(l['id'], []))})" for l in lister])
    for fane, liste in zip(faner, lister):
        with fane:
            _vis_en_liste(lager, liste, lister, per_liste.get(liste["id"], []),
                          bors_navn, screening)

    st.divider()
    _vis_dagbok(lager)


def _administrer_lister(lager: db.Lager, lister: list[dict]) -> None:
    """Opprett ny liste + omdøp/slett eksisterende, pakket i hver sin popover."""
    c1, c2 = st.columns(2)
    with c1.popover("＋ Ny liste", width="stretch"):
        with st.form("ny_liste", clear_on_submit=True):
            navn = st.text_input("Navn", placeholder="f.eks. Momentum")
            farge = st.color_picker("Farge", value="#3b82f6")
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
            # Slett med bekreftelse.
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


def _vis_en_liste(lager, liste, alle_lister, aksjer, bors_navn, screening) -> None:
    # Legg til aksje manuelt.
    with st.form(f"legg_til_{liste['id']}", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
        ticker = c1.text_input("Ticker", placeholder="EQNR eller AAPL",
                               key=f"nyt_{liste['id']}")
        pivot = c2.number_input("Pivot", min_value=0.0, step=0.1, format="%.2f",
                                key=f"nyp_{liste['id']}")
        stop = c3.number_input("Stop", min_value=0.0, step=0.1, format="%.2f",
                               key=f"nys_{liste['id']}")
        mal = c4.number_input("Mål", min_value=0.0, step=0.1, format="%.2f",
                              key=f"nym_{liste['id']}")
        if c5.form_submit_button("＋ Legg til", type="primary"):
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

    df = _berik_aksjer(aksjer, screening)
    st.dataframe(df.drop(columns=["id"]), width="stretch", hide_index=True,
                 column_config=_AKSJE_KOLONNER)
    if screening is None:
        st.caption("💡 Skann børsen for å fylle inn Pris, Setup, RS og TrendScore.")

    # Flytt eller fjern en aksje.
    with st.expander("Flytt eller fjern en aksje"):
        etikett = {a["ticker"]: a for a in aksjer}
        valgt = st.selectbox("Aksje", list(etikett), key=f"endre_valg_{liste['id']}")
        rad = etikett[valgt]
        andre = [l for l in alle_lister if l["id"] != liste["id"]]
        c1, c2 = st.columns(2)
        if andre:
            mal_liste = c1.selectbox("Flytt til", [l["navn"] for l in andre],
                                     key=f"flytt_valg_{liste['id']}")
            if c1.button("Flytt", key=f"flytt_{liste['id']}"):
                mid = next(l["id"] for l in andre if l["navn"] == mal_liste)
                try:
                    lager.flytt_aksje(rad["id"], mid)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
        if c2.button("🗑 Fjern fra listen", key=f"fjern_{liste['id']}"):
            try:
                lager.fjern_aksje(rad["id"])
            except db.JournalFeil as e:
                st.error(str(e))
            else:
                st.rerun()


# ---------------------------------------------------------------------------
# Dagbok
# ---------------------------------------------------------------------------
def _vis_dagbok(lager: db.Lager) -> None:
    st.subheader("📓 Dagbok")
    st.caption("Skriv daterte notater om en aksje. Gamle notater består, så du "
               "kan følge tankerekken din over tid.")

    try:
        notater = lager.hent_notater()
    except db.JournalFeil as e:
        st.error(str(e))
        return

    with st.form("nytt_notat", clear_on_submit=True):
        c1, c2 = st.columns([1, 3])
        ticker = c1.text_input("Ticker", placeholder="EQNR")
        tekst = c2.text_area("Notat", placeholder="Hva ser du? Hva er planen?", height=80)
        bors = st.session_state.get("bors_navn", "Oslo Børs")
        if st.form_submit_button("Lagre notat", type="primary"):
            if not ticker.strip() or not tekst.strip():
                st.warning("Både ticker og tekst må fylles inn.")
            else:
                try:
                    lager.lag_notat(ticker, bors, tekst)
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()

    if not notater:
        st.caption("Ingen notater ennå.")
        return

    # Filtrer på ticker.
    tickere = sorted({n["ticker"] for n in notater})
    valgt = st.selectbox("Vis notater for", ["Alle"] + tickere, key="dagbok_filter")
    vist = notater if valgt == "Alle" else [n for n in notater if n["ticker"] == valgt]

    for n in vist:
        dato = _formater_dato(n.get("opprettet"))
        with st.container(border=True):
            top = st.columns([3, 1])
            top[0].markdown(f"**{n['ticker']}** · {dato}")
            if top[1].button("🗑", key=f"slett_notat_{n['id']}", help="Slett notatet"):
                try:
                    lager.slett_notat(n["id"])
                except db.JournalFeil as e:
                    st.error(str(e))
                else:
                    st.rerun()
            st.write(n.get("tekst") or "")


def _formater_dato(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return str(iso)[:16]
