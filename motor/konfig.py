"""
konfig.py – ALLE innstillinger og terskler samlet på ett sted.

Her kan du justere tall (f.eks. likviditetsgrense eller kriterier) uten å røre
resten av koden. Endrer du noe her, endres det i hele appen.
"""
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Datahenting
# ---------------------------------------------------------------------------
BENCHMARK = "^OSEBX"          # Oslo Børs hovedindeks (brukes til relativ styrke)
HISTORIKK_AAR = 10            # antall år som hentes ved aller første kjøring
BORS_SUFFIKS = ".OL"         # Oslo Børs-tickere slutter på dette

# ---------------------------------------------------------------------------
# Filstier (relativt til prosjektmappa)
# ---------------------------------------------------------------------------
DATA_MAPPE = "data"
PRISER_FIL = f"{DATA_MAPPE}/priser.parquet"        # all kurshistorikk (vokser dag for dag)
UNIVERS_FIL = f"{DATA_MAPPE}/univers.txt"           # liste over tickere
SISTE_LISTE_FIL = f"{DATA_MAPPE}/siste_liste.json"  # forrige screening (til e-post-sammenligning)

# ---------------------------------------------------------------------------
# Likviditetsfilter (fjern aksjer det handles for lite i)
# ---------------------------------------------------------------------------
MIN_DAGSOMSETNING = 500_000   # NOK/dag i snitt siste 20 dager
OMSETNING_VINDU = 20

# ---------------------------------------------------------------------------
# Glidende snitt (SMA) og 52-ukers høy/lav
# ---------------------------------------------------------------------------
SMA_PERIODER = (50, 150, 200)
VINDU_52U = 252               # ~52 uker i handelsdager
SMA200_STIGNING_DAGER = 22    # SMA200 i dag sammenlignes med for 22 dager siden
MIN_HANDELSDAGER = 200        # aksjen må ha minst så mange dager for å vurderes

# ---------------------------------------------------------------------------
# Relativ styrke (RS) – IBD-metoden
# ---------------------------------------------------------------------------
RS_PERIODER = (63, 126, 189, 252)      # 3, 6, 9, 12 måneder målt i handelsdager
RS_VEKTER = (0.40, 0.20, 0.20, 0.20)
RS_MIN = 70                            # Minervinis fulle template krever RS >= 70

# ---------------------------------------------------------------------------
# VCP – Volatility Contraction Pattern (pivot/kjøpsnivå)
# ---------------------------------------------------------------------------
VCP_LOOKBACK = 120            # se på de siste ~120 dagene
VCP_MIN_DAGER = 15            # minst så mange dager for å prøve
VCP_SVING_VINDU = 5           # vindu for å finne lokale topper/bunner
VCP_STOY_GRENSE = 0.03        # ignorer kontraksjoner under 3 %
VCP_TOLERANSE = 1.15          # litt slingringsmonn på "stadig strammere"
VCP_MIN_KONTR = 2             # minst 2 kontraksjoner
VCP_MAKS_KONTR = 6            # maks 6 kontraksjoner
VCP_FORSTE_MAKS = 0.40        # dypeste (første) kontraksjon <= 40 %
VCP_SISTE_MAKS = 0.15         # strammeste (siste) kontraksjon <= 15 %
VCP_MAKS_UNDER_PIVOT = 0.12   # dagens kurs maks 12 % under pivot for å være "klar"

# ---------------------------------------------------------------------------
# Brudd (kjøpstriggeren)
# ---------------------------------------------------------------------------
BRUDD_FERSK_DAGER = 5         # brudd regnes som "ferskt" i så mange dager
BRUDD_VOLUM_FAKTOR = 1.2      # volum >= 1.2x 50-dagers snitt = bekreftet
BRUDD_FORLENGET = 0.10        # mer enn 10 % over pivot = "forlenget" (ikke jag)


# ---------------------------------------------------------------------------
# Presets (ferdige oppsett du kan velge mellom i nettsiden)
# ---------------------------------------------------------------------------
@dataclass
class Preset:
    navn: str
    over_lav: float      # kurs må være minst så mye over 52-ukers lav (0.30 = 30 %)
    under_hoy: float     # kurs må være maks så mye under 52-ukers høy (0.25 = 25 %)
    krev_antall: int     # hvor mange av de 7 kriteriene som kreves
    krev_rs: bool = False  # skal RS >= RS_MIN også kreves?


STANDARD = Preset("Standard (Minervini)", over_lav=0.30, under_hoy=0.25, krev_antall=7, krev_rs=False)
TIDLIG_FASE = Preset("Tidlig fase", over_lav=0.25, under_hoy=0.30, krev_antall=6, krev_rs=False)

PRESETS = {STANDARD.navn: STANDARD, TIDLIG_FASE.navn: TIDLIG_FASE}
