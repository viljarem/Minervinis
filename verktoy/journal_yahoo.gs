/**
 * Yahoo Finance-kurser for Tradingjournal (Google Sheets).
 *
 * Installer: Utvidelser → Apps Script → lim inn hele denne fila → Lagre (💾).
 * Første gang en formel kjøres ber Google om tillatelse – godta.
 *
 * Bruk i arket:
 *   =YAHOOKURS("EQNR.OL"; DATO(2026;1;1); I DAG())   → Date, Open, High, Low, Close
 *   =YAHOONAVN("EQNR.OL")                              → "Equinor ASA"
 * Oslo Børs-aksjer har endelsen .OL, amerikanske skrives uten (NVDA).
 */

function _yahooHent_(symbol, fra, til) {
  symbol = String(symbol || '').trim().toUpperCase();
  if (!symbol) throw new Error('Mangler ticker');
  var p1 = Math.floor(new Date(fra).getTime() / 1000);
  var p2 = Math.floor(new Date(til).getTime() / 1000) + 86400;
  var nokkel = 'y_' + symbol + '_' + p1 + '_' + p2;
  var cache = CacheService.getScriptCache();
  var lagret = cache.get(nokkel);
  if (lagret) return JSON.parse(lagret);

  var url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(symbol) +
            '?period1=' + p1 + '&period2=' + p2 + '&interval=1d&events=history';
  var svar = UrlFetchApp.fetch(url, {
    muteHttpExceptions: true,
    headers: { 'User-Agent': 'Mozilla/5.0' }
  });
  if (svar.getResponseCode() !== 200) {
    throw new Error('Yahoo svarte ' + svar.getResponseCode() + ' for ' + symbol);
  }
  var json = JSON.parse(svar.getContentText());
  var r = json.chart && json.chart.result && json.chart.result[0];
  if (!r || !r.timestamp) throw new Error('Fant ikke ' + symbol + ' hos Yahoo');
  var q = r.indicators.quote[0];
  var data = {
    navn: r.meta.longName || r.meta.shortName || symbol,
    t: r.timestamp, o: q.open, h: q.high, l: q.low, c: q.close
  };
  try { cache.put(nokkel, JSON.stringify(data), 1800); } catch (e) { /* for stor – hopp over */ }
  return data;
}

/**
 * Daglige kurser fra Yahoo Finance.
 * @param {string} symbol Ticker, f.eks. "EQNR.OL"
 * @param {Date} fra Startdato
 * @param {Date} til Sluttdato
 * @return Tabell med Date, Open, High, Low, Close
 * @customfunction
 */
function YAHOOKURS(symbol, fra, til) {
  var d = _yahooHent_(symbol, fra, til || new Date());
  var ut = [['Date', 'Open', 'High', 'Low', 'Close']];
  for (var i = 0; i < d.t.length; i++) {
    if (d.c[i] == null) continue;
    var dt = new Date(d.t[i] * 1000);
    ut.push([new Date(dt.getFullYear(), dt.getMonth(), dt.getDate()),
             d.o[i], d.h[i], d.l[i], d.c[i]]);
  }
  return ut;
}

/**
 * Selskapsnavn fra Yahoo Finance.
 * @param {string} symbol Ticker, f.eks. "EQNR.OL"
 * @return Navn
 * @customfunction
 */
function YAHOONAVN(symbol) {
  var til = new Date();
  var fra = new Date(til.getTime() - 7 * 86400000);
  return _yahooHent_(symbol, fra, til).navn;
}
