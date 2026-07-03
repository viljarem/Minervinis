"""
oppdater.py – dette er "robotens" skript. GitHub Actions kjører det hver kveld.

Steg:
  1. Hent dagens kurser og oppdater datafila (som committes tilbake til GitHub).
  2. Kjør screeningen.
  3. Lag "dagens liste" og sammenlign den mot forrige kjøring.
  4. Send en e-post med endringene + en topp-10-tabell.

Du kan velge HVILKEN børs som skal oppdateres med et argument (børsens "kind"):
    python oppdater.py oslo      # bare Oslo Børs
    python oppdater.py sp500     # bare S&P 500
    python oppdater.py           # alle børser (greit ved lokal testing)
Slik kan roboten kjøre Oslo tidlig (17:00) og USA sent (23:00) hver for seg.
E-post sendes bare hvis e-post-innstillingene (GitHub Secrets) er satt.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

from motor import konfig, data as datamod, screener


# ---------------------------------------------------------------------------
# E-post
# ---------------------------------------------------------------------------
def _epost_innstillinger() -> dict | None:
    """Leser e-post-innstillinger fra miljøvariabler (GitHub Secrets). None hvis mangler."""
    avsender = os.environ.get("EPOST_AVSENDER")
    passord = os.environ.get("EPOST_PASSORD")
    mottaker = os.environ.get("EPOST_MOTTAKER")
    if not (avsender and passord and mottaker):
        return None
    return {
        "avsender": avsender,
        "passord": passord,
        "mottaker": mottaker,
        "server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
    }


def _topp10_html(df: pd.DataFrame) -> str:
    """Lager en enkel HTML-tabell med de 10 beste treffene."""
    if df.empty:
        return "<p>Ingen aksjer oppfyller kriteriene i dag.</p>"
    kolonner = ["ticker", "pris", "rs", "score", "pivot", "avstand_pivot", "kvalitet", "status"]
    navn = ["Ticker", "Pris", "RS", "Score", "Pivot", "Avstand %", "Kvalitet", "Status"]
    topp = df[df["oppfyller"]].head(10)
    if topp.empty:
        topp = df.head(10)
    tabell = topp[kolonner].copy()
    tabell.columns = navn
    return tabell.to_html(index=False, border=0, justify="center")


def _seksjon_html(bors: "konfig.Bors", df: pd.DataFrame, endringer: dict) -> str:
    """HTML-seksjon for én børs (overskrift, endringslister og topp 10)."""
    antall = int(df["oppfyller"].sum()) if not df.empty else 0

    def liste(navn, tickere):
        if not tickere:
            return f"<p><b>{navn}:</b> ingen</p>"
        return f"<p><b>{navn}:</b> {', '.join(tickere)}</p>"

    return f"""
    <h2>{bors.navn}</h2>
    <p>{antall} aksjer oppfyller trend-kriteriene i dag.</p>
    {liste("🟢 Ferske brudd (over pivot på volum)", endringer["ferske_brudd"])}
    {liste("🆕 Nye i lista", endringer["nye"])}
    {liste("❌ Falt ut av lista", endringer["falt_ut"])}
    <h3>Topp 10</h3>
    {_topp10_html(df)}
    """


def _bygg_epost(resultater: list[dict]) -> tuple[str, str]:
    """Returnerer (emne, html-innhold). Én seksjon per børs."""
    dato = datetime.now().strftime("%d.%m.%Y")
    total_treff = sum(
        int(r["df"]["oppfyller"].sum()) if not r["df"].empty else 0 for r in resultater
    )
    total_brudd = sum(len(r["endringer"]["ferske_brudd"]) for r in resultater)
    # Nevn børsen i emnet når vi kjører bare én (Oslo 17:00 / USA 23:00 hver for
    # seg) – da er de to daglige e-postene lette å skille i innboksen.
    marked = resultater[0]["bors"].navn if len(resultater) == 1 else "alle børser"
    emne = f"DEMO-Screener · {marked} · {dato} · {total_treff} treff · {total_brudd} ferske brudd"

    seksjoner = "<hr>".join(
        _seksjon_html(r["bors"], r["df"], r["endringer"]) for r in resultater
    )
    html = f"""
    <h1>DEMO-Screener · {dato}</h1>
    {seksjoner}
    <p style="color:#888;font-size:12px;">Automatisk e-post fra din egen Minervini-robot.</p>
    """
    return emne, html


def send_epost(resultater: list[dict]) -> None:
    """Sender oppsummerings-e-posten. Hopper stille over hvis innstillinger mangler."""
    if not resultater:
        print("E-post hoppes over (ingen børser ble oppdatert).")
        return
    innst = _epost_innstillinger()
    if innst is None:
        print("E-post hoppes over (mangler EPOST_AVSENDER/EPOST_PASSORD/EPOST_MOTTAKER).")
        return

    emne, html = _bygg_epost(resultater)
    melding = MIMEMultipart("alternative")
    melding["Subject"] = emne
    melding["From"] = innst["avsender"]
    melding["To"] = innst["mottaker"]
    melding.attach(MIMEText(html, "html", "utf-8"))

    kontekst = ssl.create_default_context()
    with smtplib.SMTP(innst["server"], innst["port"]) as server:
        server.starttls(context=kontekst)
        server.login(innst["avsender"], innst["passord"])
        server.sendmail(innst["avsender"], innst["mottaker"], melding.as_string())
    print(f"E-post sendt til {innst['mottaker']}.")


# ---------------------------------------------------------------------------
# Hovedløp
# ---------------------------------------------------------------------------
def kjor_bors(bors: "konfig.Bors") -> dict:
    """Oppdaterer data, screener og sammenligner for én børs.
    Returnerer {'bors', 'df', 'endringer'} som e-posten bygges av."""
    print(f"\n########## {bors.navn} ##########")
    print("=== 1) Henter og oppdaterer kursdata ===")
    priser = datamod.hent_og_oppdater(bors)

    print("=== 2) Kjører screening ===")
    df = screener.screen(priser, konfig.STANDARD)
    antall = int(df["oppfyller"].sum()) if not df.empty else 0
    print(f"   {antall} aksjer oppfyller Standard-oppsettet (7/7).")

    print("=== 3) Sammenligner med forrige kjøring ===")
    forrige = screener.les_forrige_liste(bors.siste_liste_fil)
    naa = screener.til_dagens_liste(df)
    endringer = screener.sammenlign(forrige, naa)
    screener.lagre_liste(naa, bors.siste_liste_fil)
    print(f"   Nye: {endringer['nye']}")
    print(f"   Falt ut: {endringer['falt_ut']}")
    print(f"   Ferske brudd: {endringer['ferske_brudd']}")

    return {"bors": bors, "df": df, "endringer": endringer}


def velg_borser(argv: list[str]) -> list["konfig.Bors"]:
    """Velger hvilke børser som skal kjøres ut fra argumentene (børsens 'kind').
    Uten argument kjøres ALLE børser (praktisk ved lokal testing)."""
    onsket = {a.lower() for a in argv}
    if not onsket:
        return list(konfig.BORSER.values())
    valgt = [b for b in konfig.BORSER.values() if b.kind in onsket]
    if not valgt:
        gyldige = ", ".join(sorted(b.kind for b in konfig.BORSER.values()))
        print(f"Ukjent børs {sorted(onsket)}. Gyldige valg: {gyldige}. Kjører alle.")
        return list(konfig.BORSER.values())
    return valgt


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    borser = velg_borser(argv)
    print(f"Skal oppdatere: {', '.join(b.navn for b in borser)}")

    resultater: list[dict] = []
    for bors in borser:
        try:
            resultater.append(kjor_bors(bors))
        except Exception as e:  # én børs som feiler skal ikke stoppe de andre
            print(f"!! Hoppet over {bors.navn} på grunn av feil: {e}")

    print("\n=== Sender e-post ===")
    send_epost(resultater)
    print("Ferdig ✅")


if __name__ == "__main__":
    main()
