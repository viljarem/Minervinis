"""
oppdater.py – dette er "robotens" skript. GitHub Actions kjører det hver kveld.

Steg:
  1. Hent dagens kurser og oppdater datafila (som committes tilbake til GitHub).
  2. Kjør screeningen.
  3. Lag "dagens liste" og sammenlign den mot forrige kjøring.
  4. Send en e-post med endringene + en topp-10-tabell.

Du kan også kjøre den selv for å teste alt:  python oppdater.py
E-post sendes bare hvis e-post-innstillingene (GitHub Secrets) er satt.
"""
from __future__ import annotations

import os
import smtplib
import ssl
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


def _bygg_epost(df: pd.DataFrame, endringer: dict) -> tuple[str, str]:
    """Returnerer (emne, html-innhold) for e-posten."""
    dato = datetime.now().strftime("%d.%m.%Y")
    antall = int(df["oppfyller"].sum()) if not df.empty else 0
    emne = f"DEMO-Screener · Oslo Børs · {dato} · {antall} treff · {len(endringer['ferske_brudd'])} ferske brudd"

    def liste(navn, tickere):
        if not tickere:
            return f"<p><b>{navn}:</b> ingen</p>"
        return f"<p><b>{navn}:</b> {', '.join(tickere)}</p>"

    html = f"""
    <h2>DEMO-Screener · {dato}</h2>
    <p>{antall} aksjer oppfyller trend-kriteriene i dag.</p>
    {liste("🟢 Ferske brudd (over pivot på volum)", endringer["ferske_brudd"])}
    {liste("🆕 Nye i lista", endringer["nye"])}
    {liste("❌ Falt ut av lista", endringer["falt_ut"])}
    <h3>Topp 10</h3>
    {_topp10_html(df)}
    <p style="color:#888;font-size:12px;">Automatisk e-post fra din egen Minervini-robot.</p>
    """
    return emne, html


def send_epost(df: pd.DataFrame, endringer: dict) -> None:
    """Sender oppsummerings-e-posten. Hopper stille over hvis innstillinger mangler."""
    innst = _epost_innstillinger()
    if innst is None:
        print("E-post hoppes over (mangler EPOST_AVSENDER/EPOST_PASSORD/EPOST_MOTTAKER).")
        return

    emne, html = _bygg_epost(df, endringer)
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
def main() -> None:
    print("=== 1) Henter og oppdaterer kursdata ===")
    priser = datamod.hent_og_oppdater()

    print("=== 2) Kjører screening ===")
    df = screener.screen(priser, konfig.STANDARD)
    antall = int(df["oppfyller"].sum()) if not df.empty else 0
    print(f"   {antall} aksjer oppfyller Standard-oppsettet (7/7).")

    print("=== 3) Sammenligner med forrige kjøring ===")
    forrige = screener.les_forrige_liste()
    naa = screener.til_dagens_liste(df)
    endringer = screener.sammenlign(forrige, naa)
    screener.lagre_liste(naa)
    print(f"   Nye: {endringer['nye']}")
    print(f"   Falt ut: {endringer['falt_ut']}")
    print(f"   Ferske brudd: {endringer['ferske_brudd']}")

    print("=== 4) Sender e-post ===")
    send_epost(df, endringer)
    print("Ferdig ✅")


if __name__ == "__main__":
    main()
