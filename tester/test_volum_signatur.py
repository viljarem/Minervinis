"""
Tester for volum-signaturen i motor/vcp.py – tallene «dag −2 … +2» rundt et brudd.

Minervini vil se at volumet TØRKER INN i basen og EKSPLODERER på selve bruddet.
Disse testene låser fast at:
  1. volum_signatur gir riktige forskyvninger (−2,−1,0,+1,+2) og markerer bruddagen.
  2. Bruddagen får høyt relativt volum (RVol) når volumet spruter der.
  3. Dager som ikke finnes ennå (framtid for et ferskt brudd) utelates – ingen krasj.
  4. Uten bruddato blir signaturen tom.
  5. rvol_serie gir riktig antall dager til mini-forløpet i lista.

Kjør slik (fra prosjektmappa):  pytest -q
"""
import pandas as pd

from motor import konfig, vcp


def _lag_df(antall: int = 60, spike_pos: int | None = None, spike: float = 3000.0) -> pd.DataFrame:
    """Bygger en enkel dag-for-dag-serie med jevnt volum og evt. ett volumhopp.

    Volumet er 1000 hver dag (så 50-dagers snittet blir ~1000), bortsett fra på
    `spike_pos`, der det settes til `spike` (et tydelig bruddvolum).
    """
    datoer = pd.bdate_range("2024-01-01", periods=antall)
    close = pd.Series(range(100, 100 + antall), index=datoer, dtype="float64")
    volum = pd.Series(1000.0, index=datoer)
    if spike_pos is not None:
        volum.iloc[spike_pos] = spike
    return pd.DataFrame({"Close": close, "Volume": volum}, index=datoer)


def test_fem_dager_med_riktige_offset_og_bruddag():
    """Brudd midt i serien gir 5 punkter (−2..+2), der bare dag 0 er bruddagen."""
    df = _lag_df(spike_pos=40)
    sig = vcp.volum_signatur(df, df.index[40])

    assert [e["offset"] for e in sig] == [-2, -1, 0, 1, 2]
    assert [e["er_brudd"] for e in sig] == [False, False, True, False, False]


def test_bruddagen_har_hoyt_relativt_volum():
    """Volumhoppet på bruddagen skal gi RVol godt over bruddterskelen (1,4×)."""
    df = _lag_df(spike_pos=40, spike=3000.0)
    sig = vcp.volum_signatur(df, df.index[40])

    bruddag = next(e for e in sig if e["er_brudd"])
    assert bruddag["rvol"] >= konfig.BRUDD_VOLUM_FAKTOR
    assert bruddag["rvol"] == 3.0  # 3000 / 1000 (snittet av de 50 dagene før)

    # Dagene FØR bruddet ligger på normalt volum (rundt 1,0×).
    for e in sig:
        if e["offset"] < 0:
            assert e["rvol"] < konfig.BRUDD_VOLUM_FAKTOR


def test_framtidsdager_utelates_for_ferskt_brudd():
    """Bryter aksjen på SISTE dag, finnes ikke +1/+2 ennå – da tas de bare ikke med."""
    df = _lag_df(antall=60, spike_pos=59)
    sig = vcp.volum_signatur(df, df.index[59])

    assert [e["offset"] for e in sig] == [-2, -1, 0]
    assert sig[-1]["er_brudd"] is True


def test_ingen_bruddato_gir_tom_signatur():
    df = _lag_df(spike_pos=40)
    assert vcp.volum_signatur(df, None) == []


def test_ukjent_bruddato_krasjer_ikke():
    """En dato som ikke finnes i serien skal gi tom liste, ikke unntak."""
    df = _lag_df(spike_pos=40)
    assert vcp.volum_signatur(df, pd.Timestamp("1990-01-01")) == []


def test_rvol_serie_lengde():
    """rvol_serie gir nøyaktig så mange dager vi ber om (til mini-forløpet)."""
    df = _lag_df(antall=60)
    assert len(vcp.rvol_serie(df, dager=10)) == 10
    assert len(vcp.rvol_serie(df, dager=5)) == 5
