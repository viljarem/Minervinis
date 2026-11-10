"""
lag_journal_v3.py – enkel, frittstående tradingjournal (uavhengig av screeneren).

Kjør:  python verktoy/lag_journal_v3.py   →  journal/Tradingjournal_v3.xlsx

Filosofi:  Analyse = planen (før trade) · Trades = utførelsen + review (etter trade).
Alt spores tilbake til en analyse via Analyse-ID.

Ark: Dashboard · Analyse · Watchlist · Trades · Weekly · Monthly · Chart · Lists

Laget for Excel (kun klassiske funksjoner + MAXIFS/MINIFS/ISOWEEKNUM fra Excel 2019/365).
Blå tekst = input, svarte tall på grå bakgrunn = formler.

Time Value (TV) = avkastning i % / antall dager holdt (min. 1). Høyere = bedre.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference, StockChart
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.updown_bars import UpDownBars
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

UT = Path(__file__).resolve().parent.parent / "journal" / "Tradingjournal_v3.xlsx"
N_ANALYSE = 300
N_TRADES = 500
A_END = N_ANALYSE + 1
T_END = N_TRADES + 1

# --- Stil -------------------------------------------------------------------
MORK = "1F3A5F"
HODE_FILL = PatternFill("solid", fgColor=MORK)
HODE_FONT = Font(bold=True, color="FFFFFF", size=10)
REFL_FILL = PatternFill("solid", fgColor="5B6B8C")
FORMEL_FILL = PatternFill("solid", fgColor="F2F4F7")
INN = Font(color="1F4FD8")                       # blå = input
INN_FET = Font(color="1F4FD8", bold=True)
TITTEL = Font(bold=True, size=16, color=MORK)
SEKSJON = Font(bold=True, size=12, color=MORK)
DIM = Font(size=9, color="6B7280", italic=True)
FET = Font(bold=True)
KANT = Border(bottom=Side(style="thin", color="E3E7ED"))
GRONN = PatternFill("solid", fgColor="D7F0E3")
ROD = PatternFill("solid", fgColor="F8D9D9")
GUL = PatternFill("solid", fgColor="FFF3C4")
BLA = PatternFill("solid", fgColor="DCE8F8")
GRA = PatternFill("solid", fgColor="E5E7EB")
VALGT = PatternFill("solid", fgColor="EAF2FF")

DATO = "DD.MM.YYYY"
KR = '#,##0.00;[Red]-#,##0.00'
KR0 = '#,##0;[Red]-#,##0'
PST = '0%'
R_FMT = '0.00"R";[Red]-0.00"R"'
TV_FMT = '0.00;[Red]-0.00'
# Watchlist-grupper: (status, antall rader, farge, forklaring)
WL_GRUPPER = [
    ("Ready", 15, "FFF3C4", "klar – venter på entry"),
    ("Triggered", 10, "DCE8F8", "entry trigget / i posisjon"),
    ("Watching", 25, "E5E7EB", "følger med – ikke klar ennå"),
]
WL_HJELP = {"Ready": "U", "Triggered": "V", "Watching": "W"}

LISTS = {
    "Posisjon": ["Åpen", "Lukket"],
    "Setup": ["VCP", "Breakout", "Pullback", "Flag", "Cup & Handle", "Reversal", "Annet"],
    "Timeframe": ["Daily", "Weekly", "4H", "1H"],
    "Status": ["Watching", "Ready", "Triggered", "Skipped", "Traded"],
    "Trend": ["Opp", "Ned", "Sideveis"],
    "Konfidens": [1, 2, 3, 4, 5],
    "Plan Followed": ["Yes", "No", "Partially"],
    "Emotion": ["Rolig", "Selvsikker", "Usikker", "FOMO", "Redd", "Grådig", "Frustrert", "Utålmodig"],
    "Mistake": ["Ingen", "Tidlig entry", "Sen entry / jaget", "Flyttet stop", "Ingen stop",
                "For stor posisjon", "Solgte for tidlig", "Holdt for lenge", "Ikke i plan"],
}
LK = {navn: get_column_letter(i + 1) for i, navn in enumerate(LISTS)}


def _oslo_tickere() -> list[str]:
    fil = Path(__file__).resolve().parent.parent / "data" / "univers_oslobors.txt"
    try:
        linjer = fil.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ["EQNR", "DNB", "NHY", "MOWI", "TEL", "YAR", "ORK", "KOG", "AKRBP", "NAS"]
    return sorted({l.strip().removesuffix(".OL") for l in linjer
                   if l.strip() and not l.startswith("#")})


OSLO = _oslo_tickere()


def liste(navn: str) -> str:
    k = LK[navn]
    return f"=Lists!${k}$2:${k}${len(LISTS[navn]) + 1}"


def dropdown(ws, omr: str, navn: str):
    dv = DataValidation(type="list", formula1=liste(navn), allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(omr)


def cf(ws, omr, formel, fill, font=None):
    ws.conditional_formatting.add(omr, FormulaRule(formula=[formel], fill=fill, font=font))


def gronn_rod(ws, omr: str):
    forste = omr.split(":")[0]
    cf(ws, omr, f"AND(ISNUMBER({forste}),{forste}>0)", GRONN)
    cf(ws, omr, f"AND(ISNUMBER({forste}),{forste}<0)", ROD)


def hode(ws, rad: int, kol: int, tekst: str, fill=HODE_FILL):
    c = ws.cell(row=rad, column=kol, value=tekst)
    c.fill, c.font = fill, HODE_FONT
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    return c


def tabell(ws, kolonner, *, forste_rad: int, antall: int, hode_rad: int):
    """kolonner = (navn, bredde, fmt, formel|None, dropdown|None). formel bruker {r}."""
    for i, (navn, bredde, fmt, formel, dd) in enumerate(kolonner, start=1):
        L = get_column_letter(i)
        hode(ws, hode_rad, i, navn)
        ws.column_dimensions[L].width = bredde
        for r in range(forste_rad, forste_rad + antall):
            c = ws.cell(row=r, column=i)
            c.border = KANT
            if fmt:
                c.number_format = fmt
            if formel:
                c.value = formel.replace("{r}", str(r))
                c.fill = FORMEL_FILL
            else:
                c.font = INN
        if dd:
            dropdown(ws, f"{L}{forste_rad}:{L}{forste_rad + antall - 1}", dd)
    ws.row_dimensions[hode_rad].height = 36


def _d(iso: str) -> date:
    return date(*(int(x) for x in iso.split("-")))


# ---------------------------------------------------------------------------
# Analyse – planen
# ---------------------------------------------------------------------------
# A ID · B Dato · C Ticker · D Timeframe · E Trend · F Setup · G Key Levels · H TA ·
# I Entry · J SL · K T1 · L T2 · M R:R · N Risiko · O Konfidens · P Status ·
# Q Katalysator · R Notater · S Trades · T P&L · U (hjelp) Ready-nr
def lag_analyse(wb):
    ws = wb.create_sheet("Analyse")
    TB, TP = f"Trades!$B$2:$B${T_END}", f"Trades!$P$2:$P${T_END}"
    kol = [
        ("Analyse-ID", 10, None, None, None),
        ("Dato", 11, DATO, None, None),
        ("Ticker", 10, None, None, None),
        ("Timeframe", 10, None, None, "Timeframe"),
        ("Trend (HTF)", 10, None, None, "Trend"),
        ("Setup", 13, None, None, "Setup"),
        ("Key Levels / Zone", 26, None, None, None),
        ("TA-notater (MA, RSI, volum, pattern)", 34, None, None, None),
        ("Desired Entry", 10, KR, None, None),
        ("Stop Loss", 10, KR, None, None),
        ("Target 1", 10, KR, None, None),
        ("Target 2", 10, KR, None, None),
        ("R:R", 7, '0.0', '=IF(OR(I{r}="",J{r}="",K{r}="",I{r}=J{r}),"",ABS(K{r}-I{r})/ABS(I{r}-J{r}))', None),
        ("Risiko (kr)", 10, KR0, None, None),
        ("Konfidens (1–5)", 9, '0', None, "Konfidens"),
        ("Status", 11, None, None, "Status"),
        ("Katalysator / Thesis", 32, None, None, None),
        ("Notater / Plan", 32, None, None, None),
        ("Trades", 7, '0', f'=IF(C{{r}}="","",COUNTIF({TB},A{{r}}))', None),
        ("P&L fra trades", 11, KR0, f'=IF(OR(C{{r}}="",S{{r}}=0),"",SUMIFS({TP},{TB},A{{r}}))', None),
    ] + [
        (f"{s}-nr (hjelp)", 8, '0', f'=IF(P{{r}}="{s}",COUNTIF(P$2:P{{r}},"{s}"),"")', None)
        for s, *_ in WL_GRUPPER
    ]
    tabell(ws, kol, forste_rad=2, antall=N_ANALYSE, hode_rad=1)
    tdv = DataValidation(type="list", formula1=f"=Tickere!$A$2:$A${len(OSLO) + 1}",
                         allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(tdv); tdv.add(f"C2:C{A_END}")
    for r in range(2, A_END + 1):
        c = ws[f"A{r}"]
        c.value, c.font, c.fill = f"A-{r - 1:03d}", Font(color="374151"), FORMEL_FILL
        for k in "GHQR":
            ws[f"{k}{r}"].alignment = Alignment(wrap_text=True, vertical="top")
    for L in WL_HJELP.values():
        ws.column_dimensions[L].hidden = True
    ws.freeze_panes = "D2"
    p = f"P2:P{A_END}"
    cf(ws, p, 'P2="Ready"', GUL)
    cf(ws, p, 'P2="Triggered"', BLA)
    cf(ws, p, 'P2="Traded"', GRONN)
    cf(ws, p, 'P2="Skipped"', GRA)
    gronn_rod(ws, f"T2:T{A_END}")
    cf(ws, f"M2:M{A_END}", "AND(ISNUMBER(M2),M2>=3)", GRONN)
    cf(ws, f"M2:M{A_END}", "AND(ISNUMBER(M2),M2<2)", ROD)

    eks = [
        ("2026-11-02", "EQNR", "Daily", "Opp", "Breakout", "Motstand 285, support 268",
         "Over MA50/200, RSI 61, volum tørker inn i basen", 286, 276, 306, 320, 1000, 4, "Traded",
         "Høyere oljepris + utbytte", "EKSEMPEL – kjøp ved brudd over 285 på volum"),
        ("2026-11-03", "KOG", "Daily", "Opp", "VCP", "Pivot 152, entry-zone 150–153",
         "3 kontraksjoner 18-9-5 %, volum lavt i siste", 152.5, 146, 170, 185, 1500, 5, "Ready",
         "Datasenter-vekst", "EKSEMPEL – vent på brudd med 1,5× volum"),
        ("2026-11-05", "MOWI", "Weekly", "Sideveis", "Pullback", "Støtte MA50 ~ 218",
         "RSI 45, venter på reversal-candle", 220, 212, 236, 245, 800, 2, "Watching",
         "", "EKSEMPEL"),
    ]
    for i, e in enumerate(eks, start=2):
        for k, v in zip("BCDEFGHIJKLNOPQR", e):
            ws[f"{k}{i}"] = _d(v) if k == "B" else v


def fra_analyse(kol: str, id_celle: str) -> str:
    idx = (f"INDEX(Analyse!${kol}$2:${kol}${A_END},"
           f"MATCH({id_celle},Analyse!$A$2:$A${A_END},0))")
    return f'IF({id_celle}="","",IFERROR(IF({idx}="","",{idx}),""))'


# ---------------------------------------------------------------------------
# Watchlist – automatisk fra Analyse (Ready) + manuell del
# ---------------------------------------------------------------------------
WL = [  # (navn, bredde, fmt, analyse-kolonne)
    ("Analyse-ID", 10, None, "A"), ("Ticker", 10, None, "C"), ("Setup", 13, None, "F"),
    ("Timeframe", 10, None, "D"), ("Desired Entry", 10, KR, "I"), ("Stop Loss", 10, KR, "J"),
    ("Target 1", 10, KR, "K"), ("Target 2", 10, KR, "L"), ("R:R", 7, '0.0', None),
    ("Risiko", 10, KR0, "N"), ("Status", 11, None, "P"), ("Dato lagt til", 11, DATO, "B"),
    ("Catalyst / Thesis", 30, None, "Q"), ("Notes", 30, None, "R"), ("Link", 12, None, None),
]
RR_WL = '=IF(OR(E{r}="",F{r}="",G{r}="",E{r}=F{r}),"",ABS(G{r}-E{r})/ABS(E{r}-F{r}))'
LINK_WL = ('=IF(B{r}="","",HYPERLINK("https://www.tradingview.com/chart/?symbol="&B{r},'
           '"TradingView"))')


def lag_watchlist(wb):
    ws = wb.create_sheet("Watchlist")
    ws["A1"] = "Fra Analyse – gruppert etter status (fylles automatisk når du endrer Status i Analyse)"
    ws["A1"].font = SEKSJON
    for i, (navn, bredde, fmt, _) in enumerate(WL, start=1):
        hode(ws, 2, i, navn)
        ws.column_dimensions[get_column_letter(i)].width = bredde
    siste_kol = get_column_letter(len(WL))
    r = 3
    for status, antall, farge, forklaring in WL_GRUPPER:
        fill = PatternFill("solid", fgColor=farge)
        ws[f"A{r}"] = (f'="{status.upper()}  ({forklaring})  –  "&'
                       f'COUNTIF(Analyse!$P$2:$P${A_END},"{status}")&" stk"')
        ws[f"A{r}"].font = Font(bold=True, color=MORK)
        for i in range(1, len(WL) + 1):
            ws.cell(row=r, column=i).fill = fill
        ws.merge_cells(f"A{r}:{siste_kol}{r}")
        ws.row_dimensions[r].height = 20
        r += 1
        hjelp = WL_HJELP[status]
        for k in range(1, antall + 1):
            for i, (navn, _, fmt, akol) in enumerate(WL, start=1):
                L = get_column_letter(i)
                c = ws[f"{L}{r}"]
                if L == "A":
                    c.value = (f'=IFERROR(INDEX(Analyse!$A$2:$A${A_END},'
                               f'MATCH({k},Analyse!${hjelp}$2:${hjelp}${A_END},0)),"")')
                elif navn == "R:R":
                    c.value = RR_WL.replace("{r}", str(r))
                elif navn == "Link":
                    c.value = LINK_WL.replace("{r}", str(r))
                else:
                    c.value = "=" + fra_analyse(akol, f"$A{r}")
                c.fill, c.border = FORMEL_FILL, KANT
                if fmt:
                    c.number_format = fmt
            r += 1
        r += 1

    MAN_TITTEL = r
    MAN_HODE, MAN_FRA, MAN_N = MAN_TITTEL + 1, MAN_TITTEL + 2, 50
    ws[f"A{MAN_TITTEL}"] = ("Manuelt – skriv inn selv (Analyse-ID er valgfritt). "
                            "Bruk filterpilen på Status for å sortere/gruppere.")
    ws[f"A{MAN_TITTEL}"].font = SEKSJON
    ws.auto_filter.ref = f"A{MAN_TITTEL + 1}:{siste_kol}{MAN_TITTEL + 51}"
    st = f"K{MAN_TITTEL + 2}:K{MAN_TITTEL + 51}"
    for status, _, farge, _ in WL_GRUPPER:
        cf(ws, st, f'K{MAN_TITTEL + 2}="{status}"', PatternFill("solid", fgColor=farge))
    cf(ws, st, f'K{MAN_TITTEL + 2}="Traded"', GRONN)
    kol = []
    for navn, bredde, fmt, _ in WL:
        formel = RR_WL if navn == "R:R" else LINK_WL if navn == "Link" else None
        dd = {"Setup": "Setup", "Timeframe": "Timeframe", "Status": "Status"}.get(navn)
        kol.append((navn, bredde, fmt, formel, dd))
    tabell(ws, kol, forste_rad=MAN_FRA, antall=MAN_N, hode_rad=MAN_HODE)
    ws.row_dimensions[2].height = 36
    ws.freeze_panes = "C3"
    ws[f"A{MAN_FRA}"] = ""
    ws[f"B{MAN_FRA}"] = "NHY"; ws[f"C{MAN_FRA}"] = "Flag"; ws[f"D{MAN_FRA}"] = "Daily"
    ws[f"E{MAN_FRA}"] = 262; ws[f"F{MAN_FRA}"] = 248; ws[f"G{MAN_FRA}"] = 290
    ws[f"K{MAN_FRA}"] = "Watching"; ws[f"L{MAN_FRA}"] = _d("2026-11-06")
    ws[f"N{MAN_FRA}"] = "EKSEMPEL – manuell rad"


# ---------------------------------------------------------------------------
# Trades – utførelsen
# ---------------------------------------------------------------------------
# A TradeID · B Analyse-ID · C Entry Date · D Exit Date · E Ticker · F Direction · G Setup ·
# H Timeframe · I Planned Entry · J Actual Entry · K Stop Loss · L Take Profit · M Size ·
# N Fees · O Exit Price · P P&L · Q R · R Result · S Plan Followed · T Emotion · U Mistake ·
# V Duration · W Notes/Lesson · X–AC hjelpekolonner (skjult)
def lag_trades(wb):
    ws = wb.create_sheet("Trades")
    kol = [
        ("TradeID", 8, None, None, None),
        ("Analyse-ID", 10, None, None, None),
        ("Entry Date", 11, DATO, None, None),
        ("Exit Date", 11, DATO, None, None),
        ("Ticker", 10, None, "=" + fra_analyse("C", "$B{r}"), None),
        ("Posisjon", 9, None, '=IF(C{r}="","",IF(D{r}="","Åpen","Lukket"))', None),
        ("Setup", 12, None, "=" + fra_analyse("F", "$B{r}"), None),
        ("Timeframe", 10, None, "=" + fra_analyse("D", "$B{r}"), None),
        ("Planned Entry", 10, KR, "=" + fra_analyse("I", "$B{r}"), None),
        ("Actual Entry", 10, KR, None, None),
        ("Stop Loss", 10, KR, None, None),
        ("Take Profit", 10, KR, None, None),
        ("Size (shares)", 9, '#,##0', None, None),
        ("Fees", 8, KR, None, None),
        ("Exit Price", 10, KR, None, None),
        ("P&L", 11, KR0, '=IF(OR(J{r}="",O{r}="",M{r}=""),"",(O{r}-J{r})*M{r}-N{r})', None),
        ("R-Multiple", 9, R_FMT, '=IF(OR(P{r}="",K{r}="",J{r}=K{r}),"",P{r}/(ABS(J{r}-K{r})*M{r}))', None),
        ("Result", 8, None, '=IF(P{r}="","",IF(AND(ISNUMBER(Q{r}),ABS(Q{r})<0.05),"BE",IF(P{r}>0,"Win",IF(P{r}<0,"Loss","BE"))))', None),
        ("Plan Followed", 10, None, None, "Plan Followed"),
        ("Emotion", 11, None, None, "Emotion"),
        ("Mistake", 15, None, None, "Mistake"),
        ("Duration (dager)", 9, '0', '=IF(OR(C{r}="",D{r}=""),"",D{r}-C{r})', None),
        ("Avkastning %", 9, '0.0%;[Red]-0.0%',
         '=IF(OR(P{r}="",J{r}="",J{r}=0),"",(O{r}-J{r})/J{r})', None),
        ("Time Value (%/dag)", 9, TV_FMT, '=IF(OR(W{r}="",V{r}=""),"",W{r}*100/MAX(V{r},1))', None),
        ("Notes / Lesson", 40, None, None, None),
        ("Uke (hjelp)", 10, DATO, '=IF(OR(R{r}="",D{r}=""),"",D{r}-WEEKDAY(D{r},2)+1)', None),
        ("Måned (hjelp)", 10, DATO, '=IF(OR(R{r}="",D{r}=""),"",DATE(YEAR(D{r}),MONTH(D{r}),1))', None),
        ("Lukket (hjelp)", 7, '0', '=IF(R{r}="","",1)', None),
        ("Kum. P&L (hjelp)", 10, KR0, '=IF(P{r}="","",SUM(P$2:P{r}))', None),
        ("Chart-treff (hjelp)", 7, '0', '=IF(OR(E{r}="",Chart!$AF$4=""),0,IF(SUBSTITUTE(UPPER(TRIM(E{r})),".OL","")=Chart!$AF$4,1,0))', None),
        ("Chart-nr (hjelp)", 7, '0', '=IF(AD{r}=1,SUM(AD$2:AD{r}),"")', None),
    ]
    tabell(ws, kol, forste_rad=2, antall=N_TRADES, hode_rad=1)
    dv = DataValidation(type="list", formula1=f"=Analyse!$A$2:$A${A_END}", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"B2:B{T_END}")
    for r in range(2, T_END + 1):
        c = ws[f"A{r}"]
        c.value, c.font, c.fill = f"T-{r - 1:03d}", Font(color="374151"), FORMEL_FILL
        ws[f"Y{r}"].alignment = Alignment(wrap_text=True, vertical="top")
    for L in ("Z", "AA", "AB", "AC", "AD", "AE"):
        ws.column_dimensions[L].hidden = True
    ws.freeze_panes = "F2"
    gronn_rod(ws, f"P2:P{T_END}")
    gronn_rod(ws, f"Q2:Q{T_END}")
    gronn_rod(ws, f"W2:W{T_END}")
    gronn_rod(ws, f"X2:X{T_END}")
    cf(ws, f"R2:R{T_END}", 'R2="Win"', GRONN)
    cf(ws, f"R2:R{T_END}", 'R2="Loss"', ROD)
    cf(ws, f"R2:R{T_END}", 'R2="BE"', GRA)
    cf(ws, f"S2:S{T_END}", 'S2="No"', ROD)
    cf(ws, f"S2:S{T_END}", 'S2="Partially"', GUL)

    eks = [  # B C D F J K L M N O S T U W
        ("A-001", "2026-11-03", "2026-11-09", 286.4, 276, 306, 100, 20, 301.0, "Yes",
         "Rolig", "Ingen", "EKSEMPEL – fulgte planen, solgte ved T1-nær"),
        ("A-002", "2026-11-04", "2026-11-06", 153.9, 146, 170, 60, 15, 146.0, "Partially",
         "FOMO", "Sen entry / jaget", "EKSEMPEL – kjøpte 1 % over pivot, stoppet ut"),
        ("A-002", "2026-11-09", None, 151.0, 146, 170, 40, 10, None, "", "", "",
         "EKSEMPEL – åpen trade"),
    ]
    for i, e in enumerate(eks, start=2):
        for k, v in zip("BCDJKLMNOSTUY", e):
            if v in (None, ""):
                continue
            ws[f"{k}{i}"] = _d(v) if k in "CD" else v


def TR(k: str) -> str:
    return f"Trades!${k}$2:${k}${T_END}"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def lag_dashboard(wb):
    ws = wb.active
    ws.title = "Dashboard"
    ws.sheet_view.showGridLines = False
    for k, b in zip("ABCDEFGHIJKLM", (2, 24, 13, 3, 16, 10, 10, 10, 12, 10, 3, 3, 3)):
        ws.column_dimensions[k].width = b
    P, Q, R, Z, G, V, TV = TR("P"), TR("Q"), TR("R"), TR("AB"), TR("G"), TR("V"), TR("X")
    ws["B1"] = "Tradingjournal"; ws["B1"].font = TITTEL
    ws["B2"] = ("Analyse = planen (før) · Trades = utførelsen + review (etter). "
                "Blå tekst = det du skriver · grå celler = formler.")
    ws["B2"].font = DIM

    # Nøkkeltall
    ws["B4"] = "Nøkkeltall (lukkede trades)"; ws["B4"].font = SEKSJON
    rader = [
        ("Antall trades", f"=SUM({Z})", '0'),                                         # 5
        ("Wins", f'=COUNTIF({R},"Win")', '0'),                                       # 6
        ("Losses", f'=COUNTIF({R},"Loss")', '0'),                                    # 7
        ("Break-even", f'=COUNTIF({R},"BE")', '0'),                                  # 8
        ("Winrate", '=IFERROR(C6/C5,"")', PST),                                      # 9
        ("Total P&L", f"=SUM({P})", KR0),                                            # 10
        ("Avg Win", f'=IFERROR(AVERAGEIFS({P},{R},"Win"),"")', KR0),                 # 11
        ("Avg Loss", f'=IFERROR(AVERAGEIFS({P},{R},"Loss"),"")', KR0),               # 12
        ("Profit Factor", f'=IFERROR(SUMIFS({P},{R},"Win")/-SUMIFS({P},{R},"Loss"),"")', '0.00'),  # 13
        ("Expectancy (avg R)", f'=IFERROR(AVERAGE({Q}),"")', R_FMT),                 # 14
        ("Beste R", f'=IF(C5=0,"",MAX({Q}))', R_FMT),                                # 15
        ("Dårligste R", f'=IF(C5=0,"",MIN({Q}))', R_FMT),                            # 16
        ("Åpne trades", f'=COUNTIFS({TR("C")},"<>",{TR("O")},"")', '0'),             # 17
        ("Avg Time Value (%/dag)", f'=IFERROR(AVERAGE({TV}),"")', TV_FMT),          # 18
    ]
    for i, (navn, formel, fmt) in enumerate(rader, start=5):
        ws[f"B{i}"] = navn
        c = ws[f"C{i}"]; c.value = formel; c.number_format = fmt; c.font = FET
        c.alignment = Alignment(horizontal="right")
        ws[f"B{i}"].border = ws[f"C{i}"].border = KANT
    for celle in ("C10", "C14", "C18"):
        cf(ws, celle, f"AND(ISNUMBER({celle}),{celle}>0)", GRONN)
        cf(ws, celle, f"AND(ISNUMBER({celle}),{celle}<0)", ROD)
    cf(ws, "C13", "AND(ISNUMBER(C13),C13>=1.5)", GRONN)
    cf(ws, "C13", "AND(ISNUMBER(C13),C13<1)", ROD)

    # Performance per setup
    ws["E4"] = "Performance per Setup"; ws["E4"].font = SEKSJON
    for i, t in enumerate(("Setup", "Antall", "Winrate", "Avg R", "Avg TV")):
        hode(ws, 5, 5 + i, t)
    for j in range(len(LISTS["Setup"])):
        r = 6 + j
        s = f"Lists!${LK['Setup']}${j + 2}"
        ws[f"E{r}"] = f"={s}"
        ws[f"F{r}"] = f"=SUMIFS({Z},{G},{s})"
        ws[f"G{r}"] = f'=IFERROR(COUNTIFS({G},{s},{R},"Win")/F{r},"")'
        ws[f"H{r}"] = f'=IFERROR(AVERAGEIFS({TR("Q")},{G},{s}),"")'
        ws[f"I{r}"] = f'=IFERROR(AVERAGEIFS({TV},{G},{s}),"")'
        ws[f"F{r}"].number_format, ws[f"G{r}"].number_format, ws[f"H{r}"].number_format = '0', PST, R_FMT
        ws[f"I{r}"].number_format = TV_FMT
        for k in "EFGHI":
            ws[f"{k}{r}"].border = KANT
        gronn_rod(ws, f"H{r}:I{r}")

    # Holdetid vs resultat
    h0 = 6 + len(LISTS["Setup"]) + 2
    ws[f"E{h0}"] = "Holdetid vs Resultat"; ws[f"E{h0}"].font = SEKSJON
    for i, t in enumerate(("Holdetid", "Antall", "Winrate", "Avg R", "Total P&L", "Avg TV")):
        hode(ws, h0 + 1, 5 + i, t)
    for j, (navn, lo, hi) in enumerate((("0–1 dag", 0, 1), ("2–3 dager", 2, 3),
                                        ("4–7 dager", 4, 7), ("8+ dager", 8, 100000))):
        r = h0 + 2 + j
        kr = f'{V},">={lo}",{V},"<={hi}"'
        ws[f"E{r}"] = navn
        ws[f"F{r}"] = f"=SUMIFS({Z},{kr})"
        ws[f"G{r}"] = f'=IFERROR(COUNTIFS({R},"Win",{kr})/F{r},"")'
        ws[f"H{r}"] = f'=IFERROR(AVERAGEIFS({TR("Q")},{kr}),"")'
        ws[f"I{r}"] = f"=SUMIFS({P},{kr})"
        ws[f"J{r}"] = f'=IFERROR(AVERAGEIFS({TV},{kr}),"")'
        for k, fmt in zip("FGHIJ", ('0', PST, R_FMT, KR0, TV_FMT)):
            ws[f"{k}{r}"].number_format = fmt
        for k in "EFGHIJ":
            ws[f"{k}{r}"].border = KANT
        gronn_rod(ws, f"H{r}:J{r}")

    # Siste trades
    s0 = 20
    ws[f"B{s0}"] = "Siste trades"; ws[f"B{s0}"].font = SEKSJON
    ws["N1"] = f"=COUNT({TR('C')})"           # antall trades med entry-dato (hjelp)
    ws["N1"].font = Font(color="FFFFFF")
    kolonner = [("TradeID", "A", None), ("Entry", "C", DATO), ("Ticker", "E", None),
                ("Posisjon", "F", None), ("Setup", "G", None), ("P&L", "P", KR0),
                ("R", "Q", R_FMT), ("Result", "R", None)]
    sk = "BCEFGHIJ"
    for (t, _, _), k in zip(kolonner, sk):
        hode(ws, s0 + 1, " ABCDEFGHIJ".index(k), t)
    for n in range(10):
        r = s0 + 2 + n
        for (t, tk, fmt), k in zip(kolonner, sk):
            idx = f"$N$1-{n}"
            verdi = f"INDEX({TR(tk)},{idx})"
            if fmt in (None,):
                verdi += '&""'
            ws[f"{k}{r}"] = f'=IF({idx}<1,"",{verdi})'
            if fmt:
                ws[f"{k}{r}"].number_format = fmt
            ws[f"{k}{r}"].border = KANT
        cf(ws, f"I{r}", f"AND(ISNUMBER(I{r}),I{r}>0)", GRONN)
        cf(ws, f"I{r}", f"AND(ISNUMBER(I{r}),I{r}<0)", ROD)
        cf(ws, f"J{r}", f'J{r}="Win"', GRONN)
        cf(ws, f"J{r}", f'J{r}="Loss"', ROD)
    ws.column_dimensions["D"].width = 3

    # Bruk
    b0 = s0 + 13
    ws[f"B{b0}"] = "Slik bruker du journalen"; ws[f"B{b0}"].font = SEKSJON
    tekst = [
        "1. Analyse – fyll ut planen først: nivåer, enkel TA, entry/stop/targets, konfidens og thesis.",
        "2. Status i Analyse styrer Watchlist: Ready / Triggered / Watching vises gruppert automatisk.",
        "Time Value = avkastning % / dager holdt (min. 1). 10 % på 3 dager = 3,33. Høyere er bedre.",
        "3. Tar du traden: ny rad i Trades, velg Analyse-ID → ticker, setup og planned entry hentes fra planen.",
        "4. Etter traden: fyll inn exit, Plan Followed, Emotion, Mistake og lærdom. Sett analysen til Traded.",
        "5. Hver helg: Weekly (velg uke, skriv refleksjon i loggen). Hver måned: Monthly.",
        "Dropdown-verdiene endres i arket Lists. Eksempelradene (merket EKSEMPEL) kan slettes.",
    ]
    for i, t in enumerate(tekst, start=1):
        c = ws[f"B{b0 + i}"]; c.value = t
        ws.merge_cells(f"B{b0 + i}:J{b0 + i}")


# ---------------------------------------------------------------------------
# Weekly / Monthly
# ---------------------------------------------------------------------------
def lag_periode(wb, *, maned: bool):
    navn = "Monthly" if maned else "Weekly"
    ws = wb.create_sheet(navn)
    ws.sheet_view.showGridLines = False
    hjelp = TR("AA" if maned else "Z")
    P, Q, R, Z, S, TV = TR("P"), TR("Q"), TR("R"), TR("AB"), TR("S"), TR("X")
    i_dag = date(2026, 11, 10)
    forste = date(2026, 11, 1) if maned else date(2026, 11, 2)
    valgt = forste

    ws["B1"] = "Månedsoppsummering" if maned else "Ukeoppsummering"; ws["B1"].font = TITTEL
    ws["B3"] = "Velg måned (1. i måneden)" if maned else "Velg uke (mandag)"
    ws["B3"].font = FET
    ws["C3"] = valgt; ws["C3"].font = INN_FET; ws["C3"].number_format = "MMMM YYYY" if maned else DATO
    if not maned:
        ws["D3"] = '="Uke "&ISOWEEKNUM(C3)'
    ws["B4"] = "Statistikk regnes på trades med exit i perioden. Skriv refleksjonen i loggen under (valgt periode er markert)."
    ws["B4"].font = DIM

    def stat(krit_kol, valgt_celle):
        k = f"{krit_kol},{valgt_celle}"
        ut = [
            ("Trades", f"=SUMIFS({Z},{k})", '0'),
            ("Wins", f'=COUNTIFS({k},{R},"Win")', '0'),
            ("Losses", f'=COUNTIFS({k},{R},"Loss")', '0'),
            ("Winrate", "=IFERROR({w}/{t},\"\")", PST),
            ("Total P&L", f"=SUMIFS({P},{k})", KR0),
            ("Avg R", f'=IFERROR(AVERAGEIFS({Q},{k}),"")', R_FMT),
            ("Avg TV", f'=IFERROR(AVERAGEIFS({TV},{k}),"")', TV_FMT),
            ("Beste R", f'=IF({{t}}=0,"",MAXIFS({Q},{k}))', R_FMT),
            ("Dårligste R", f'=IF({{t}}=0,"",MINIFS({Q},{k}))', R_FMT),
        ]
        if maned:
            ut += [
                ("Profit Factor", f'=IFERROR(SUMIFS({P},{k},{R},"Win")/-SUMIFS({P},{k},{R},"Loss"),"")', '0.00'),
                ("% Plan Followed", f'=IFERROR(COUNTIFS({k},{S},"Yes")/{{t}},"")', PST),
            ]
        return ut

    # Valgt periode
    rad0 = 6
    for i, (n, f, fmt) in enumerate(stat(hjelp, "$C$3")):
        r = rad0 + i
        ws[f"B{r}"] = n
        c = ws[f"C{r}"]
        c.value = f.replace("{w}", f"C{rad0 + 1}").replace("{t}", f"C{rad0}")
        c.number_format, c.font = fmt, FET
        ws[f"B{r}"].border = ws[f"C{r}"].border = KANT
    for r in (rad0 + 4, rad0 + 5, rad0 + 6):
        cf(ws, f"C{r}", f"AND(ISNUMBER(C{r}),C{r}>0)", GRONN)
        cf(ws, f"C{r}", f"AND(ISNUMBER(C{r}),C{r}<0)", ROD)

    # Logg
    antall = 36 if maned else 104
    logg_hode = rad0 + len(stat(hjelp, "$C$3")) + 3
    ws[f"B{logg_hode - 1}"] = "Logg – én rad per " + ("måned" if maned else "uke"); ws[f"B{logg_hode - 1}"].font = SEKSJON
    statkol = [("Trades", '0'), ("Wins", '0'), ("Losses", '0'), ("Winrate", PST),
               ("P&L", KR0), ("Avg R", R_FMT), ("Avg TV", TV_FMT)]
    if maned:
        statkol += [("Profit Factor", '0.00'), ("% Plan Followed", PST)]
    refl = (["Månedens lærdom", "Gjør mer av", "Gjør mindre av", "Prosessmål neste måned"]
            if maned else ["Hva gikk bra?", "Hva må forbedres?", "Én ting jeg fokuserer på neste uke"])
    overskr = ["Måned" if maned else "Uke (mandag)"] + [s for s, _ in statkol] + ["Kumulativ P&L"] + refl
    for i, t in enumerate(overskr, start=2):
        hode(ws, logg_hode, i, t, fill=REFL_FILL if t in refl else HODE_FILL)
    ws.row_dimensions[logg_hode].height = 34
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 13
    for i in range(4, 3 + len(statkol) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 10
    kum_kol = get_column_letter(3 + len(statkol))
    pl_kol = get_column_letter(3 + [s for s, _ in statkol].index("P&L"))
    for j in range(len(refl)):
        ws.column_dimensions[get_column_letter(4 + len(statkol) + j)].width = 34

    forste_logg = logg_hode + 1
    siste_logg = forste_logg + antall - 1
    for n in range(antall):
        r = forste_logg + n
        a = ws[f"B{r}"]
        if n == 0:
            a.value = forste
        else:
            a.value = f"=EDATE(B{r - 1},1)" if maned else f"=B{r - 1}+7"
        a.number_format = "MMMM YYYY" if maned else DATO
        a.fill = FORMEL_FILL
        st = dict((s, f) for s, _, f in [(x[0], None, x[1]) for x in stat(hjelp, f"$B{r}")])
        t_ref, w_ref = f"C{r}", f"D{r}"
        for i, (s, fmt) in enumerate(statkol):
            L = get_column_letter(3 + i)
            src = {"P&L": "Total P&L"}.get(s, s)
            ws[f"{L}{r}"] = st[src].replace("{w}", w_ref).replace("{t}", t_ref)
            ws[f"{L}{r}"].number_format = fmt
            ws[f"{L}{r}"].fill = FORMEL_FILL
        ws[f"{kum_kol}{r}"] = f'=IF(B{r}>TODAY(),NA(),SUM(${pl_kol}${forste_logg}:{pl_kol}{r}))'
        ws[f"{kum_kol}{r}"].number_format = KR0
        ws[f"{kum_kol}{r}"].fill = FORMEL_FILL
        for j in range(len(refl)):
            c = ws.cell(row=r, column=4 + len(statkol) + j)
            c.font = INN
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for i in range(2, 4 + len(statkol) + len(refl)):
            ws.cell(row=r, column=i).border = KANT
        ws.row_dimensions[r].height = 30
    sist = get_column_letter(3 + len(statkol) + len(refl))
    omr = f"B{forste_logg}:{sist}{siste_logg}"
    cf(ws, omr, f"$B{forste_logg}=$C$3", VALGT)
    cf(ws, f"{kum_kol}{forste_logg}:{kum_kol}{siste_logg}",
       f"ISERROR({kum_kol}{forste_logg})", PatternFill(fill_type=None), Font(color="FFFFFF"))
    pl_i = [s for s, _ in statkol].index("P&L")
    for L in (get_column_letter(3 + pl_i + d) for d in range(3)):
        gronn_rod(ws, f"{L}{forste_logg}:{L}{siste_logg}")
    for L in (kum_kol,):
        gronn_rod(ws, f"{L}{forste_logg}:{L}{siste_logg}")
    ws.freeze_panes = f"C{forste_logg}"

    # Equity curve
    ch = LineChart()
    ch.title = "Equity curve (kumulativ P&L)"
    ch.height, ch.width = 7.5, 16
    ch.legend = None
    ch.y_axis.numFmt = '#,##0'
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    data = Reference(ws, min_col=3 + len(statkol), min_row=logg_hode, max_row=siste_logg)
    kat = Reference(ws, min_col=2, min_row=forste_logg, max_row=siste_logg)
    ch.add_data(data, titles_from_data=True)
    ch.set_categories(kat)
    ch.series[0].smooth = False
    ws.add_chart(ch, "E3")


# ---------------------------------------------------------------------------
# Chart (Excel – lim inn kursdata, candlestick-diagram oppdateres selv)
# ---------------------------------------------------------------------------
CHART_N = 120          # antall handelsdager i diagrammet
RA_FRA, RA_TIL = 7, 1006


def lag_chart(wb, google: bool = False):
    ws = wb.create_sheet("Chart")
    ws.sheet_view.showGridLines = False
    ws["B1"] = "Chart"; ws["B1"].font = TITTEL
    ws["B3"] = "Ticker (f.eks. EQNR)"; ws["B3"].font = FET
    ws["C3"] = "EQNR"; ws["C3"].font = INN_FET
    tdv = DataValidation(type="list", formula1=f"=Tickere!$A$2:$A${len(OSLO) + 1}",
                         allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(tdv); tdv.add("C3")
    ws["B4"] = "Slutt dato (tom = i dag)" if google else "Slutt dato (tom = siste)"; ws["B4"].font = FET
    ws["C4"].font = INN_FET; ws["C4"].number_format = DATO
    # Renset ticker (uten .OL / mellomrom) – brukes til å finne dine trades
    ws["AF3"] = "Ticker renset (hjelp)"; ws["AF3"].font = DIM
    ws["AF4"] = '=SUBSTITUTE(UPPER(TRIM($C$3)),".OL","")'
    if google:
        ws["B5"] = "Børs"; ws["B5"].font = FET
        ws["C5"] = "OSL"; ws["C5"].font = INN_FET
        dv = DataValidation(type="list", formula1='"OSL,USA"',
                            allow_blank=True, showErrorMessage=False)
        ws.add_data_validation(dv); dv.add("C5")
        # Yahoo-symbol: Oslo = EQNR.OL, USA = NVDA
        ws["AF5"] = '=IF($C$5="USA",$AF$4,$AF$4&".OL")'
        ws["E3"] = ("Velg ticker fra listen (Oslo Børs) eller skriv selv. Kursene hentes fra Yahoo Finance "
                    "via skriptet journal_yahoo.gs (Utvidelser → Apps Script – se arket Tickere).")
        ws["E4"] = ('=IFERROR("Henter: "&$AF$5&"  –  "&YAHOONAVN($AF$5),'
                    '"Fant ikke "&$AF$5&" – er Apps Script-koden installert? Sjekk ticker i Tickere")')
        ws["E5"] = ("▲ grønn = kjøp, ▼ rød = salg (fra Trades). Lysestake-alternativ: marker X6:AB"
                    f"{6 + CHART_N} → Sett inn → Diagram → Lysestake (uten markører).")
        ws["E5"].font = DIM
        ws["E4"].font = FET
    else:
        ws["E3"] = ("1) Last ned kurser (f.eks. Yahoo Finance → Historical Data → Download, daglig). "
                    "2) Lim inn Date, Open, High, Low, Close i kolonne R–V fra rad 7 (eldste øverst).")
        ws["E4"] = (f"Diagrammet viser de siste {CHART_N} handelsdagene fram til slutt dato. "
                    "Trades på tickeren listes under diagrammet.")
        ws["E4"].font = DIM
    ws["E3"].font = DIM
    for k, b in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    (2, 24, 12, 3, 11, 11, 11, 11, 11, 11, 11, 40, 3, 3, 3, 3, 3,
                     11, 9, 9, 9, 9, 3, 11, 9, 9)):
        ws.column_dimensions[k].width = b

    # Kursdata R:V (Google: GOOGLEFINANCE spres fra R6 inkl. overskrift)
    if google:
        ws["R5"] = "Kursdata (Yahoo – ikke skriv her)"; ws["R5"].font = DIM
        slutt = 'IF($C$4="",TODAY(),$C$4)'
        ws["R6"] = (f'=IFERROR(YAHOOKURS($AF$5,{slutt}-{CHART_N * 2},{slutt}),'
                    f'"Fant ikke kurser – sjekk ticker / Apps Script")')
        ws.column_dimensions["W"].width = 3
    else:
        ws["R5"] = "LIM INN KURSDATA HER"; ws["R5"].font = SEKSJON
        for i, t in enumerate(("Date", "Open", "High", "Low", "Close")):
            hode(ws, 6, 18 + i, t)
    for r in range(RA_FRA, RA_TIL + 1):
        ws[f"R{r}"].number_format = DATO
        for k in "STUV":
            ws[f"{k}{r}"].number_format = KR
        if not google:
            for k in "RSTUV":
                ws[f"{k}{r}"].font = INN

    # Hjelpeområde X:AB – siste CHART_N rader fram til slutt dato
    rd = f"$R${RA_FRA}:$R${RA_TIL}"
    ws["AF1"] = "Siste rad (hjelp)"; ws["AF1"].font = DIM
    ws["AF2"] = f'=IF(COUNT({rd})=0,0,IF($C$4="",COUNT({rd}),IFERROR(MATCH($C$4+0.99,{rd},1),0)))'
    ws["X5"] = "Chart-data (formler)"; ws["X5"].font = DIM
    # Google lysestake vil ha Dato, Low, Open, Close, High – Excel vil ha O, H, L, C
    rekkefølge = (("Low", "U"), ("Open", "S"), ("Close", "V"), ("High", "T")) if google else \
        (("Open", "S"), ("High", "T"), ("Low", "U"), ("Close", "V"))
    for i, t in enumerate(("Date",) + tuple(n for n, _ in rekkefølge) + ("Kjøp", "Salg")):
        hode(ws, 6, 24 + i, t)
    forste_h, siste_h = 7, 6 + CHART_N
    treff = TR("AD")
    for k in range(1, CHART_N + 1):
        r = 6 + k
        idx = f"($AF$2-{CHART_N}+{k})"
        ws[f"X{r}"] = f'=IF({idx}<1,"",INT(INDEX({rd},{idx})))'
        ws[f"X{r}"].number_format = "DD.MM.YY"
        for (_, src), dst in zip(rekkefølge, ("Y", "Z", "AA", "AB")):
            ws[f"{dst}{r}"] = f"=IF({idx}<1,NA(),INDEX(${src}${RA_FRA}:${src}${RA_TIL},{idx}))"
            ws[f"{dst}{r}"].number_format = KR
        ws[f"AC{r}"] = (f'=IF(X{r}="",NA(),IFERROR(AVERAGEIFS({TR("J")},{treff},1,'
                        f'{TR("C")},X{r}),NA()))')
        ws[f"AD{r}"] = (f'=IF(X{r}="",NA(),IFERROR(AVERAGEIFS({TR("O")},{treff},1,'
                        f'{TR("D")},X{r}),NA()))')
        for dst in ("X", "Y", "Z", "AA", "AB", "AC", "AD"):
            ws[f"{dst}{r}"].fill = FORMEL_FILL
        ws[f"AC{r}"].number_format = ws[f"AD{r}"].number_format = KR

    if google:
        _google_chart(ws, forste_h, siste_h)
    else:
        _excel_lysestake(ws, forste_h, siste_h)

    # Mine trades på valgt ticker
    _chart_trades(ws)


def _google_chart(ws, forste_h, siste_h):
    """Linjediagram: Close + kjøp (grønn ▲) + salg (rød ▼). Google importerer dette."""
    from openpyxl.chart.marker import Marker
    ch = LineChart()
    ch.title = None
    ch.height, ch.width = 10, 27
    ch.legend.position = "b"
    kat = Reference(ws, min_col=24, min_row=forste_h, max_row=siste_h)
    for kol in (27, 29, 30):  # Close (AA), Kjøp (AC), Salg (AD)
        ch.add_data(Reference(ws, min_col=kol, min_row=6, max_row=siste_h), titles_from_data=True)
    ch.set_categories(kat)
    close, kjop, salg = ch.series
    close.graphicalProperties.line.solidFill = "1F4FD8"
    close.graphicalProperties.line.width = 20000
    close.marker = Marker(symbol="none")
    close.smooth = False
    for s, sym, farge in ((kjop, "triangle", "16A34A"), (salg, "diamond", "DC2626")):
        s.graphicalProperties.line.noFill = True
        s.marker = Marker(symbol=sym, size=10)
        s.marker.graphicalProperties = GraphicalProperties(solidFill=farge)
        s.marker.graphicalProperties.line.solidFill = farge
    ch.y_axis.numFmt = "#,##0.00"
    ch.y_axis.majorGridlines = ChartLines()
    ch.x_axis.number_format = "DD.MM"
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ws.add_chart(ch, "B7")


def _excel_lysestake(ws, forste_h, siste_h):
    ch = StockChart()
    ch.title = None
    ch.height, ch.width = 10, 27
    ch.legend = None
    data = Reference(ws, min_col=25, max_col=28, min_row=6, max_row=siste_h)
    ch.add_data(data, titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=24, min_row=forste_h, max_row=siste_h))
    for s in ch.series:
        s.graphicalProperties.line.noFill = True
    ch.hiLowLines = ChartLines()
    ch.upDownBars = UpDownBars(
        gapWidth=60,
        upBars=ChartLines(spPr=GraphicalProperties(solidFill="26A69A")),
        downBars=ChartLines(spPr=GraphicalProperties(solidFill="EF5350")),
    )
    ch.y_axis.numFmt = "#,##0.00"
    ch.y_axis.majorGridlines = ChartLines()
    ch.x_axis.number_format = "DD.MM"
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ws.add_chart(ch, "B6")


def _chart_trades(ws):
    t0 = 28
    ws[f"B{t0}"] = '="Mine trades på "&$C$3'; ws[f"B{t0}"].font = SEKSJON
    kol = [("TradeID", "A", None), ("Entry Date", "C", DATO), ("Exit Date", "D", DATO),
           ("Posisjon", "F", None), ("Actual Entry", "J", KR), ("Exit Price", "O", KR),
           ("P&L", "P", KR0), ("R", "Q", R_FMT), ("TV", "X", TV_FMT), ("Result", "R", None),
           ("Lesson", "Y", None)]
    for i, (t, _, _) in enumerate(kol):
        hode(ws, t0 + 1, 2 + i, t)
    for n in range(1, 21):
        r = t0 + 1 + n
        m = f"MATCH({n},{TR('AE')},0)"
        for i, (t, tk, fmt) in enumerate(kol):
            c = ws.cell(row=r, column=2 + i)
            c.value = f'=IFERROR(INDEX({TR(tk)},{m}){"&\"\"" if fmt is None else ""},"")'
            if fmt:
                c.number_format = fmt
            c.border = KANT
        L_pl, L_res = get_column_letter(2 + 6), get_column_letter(2 + 9)
        cf(ws, f"{L_pl}{r}", f"AND(ISNUMBER({L_pl}{r}),{L_pl}{r}>0)", GRONN)
        cf(ws, f"{L_pl}{r}", f"AND(ISNUMBER({L_pl}{r}),{L_pl}{r}<0)", ROD)
        cf(ws, f"{L_res}{r}", f'{L_res}{r}="Win"', GRONN)
        cf(ws, f"{L_res}{r}", f'{L_res}{r}="Loss"', ROD)
    ws.column_dimensions["L"].width = 40


def lag_tickere(wb, google: bool):
    ws = wb.create_sheet("Tickere")
    hode(ws, 1, 1, "Ticker (Oslo Børs)")
    hode(ws, 1, 2, "Yahoo-symbol")
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 16
    for i, t in enumerate(OSLO, start=2):
        ws[f"A{i}"] = t
        ws[f"B{i}"] = f"{t}.OL"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:B{len(OSLO) + 1}"
    ws["D1"] = "Ticker skrives uten .OL i journalen. Usikker? Søk på finance.yahoo.com – symbolet der (f.eks. EQNR.OL) uten .OL er riktig."
    ws["D1"].font = DIM
    if google:
        ws["D3"] = "Installer kurshenting (én gang):"; ws["D3"].font = SEKSJON
        for j, t in enumerate((
            "1. Utvidelser → Apps Script.",
            "2. Slett alt i Kode.gs og lim inn hele innholdet i verktoy/journal_yahoo.gs.",
            "3. Klikk Lagre (diskett-ikonet) og lukk fanen.",
            "4. Gå til Chart-arket. Første gang ber Google om tillatelse – godta.",
            "Test: skriv =YAHOONAVN(\"EQNR.OL\") i en tom celle → skal vise Equinor ASA.",
        ), start=4):
            ws[f"D{j}"] = t


def lag_lists(wb):
    ws = wb.create_sheet("Lists")
    for navn, verdier in LISTS.items():
        k = LK[navn]
        hode(ws, 1, ws[f"{k}1"].column, navn)
        ws.column_dimensions[k].width = 18
        for j, v in enumerate(verdier, start=2):
            ws[f"{k}{j}"] = v
            ws[f"{k}{j}"].font = INN
    ws["A12"] = "Legg til/endre verdier rett under hver overskrift. Nye setups dukker opp i Dashboard automatisk."
    ws["A12"].font = DIM


def _xlfn(wb):
    for ws in wb.worksheets:
        for rad in ws.iter_rows():
            for c in rad:
                if isinstance(c.value, str) and c.value.startswith("="):
                    v = c.value
                    for fn in ("ISOWEEKNUM(", "MAXIFS(", "MINIFS("):
                        v = v.replace(fn, "_xlfn." + fn)
                    c.value = v


def lag(google: bool):
    wb = Workbook()
    lag_dashboard(wb)
    lag_analyse(wb)
    lag_watchlist(wb)
    lag_trades(wb)
    lag_periode(wb, maned=False)
    lag_periode(wb, maned=True)
    lag_chart(wb, google=google)
    lag_lists(wb)
    lag_tickere(wb, google)
    _xlfn(wb)
    ut = UT.with_name("Tradingjournal_v3_google.xlsx") if google else UT
    ut.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ut)
    print(f"Lagret: {ut}")


def main():
    lag(google=False)
    lag(google=True)


if __name__ == "__main__":
    main()
