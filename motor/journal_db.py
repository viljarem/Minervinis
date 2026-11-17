"""
journal_db.py – lagringslaget mot Supabase (PostgREST).

All kommunikasjon med databasen skjer her. Resten av appen kaller disse
funksjonene og slipper å vite noe om HTTP. Matematikken ligger i
journal_tall.py; denne fila henter og lagrer bare rader.

Viktig:
  * service_role-nøkkelen brukes KUN her, på serveren. Aldri i nettleseren.
  * På macOS må HTTPS bruke certifi sine rot-sertifikater, ellers feiler
    alle kall (SSL: CERTIFICATE_VERIFY_FAILED). Derfor SSL_KONTEKST under.
  * Alt pakkes i JournalFeil med en trygg, lesbar melding til brukeren.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

try:
    import certifi
    _CAFILE = certifi.where()
except Exception:                       # certifi bør finnes, men ikke krasj uansett
    _CAFILE = None

SSL_KONTEKST = ssl.create_default_context(cafile=_CAFILE) if _CAFILE else None

EIER = "meg"                            # fast eier nå; klar for flerbruker senere


class JournalFeil(Exception):
    """Noe gikk galt mot databasen. Meldingen er trygg å vise i appen."""

    def __init__(self, melding: str, kode: int | None = None):
        super().__init__(melding)
        self.kode = kode


# ---------------------------------------------------------------------------
# Secrets og passord
# ---------------------------------------------------------------------------
def les_secrets() -> dict | None:
    """URL, service-nøkkel og journalpassord fra Streamlit Secrets. None hvis noe mangler."""
    try:
        import streamlit as st
        url = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
        key = str(st.secrets["SUPABASE_SERVICE_KEY"]).strip()
        pw = str(st.secrets["JOURNAL_PASSORD"])
    except Exception:
        return None
    if not url or not key or not pw.strip():
        return None
    return {"url": url, "key": key, "passord": pw}


def passord_ok(skrevet: str, fasit: str) -> bool:
    """Konstant-tids sammenligning så passordet ikke kan gjettes på timing."""
    import hmac
    if not skrevet or not fasit:
        return False
    return hmac.compare_digest(str(skrevet), str(fasit))


# ---------------------------------------------------------------------------
# Hjelpere
# ---------------------------------------------------------------------------
def normaliser_ticker(ticker: str, bors: str) -> str:
    """Skriver ticker slik Yahoo/screeneren gjør (EQNR → EQNR.OL på Oslo)."""
    t = (ticker or "").strip().upper()
    if bors == "Oslo Børs" and t and "." not in t and not t.startswith("^"):
        t += ".OL"
    return t


def _tall(verdi):
    if verdi is None or verdi == "":
        return None
    try:
        t = float(verdi)
    except (TypeError, ValueError):
        return None
    return None if t != t else t        # NaN → None


# ---------------------------------------------------------------------------
# Klienten
# ---------------------------------------------------------------------------
class Lager:
    """Liten PostgREST-klient mot Supabase. Opprett med Lager.fra_secrets()."""

    def __init__(self, url: str, nokkel: str, timeout: float = 20):
        self.url = url.rstrip("/")
        self.nokkel = nokkel
        self.timeout = timeout

    @classmethod
    def fra_secrets(cls) -> "Lager | None":
        konf = les_secrets()
        return cls(konf["url"], konf["key"]) if konf else None

    # -- lavnivå HTTP -------------------------------------------------------
    def _kall(self, metode: str, sti: str, body=None, prefer: str | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + sti, data=data, method=metode)
        req.add_header("apikey", self.nokkel)
        req.add_header("Authorization", f"Bearer {self.nokkel}")
        req.add_header("Content-Type", "application/json")
        if prefer:
            req.add_header("Prefer", prefer)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_KONTEKST) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else []
        except urllib.error.HTTPError as e:
            try:
                detalj = e.read().decode()
            except Exception:
                detalj = ""
            if e.code in (401, 403):
                raise JournalFeil(
                    "Databasen avviste nøkkelen. Sjekk at service_role/secret-nøkkelen "
                    "ligger i Streamlit Secrets.", e.code) from e
            if e.code == 409:
                raise JournalFeil("Finnes allerede (duplikat).", e.code) from e
            if e.code in (502, 503, 521, 522, 523, 524):
                raise JournalFeil(
                    "Databasen svarer ikke. Gratis-prosjektet har trolig sovnet – "
                    "åpne Supabase-dashbordet én gang for å vekke det.", e.code) from e
            raise JournalFeil(f"Databasen svarte med feil ({e.code}). {detalj[:200]}", e.code) from e
        except urllib.error.URLError as e:
            raise JournalFeil(
                "Fikk ikke kontakt med databasen. Sover gratis-prosjektet? "
                "Åpne Supabase og vekk det, og sjekk nettforbindelsen.") from e

    # ===================================================================
    # LISTER
    # ===================================================================
    def hent_lister(self) -> list[dict]:
        return self._kall("GET", "/rest/v1/lister?select=*&order=rekkefolge.asc,navn.asc")

    def lag_liste(self, navn: str, farge: str = "#6B7280", rekkefolge: int = 0) -> dict:
        navn = (navn or "").strip()
        if not navn:
            raise JournalFeil("Listen må ha et navn.")
        body = {"eier": EIER, "navn": navn, "farge": farge, "rekkefolge": rekkefolge}
        try:
            rader = self._kall("POST", "/rest/v1/lister", body, prefer="return=representation")
        except JournalFeil as e:
            if e.kode == 409:
                raise JournalFeil(f"Du har allerede en liste som heter «{navn}».") from e
            raise
        return rader[0] if rader else {}

    def omdop_liste(self, liste_id: str, navn: str = None, farge: str = None,
                    rekkefolge: int = None) -> None:
        body = {}
        if navn is not None:
            body["navn"] = navn.strip()
        if farge is not None:
            body["farge"] = farge
        if rekkefolge is not None:
            body["rekkefolge"] = rekkefolge
        if body:
            self._kall("PATCH", f"/rest/v1/lister?id=eq.{liste_id}", body,
                       prefer="return=minimal")

    def slett_liste(self, liste_id: str) -> None:
        # Aksjene på lista fjernes automatisk (ON DELETE CASCADE i SQL).
        self._kall("DELETE", f"/rest/v1/lister?id=eq.{liste_id}", prefer="return=minimal")

    # ===================================================================
    # AKSJER PÅ LISTER
    # ===================================================================
    def hent_liste_aksjer(self, liste_id: str = None) -> list[dict]:
        sti = "/rest/v1/liste_aksjer?select=*&order=opprettet.desc"
        if liste_id:
            sti = (f"/rest/v1/liste_aksjer?liste_id=eq.{liste_id}"
                   "&select=*&order=opprettet.desc")
        return self._kall("GET", sti)

    def legg_til_aksje(self, liste_id: str, ticker: str, bors: str,
                       pivot=None, stop=None, mal=None,
                       kommentar=None, bilde=None) -> str:
        """Returnerer 'ny' eller 'finnes' (aksjen lå allerede på lista)."""
        body = {
            "eier": EIER, "liste_id": liste_id,
            "ticker": normaliser_ticker(ticker, bors), "bors": bors,
        }
        for felt, verdi in (("pivot", pivot), ("stop", stop), ("mal", mal)):
            if _tall(verdi) is not None:
                body[felt] = _tall(verdi)
        if kommentar:
            body["kommentar"] = kommentar
        if bilde:
            body["bilde"] = bilde
        try:
            self._kall("POST", "/rest/v1/liste_aksjer", body, prefer="return=representation")
            return "ny"
        except JournalFeil as e:
            if e.kode == 409:
                return "finnes"
            raise

    def flytt_aksje(self, rad_id: str, ny_liste_id: str) -> None:
        self._kall("PATCH", f"/rest/v1/liste_aksjer?id=eq.{rad_id}",
                   {"liste_id": ny_liste_id}, prefer="return=minimal")

    def oppdater_aksje(self, rad_id: str, **felt) -> None:
        body = {k: _tall(felt[k]) for k in ("pivot", "stop", "mal") if k in felt}
        # Fritekst-kommentar og chart-bilde (base64 data-URI) lagres som de er.
        # None tillates eksplisitt (brukes for aa nullstille/fjerne).
        for k in ("kommentar", "bilde"):
            if k in felt:
                body[k] = felt[k]
        if body:
            self._kall("PATCH", f"/rest/v1/liste_aksjer?id=eq.{rad_id}", body,
                       prefer="return=minimal")

    def fjern_aksje(self, rad_id: str) -> None:
        self._kall("DELETE", f"/rest/v1/liste_aksjer?id=eq.{rad_id}", prefer="return=minimal")

    # ===================================================================
    # NOTATER (dagbok)
    # ===================================================================
    def hent_notater(self, ticker: str = None) -> list[dict]:
        sti = "/rest/v1/notater?select=*&order=opprettet.desc"
        if ticker:
            sti = f"/rest/v1/notater?ticker=eq.{ticker}&select=*&order=opprettet.desc"
        return self._kall("GET", sti)

    def lag_notat(self, ticker: str, bors: str, tekst: str,
                  normaliser: bool = True) -> dict:
        # normaliser=False lagrer tickeren akkurat slik den skrives (kun
        # trimmet + store bokstaver), uten aa tvinge paa .OL-endingen.
        t = (normaliser_ticker(ticker, bors) if normaliser
             else (ticker or "").strip().upper())
        body = {"eier": EIER, "ticker": t, "bors": bors, "tekst": tekst or ""}
        rader = self._kall("POST", "/rest/v1/notater", body, prefer="return=representation")
        return rader[0] if rader else {}

    def oppdater_notat(self, notat_id: str, tekst: str) -> None:
        self._kall("PATCH", f"/rest/v1/notater?id=eq.{notat_id}",
                   {"tekst": tekst or ""}, prefer="return=minimal")

    def slett_notat(self, notat_id: str) -> None:
        self._kall("DELETE", f"/rest/v1/notater?id=eq.{notat_id}", prefer="return=minimal")

    # ===================================================================
    # HANDLER + DELSALG
    # ===================================================================
    def hent_handler(self, status: str = None) -> list[dict]:
        sti = "/rest/v1/handler?select=*&order=kjop_dato.desc"
        if status:
            sti = f"/rest/v1/handler?status=eq.{status}&select=*&order=kjop_dato.desc"
        return self._kall("GET", sti)

    def hent_delsalg(self, handel_id: str = None) -> list[dict]:
        sti = "/rest/v1/delsalg?select=*&order=salg_dato.asc"
        if handel_id:
            sti = f"/rest/v1/delsalg?handel_id=eq.{handel_id}&select=*&order=salg_dato.asc"
        return self._kall("GET", sti)

    def lag_handel(self, rad: dict) -> dict:
        body = {
            "eier": EIER,
            "ticker": normaliser_ticker(rad["ticker"], rad["bors"]),
            "bors": rad["bors"],
            "status": "OPEN",
            "kjop_dato": rad["kjop_dato"],
            "kjop_kurs": _tall(rad["kjop_kurs"]),
            "antall": _tall(rad["antall"]),
            "setup": rad.get("setup") or "",
            "kilde": rad.get("kilde") or "",
            "trigger": rad.get("trigger") or "",
            "notat": rad.get("notat") or "",
        }
        for felt in ("stop", "mal", "pivot"):
            if _tall(rad.get(felt)) is not None:
                body[felt] = _tall(rad[felt])
        rader = self._kall("POST", "/rest/v1/handler", body, prefer="return=representation")
        return rader[0] if rader else {}

    def oppdater_handel(self, handel_id: str, **felt) -> None:
        lovlige = ("ticker", "bors", "status", "kjop_dato", "kjop_kurs", "antall",
                   "stop", "mal", "pivot", "setup", "kilde", "trigger", "notat",
                   "fulgte_plan", "evaluering")
        body = {k: felt[k] for k in lovlige if k in felt}
        for t in ("kjop_kurs", "antall", "stop", "mal", "pivot"):
            if t in body:
                body[t] = _tall(body[t])
        if body:
            self._kall("PATCH", f"/rest/v1/handler?id=eq.{handel_id}", body,
                       prefer="return=minimal")

    def slett_handel(self, handel_id: str) -> None:
        # Delsalg og tag-koblinger fjernes automatisk (CASCADE).
        self._kall("DELETE", f"/rest/v1/handler?id=eq.{handel_id}", prefer="return=minimal")

    def lag_delsalg(self, handel_id: str, salg_dato: str, salg_kurs, antall,
                    arsak: str = "") -> dict:
        body = {"eier": EIER, "handel_id": handel_id, "salg_dato": salg_dato,
                "salg_kurs": _tall(salg_kurs), "antall": _tall(antall), "arsak": arsak or ""}
        rader = self._kall("POST", "/rest/v1/delsalg", body, prefer="return=representation")
        return rader[0] if rader else {}

    def slett_delsalg(self, delsalg_id: str) -> None:
        self._kall("DELETE", f"/rest/v1/delsalg?id=eq.{delsalg_id}", prefer="return=minimal")

    def sett_status(self, handel_id: str, status: str) -> None:
        self._kall("PATCH", f"/rest/v1/handler?id=eq.{handel_id}",
                   {"status": status}, prefer="return=minimal")

    # ===================================================================
    # TAGGER
    # ===================================================================
    def hent_tagger(self) -> list[dict]:
        return self._kall("GET", "/rest/v1/tagger?select=*&order=navn.asc")

    def lag_tag(self, navn: str, farge: str = "#6B7280") -> dict:
        navn = (navn or "").strip()
        if not navn:
            raise JournalFeil("Taggen må ha et navn.")
        try:
            rader = self._kall("POST", "/rest/v1/tagger",
                               {"eier": EIER, "navn": navn, "farge": farge},
                               prefer="return=representation")
        except JournalFeil as e:
            if e.kode == 409:
                # Finnes allerede – hent den eksisterende i stedet.
                eksisterende = self._kall(
                    "GET", f"/rest/v1/tagger?navn=eq.{urllib.parse.quote(navn)}&select=*")
                if eksisterende:
                    return eksisterende[0]
            raise
        return rader[0] if rader else {}

    def slett_tag(self, tag_id: str) -> None:
        self._kall("DELETE", f"/rest/v1/tagger?id=eq.{tag_id}", prefer="return=minimal")

    def hent_handel_tagger(self) -> list[dict]:
        return self._kall("GET", "/rest/v1/handel_tagger?select=*")

    def sett_tag_pa_handel(self, handel_id: str, tag_id: str) -> None:
        try:
            self._kall("POST", "/rest/v1/handel_tagger",
                       {"handel_id": handel_id, "tag_id": tag_id}, prefer="return=minimal")
        except JournalFeil as e:
            if e.kode != 409:               # allerede satt = greit
                raise

    def fjern_tag_fra_handel(self, handel_id: str, tag_id: str) -> None:
        self._kall("DELETE",
                   f"/rest/v1/handel_tagger?handel_id=eq.{handel_id}&tag_id=eq.{tag_id}",
                   prefer="return=minimal")

    # ===================================================================
    # INNSTILLINGER (enkel nokkel/verdi, synkes paa tvers av enheter)
    # ===================================================================
    def hent_innstilling(self, nokkel: str, standard=None):
        """Leser en lagret verdi. Mangler tabellen/raden, returneres standard."""
        try:
            rader = self._kall(
                "GET", f"/rest/v1/innstillinger?nokkel=eq.{urllib.parse.quote(nokkel)}"
                       "&select=verdi")
        except JournalFeil:
            return standard
        if rader and rader[0].get("verdi") is not None:
            return rader[0]["verdi"]
        return standard

    def sett_innstilling(self, nokkel: str, verdi) -> None:
        """Lagrer en verdi (upsert). Stille hvis tabellen ikke finnes ennaa."""
        body = {"eier": EIER, "nokkel": nokkel, "verdi": verdi}
        try:
            self._kall("POST", "/rest/v1/innstillinger", body,
                       prefer="resolution=merge-duplicates,return=minimal")
        except JournalFeil:
            raise

    # ===================================================================
    # TEGNINGER (chart-annotasjoner: nivaaer, trendlinjer, kanal, tekst)
    # ===================================================================
    # Én rad per ticker+bors (aktiv arbeidslag). 'data' er en liste av
    # tegne-objekter: {id, type, points, farge, label}. Alt synkes paa
    # tvers av enheter. Appen takler at tabellen mangler (faller tilbake
    # til ingen tegninger).
    def hent_tegninger(self, ticker: str, bors: str) -> list[dict]:
        """Henter lista med tegninger for én aksje. Tom liste hvis ingen/feil."""
        t = (ticker or "").strip().upper()
        try:
            rader = self._kall(
                "GET",
                f"/rest/v1/tegninger?ticker=eq.{urllib.parse.quote(t)}"
                f"&bors=eq.{urllib.parse.quote(bors)}&aktiv=eq.true&select=id,data")
        except JournalFeil:
            return []
        if rader and isinstance(rader[0].get("data"), list):
            return rader[0]["data"]
        return []

    def lagre_tegninger(self, ticker: str, bors: str, data: list) -> None:
        """Lagrer (upsert) hele tegne-lista for en aksje. Oppretter raden ved behov."""
        t = (ticker or "").strip().upper()
        data = data or []
        try:
            rader = self._kall(
                "GET",
                f"/rest/v1/tegninger?ticker=eq.{urllib.parse.quote(t)}"
                f"&bors=eq.{urllib.parse.quote(bors)}&aktiv=eq.true&select=id")
        except JournalFeil:
            rader = []
        if rader:
            rad_id = rader[0]["id"]
            self._kall("PATCH", f"/rest/v1/tegninger?id=eq.{rad_id}",
                       {"data": data}, prefer="return=minimal")
        else:
            body = {"eier": EIER, "ticker": t, "bors": bors,
                    "aktiv": True, "data": data}
            self._kall("POST", "/rest/v1/tegninger", body, prefer="return=minimal")

