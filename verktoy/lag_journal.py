"""
lag_journal.py – genererer Tradingjournal.xlsx (Minervini-stil).

Kjør:  python verktoy/lag_journal.py   →  journal/Tradingjournal.xlsx

Fila fungerer i Excel OG Google Sheets (Fil → Importer / last opp og åpne).
Bevisst bare vanlige formler (COUNTIFS, SUMIFS, AVERAGEIFS, MAXIFS, IFERROR) og
ingen Excel-tabeller/makroer, så alt overlever importen til Google Sheets.

Faner:
  Instruks        – kort bruksanvisning
  Watchlist       – kandidater du følger (pivot, stop, R/R, avstand til pivot)
  Forhåndsanalyse – Minervini-sjekkliste før kjøp (Ja/Nei → poeng og karakter)
  Handler         – kjøp og salg, én rad per handel; resultat, %, R og dager regnes
  Statistikk      – hva funker: treff%, snitt gevinst/tap, R, og per setup/RS/TS/marked
  Lister          – verdiene i nedtrekkslistene (kan redigeres)
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

RADER = 500                      # antall forhåndsformaterte rader
UT = Path(__file__).resolve().parent.parent / "journal" / "Tradingjournal.xlsx"

# --- Stil -------------------------------------------------------------------
GRONN_MORK = "2E5E4E"
HODE_FILL = PatternFill("solid", fgColor=GRONN_MORK)
HODE_FONT = Font(bold=True, color="FFFFFF", size=10)
BEREGNET_FILL = PatternFill("solid", fgColor="F3F6F4")   # formelceller (ikke rør)
SEKSJON_FONT = Font(bold=True, size=12, color=GRONN_MORK)
TITTEL_FONT = Font(bold=True, size=16, color=GRONN_MORK)
DIM_FONT = Font(size=9, color="6B7280", italic=True)
TYNN = Side(style="thin", color="D9E2DC")
KANT = Border(bottom=TYNN)
GRONN_FILL = PatternFill("solid", fgColor="D7F0E3")
ROD_FILL = PatternFill("solid", fgColor="F8D9D9")
GUL_FILL = PatternFill("solid", fgColor="FFF3C4")

DATO = "DD.MM.YYYY"
KR = '#,##0.00;[Red]-#,##0.00'
KR0 = '#,##0;[Red]-#,##0'
PST = '0.0%;[Red]-0.0%'
R_FMT = '0.00"R";[Red]-0.00"R"'

LISTER = {
    "Setup": ["VCP-brudd", "Pivot-brudd", "Pullback til MA50", "Høy stram flagg",
              "Golden cross", "IPO-base", "Annet"],
    "Børs": ["Oslo Børs", "S&P 500", "Annen"],
    "Marked": ["Opptrend", "Under press", "Nedtrend"],
    "Salgsårsak": ["Stop truffet", "Mål nådd", "Trailing stop", "Brøt MA50",
                   "Klimaks/topp-tegn", "Tidsstopp", "Svakt marked", "Annet"],
    "JaNei": ["Ja", "Nei"],
    "Watchstatus": ["Venter", "Nær pivot", "Kjøpt", "Droppet"],
    "Beslutning": ["Kjøp", "Følg", "Dropp"],
}
LISTE_KOL = {navn: get_column_letter(i + 1) for i, navn in enumerate(LISTER)}


def liste_ref(navn: str) -> str:
    k = LISTE_KOL[navn]
    return f"=Lister!${k}$2:${k}${len(LISTER[navn]) + 1}"


def oppsett_ark(ws, kolonner, *, frys="B2"):
    """Overskrifter, bredder, formater og formler for rad 2..RADER+1."""
    for i, (navn, bredde, fmt, formel, hjelp) in enumerate(kolonner, start=1):
        c = ws.cell(row=1, column=i, value=navn)
        c.fill, c.font = HODE_FILL, HODE_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = bredde
        for r in range(2, RADER + 2):
            cell = ws.cell(row=r, column=i)
            if fmt:
                cell.number_format = fmt
            cell.border = KANT
            if formel:
                cell.value = formel.replace("{r}", str(r))
                cell.fill = BEREGNET_FILL
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = frys
    ws.sheet_view.zoomScale = 110


def validering(ws, kolonne: str, liste: str):
    dv = DataValidation(type="list", formula1=liste_ref(liste), allow_blank=True)
    dv.error, dv.errorTitle = "Velg fra lista (redigeres i fanen Lister).", "Ugyldig verdi"
    ws.add_data_validation(dv)
    dv.add(f"{kolonne}2:{kolonne}{RADER + 1}")


def farge_pluss_minus(ws, kolonner):
    for k in kolonner:
        omr = f"{k}2:{k}{RADER + 1}"
        ws.conditional_formatting.add(
            omr, FormulaRule(formula=[f"AND(ISNUMBER({k}2),{k}2>0)"], fill=GRONN_FILL))
        ws.conditional_formatting.add(
            omr, FormulaRule(formula=[f"AND(ISNUMBER({k}2),{k}2<0)"], fill=ROD_FILL))


# ---------------------------------------------------------------------------
def lag_instruks(wb):
    ws = wb.active
    ws.title = "Instruks"
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 110
    linjer = [
        ("Tradingjournal – Minervini-stil", TITTEL_FONT),
        ("", None),
        ("Slik bruker du den", SEKSJON_FONT),
        ("1. Watchlist – legg inn kandidater fra screeneren: pivot, stop, mål, RS, TrendScore. "
         "Fyll inn «Kurs nå» for å se avstand til pivot (gul = nær pivot, grønn = over).", None),
        ("2. Forhåndsanalyse – før kjøp: svar Ja/Nei på sjekklista. Poeng og karakter regnes "
         "automatisk (A = kjøpbar, B = følg, C = vent).", None),
        ("3. Handler – én rad per handel. Fyll inn kjøp (dato, kurs, antall, stop, mål). "
         "Når du selger: fyll inn salgsdato, salgskurs og årsak. For åpne handler kan du "
         "fylle «Kurs nå» for å se urealisert resultat.", None),
        ("   Delsalg: del handelen i to rader (f.eks. 100 aksjer → 50 + 50) med hver sin salgskurs.", DIM_FONT),
        ("4. Statistikk – oppdateres av seg selv. Viser treffprosent, snitt gevinst mot tap, "
         "R-multippel og hva som funker per setup, RS-nivå, TrendScore, kriterier og marked.", None),
        ("", None),
        ("Regler for fargene", SEKSJON_FONT),
        ("Grå celler er formler – ikke skriv i dem. Hvite celler fyller du selv. "
         "Nedtrekkslistene redigeres i fanen «Lister».", None),
        ("", None),
        ("Minervinis tommelfingerregler (sammenlign med Statistikk)", SEKSJON_FONT),
        ("• Kutt tap tidlig: snittap bør ligge rundt 5–8 %, aldri over 10 %.", None),
        ("• Gevinst/tap-forhold ≥ 2–3 : 1. Da tjener du penger selv med 40–50 % treff.", None),
        ("• R-multippel = resultat delt på planlagt risiko. Snitt R over 0 = systemet tjener penger.", None),
        ("• Se etter mønstre: hvilke setup, RS-nivå og markedsforhold gir de beste handlene?", None),
        ("", None),
        ("Google Sheets", SEKSJON_FONT),
        ("Last opp fila i Google Drive → høyreklikk → Åpne med Google Regneark → "
         "Fil → Lagre som Google Regneark. Alle formler og nedtrekkslister følger med.", None),
        ("Eksempelradene (merket EKSEMPEL) kan slettes når du har sett hvordan det virker.", DIM_FONT),
    ]
    for i, (tekst, font) in enumerate(linjer, start=1):
        c = ws.cell(row=i, column=2, value=tekst)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if font:
            c.font = font
    ws.sheet_view.showGridLines = False


def lag_lister(wb):
    ws = wb.create_sheet("Lister")
    for navn, verdier in LISTER.items():
        k = LISTE_KOL[navn]
        c = ws[f"{k}1"]
        c.value, c.fill, c.font = navn, HODE_FILL, HODE_FONT
        ws.column_dimensions[k].width = 20
        for j, v in enumerate(verdier, start=2):
            ws[f"{k}{j}"] = v


def lag_watchlist(wb):
    ws = wb.create_sheet("Watchlist")
    kol = [
        ("Lagt til", 11, DATO, None, ""),
        ("Ticker", 11, None, None, ""),
        ("Børs", 11, None, None, ""),
        ("Setup", 17, None, None, ""),
        ("Pivot", 10, KR, None, ""),
        ("Stop", 10, KR, None, ""),
        ("Mål", 10, KR, None, ""),
        ("Stop %", 8, PST, '=IF(OR(E{r}="",F{r}=""),"",(E{r}-F{r})/E{r})', ""),
        ("R/R", 7, '0.0', '=IF(OR(E{r}="",F{r}="",G{r}="",E{r}<=F{r}),"",(G{r}-E{r})/(E{r}-F{r}))', ""),
        ("Kurs nå", 10, KR, None, ""),
        ("Til pivot", 9, PST, '=IF(OR(J{r}="",E{r}=""),"",J{r}/E{r}-1)', ""),
        ("RS", 6, '0', None, ""),
        ("Trend-Score", 8, '0', None, ""),
        ("Kriterier x/7", 9, '0', None, ""),
        ("Fund x/5", 8, '0', None, ""),
        ("Katalysator / notat", 40, None, None, ""),
        ("Status", 12, None, None, ""),
    ]
    oppsett_ark(ws, kol, frys="C2")
    validering(ws, "C", "Børs")
    validering(ws, "D", "Setup")
    validering(ws, "Q", "Watchstatus")
    s = f"2:{RADER + 1}"
    ws.conditional_formatting.add(f"K{s.replace(':', ':K')}", FormulaRule(
        formula=["AND(ISNUMBER(K2),K2>=-0.03,K2<0)"], fill=GUL_FILL))
    ws.conditional_formatting.add(f"K{s.replace(':', ':K')}", FormulaRule(
        formula=["AND(ISNUMBER(K2),K2>=0)"], fill=GRONN_FILL))
    ws.conditional_formatting.add(f"H{s.replace(':', ':H')}", FormulaRule(
        formula=["AND(ISNUMBER(H2),H2>0.08)"], fill=ROD_FILL))
    ws.conditional_formatting.add(f"I{s.replace(':', ':I')}", FormulaRule(
        formula=["AND(ISNUMBER(I2),I2>=3)"], fill=GRONN_FILL))
    eks = [
        ("2026-11-03", "EKSEMPEL1", "Oslo Børs", "VCP-brudd", 152.4, 142.0, 185.0, 150.1, 94, 81, 7, 4,
         "Q3: salg +32 %, akselererende. Tredje kontraksjon 6 %.", "Nær pivot"),
        ("2026-11-05", "EKSEMPEL2", "S&P 500", "Pivot-brudd", 88.0, 82.5, 105.0, 79.0, 78, 62, 6, 3,
         "Venter på at volumet tørker inn.", "Venter"),
    ]
    for i, e in enumerate(eks, start=2):
        dato, tk, b, st_, piv, stp, mal, kurs, rs, ts, kr_, fu, notat, status = e
        ws[f"A{i}"] = _dato(dato); ws[f"B{i}"] = tk; ws[f"C{i}"] = b; ws[f"D{i}"] = st_
        ws[f"E{i}"] = piv; ws[f"F{i}"] = stp; ws[f"G{i}"] = mal; ws[f"J{i}"] = kurs
        ws[f"L{i}"] = rs; ws[f"M{i}"] = ts; ws[f"N{i}"] = kr_; ws[f"O{i}"] = fu
        ws[f"P{i}"] = notat; ws[f"Q{i}"] = status


SJEKK = ["Trend template 7/7", "RS ≥ 70", "RS-linje stiger", "VCP / stram base",
         "Volum tørker inn", "Salg Q ≥ 25 %", "Resultat Q ≥ 25 %", "Vekst akselererer",
         "Marked i opptrend", "Sterk sektor"]


def lag_forhandsanalyse(wb):
    ws = wb.create_sheet("Forhåndsanalyse")
    forste = get_column_letter(4)
    siste = get_column_letter(3 + len(SJEKK))
    p_kol = get_column_letter(4 + len(SJEKK))
    kol = [("Dato", 11, DATO, None, ""), ("Ticker", 11, None, None, ""),
           ("Setup", 17, None, None, "")]
    kol += [(s, 10, None, None, "") for s in SJEKK]
    kol += [
        ("Poeng", 7, '0', f'=IF(B{{r}}="","",COUNTIF({forste}{{r}}:{siste}{{r}},"Ja"))', ""),
        ("Karakter", 12, None,
         f'=IF(B{{r}}="","",IF({p_kol}{{r}}>=8,"A – kjøpbar",IF({p_kol}{{r}}>=6,"B – følg","C – vent")))', ""),
        ("Pivot", 10, KR, None, ""),
        ("Stop", 10, KR, None, ""),
        ("Stop %", 8, PST, None, ""),
        ("Beslutning", 11, None, None, ""),
        ("Notat", 44, None, None, ""),
    ]
    oppsett_ark(ws, kol, frys="C2")
    k_kol = get_column_letter(5 + len(SJEKK))
    piv, stp, stp_pct = (get_column_letter(6 + len(SJEKK) + j) for j in range(3))
    for r in range(2, RADER + 2):
        ws[f"{stp_pct}{r}"] = f'=IF(OR({piv}{r}="",{stp}{r}=""),"",({piv}{r}-{stp}{r})/{piv}{r})'
        ws[f"{stp_pct}{r}"].fill = BEREGNET_FILL
    validering(ws, "C", "Setup")
    for j in range(len(SJEKK)):
        validering(ws, get_column_letter(4 + j), "JaNei")
    validering(ws, get_column_letter(9 + len(SJEKK)), "Beslutning")
    omr = f"{forste}2:{siste}{RADER + 1}"
    ws.conditional_formatting.add(omr, FormulaRule(formula=[f'{forste}2="Ja"'], fill=GRONN_FILL))
    ws.conditional_formatting.add(omr, FormulaRule(formula=[f'{forste}2="Nei"'], fill=ROD_FILL))
    ko = f"{k_kol}2:{k_kol}{RADER + 1}"
    ws.conditional_formatting.add(ko, FormulaRule(formula=[f'LEFT({k_kol}2,1)="A"'], fill=GRONN_FILL))
    ws.conditional_formatting.add(ko, FormulaRule(formula=[f'LEFT({k_kol}2,1)="B"'], fill=GUL_FILL))
    ws.conditional_formatting.add(ko, FormulaRule(formula=[f'LEFT({k_kol}2,1)="C"'], fill=ROD_FILL))
    ws.row_dimensions[1].height = 46
    svar = ["Ja", "Ja", "Ja", "Ja", "Nei", "Ja", "Ja", "Ja", "Ja", "Nei"]
    ws["A2"] = _dato("2026-11-04"); ws["B2"] = "EKSEMPEL1"; ws["C2"] = "VCP-brudd"
    for j, s in enumerate(svar):
        ws.cell(row=2, column=4 + j, value=s)
    ws[f"{piv}2"] = 152.4; ws[f"{stp}2"] = 142.0
    ws[f"{get_column_letter(9 + len(SJEKK))}2"] = "Kjøp"
    ws[f"{get_column_letter(10 + len(SJEKK))}2"] = "Kjøp ved brudd på 1,5× volum."


# Kolonner i Handler (bokstav brukes i Statistikk).
H = dict(tk="A", bors="B", setup="C", kdato="D", kkurs="E", antall="F", stop="G", mal="H",
         pos="I", risiko="J", stoppct="K", rr="L", rs="M", ts="N", krit="O", marked="P",
         begr="Q", sdato="R", skurs="S", sarsak="T", naa="U", status="V", res="W",
         respct="X", r="Y", dager="Z", plan="AA", laerdom="AB")


def lag_handler(wb):
    ws = wb.create_sheet("Handler")
    kol = [
        ("Ticker", 11, None, None, ""),
        ("Børs", 11, None, None, ""),
        ("Setup", 17, None, None, ""),
        ("Kjøps-dato", 11, DATO, None, ""),
        ("Kjøps-kurs", 10, KR, None, ""),
        ("Antall", 8, '#,##0', None, ""),
        ("Initial stop", 10, KR, None, ""),
        ("Mål", 10, KR, None, ""),
        ("Posisjon", 11, KR0, '=IF(OR(E{r}="",F{r}=""),"",E{r}*F{r})', ""),
        ("Risiko kr", 10, KR0, '=IF(OR(E{r}="",F{r}="",G{r}=""),"",(E{r}-G{r})*F{r})', ""),
        ("Stop %", 8, PST, '=IF(OR(E{r}="",G{r}=""),"",(E{r}-G{r})/E{r})', ""),
        ("Plan R/R", 8, '0.0', '=IF(OR(E{r}="",G{r}="",H{r}="",E{r}<=G{r}),"",(H{r}-E{r})/(E{r}-G{r}))', ""),
        ("RS ved kjøp", 7, '0', None, ""),
        ("Trend-Score", 7, '0', None, ""),
        ("Kriterier x/7", 8, '0', None, ""),
        ("Marked", 11, None, None, ""),
        ("Begrunnelse", 36, None, None, ""),
        ("Salgs-dato", 11, DATO, None, ""),
        ("Salgs-kurs", 10, KR, None, ""),
        ("Salgsårsak", 15, None, None, ""),
        ("Kurs nå (åpne)", 10, KR, None, ""),
        ("Status", 8, None, '=IF(A{r}="","",IF(S{r}<>"","Lukket","Åpen"))', ""),
        ("Resultat kr", 11, KR0,
         '=IF(OR(A{r}="",E{r}="",F{r}=""),"",IF(S{r}<>"",(S{r}-E{r})*F{r},IF(U{r}<>"",(U{r}-E{r})*F{r},"")))', ""),
        ("Resultat %", 9, PST, '=IF(OR(W{r}="",I{r}="",I{r}=0),"",W{r}/I{r})', ""),
        ("R-multippel", 9, R_FMT, '=IF(OR(W{r}="",J{r}="",J{r}<=0),"",W{r}/J{r})', ""),
        ("Dager", 7, '0', '=IF(OR(A{r}="",D{r}=""),"",IF(R{r}<>"",R{r},TODAY())-D{r})', ""),
        ("Fulgte planen?", 9, None, None, ""),
        ("Lærdom", 40, None, None, ""),
    ]
    oppsett_ark(ws, kol, frys="B2")
    validering(ws, "B", "Børs")
    validering(ws, "C", "Setup")
    validering(ws, "P", "Marked")
    validering(ws, "T", "Salgsårsak")
    validering(ws, "AA", "JaNei")
    farge_pluss_minus(ws, ["W", "X", "Y"])
    ws.conditional_formatting.add(f"K2:K{RADER + 1}", FormulaRule(
        formula=["AND(ISNUMBER(K2),K2>0.08)"], fill=ROD_FILL))
    ws.conditional_formatting.add(f"V2:V{RADER + 1}", FormulaRule(
        formula=['V2="Åpen"'], fill=GUL_FILL))
    ws.row_dimensions[1].height = 40
    eks = [
        ("EKSEMPEL1", "Oslo Børs", "VCP-brudd", "2026-09-02", 100.0, 200, 93.0, 125.0, 92, 84, 7,
         "Opptrend", "Brudd på 2,1× volum", "2026-10-14", 121.5, "Trailing stop", None, "Ja",
         "Holdt gjennom første test av MA50 – riktig."),
        ("EKSEMPEL2", "Oslo Børs", "Pivot-brudd", "2026-09-20", 50.0, 400, 47.0, 60.0, 74, 55, 6,
         "Under press", "Litt tidlig, svakt volum", "2026-09-29", 47.0, "Stop truffet", None, "Ja",
         "Svakt marked + lavt volum = vent neste gang."),
        ("EKSEMPEL3", "S&P 500", "Høy stram flagg", "2026-10-25", 210.0, 50, 196.0, 250.0, 96, 88, 7,
         "Opptrend", "Høy stram flagg etter +110 %", None, None, None, 223.0, "", ""),
    ]
    for i, e in enumerate(eks, start=2):
        (tk, b, setup, kd, kk, ant, stp, mal, rs, ts, kr_, mk, begr, sd, sk, sa, naa, plan, laer) = e
        ws[f"A{i}"] = tk; ws[f"B{i}"] = b; ws[f"C{i}"] = setup; ws[f"D{i}"] = _dato(kd)
        ws[f"E{i}"] = kk; ws[f"F{i}"] = ant; ws[f"G{i}"] = stp; ws[f"H{i}"] = mal
        ws[f"M{i}"] = rs; ws[f"N{i}"] = ts; ws[f"O{i}"] = kr_; ws[f"P{i}"] = mk; ws[f"Q{i}"] = begr
        if sd:
            ws[f"R{i}"] = _dato(sd); ws[f"S{i}"] = sk; ws[f"T{i}"] = sa
        if naa:
            ws[f"U{i}"] = naa
        if plan:
            ws[f"AA{i}"] = plan
        if laer:
            ws[f"AB{i}"] = laer


def rng(k: str) -> str:
    return f"Handler!${k}$2:${k}${RADER + 1}"


def lag_statistikk(wb):
    ws = wb.create_sheet("Statistikk")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 34
    ws.column_dimensions["E"].width = 3
    for k, b in zip("FGHIJ", (22, 9, 9, 12, 9)):
        ws.column_dimensions[k].width = b

    V, W, X, Y, Z, J = (rng(H[n]) for n in ("status", "res", "respct", "r", "dager", "risiko"))
    L = f'{V},"Lukket"'

    ws["B1"] = "Statistikk"; ws["B1"].font = TITTEL_FONT
    ws["B2"] = "Oppdateres automatisk fra fanen Handler. Kun lukkede handler teller (unntatt «Åpne»)."
    ws["B2"].font = DIM_FONT

    nokkel = [
        ("Resultat", None, None, None),
        ("Lukkede handler", f"=COUNTIFS({L})", '0', ""),
        ("Vinnere", f'=COUNTIFS({L},{W},">0")', '0', ""),
        ("Tapere", f'=COUNTIFS({L},{W},"<0")', '0', ""),
        ("Treffprosent", "=IFERROR(C5/C4,\"\")", PST, "40–50 % er helt fint med god gevinst/tap"),
        ("Totalt realisert", f"=SUMIFS({W},{L})", KR0, ""),
        ("Snittgevinst", f'=IFERROR(AVERAGEIFS({W},{L},{W},">0"),"")', KR0, ""),
        ("Snittap", f'=IFERROR(AVERAGEIFS({W},{L},{W},"<0"),"")', KR0, ""),
        ("Gevinst/tap-forhold", '=IFERROR(-C9/C10,"")', '0.00" : 1"', "Minervini: ≥ 2–3 : 1"),
        ("Snitt gevinst %", f'=IFERROR(AVERAGEIFS({X},{L},{X},">0"),"")', PST, ""),
        ("Snitt tap %", f'=IFERROR(AVERAGEIFS({X},{L},{X},"<0"),"")', PST, "Bør ligge rundt −5 til −8 %"),
        ("Snitt R-multippel", f'=IFERROR(AVERAGEIFS({Y},{L}),"")', R_FMT, "Over 0 = systemet tjener penger"),
        ("Forventning per handel", '=IFERROR(C7*C9+(1-C7)*C10,"")', KR0, "treff × snittgevinst + (1−treff) × snittap"),
        ("Største gevinst", f'=IFERROR(MAXIFS({W},{V},"Lukket"),"")', KR0, ""),
        ("Største tap", f'=IFERROR(MINIFS({W},{V},"Lukket"),"")', KR0, ""),
        ("Snitt dager – vinnere", f'=IFERROR(AVERAGEIFS({Z},{L},{W},">0"),"")', '0', "Vinnere bør holdes lenger"),
        ("Snitt dager – tapere", f'=IFERROR(AVERAGEIFS({Z},{L},{W},"<0"),"")', '0', "… enn tapere"),
        ("", None, None, None),
        ("Åpne posisjoner", None, None, None),
        ("Antall åpne", f'=COUNTIF({V},"Åpen")', '0', ""),
        ("Åpen risiko (til stop)", f'=SUMIFS({J},{V},"Åpen")', KR0, "Hva du taper om alle stopper ut"),
        ("Urealisert resultat", f'=SUMIFS({W},{V},"Åpen")', KR0, "Krever «Kurs nå» i Handler"),
    ]
    rad = 3
    for navn, formel, fmt, hint in nokkel:
        if formel is None:
            if navn:
                ws[f"B{rad}"] = navn; ws[f"B{rad}"].font = SEKSJON_FONT
            rad += 1
            continue
        ws[f"B{rad}"] = navn
        c = ws[f"C{rad}"]; c.value = formel; c.number_format = fmt
        c.font = Font(bold=True); c.alignment = Alignment(horizontal="right")
        ws[f"D{rad}"] = hint; ws[f"D{rad}"].font = DIM_FONT
        for k in "BCD":
            ws[f"{k}{rad}"].border = KANT
        rad += 1
    # Farge på nøkkeltall.
    for celle in ("C8", "C14", "C15", "C24"):
        ws.conditional_formatting.add(celle, FormulaRule(formula=[f"AND(ISNUMBER({celle}),{celle}>0)"], fill=GRONN_FILL))
        ws.conditional_formatting.add(celle, FormulaRule(formula=[f"AND(ISNUMBER({celle}),{celle}<0)"], fill=ROD_FILL))
    ws.conditional_formatting.add("C11", FormulaRule(formula=["AND(ISNUMBER(C11),C11>=2)"], fill=GRONN_FILL))
    ws.conditional_formatting.add("C11", FormulaRule(formula=["AND(ISNUMBER(C11),C11<1.5)"], fill=ROD_FILL))
    ws.conditional_formatting.add("C13", FormulaRule(formula=["AND(ISNUMBER(C13),C13<-0.1)"], fill=ROD_FILL))

    # --- Hva funker? Grupperte tabeller til høyre ------------------------------
    C_, M_, N_, O_, P_, AA_ = (rng(H[n]) for n in ("setup", "rs", "ts", "krit", "marked", "plan"))
    grupper = [
        ("Per setup", [(f"=Lister!$A${i + 2}", [f"{C_},Lister!$A${i + 2}"])
                       for i in range(len(LISTER["Setup"]))]),
        ("Per RS ved kjøp", [("90–99", [f'{M_},">=90"']),
                             ("80–89", [f'{M_},">=80"', f'{M_},"<90"']),
                             ("70–79", [f'{M_},">=70"', f'{M_},"<80"']),
                             ("Under 70", [f'{M_},"<70"'])]),
        ("Per TrendScore ved kjøp", [("70+", [f'{N_},">=70"']),
                                     ("40–69", [f'{N_},">=40"', f'{N_},"<70"']),
                                     ("Under 40", [f'{N_},"<40"'])]),
        ("Per kriterier", [("7/7", [f'{O_},7']), ("6/7", [f'{O_},6']), ("5 eller færre", [f'{O_},"<=5"'])]),
        ("Per marked", [(m, [f'{P_},"{m}"']) for m in LISTER["Marked"]]),
        ("Fulgte planen?", [("Ja", [f'{AA_},"Ja"']), ("Nei", [f'{AA_},"Nei"'])]),
    ]
    ws["F1"] = "Hva funker?"; ws["F1"].font = TITTEL_FONT
    ws["F2"] = "Lukkede handler gruppert. Se etter grupper med høy treff% og positiv snitt R."
    ws["F2"].font = DIM_FONT
    rad = 3
    for tittel, rader in grupper:
        for k, t in zip("FGHIJ", (tittel, "Antall", "Treff %", "Sum kr", "Snitt R")):
            c = ws[f"{k}{rad}"]; c.value = t; c.fill = HODE_FILL; c.font = HODE_FONT
            c.alignment = Alignment(horizontal="left" if k == "F" else "right")
        rad += 1
        for etikett, krit in rader:
            kr = ",".join(krit)
            ws[f"F{rad}"] = etikett
            ws[f"G{rad}"] = f"=COUNTIFS({L},{kr})"
            ws[f"H{rad}"] = f'=IFERROR(COUNTIFS({L},{W},">0",{kr})/G{rad},"")'
            ws[f"I{rad}"] = f"=SUMIFS({W},{L},{kr})"
            ws[f"J{rad}"] = f'=IFERROR(AVERAGEIFS({Y},{L},{kr}),"")'
            ws[f"G{rad}"].number_format = '0'
            ws[f"H{rad}"].number_format = PST
            ws[f"I{rad}"].number_format = KR0
            ws[f"J{rad}"].number_format = R_FMT
            for k in "FGHIJ":
                ws[f"{k}{rad}"].border = KANT
            for k in "IJ":
                ws.conditional_formatting.add(f"{k}{rad}", FormulaRule(
                    formula=[f"AND(ISNUMBER({k}{rad}),{k}{rad}>0)"], fill=GRONN_FILL))
                ws.conditional_formatting.add(f"{k}{rad}", FormulaRule(
                    formula=[f"AND(ISNUMBER({k}{rad}),{k}{rad}<0)"], fill=ROD_FILL))
            rad += 1
        rad += 1
    ws.freeze_panes = "A3"


def _dato(iso: str):
    from datetime import date
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d)


def main():
    wb = Workbook()
    lag_instruks(wb)
    lag_watchlist(wb)
    lag_forhandsanalyse(wb)
    lag_handler(wb)
    lag_statistikk(wb)
    lag_lister(wb)
    UT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(UT)
    print(f"Lagret: {UT}")


if __name__ == "__main__":
    main()
