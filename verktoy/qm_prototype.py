"""
qm_prototype.py – ENGANGS eksperiment (ikke del av appen).

Tester Qullamaggie BREAKOUT-logikken (setup-variant, INGEN score) mot ekte
kursdata for aa se: finner den gode treff, eller mest stoey?

Kjoeres manuelt:  python verktoy/qm_prototype.py
Roerer ingenting i motoren/appen.
"""
from __future__ import annotations

import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor import data as datamod  # noqa: E402


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def adr_pct(d: pd.DataFrame, n: int = 20) -> float:
    """Average Daily Range i prosent (Qullamaggies #1 volatilitetsmaal)."""
    r = (d["High"] / d["Low"]).tail(n)
    return float((r.mean() - 1.0) * 100.0)


def analyser(d: pd.DataFrame) -> dict | None:
    """Returnerer kriterie-dict for siste dag, eller None hvis for kort."""
    if d is None or len(d) < 150:
        return None
    c = d["Close"]
    pris = float(c.iloc[-1])

    e10, e20, e50 = ema(c, 10), ema(c, 20), ema(c, 50)
    adr = adr_pct(d, 20)

    # Momentum-vinduer (raa avkastning)
    def avk(n):
        if len(c) <= n:
            return np.nan
        return (pris / float(c.iloc[-n - 1]) - 1.0) * 100.0

    m1, m3, m6 = avk(21), avk(63), avk(126)

    # Reelt byks siste 1-3 mnd: beste N-dagers loeft i vinduet
    vindu = c.tail(63)
    byks = (vindu.max() / vindu.min() - 1.0) * 100.0 if len(vindu) > 5 else np.nan

    # Konsolidering siste 20 dager: pivot = toppen (motstand), stramhet = range/ADR
    base = d.tail(20)
    piv = float(base["High"].max())
    base_lav = float(base["Low"].min())
    range_pct = (piv / base_lav - 1.0) * 100.0 if base_lav > 0 else np.nan
    tightness = range_pct / adr if adr and adr > 0 else np.nan
    avstand_pivot = (piv / pris - 1.0) * 100.0  # hvor langt UNDER pivot (positiv)

    # Hoyere bunner: sammenlign min i foerste vs siste halvdel av basen
    h1 = base["Low"].iloc[:10].min()
    h2 = base["Low"].iloc[10:].min()
    hoyere_bunner = bool(h2 >= h1)

    # Volum: toerker inn i basen vs forrige 20 dager?
    v_base = d["Volume"].tail(20).mean()
    v_foer = d["Volume"].tail(60).head(40).mean()
    volum_toerke = bool(v_base < v_foer)

    # Trend-struktur
    surfer = bool(pris >= float(e20.iloc[-1]) and e10.iloc[-1] > e20.iloc[-1] > e50.iloc[-1])

    # Stop = DAGENS low (Qullamaggie), bredde i % <= ADR%?
    dag_lav = float(d["Low"].iloc[-1])
    stop_bredde = (pris / dag_lav - 1.0) * 100.0 if dag_lav > 0 else np.nan

    return {
        "pris": pris, "adr": adr, "m1": m1, "m3": m3, "m6": m6, "byks": byks,
        "pivot": piv, "avstand_pivot": avstand_pivot, "range_pct": range_pct,
        "tightness": tightness, "hoyere_bunner": hoyere_bunner,
        "volum_toerke": volum_toerke, "surfer": surfer, "stop_bredde": stop_bredde,
    }


def main(parquet: str, navn: str):
    print(f"\n{'='*70}\n{navn}\n{'='*70}")
    df = datamod.les_priser(parquet)
    tickere = sorted(df["Ticker"].unique())
    print(f"Univers: {len(tickere)} tickere, siste dato: {df['Date'].max().date()}")

    rader = []
    for t in tickere:
        try:
            r = analyser(datamod.serie_for(df, t))
            if r:
                r["ticker"] = t
                rader.append(r)
        except Exception:
            pass

    res = pd.DataFrame(rader)

    # KRITERIER (setup-variant, passerer/feiler):
    #  - momentum-leder: topp ~10 % paa 3M (persentil)
    #  - reelt byks >= 30 %
    #  - surfer stigende EMA
    #  - hoyere bunner
    #  - stram base (tightness < 4)  [range er < 4x ADR]
    #  - ADR% >= 3 (nok bevegelse)
    m3_terskel = res["m3"].quantile(0.90)
    res["krit_momentum"] = res["m3"] >= m3_terskel
    res["krit_byks"] = res["byks"] >= 30
    res["krit_surf"] = res["surfer"]
    res["krit_bunner"] = res["hoyere_bunner"]
    res["krit_stram"] = res["tightness"] < 4
    res["krit_adr"] = res["adr"] >= 3
    res["krit_stop"] = res["stop_bredde"] <= res["adr"]  # stop (dagens low) <= ADR%

    krit_kol = [k for k in res.columns if k.startswith("krit_")]
    res["antall_ok"] = res[krit_kol].sum(axis=1)
    res["gyldig_setup"] = res[krit_kol].all(axis=1)

    print(f"\nMomentum-terskel (3M topp 10 %): {m3_terskel:.1f} %")
    print(f"Aksjer analysert: {len(res)}")
    print(f"GYLDIGE SETUP (alle 7 kriterier): {int(res['gyldig_setup'].sum())}")
    print(f"Naesten (6 av 7): {int((res['antall_ok']==6).sum())}")

    print("\n--- TOPP GYLDIGE SETUP (sortert: naermest utbrudd) ---")
    g = res[res["gyldig_setup"]].sort_values("avstand_pivot")
    _vis(g.head(15))

    print("\n--- NAESTEN (6/7), sortert: sterkest 3M-momentum ---")
    n = res[res["antall_ok"] == 6].sort_values("m3", ascending=False)
    _vis(n.head(10))


def _vis(g: pd.DataFrame):
    if g.empty:
        print("  (ingen)")
        return
    for _, r in g.iterrows():
        mangler = [k.replace("krit_", "") for k in g.columns
                   if k.startswith("krit_") and not r[k]]
        print(f"  {r['ticker']:12s} 3M:{r['m3']:6.1f}% byks:{r['byks']:6.1f}% "
              f"ADR:{r['adr']:4.1f}% til_pivot:{r['avstand_pivot']:5.1f}% "
              f"stram:{r['tightness']:4.1f} "
              + (f"MANGLER:{mangler}" if mangler else "OK"))


if __name__ == "__main__":
    main("data/priser_sp500.parquet", "S&P 500")
    main("data/priser.parquet", "OSLO BOERS")
