# 📈 Minervini-screener for Oslo Børs

En liten nettapp som hver kveld henter kurser, sjekker Mark Minervinis 7
trend-kriterier, finner VCP-pivot (kjøpsnivå) og sender deg en e-post med dagens
endringer. Nettsiden viser en sorterbar liste og interaktive chart.

**Du trenger ikke kunne kode.** Følg stegene under i rekkefølge. Alt er gratis.

---

## 🧠 Først: to begreper forklart enkelt

**«Kjøre lokalt» vs «kjøre på nett»**
- *Lokalt* = programmet kjører på din egen PC. Virker bare når PC-en er på.
- *På nett* = programmet kjører på en gratis tjener (server) døgnet rundt, uten
  at din PC er på. Det er dette vi setter opp.

**Robot-trikset (viktigst for deg)**
En «robot» (GitHub Actions) er et lite program som starter automatisk til fast
tid. Hver kveld: henter dagens kurser → legger dem i datafila → **lagrer fila
tilbake til GitHub**. Fordi fila blir liggende fast, vokser den for hver dag, og
**historikken bygger seg opp av seg selv**. Nettsiden leser samme fil og viser
alltid ferske tall.

---

## 🗂️ Hva de ulike delene gjør (kort)

| Del | Fil / mappe | Oppgave |
|-----|-------------|---------|
| Motoren | `motor/` | All beregning: kriterier, VCP, RS (ingen nettside – lett å teste) |
| Nettsiden | `app.py` | Viser liste, chart og søk (Streamlit) |
| Roboten | `oppdater.py` + `.github/workflows/daglig.yml` | Henter data, lagrer, screener, sender e-post |
| Dataene | `data/` | Tickerliste + kurshistorikk (parquet) som vokser dag for dag |
| Tester | `tester/` | Sjekker at motoren regner riktig |

---

## ✅ Steg-for-steg-oppsett

### Steg 1 – Lag gratis GitHub-konto og last opp mappa

GitHub er et gratis «nettskap» for prosjekter som dette.

1. Gå til [github.com/signup](https://github.com/signup) og opprett en konto.
2. Klikk **+** øverst til høyre → **New repository**.
   - *Repository name*: f.eks. `minervini`
   - Velg **Private** (eller Public – begge funker gratis).
   - Klikk **Create repository**.
3. På den nye siden, klikk lenken **uploading an existing file**.
4. Åpne prosjektmappa på PC-en din og **dra ALLE filene og mappene inn** i
   nettleseren.
   > ⚠️ **Ikke last opp mappene `.venv` og `__pycache__`** (de er bare
   > hjelpefiler på din PC). Resten skal med, inkludert `.github`-mappa.
   > (Ser du ikke `.github`? Slå på «vis skjulte filer»: `Cmd + Shift + .` på Mac.)
5. Klikk **Commit changes**. Nå ligger prosjektet på GitHub. 🎉

---

### Steg 2 – Skru på og test roboten (ÉN knapp)

Dette henter data første gang (~10 år, tar noen minutter), kjører screeningen og
tester alt. Etterpå går den automatisk hver hverdag.

1. På GitHub, gå til fanen **Actions** (øverst).
2. Ser du en gul boks? Klikk **I understand my workflows, go ahead and enable them**.
3. Klikk **Daglig oppdatering** i venstre kolonne.
4. Klikk **Run workflow** (grå knapp til høyre) → **Run workflow** igjen.
5. Vent. Klikk deg inn i kjøringen for å se den jobbe. Grønn hake = ferdig. ✅

Når den er ferdig, har roboten laget `data/priser.parquet` og lagret den tilbake
til GitHub. **Dette er «ÉN-klikks-testen» din** – den beviser at datahenting +
screening (+ e-post hvis satt opp) virker.

> 💡 Roboten kjører automatisk **mandag–fredag kl. 17:00 UTC**. Det er 18:00
> norsk tid om vinteren og 19:00 om sommeren. Vil du endre tidspunktet, se
> [.github/workflows/daglig.yml](.github/workflows/daglig.yml).

---

### Steg 3 – Publiser nettsiden (Streamlit Community Cloud)

Streamlit Community Cloud er en gratis tjeneste som gjør prosjektet til en
nettside og oppdaterer den automatisk hver gang roboten legger inn nye data.

1. Gå til [share.streamlit.io](https://share.streamlit.io) og klikk
   **Sign in with GitHub** (bruk samme konto).
2. Klikk **Create app** → **Deploy a public app from GitHub** (eller «from
   existing repo»).
3. Fyll inn:
   - **Repository**: velg `minervini`-repoet ditt
   - **Branch**: `main`
   - **Main file path**: `app.py`
4. Klikk **Deploy**. Etter et par minutter får du en nettadresse (URL) du kan
   åpne fra hvor som helst. 🌍

> Kjørte du **ikke** roboten i Steg 2 først, sier siden bare at det mangler data.
> Da: kjør roboten (Steg 2), og siden fyller seg automatisk.

---

### Steg 4 – Sett opp e-post (GitHub Secrets)

«Secrets» = hemmeligheter som lagres trygt på GitHub, **aldri i koden**. Her
legger vi inn e-postadressen din og et passord slik at roboten kan sende deg
oppsummeringen.

Enklest med Gmail:

1. Skru på **totrinnsbekreftelse** på Google-kontoen din:
   [myaccount.google.com/security](https://myaccount.google.com/security).
2. Lag et **App-passord** (16 tegn):
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
   Kall det f.eks. «Minervini». Kopier de 16 tegnene.
3. På GitHub: repoet → **Settings** → i venstremenyen **Secrets and variables**
   → **Actions** → **New repository secret**. Legg inn disse, én om gangen:

   | Name (nøyaktig) | Secret (verdi) |
   |-----------------|----------------|
   | `EPOST_AVSENDER` | din Gmail-adresse, f.eks. `dittnavn@gmail.com` |
   | `EPOST_PASSORD`  | de 16 tegnene fra app-passordet (uten mellomrom) |
   | `EPOST_MOTTAKER` | adressen du vil motta e-post på |

   Bruker du **ikke** Gmail, legg i tillegg til `SMTP_SERVER` og `SMTP_PORT` for
   din leverandør. Med Gmail trengs de ikke (standard er `smtp.gmail.com` / `587`).
4. Kjør roboten på nytt (Steg 2, punkt 3–4) for å teste e-posten.

> Legger du ikke inn secrets, fungerer alt annet fint – roboten hopper bare
> stille over e-posten.

---

## 🖱️ Daglig bruk

Du trenger ikke gjøre noe. Hver hverdag:
1. Roboten henter dagens kurser og utvider historikken.
2. Den sender deg en e-post med endringer + topp 10.
3. Nettsiden oppdaterer seg selv med ferske tall.

Vil du følge flere aksjer? Åpne [data/univers.txt](data/univers.txt) på GitHub,
klikk blyant-ikonet ✏️, legg til én ticker per linje (må slutte på `.OL`), og
klikk **Commit changes**.

---

## 🧪 Vil du teste på egen PC først? (valgfritt)

Er du litt nysgjerrig, kan du teste lokalt. Åpne en terminal i prosjektmappa:

```bash
# 1) Lag et lokalt miljø og installer bibliotekene (gjøres én gang)
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

# 2) ÉN kommando som tester HELE kjeden (henting + screening + e-post):
./.venv/bin/python oppdater.py

# 3) Vis nettsiden lokalt i nettleseren:
./.venv/bin/streamlit run app.py

# 4) Kjør de innebygde testene:
./.venv/bin/pytest -q
```

> E-post i punkt 2 sendes bare hvis du har satt miljøvariablene
> `EPOST_AVSENDER`, `EPOST_PASSORD` og `EPOST_MOTTAKER` i terminalen. Uten dem
> testes henting + screening, og e-post hoppes over.

---

## ⚙️ Justere terskler og oppsett

Alle tall og «presets» ligger samlet i [motor/konfig.py](motor/konfig.py) – f.eks.
likviditetsgrense, RS-krav og VCP-innstillinger. Endre der, så gjelder det i hele
appen (både robot og nettside). Ferdige oppsett:

- **Standard (Minervini)**: ≥ 30 % over 52u lav, ≤ 25 % under 52u høy, krever 7/7.
- **Tidlig fase**: ≥ 25 % over lav, ≤ 30 % under høy, krever 6/7.

---

## ❓ Vanlige spørsmål

**«Nettsiden sier at det mangler data.»** Kjør roboten (Steg 2) – den lager
datafila. Streamlit oppdaterer seg selv rett etter.

**«En ticker mangler / er feil.»** Rediger [data/univers.txt](data/univers.txt).
Roboten hopper automatisk over tickere Yahoo ikke kjenner igjen.

**«Hvor lagres historikken?»** I `data/priser.parquet` på GitHub. Den vokser for
hver dag roboten kjører, så du bygger opp din egen faste historikk.

**«Er dette investeringsråd?»** Nei. Verktøyet er kun for research og læring.
