"""
lag_journal_v2.py – genererer Tradingjournal.xlsx (Minervini-stil), versjon 2.

Kjør:  python verktoy/lag_journal_v2.py   →  journal/Tradingjournal.xlsx

Flyt: ANALYSE først → HANDEL koblet til analysen (via Analyse-ID) → UKE/MÅNED-
oppsummering med læringsnotater → STATISTIKK (hva funker).

Fungerer i Excel og Google Sheets (bare vanlige formler: COUNTIFS, SUMIFS,
AVERAGEIFS, INDEX/MATCH, ISOWEEKNUM, EDATE – ingen makroer/tabeller).

Faner:
  Instruks          – bruksanvisning
  Analyse           – datert analyse per ticker, liste (Watchlist/High alert/Parkert/…),
                      plan (pivot/stop/mål), sjekkliste → poeng/karakter, kobling til handler
  Handler           – velg Analyse-ID → ticker, setup, RS, TS, karakter hentes automatisk
  Ukeoppsummering   – én rad per uke: tall regnes ut, du skriver læringsnotat
  Månedsoppsummering– én rad per måned: tall + læringsnotat
  Statistikk        – treff%, R, gevinst/tap og «hva funker» (setup, karakter, RS, TS, marked, plan)
  Lister            – nedtrekksverdier (kan redigeres)
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

RADER = 500
UT = Path(__file__).resolve().parent.parent / "journal" / "Tradingjournal.xlsx"
SLUTT = RADER + 1

# --- Stil -------------------------------------------------------------------
GRONN_MORK = "2E5E4E"
HODE_FILL = PatternFill("solid", fgColor=GRONN_MORK)
HODE_FONT = Font(bold=True, color="FFFFFF", size=10)
NOTAT_HODE_FILL = PatternFill("solid", fgColor="5B6B8C")
BEREGNET_FILL = PatternFill("solid", fgColor="F3F6F4")
SEKSJON_FONT = Font(bold=True, size=12, color=GRONN_MORK)
TITTEL_FONT = Font(bold=True, size=16, color=GRONN_MORK)
DIM_FONT = Font(size=9, color="6B7280", italic=True)
ID_FONT = Font(size=9, color="6B7280")
TYNN = Side(style="thin", color="D9E2DC")
KANT = Border(bottom=TYNN)
GRONN_FILL = PatternFill("solid", fgColor="D7F0E3")
ROD_FILL = PatternFill("solid", fgColor="F8D9D9")
GUL_FILL = PatternFill("solid", fgColor="FFF3C4")
ORANSJE_FILL = PatternFill("solid", fgColor="FFD8B0")
BLA_FILL = PatternFill("solid", fgColor="DCE8F8")
GRA_FILL = PatternFill("solid", fgColor="E5E7EB")
DENNE_FILL = PatternFill("solid", fgColor="EAF2FF")

DATO = "DD.MM.YYYY"
KR = '#,##0.00;[Red]-#,##0.00'
KR0 = '#,##0;[Red]-#,##0'
PST = '0.0%;[Red]-0.0%'
R_FMT = '0.00"R";[Red]-0.00"R"'

LISTER = {
    "Liste": ["Watchlist", "High alert", "Parkert", "Kjøpt", "Droppet"],
    "Setup": ["VCP-brudd", "Pivot-brudd", "Pullback til MA50", "Høy stram flagg",
              "Golden cross", "IPO-base", "Annet"],
    "Børs": ["Oslo Børs", "S&P 500", "Annen"],
    "Marked": ["Opptrend", "Under press", "Nedtrend"],
    "Salgsårsak": ["Stop truffet", "Mål nådd", "Trailing stop", "Brøt MA50",
                   "Klimaks/topp-tegn", "Tidsstopp", "Svakt marked", "Annet"],
    "JaNei": ["Ja", "Nei"],
}
LISTE_KOL = {navn: get_column_letter(i + 1) for i, navn in enumerate(LISTER)}

SJEKK = ["Trend template 7/7", "RS ≥ 70", "RS-linje stiger", "VCP / stram base",
         "Volum tørker inn", "Salg Q ≥ 25 %", "Resultat Q ≥ 25 %", "Vekst akselererer",
         "Marked i opptrend", "Sterk sektor"]


def uke_nokkel(c: str) -> str:
    """ISO-uke som tall ÅÅÅÅUU fra en datocelle (f.eks. 202645). Uten TEXT() – språknøytral."""
    return f"YEAR({c}-WEEKDAY({c},2)+4)*100+ISOWEEKNUM({c})"


def mnd_nokkel(c: str) -> str:
    return f"YEAR({c})*100+MONTH({c})"


def liste_ref(navn: str) -> str:
    k = LISTE_KOL[navn]
    return f"=Lister!${k}$2:${k}${len(LISTER[navn]) + 1}"


def oppsett_ark(ws, kolonner, *, frys="B2", rader=RADER, notat_fra: int | None = None):
    """Overskrifter, bredder, formater og formler. kolonner = (navn, bredde, fmt, formel)."""
    for i, (navn, bredde, fmt, formel) in enumerate(kolonner, start=1):
        c = ws.cell(row=1, column=i, value=navn)
        c.fill = NOTAT_HODE_FILL if notat_fra and i >= notat_fra else HODE_FILL
        c.font = HODE_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = bredde
        for r in range(2, rader + 2):
            cell = ws.cell(row=r, column=i)
            if fmt:
                cell.number_format = fmt
            cell.border = KANT
            if formel:
                cell.value = formel.replace("{r}", str(r))
                cell.fill = BEREGNET_FILL
            if notat_fra and i >= notat_fra:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[1].height = 40
    ws.freeze_panes = frys
    ws.sheet_view.zoomScale = 110


def validering(ws, kolonne: str, formel: str, rader=RADER):
    dv = DataValidation(type="list", formula1=formel, allow_blank=True)
    dv.error, dv.errorTitle = "Velg fra lista.", "Ugyldig verdi"
    ws.add_data_validation(dv)
    dv.add(f"{kolonne}2:{kolonne}{rader + 1}")


def cf(ws, omr, formel, fill):
    ws.conditional_formatting.add(omr, FormulaRule(formula=[formel], fill=fill))


def pluss_minus(ws, k, rader=RADER):
    omr = f"{k}2:{k}{rader + 1}"
    cf(ws, omr, f"AND(ISNUMBER({k}2),{k}2>0)", GRONN_FILL)
    cf(ws, omr, f"AND(ISNUMBER({k}2),{k}2<0)", ROD_FILL)


def _d(iso: str) -> date:
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d)


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------
# A ID · B Dato · C Ticker · D Børs · E Setup · F Liste · G Pivot · H Stop · I Mål ·
# J Stop% · K R/R · L Kurs nå · M Til pivot · N RS · O TS · P Krit · Q Fund · R Marked ·
# S..AB sjekkliste · AC Poeng · AD Karakter · AE Tese · AF Handler · AG Resultat ·
# AH Uke-nøkkel · AI Måned-nøkkel
SJ_FRA = 19                                   # kolonne S
SJ_TIL = SJ_FRA + len(SJEKK) - 1              # kolonne AB
A_POENG = get_column_letter(SJ_TIL + 1)       # AC
A_KAR = get_column_letter(SJ_TIL + 2)         # AD
A_TESE = get_column_letter(SJ_TIL + 3)        # AE
A_ANT = get_column_letter(SJ_TIL + 4)         # AF
A_RES = get_column_letter(SJ_TIL + 5)         # AG
A_UKE = get_column_letter(SJ_TIL + 6)         # AH
A_MND = get_column_letter(SJ_TIL + 7)         # AI


def lag_analyse(wb):
    ws = wb.create_sheet("Analyse")
    sf, st_ = get_column_letter(SJ_FRA), get_column_letter(SJ_TIL)
    kol = [
        ("ID", 7, None, None),
        ("Dato", 11, DATO, None),
        ("Ticker", 11, None, None),
        ("Børs", 11, None, None),
        ("Setup", 16, None, None),
        ("Liste", 12, None, None),
        ("Pivot", 10, KR, None),
        ("Stop", 10, KR, None),
        ("Mål", 10, KR, None),
        ("Stop %", 8, PST, '=IF(OR(G{r}="",H{r}=""),"",(G{r}-H{r})/G{r})'),
        ("R/R", 7, '0.0', '=IF(OR(G{r}="",H{r}="",I{r}="",G{r}<=H{r}),"",(I{r}-G{r})/(G{r}-H{r}))'),
        ("Kurs nå", 10, KR, None),
        ("Til pivot", 9, PST, '=IF(OR(L{r}="",G{r}=""),"",L{r}/G{r}-1)'),
        ("RS", 6, '0', None),
        ("Trend-Score", 7, '0', None),
        ("Kriterier x/7", 8, '0', None),
        ("Fund x/5", 7, '0', None),
        ("Marked", 11, None, None),
    ]
    kol += [(s, 9, None, None) for s in SJEKK]
    kol += [
        ("Poeng", 7, '0', f'=IF(C{{r}}="","",COUNTIF({sf}{{r}}:{st_}{{r}},"Ja"))'),
        ("Karakter", 8, None,
         f'=IF(C{{r}}="","",IF({A_POENG}{{r}}>=8,"A",IF({A_POENG}{{r}}>=6,"B","C")))'),
        ("Tese / plan / notat", 46, None, None),
        ("Handler", 8, '0', f'=IF(C{{r}}="","",COUNTIF(Handler!$A$2:$A${SLUTT},A{{r}}))'),
        ("Resultat kr", 11, KR0,
         f'=IF(OR(C{{r}}="",{A_ANT}{{r}}=0),"",SUMIFS(Handler!$X$2:$X${SLUTT},Handler!$A$2:$A${SLUTT},A{{r}}))'),
        ("Uke", 8, '0', f'=IF(B{{r}}="","",{uke_nokkel("B{r}")})'),
        ("Måned", 8, '0', f'=IF(B{{r}}="","",{mnd_nokkel("B{r}")})'),
    ]
    oppsett_ark(ws, kol, frys="D2")
    # Faste ID-er (verdier, ikke formler) – tåler sortering, så koblingen holder.
    for r in range(2, SLUTT + 1):
        c = ws[f"A{r}"]
        c.value = f"A{r - 1:03d}"
        c.font = ID_FONT
        c.fill = BEREGNET_FILL
    validering(ws, "D", liste_ref("Børs"))
    validering(ws, "E", liste_ref("Setup"))
    validering(ws, "F", liste_ref("Liste"))
    validering(ws, "R", liste_ref("Marked"))
    for j in range(len(SJEKK)):
        validering(ws, get_column_letter(SJ_FRA + j), liste_ref("JaNei"))

    # Farger
    f_omr = f"F2:F{SLUTT}"
    cf(ws, f_omr, 'F2="High alert"', ORANSJE_FILL)
    cf(ws, f_omr, 'F2="Watchlist"', BLA_FILL)
    cf(ws, f_omr, 'F2="Kjøpt"', GRONN_FILL)
    cf(ws, f_omr, 'OR(F2="Parkert",F2="Droppet")', GRA_FILL)
    cf(ws, f"M2:M{SLUTT}", "AND(ISNUMBER(M2),M2>=0)", GRONN_FILL)
    cf(ws, f"M2:M{SLUTT}", "AND(ISNUMBER(M2),M2>=-0.03,M2<0)", GUL_FILL)
    cf(ws, f"J2:J{SLUTT}", "AND(ISNUMBER(J2),J2>0.08)", ROD_FILL)
    cf(ws, f"K2:K{SLUTT}", "AND(ISNUMBER(K2),K2>=3)", GRONN_FILL)
    sj = f"{sf}2:{st_}{SLUTT}"
    cf(ws, sj, f'{sf}2="Ja"', GRONN_FILL)
    cf(ws, sj, f'{sf}2="Nei"', ROD_FILL)
    k = f"{A_KAR}2:{A_KAR}{SLUTT}"
    cf(ws, k, f'{A_KAR}2="A"', GRONN_FILL)
    cf(ws, k, f'{A_KAR}2="B"', GUL_FILL)
    cf(ws, k, f'{A_KAR}2="C"', ROD_FILL)
    pluss_minus(ws, A_RES)
    ws.row_dimensions[1].height = 50

    eks = [
        ("2026-11-02", "EKSEMPEL1", "Oslo Børs", "VCP-brudd", "Kjøpt", 100.0, 93.0, 125.0, None,
         92, 84, 7, 4, "Opptrend", "JJJJJJJJJN",
         "3 kontraksjoner 18-9-5 %. Salg +32 % akselererende. Kjøp ved brudd på 1,5× volum."),
        ("2026-11-03", "EKSEMPEL2", "Oslo Børs", "Pivot-brudd", "Kjøpt", 50.0, 47.0, 60.0, None,
         74, 55, 6, 2, "Under press", "JJNJNJNNNN", "Svakere case – liten posisjon."),
        ("2026-11-04", "EKSEMPEL3", "S&P 500", "Høy stram flagg", "High alert", 210.0, 196.0, 250.0,
         207.5, 96, 88, 7, 5, "Opptrend", "JJJJJJJJJJ", "Ligger 1 % under pivot. Alarm satt."),
        ("2026-11-05", "EKSEMPEL4", "S&P 500", "Pullback til MA50", "Watchlist", 88.0, 82.5, 105.0,
         79.0, 78, 62, 6, 3, "Opptrend", "JJJNNJJNJN", "Vent på stram base."),
        ("2026-11-06", "EKSEMPEL5", "Oslo Børs", "Annet", "Parkert", None, None, None, None,
         61, 35, 4, 1, "Opptrend", "NNNNNNNNJN", "For svak RS. Se igjen om 1 mnd."),
    ]
    for i, e in enumerate(eks, start=2):
        (dt, tk, b, setup, liste, piv, stp, mal, naa, rs, ts, kr_, fu, mk, svar, tese) = e
        ws[f"B{i}"] = _d(dt); ws[f"C{i}"] = tk; ws[f"D{i}"] = b; ws[f"E{i}"] = setup
        ws[f"F{i}"] = liste
        for col, v in (("G", piv), ("H", stp), ("I", mal), ("L", naa)):
            if v is not None:
                ws[f"{col}{i}"] = v
        ws[f"N{i}"] = rs; ws[f"O{i}"] = ts; ws[f"P{i}"] = kr_; ws[f"Q{i}"] = fu; ws[f"R{i}"] = mk
        for j, s in enumerate(svar):
            ws.cell(row=i, column=SJ_FRA + j, value="Ja" if s == "J" else "Nei")
        ws[f"{A_TESE}{i}"] = tese


# ---------------------------------------------------------------------------
# Handler (koblet til Analyse)
# ---------------------------------------------------------------------------
H = dict(id="A", tk="B", bors="C", setup="D", kdato="E", kkurs="F", antall="G", stop="H",
         mal="I", pos="J", risiko="K", stoppct="L", rr="M", rs="N", ts="O", krit="P",
         marked="Q", kar="R", sdato="S", skurs="T", sarsak="U", naa="V", status="W",
         res="X", respct="Y", r="Z", dager="AA", plan="AB", laerdom="AC",
         suke="AD", smnd="AE", kuke="AF", kmnd="AG")


def oppslag(analyse_kol: str) -> str:
    """Henter en verdi fra Analyse-raden med samme ID (tom hvis ID mangler)."""
    idx = f"INDEX(Analyse!${analyse_kol}$2:${analyse_kol}${SLUTT},MATCH($A{{r}},Analyse!$A$2:$A${SLUTT},0))"
    return f'=IF($A{{r}}="","",IFERROR(IF({idx}="","",{idx}),""))'


def lag_handler(wb):
    ws = wb.create_sheet("Handler")
    kol = [
        ("Analyse-ID", 9, None, None),
        ("Ticker", 11, None, oppslag("C")),
        ("Børs", 10, None, oppslag("D")),
        ("Setup", 15, None, oppslag("E")),
        ("Kjøps-dato", 11, DATO, None),
        ("Kjøps-kurs", 10, KR, None),
        ("Antall", 8, '#,##0', None),
        ("Initial stop", 10, KR, None),
        ("Mål", 10, KR, None),
        ("Posisjon", 11, KR0, '=IF(OR(F{r}="",G{r}=""),"",F{r}*G{r})'),
        ("Risiko kr", 10, KR0, '=IF(OR(F{r}="",G{r}="",H{r}=""),"",(F{r}-H{r})*G{r})'),
        ("Stop %", 8, PST, '=IF(OR(F{r}="",H{r}=""),"",(F{r}-H{r})/F{r})'),
        ("Plan R/R", 8, '0.0', '=IF(OR(F{r}="",H{r}="",I{r}="",F{r}<=H{r}),"",(I{r}-F{r})/(F{r}-H{r}))'),
        ("RS", 6, '0', oppslag("N")),
        ("Trend-Score", 7, '0', oppslag("O")),
        ("Kriterier x/7", 8, '0', oppslag("P")),
        ("Marked", 11, None, oppslag("R")),
        ("Analyse-karakter", 9, None, oppslag(A_KAR)),
        ("Salgs-dato", 11, DATO, None),
        ("Salgs-kurs", 10, KR, None),
        ("Salgsårsak", 15, None, None),
        ("Kurs nå (åpne)", 10, KR, None),
        ("Status", 8, None, '=IF(E{r}="","",IF(T{r}<>"","Lukket","Åpen"))'),
        ("Resultat kr", 11, KR0,
         '=IF(OR(E{r}="",F{r}="",G{r}=""),"",IF(T{r}<>"",(T{r}-F{r})*G{r},IF(V{r}<>"",(V{r}-F{r})*G{r},"")))'),
        ("Resultat %", 9, PST, '=IF(OR(X{r}="",J{r}="",J{r}=0),"",X{r}/J{r})'),
        ("R-multippel", 9, R_FMT, '=IF(OR(X{r}="",K{r}="",K{r}<=0),"",X{r}/K{r})'),
        ("Dager", 7, '0', '=IF(E{r}="","",IF(S{r}<>"",S{r},TODAY())-E{r})'),
        ("Fulgte planen?", 9, None, None),
        ("Lærdom fra handelen", 40, None, None),
        ("Salgs-uke", 8, '0', f'=IF(S{{r}}="","",{uke_nokkel("S{r}")})'),
        ("Salgs-måned", 8, '0', f'=IF(S{{r}}="","",{mnd_nokkel("S{r}")})'),
        ("Kjøps-uke", 8, '0', f'=IF(E{{r}}="","",{uke_nokkel("E{r}")})'),
        ("Kjøps-måned", 8, '0', f'=IF(E{{r}}="","",{mnd_nokkel("E{r}")})'),
    ]
    oppsett_ark(ws, kol, frys="C2")
    validering(ws, "A", f"=Analyse!$A$2:$A${SLUTT}")
    validering(ws, "U", liste_ref("Salgsårsak"))
    validering(ws, "AB", liste_ref("JaNei"))
    for k in ("X", "Y", "Z"):
        pluss_minus(ws, k)
    cf(ws, f"L2:L{SLUTT}", "AND(ISNUMBER(L2),L2>0.08)", ROD_FILL)
    cf(ws, f"W2:W{SLUTT}", 'W2="Åpen"', GUL_FILL)
    cf(ws, f"R2:R{SLUTT}", 'R2="A"', GRONN_FILL)
    cf(ws, f"R2:R{SLUTT}", 'R2="B"', GUL_FILL)
    cf(ws, f"R2:R{SLUTT}", 'R2="C"', ROD_FILL)
    ws.row_dimensions[1].height = 44

    eks = [
        ("A001", "2026-11-03", 101.2, 200, 93.0, 125.0, "2026-11-12", 118.5, "Trailing stop", None,
         "Ja", "Holdt gjennom første test av MA50 – riktig."),
        ("A002", "2026-11-04", 50.4, 400, 47.0, 60.0, "2026-11-06", 47.0, "Stop truffet", None,
         "Ja", "Svakt marked + C-karakter = burde stått over."),
        ("A001", "2026-11-09", 112.0, 100, 106.0, 125.0, None, None, None, 116.0, "", ""),
    ]
    for i, e in enumerate(eks, start=2):
        (aid, kd, kk, ant, stp, mal, sd, sk, sa, naa, plan, laer) = e
        ws[f"A{i}"] = aid; ws[f"E{i}"] = _d(kd); ws[f"F{i}"] = kk; ws[f"G{i}"] = ant
        ws[f"H{i}"] = stp; ws[f"I{i}"] = mal
        if sd:
            ws[f"S{i}"] = _d(sd); ws[f"T{i}"] = sk; ws[f"U{i}"] = sa
        if naa:
            ws[f"V{i}"] = naa
        if plan:
            ws[f"AB{i}"] = plan
        if laer:
            ws[f"AC{i}"] = laer


def hr(n: str) -> str:
    k = H[n]
    return f"Handler!${k}$2:${k}${SLUTT}"


# ---------------------------------------------------------------------------
# Uke- og månedsoppsummering
# ---------------------------------------------------------------------------
def lag_oppsummering(wb, *, navn: str, perioder: int, start: date, maned: bool):
    ws = wb.create_sheet(navn)
    a_nokkel = f"Analyse!${A_MND if maned else A_UKE}$2:${A_MND if maned else A_UKE}${SLUTT}"
    s_nokkel = hr("smnd" if maned else "suke")
    k_nokkel = hr("kmnd" if maned else "kuke")
    W, X, Z, AB = hr("status"), hr("res"), hr("r"), hr("plan")
    L = f'{W},"Lukket",{s_nokkel},$C{{r}}'
    if maned:
        etikett = ('=CHOOSE(MONTH(A{r}),"Januar","Februar","Mars","April","Mai","Juni","Juli",'
                   '"August","September","Oktober","November","Desember")&" "&YEAR(A{r})')
        nokkel = f"={mnd_nokkel('A{r}')}"
        forste = ("Måned", 11, "MM.YYYY", None)
    else:
        etikett = '="Uke "&ISOWEEKNUM(A{r})&" · "&TEXT(DAY(A{r}),"0")&"."&MONTH(A{r})&"–"&DAY(A{r}+6)&"."&MONTH(A{r}+6)'
        nokkel = f"={uke_nokkel('A{r}')}"
        forste = ("Uke fra (mandag)", 11, DATO, None)
    kol = [
        forste,
        ("Periode", 22 if maned else 20, None, etikett),
        ("Nøkkel", 8, '0', nokkel),
        ("Analyser", 8, '0', f'=COUNTIF({a_nokkel},C{{r}})'),
        ("Nye kjøp", 8, '0', f'=COUNTIF({k_nokkel},C{{r}})'),
        ("Lukket", 8, '0', f'=COUNTIFS({L})'),
        ("Vinnere", 8, '0', f'=COUNTIFS({L},{X},">0")'),
        ("Treff %", 8, PST, '=IF(F{r}=0,"",G{r}/F{r})'),
        ("Resultat kr", 11, KR0, f'=IF(F{{r}}=0,"",SUMIFS({X},{L}))'),
        ("Snitt R", 8, R_FMT, f'=IF(F{{r}}=0,"",AVERAGEIFS({Z},{L}))'),
        ("Fulgte planen", 9, PST, f'=IF(F{{r}}=0,"",COUNTIFS({L},{AB},"Ja")/F{{r}})'),
        ("Hva gikk bra?", 36, None, None),
        ("Hva gikk dårlig / regelbrudd?", 36, None, None),
        ("Lærdom / fokus neste " + ("måned" if maned else "uke"), 42, None, None),
    ]
    oppsett_ark(ws, kol, frys="C2", rader=perioder, notat_fra=12)
    ws["A2"] = start
    ws["A2"].fill = PatternFill(fill_type=None)
    for r in range(3, perioder + 2):
        ws[f"A{r}"] = f"=EDATE(A{r - 1},1)" if maned else f"=A{r - 1}+7"
        ws[f"A{r}"].fill = BEREGNET_FILL
    for r in range(2, perioder + 2):
        ws.row_dimensions[r].height = 30
        ws[f"C{r}"].font = ID_FONT
    sl = perioder + 1
    for k in ("I", "J"):
        pluss_minus(ws, k, rader=perioder)
    # Marker inneværende periode.
    if maned:
        naa = "AND(YEAR(TODAY())=YEAR($A2),MONTH(TODAY())=MONTH($A2))"
    else:
        naa = "AND(TODAY()>=$A2,TODAY()<$A2+7)"
    cf(ws, f"A2:K{sl}", naa, DENNE_FILL)
    ws.column_dimensions["C"].hidden = True
    if maned:
        tekst = "Fyll inn læringsnotat på slutten av hver måned. Blå rad = denne måneden."
    else:
        tekst = "Fyll inn læringsnotat hver helg. Blå rad = denne uka."
    ws[f"L{sl + 2}"] = tekst
    ws[f"L{sl + 2}"].font = DIM_FONT
    if not maned:
        ws["L2"] = "Eksempel: Fulgte reglene, ventet på volum."
        ws["M2"] = "Tok EKSEMPEL2 med C-karakter i svakt marked."
        ws["N2"] = "Bare A/B-karakter når markedet er under press."


# ---------------------------------------------------------------------------
# Statistikk
# ---------------------------------------------------------------------------
def lag_statistikk(wb):
    ws = wb.create_sheet("Statistikk")
    ws.sheet_view.showGridLines = False
    for k, b in zip("ABCDE", (2, 30, 14, 36, 3)):
        ws.column_dimensions[k].width = b
    for k, b in zip("FGHIJ", (22, 9, 9, 12, 9)):
        ws.column_dimensions[k].width = b

    W, X, Y, Z = hr("res"), hr("respct"), hr("r"), hr("dager")
    ST = hr("status")
    L = f'{ST},"Lukket"'

    ws["B1"] = "Statistikk"; ws["B1"].font = TITTEL_FONT
    ws["B2"] = "Oppdateres automatisk fra Handler. Kun lukkede handler teller (unntatt «Åpne»)."
    ws["B2"].font = DIM_FONT
    nokkel = [
        ("Resultat", None, None, None),                                                   # 3
        ("Lukkede handler", f"=COUNTIFS({L})", '0', ""),                                  # 4
        ("Vinnere", f'=COUNTIFS({L},{W},">0")', '0', ""),                                 # 5
        ("Tapere", f'=COUNTIFS({L},{W},"<0")', '0', ""),                                  # 6
        ("Treffprosent", '=IFERROR(C5/C4,"")', PST, "40–50 % er fint med god gevinst/tap"),  # 7
        ("Totalt realisert", f"=SUMIFS({W},{L})", KR0, ""),                               # 8
        ("Snittgevinst", f'=IFERROR(AVERAGEIFS({W},{L},{W},">0"),"")', KR0, ""),          # 9
        ("Snittap", f'=IFERROR(AVERAGEIFS({W},{L},{W},"<0"),"")', KR0, ""),               # 10
        ("Gevinst/tap-forhold", '=IFERROR(-C9/C10,"")', '0.00" : 1"', "Minervini: ≥ 2–3 : 1"),  # 11
        ("Snitt gevinst %", f'=IFERROR(AVERAGEIFS({X},{L},{X},">0"),"")', PST, ""),       # 12
        ("Snitt tap %", f'=IFERROR(AVERAGEIFS({X},{L},{X},"<0"),"")', PST, "Bør ligge rundt −5 til −8 %"),  # 13
        ("Snitt R-multippel", f'=IFERROR(AVERAGEIFS({Y},{L}),"")', R_FMT, "Over 0 = systemet tjener penger"),  # 14
        ("Forventning per handel", '=IFERROR(C7*C9+(1-C7)*C10,"")', KR0, "treff × snittgevinst + (1−treff) × snittap"),  # 15
        ("Største gevinst", f'=IFERROR(MAXIFS({W},{ST},"Lukket"),"")', KR0, ""),          # 16
        ("Største tap", f'=IFERROR(MINIFS({W},{ST},"Lukket"),"")', KR0, ""),              # 17
        ("Snitt dager – vinnere", f'=IFERROR(AVERAGEIFS({Z},{L},{W},">0"),"")', '0', "Vinnere bør holdes lenger"),  # 18
        ("Snitt dager – tapere", f'=IFERROR(AVERAGEIFS({Z},{L},{W},"<0"),"")', '0', "… enn tapere"),  # 19
        ("", None, None, None),                                                           # 20
        ("Åpne posisjoner", None, None, None),                                            # 21
        ("Antall åpne", f'=COUNTIF({ST},"Åpen")', '0', ""),                               # 22
        ("Åpen risiko (til stop)", f'=SUMIFS({hr("risiko")},{ST},"Åpen")', KR0, "Hva du taper om alle stopper ut"),  # 23
        ("Urealisert resultat", f'=SUMIFS({W},{ST},"Åpen")', KR0, "Krever «Kurs nå» i Handler"),  # 24
        ("", None, None, None),                                                           # 25
        ("Analyser", None, None, None),                                                   # 26
        ("High alert nå", '=COUNTIF(Analyse!$F$2:$F$501,"High alert")', '0', ""),         # 27
        ("Watchlist nå", '=COUNTIF(Analyse!$F$2:$F$501,"Watchlist")', '0', ""),           # 28
        ("Parkert", '=COUNTIF(Analyse!$F$2:$F$501,"Parkert")', '0', ""),                  # 29
        ("Andel analyser som ble kjøpt", '=IFERROR(COUNTIF(Analyse!$' + A_ANT + '$2:$' + A_ANT
         + '$501,">0")/COUNTA(Analyse!$C$2:$C$501),"")', PST, "Lav andel = selektiv (bra)"),  # 30
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
    for celle in ("C8", "C14", "C15", "C24"):
        cf(ws, celle, f"AND(ISNUMBER({celle}),{celle}>0)", GRONN_FILL)
        cf(ws, celle, f"AND(ISNUMBER({celle}),{celle}<0)", ROD_FILL)
    cf(ws, "C11", "AND(ISNUMBER(C11),C11>=2)", GRONN_FILL)
    cf(ws, "C11", "AND(ISNUMBER(C11),C11<1.5)", ROD_FILL)
    cf(ws, "C13", "AND(ISNUMBER(C13),C13<-0.1)", ROD_FILL)

    D_, N_, O_, P_, Q_, R_, AB_ = (hr(n) for n in ("setup", "rs", "ts", "krit", "marked", "kar", "plan"))
    grupper = [
        ("Per analyse-karakter", [("A (8–10 poeng)", [f'{R_},"A"']), ("B (6–7)", [f'{R_},"B"']),
                                  ("C (under 6)", [f'{R_},"C"'])]),
        ("Per setup", [(f"=Lister!${LISTE_KOL['Setup']}${i + 2}",
                        [f"{D_},Lister!${LISTE_KOL['Setup']}${i + 2}"])
                       for i in range(len(LISTER["Setup"]))]),
        ("Per RS ved analyse", [("90–99", [f'{N_},">=90"']),
                                ("80–89", [f'{N_},">=80"', f'{N_},"<90"']),
                                ("70–79", [f'{N_},">=70"', f'{N_},"<80"']),
                                ("Under 70", [f'{N_},"<70"'])]),
        ("Per TrendScore", [("70+", [f'{O_},">=70"']), ("40–69", [f'{O_},">=40"', f'{O_},"<70"']),
                            ("Under 40", [f'{O_},"<40"'])]),
        ("Per kriterier", [("7/7", [f'{P_},7']), ("6/7", [f'{P_},6']), ("5 eller færre", [f'{P_},"<=5"'])]),
        ("Per marked", [(m, [f'{Q_},"{m}"']) for m in LISTER["Marked"]]),
        ("Fulgte planen?", [("Ja", [f'{AB_},"Ja"']), ("Nei", [f'{AB_},"Nei"'])]),
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
            for k, fmt in zip("GHIJ", ('0', PST, KR0, R_FMT)):
                ws[f"{k}{rad}"].number_format = fmt
            for k in "FGHIJ":
                ws[f"{k}{rad}"].border = KANT
            for k in "IJ":
                cf(ws, f"{k}{rad}", f"AND(ISNUMBER({k}{rad}),{k}{rad}>0)", GRONN_FILL)
                cf(ws, f"{k}{rad}", f"AND(ISNUMBER({k}{rad}),{k}{rad}<0)", ROD_FILL)
            rad += 1
        rad += 1
    ws.freeze_panes = "A3"


# ---------------------------------------------------------------------------
def lag_instruks(wb):
    ws = wb.active
    ws.title = "Instruks"
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 112
    linjer = [
        ("Tradingjournal – Minervini-stil", TITTEL_FONT),
        ("Flyt:  Analyse  →  Handel  →  Uke-/månedsoppsummering  →  Statistikk", Font(bold=True, size=11)),
        ("", None),
        ("1. Analyse – start alltid her", SEKSJON_FONT),
        ("Én rad per analyse, datert. Hver rad har en fast ID (A001, A002 …). Velg liste: "
         "Watchlist, High alert (nær kjøp), Parkert, Kjøpt eller Droppet. Fyll inn pivot/stop/mål, "
         "RS, TrendScore og svar Ja/Nei på sjekklista → poeng og karakter (A = kjøpbar, B = følg, C = vent).", None),
        ("Ny analyse av samme aksje senere? Lag en ny rad med ny dato – da ser du hvordan caset utviklet seg.", DIM_FONT),
        ("", None),
        ("2. Handler – koble til analysen", SEKSJON_FONT),
        ("Velg Analyse-ID i første kolonne. Ticker, setup, RS, TrendScore, marked og karakter hentes "
         "automatisk. Fyll inn kjøp (dato, kurs, antall, stop, mål). Ved salg: salgsdato, -kurs og årsak. "
         "Sett gjerne analysens liste til «Kjøpt».", None),
        ("Delsalg: del handelen i to rader med samme Analyse-ID. Flere kjøp på samme analyse er også ok.", DIM_FONT),
        ("", None),
        ("3. Ukeoppsummering og Månedsoppsummering", SEKSJON_FONT),
        ("Tallene (analyser, kjøp, lukkede, treff %, resultat, R, fulgte planen) fylles ut automatisk. "
         "Du skriver: Hva gikk bra? Hva gikk dårlig / regelbrudd? Lærdom / fokus neste periode. "
         "Inneværende uke/måned er markert blå.", None),
        ("", None),
        ("4. Statistikk", SEKSJON_FONT),
        ("Treffprosent, gevinst/tap-forhold, R-multippel – og «hva funker» per analyse-karakter, setup, "
         "RS, TrendScore, kriterier, marked og om du fulgte planen. Gir A-analyser bedre resultat enn C?", None),
        ("", None),
        ("Farger", SEKSJON_FONT),
        ("Grå celler er formler – ikke skriv i dem. Hvite celler fyller du selv. Nedtrekkslister redigeres i «Lister».", None),
        ("", None),
        ("Minervinis tommelfingerregler", SEKSJON_FONT),
        ("• Kutt tap tidlig: snittap rundt 5–8 %, aldri over 10 %.", None),
        ("• Gevinst/tap-forhold ≥ 2–3 : 1 – da tjener du penger selv med 40–50 % treff.", None),
        ("• Snitt R over 0 = systemet tjener penger.", None),
        ("", None),
        ("Google Sheets", SEKSJON_FONT),
        ("Last opp i Google Drive → høyreklikk → Åpne med Google Regneark → Fil → Lagre som Google Regneark.", None),
        ("Eksempelradene (EKSEMPEL1–5) kan slettes. I Handler: slett hele raden. I Analyse: tøm cellene, men la ID stå.", DIM_FONT),
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


def _nye_funksjoner(wb):
    """Excel krever _xlfn.-prefiks i fila for funksjoner nyere enn 2007, ellers #NAME?.
    Excel og Google Sheets viser dem uten prefiks."""
    for ws in wb.worksheets:
        for rad in ws.iter_rows():
            for c in rad:
                if isinstance(c.value, str) and c.value.startswith("="):
                    v = c.value
                    for fn in ("ISOWEEKNUM(", "MAXIFS(", "MINIFS("):
                        v = v.replace(fn, "_xlfn." + fn)
                    c.value = v


def main():
    wb = Workbook()
    lag_instruks(wb)
    lag_analyse(wb)
    lag_handler(wb)
    i_dag = date.today()
    mandag = i_dag - timedelta(days=i_dag.weekday())
    lag_oppsummering(wb, navn="Ukeoppsummering", perioder=104,
                     start=min(mandag, date(2026, 11, 2)), maned=False)
    lag_oppsummering(wb, navn="Månedsoppsummering", perioder=36,
                     start=min(date(i_dag.year, i_dag.month, 1), date(2026, 11, 1)), maned=True)
    lag_statistikk(wb)
    lag_lister(wb)
    _nye_funksjoner(wb)
    UT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(UT)
    print(f"Lagret: {UT}")


if __name__ == "__main__":
    main()
