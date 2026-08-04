/**
 * Simulatore Predittivo Pro — App principale
 * Dixon-Coles client-side + dati da GitHub Actions
 */

// ===================== CONFIG =====================
const DATA_URL = './data/fixtures_processed.json';
const ODDS_URL = './data/odds.json';

// Parametri lega per modalità manuale
const LEAGUE_AVG_GF = 1.45;
const LEAGUE_AVG_GA = 1.20;
const RHO_DEFAULT = -0.07;
const HOME_ADV = 0.15;
const FORM_WEIGHT = 0.08;

// ===================== STATO =====================
let allData = null;
let currentMatch = null;
let registry = JSON.parse(localStorage.getItem('simRegistry') || '[]');

// ===================== UTILS =====================
function formatPct(p) { return (p * 100).toFixed(1) + '%'; }
function formatOdd(o) { return o ? o.toFixed(2) : '—'; }

function computeValueJS(pred, odds) {
  if (!odds) return null;
  const src = odds.best || odds;
  const markets = {
    '1': [pred.p1, src['1']], 'X': [pred.px, src['X']], '2': [pred.p2, src['2']],
    'Over 2.5': [pred.pOver25, src.over25], 'Under 2.5': [pred.pUnder25, src.under25]
  };
  const rows = [];
  for (const m in markets) {
    const p = markets[m][0], q = markets[m][1];
    if (!q || q <= 1 || p == null) continue;
    const b = q - 1;
    const edge = p * q - 1;
    const kelly = b > 0 ? Math.min(0.05, Math.max(0, (p * q - 1) / b) / 2) : 0;
    rows.push({ market: m, p, odds: q, edge, kelly });
  }
  rows.sort((a, b) => b.edge - a.edge);
  const bet = rows.length && rows[0].edge >= 0.03 ? rows[0] : null;
  return { rows, bestBet: bet };
}

function renderValue(value) {
  const card = document.getElementById('predictionCard');
  if (!card) return;
  let box = document.getElementById('valueCard');
  if (!box) {
    box = document.createElement('div');
    box.className = 'sub-card';
    box.id = 'valueCard';
    const actions = card.querySelector('.actions');
    if (actions) card.insertBefore(box, actions); else card.appendChild(box);
  }
  if (!value || !value.rows || !value.rows.length) {
    box.innerHTML = '<h3>\uD83D\uDC8E Valore</h3><p class="note">Quote non disponibili: nessun confronto di valore per questa partita.</p>';
    return;
  }
  let html = '<h3>\uD83D\uDC8E Valore \u2014 modello vs quota migliore</h3>';
  if (value.bestBet && value.bestBet.edge > 0.25) {
    const bb = value.bestBet;
    html += '<div class="best-bet warn">\u26A0\uFE0F Vantaggio anomalo su <strong>' + bb.market + '</strong> (' + (bb.edge*100).toFixed(0) + '%). ' +
            'Un margine cos\u00EC grande contro il bookmaker quasi sempre significa che il modello ha dati insufficienti ' +
            '(inizio stagione, poche partite giocate), non che la quota sia regalata. Nessuna puntata consigliata.</div>';
  } else if (value.bestBet) {
    const bb = value.bestBet;
    html += '<div class="best-bet">\u2705 Bet di valore: <strong>' + bb.market + '</strong> @ ' + bb.odds.toFixed(2) +
            ' \u00B7 vantaggio <strong>' + (bb.edge*100).toFixed(1) + '%</strong>' +
            ' \u00B7 puntata (\u00BD Kelly) <strong>' + (bb.kelly*100).toFixed(1) + '%</strong> del bankroll</div>';
  } else {
    html += '<p class="note">Nessuna bet con vantaggio \u2265 3%: qui il mercato non offre valore secondo il modello.</p>';
  }
  html += '<div class="value-table"><div class="value-row value-head"><span>Mercato</span><span>Modello</span><span>Quota</span><span>Vantaggio</span><span>\u00BD Kelly</span></div>';
  for (const r of value.rows) {
    const cls = r.edge >= 0.03 ? ' value-pos' : (r.edge < 0 ? ' value-neg' : '');
    html += '<div class="value-row' + cls + '"><span>' + r.market + '</span><span>' + (r.p*100).toFixed(1) + '%</span><span>' +
            r.odds.toFixed(2) + '</span><span>' + (r.edge*100).toFixed(1) + '%</span><span>' +
            (r.kelly>0 ? (r.kelly*100).toFixed(1)+'%' : '\u2014') + '</span></div>';
  }
  html += '</div><p class="note hint">\u2139\uFE0F <strong>Vantaggio (EV)</strong> = probabilit\u00E0 del modello \u00D7 quota \u2212 1: quanto guadagni in media per ogni euro giocato se il modello ha ragione. Esempio: 40% con quota 3.00 \u2192 +20%. Sotto zero la quota \u00E8 pagata meno del giusto.<br>\u2139\uFE0F <strong>\u00BD Kelly</strong> = quota del <em>bankroll totale</em> da puntare, gi\u00E0 dimezzata e tappata al 5% per prudenza. Gioca solo ci\u00F2 che puoi permetterti di perdere.</p>';
  box.innerHTML = html;
}

function poissonPMF(k, lambda) {
  return (Math.pow(lambda, k) * Math.exp(-lambda)) / factorial(k);
}
function factorial(n) {
  if (n <= 1) return 1;
  let r = 1;
  for (let i = 2; i <= n; i++) r *= i;
  return r;
}

function tau(x, y, lamH, lamA, rho) {
  if (x === 0 && y === 0) return Math.max(0.1, 1.0 - lamH * lamA * rho);
  if (x === 0 && y === 1) return Math.max(0.1, 1.0 + lamH * rho);
  if (x === 1 && y === 0) return Math.max(0.1, 1.0 + lamA * rho);
  if (x === 1 && y === 1) return Math.max(0.1, 1.0 - rho);
  return 1.0;
}

function dixonColesMatrix(lamH, lamA, rho, maxGoals = 7) {
  let raw = {};
  let total = 0;

  for (let h = 0; h <= maxGoals; h++) {
    for (let a = 0; a <= maxGoals; a++) {
      let p = poissonPMF(h, lamH) * poissonPMF(a, lamA) * tau(h, a, lamH, lamA, rho);
      raw[`${h}-${a}`] = p;
      total += p;
    }
  }

  // Normalizza
  let probs = {};
  for (let k in raw) probs[k] = raw[k] / total;

  // Aggregati
  let p1 = 0, px = 0, p2 = 0, pOver = 0, pGG = 0;
  let top = [];

  for (let k in probs) {
    let [h, a] = k.split('-').map(Number);
    let p = probs[k];
    if (h > a) p1 += p;
    else if (h === a) px += p;
    else p2 += p;
    if (h + a >= 3) pOver += p;
    if (h >= 1 && a >= 1) pGG += p;
    top.push({score: k, prob: p});
  }

  top.sort((a, b) => b.prob - a.prob);

  // Distribuzione gol totali
  let dist = {};
  for (let g = 0; g <= maxGoals; g++) {
    if (g < maxGoals) {
      dist[g] = 0;
      for (let k in probs) {
        let [h, a] = k.split('-').map(Number);
        if (h + a === g) dist[g] += probs[k];
      }
    } else {
      dist[g + '+'] = 0;
      for (let k in probs) {
        let [h, a] = k.split('-').map(Number);
        if (h + a >= g) dist[g + '+'] += probs[k];
      }
    }
  }

  return {
    p1, px, p2,
    pOver25: pOver, pUnder25: 1 - pOver,
    pGG: pGG, pNG: 1 - pGG,
    topExact: top.slice(0, 3),
    totalGoalsDist: dist,
    lamH, lamA, rho
  };
}

function computeLambdasManual(homeGF, homeGA, awayGF, awayGA, homeForm, awayForm) {
  const homeAttack = homeGF / LEAGUE_AVG_GF;
  const homeDefense = homeGA / LEAGUE_AVG_GA;
  const awayAttack = awayGF / LEAGUE_AVG_GF;
  const awayDefense = awayGA / LEAGUE_AVG_GA;

  const formMap = {'W': 1, 'D': 0, 'L': -1};
  function formBonus(form) {
    if (!form) return 1.0;
    const scores = form.slice(-5).split('').map(c => formMap[c.toUpperCase()] || 0);
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    return 1.0 + avg * FORM_WEIGHT;
  }

  const formH = formBonus(homeForm);
  const formA = formBonus(awayForm);

  let lamH = LEAGUE_AVG_GF * homeAttack * awayDefense * formH * (1 + HOME_ADV);
  let lamA = LEAGUE_AVG_GF * awayAttack * homeDefense * formA;

  return [Math.max(0.3, Math.min(lamH, 4.0)), Math.max(0.3, Math.min(lamA, 3.5))];
}

// ===================== UI =====================
async function loadData() {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    allData = await res.json();

    const updateEl = document.getElementById('lastUpdate');
    if (allData.updated) {
      const d = new Date(allData.updated);
      updateEl.textContent = '🕐 Aggiornato: ' + d.toLocaleString('it-IT');
    } else {
      updateEl.textContent = '⚠️ Dati non disponibili';
    }

    populateCompetitions();
    removeUnusedOddsBoxes();
    renderGlossary();
    renderImportControl();
    renderMultiCalc();
    renderCreditsBadge(allData.apiCredits);
    loadTrackRecord();
  } catch (e) {
    console.error(e);
    document.getElementById('lastUpdate').textContent = '⚠️ Errore caricamento dati';
    // Mostra comunque modalità manuale
  }
}

function populateCompetitions() {
  const sel = document.getElementById('compSelect');
  sel.innerHTML = '<option value="">-- Scegli competizione --</option>';

  if (!allData || !allData.competitions) return;

  const comps = Object.entries(allData.competitions).sort((a, b) => 
    a[1].name.localeCompare(b[1].name)
  );

  for (const [id, info] of comps) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = info.name + ' (' + info.country + ')';
    sel.appendChild(opt);
  }
}

function populateMatches(compId) {
  const sel = document.getElementById('matchSelect');
  sel.innerHTML = '<option value="">-- Scegli partita --</option>';

  if (!compId || !allData.competitions[compId]) {
    sel.disabled = true;
    return;
  }

  const fixtures = allData.competitions[compId].fixtures || [];
  if (fixtures.length === 0) {
    sel.innerHTML = '<option value="">Nessuna partita programmata</option>';
    sel.disabled = true;
    return;
  }

  sel.disabled = false;
  for (const f of fixtures) {
    const opt = document.createElement('option');
    opt.value = f.id;
    opt.textContent = `${f.homeTeam} vs ${f.awayTeam} — ${f.date}`;
    sel.appendChild(opt);
  }
}

function showMatchData(fixture) {
  currentMatch = fixture;

  document.getElementById('dataCard').style.display = 'block';
  document.getElementById('predictionCard').style.display = 'block';
  document.getElementById('oddsRow').style.display = '';

  // Squadra casa
  document.getElementById('homeName').textContent = fixture.homeTeam;
  document.getElementById('homeElo').textContent = 'Elo ' + (fixture.homeStats.elo || 1500);
  document.getElementById('homeGF').textContent = fixture.homeStats.gf_pg || '—';
  document.getElementById('homeGA').textContent = fixture.homeStats.ga_pg || '—';
  document.getElementById('homeForm').textContent = fixture.homeStats.form || 'N/D';
  document.getElementById('homePlayed').textContent = fixture.homeStats.played || '—';

  // Squadra trasferta
  document.getElementById('awayName').textContent = fixture.awayTeam;
  document.getElementById('awayElo').textContent = 'Elo ' + (fixture.awayStats.elo || 1500);
  document.getElementById('awayGF').textContent = fixture.awayStats.gf_pg || '—';
  document.getElementById('awayGA').textContent = fixture.awayStats.ga_pg || '—';
  document.getElementById('awayForm').textContent = fixture.awayStats.form || 'N/D';
  document.getElementById('awayPlayed').textContent = fixture.awayStats.played || '—';

  // Quote
  const odds = fixture.odds;
  if (odds && odds['1']) {
    document.getElementById('odd1').textContent = formatOdd(odds['1']);
    document.getElementById('oddX').textContent = formatOdd(odds['X']);
    document.getElementById('odd2').textContent = formatOdd(odds['2']);
    document.getElementById('oddOver').textContent = formatOdd(odds.over25);
    document.getElementById('oddUnder').textContent = formatOdd(odds.under25);
    const _gg1 = document.getElementById('oddGG'); if (_gg1) _gg1.textContent = formatOdd(odds.gg);
    document.getElementById('oddsNote').textContent = 'Quote recuperate automaticamente da The Odds API';
  } else {
    document.getElementById('odd1').textContent = '—';
    document.getElementById('oddX').textContent = '—';
    document.getElementById('odd2').textContent = '—';
    document.getElementById('oddOver').textContent = '—';
    document.getElementById('oddUnder').textContent = '—';
    const _gg2 = document.getElementById('oddGG'); if (_gg2) _gg2.textContent = '—';
    document.getElementById('oddsNote').textContent = 'Quote non disponibili per questa partita — il modello usa solo dati statistici';
  }

  // Predizioni
  if (!fixture._basePrediction) {
    fixture._basePrediction = JSON.parse(JSON.stringify(fixture.prediction));
  }
  showPrediction(fixture.prediction);
  renderOddsInput(fixture);
  renderInlineHints();
}

function showPrediction(pred) {
  if (!pred) return;

  // Barra probabilità
  const p1 = pred.p1 || 0;
  const px = pred.px || 0;
  const p2 = pred.p2 || 0;
  const total = p1 + px + p2;

  document.getElementById('bar1').style.width = ((p1 / total) * 100) + '%';
  document.getElementById('barX').style.width = ((px / total) * 100) + '%';
  document.getElementById('bar2').style.width = ((p2 / total) * 100) + '%';

  document.getElementById('p1').textContent = formatPct(p1);
  document.getElementById('pX').textContent = formatPct(px);
  document.getElementById('p2').textContent = formatPct(p2);

  // Top esatti
  const exactEl = document.getElementById('topExact');
  exactEl.innerHTML = '';
  if (pred.topExact) {
    for (const [score, prob] of pred.topExact) {
      exactEl.innerHTML += `<div class="exact-item"><span class="score">${score}</span><span class="prob">${formatPct(prob)}</span></div>`;
    }
  }

  // Mercati
  document.getElementById('pOver').textContent = formatPct(pred.pOver25 || 0);
  document.getElementById('pUnder').textContent = formatPct(pred.pUnder25 || 0);
  document.getElementById('pGG').textContent = formatPct(pred.pGG || 0);
  document.getElementById('pNG').textContent = formatPct(pred.pNG || 0);

  // Chart
  renderChart(pred.totalGoalsDist);

  // Parametri
  document.getElementById('lambdaH').textContent = (pred.lambdaH || 0).toFixed(2);
  document.getElementById('lambdaA').textContent = (pred.lambdaA || 0).toFixed(2);
  document.getElementById('rhoVal').textContent = (pred.rho || 0).toFixed(3);

  renderValue(pred.value);
}

function renderChart(dist) {
  const el = document.getElementById('goalsChart');
  el.innerHTML = '';
  if (!dist) return;

  const keys = Object.keys(dist);
  const maxVal = Math.max(...Object.values(dist));

  for (const k of keys) {
    const pct = dist[k];
    const height = Math.max(4, (pct / maxVal) * 140);
    const bar = document.createElement('div');
    bar.className = 'chart-bar';
    bar.style.height = height + 'px';
    bar.innerHTML = `<span class="chart-pct">${formatPct(pct)}</span><span class="chart-label">${k}</span>`;
    el.appendChild(bar);
  }
}

// ===================== REGISTRO =====================
function renderRegistry() {
  const el = document.getElementById('registryTable');
  if (registry.length === 0) {
    el.innerHTML = '<p class="note">Nessuna previsione salvata. Seleziona una partita e clicca "Salva nel registro".</p>';
    return;
  }

  let html = `<table>
    <thead><tr>
      <th>Data</th><th>Partita</th><th>1</th><th>X</th><th>2</th>
      <th>O2.5</th><th>GG</th><th>Top</th><th>λH</th><th>λA</th>
    </tr></thead><tbody>`;

  for (const r of registry.slice().reverse()) {
    html += `<tr>
      <td>${r.date}</td>
      <td><strong>${r.home}</strong> vs <strong>${r.away}</strong></td>
      <td>${formatPct(r.p1)}</td>
      <td>${formatPct(r.px)}</td>
      <td>${formatPct(r.p2)}</td>
      <td>${formatPct(r.pOver)}</td>
      <td>${formatPct(r.pGG)}</td>
      <td>${r.topExact || '—'}</td>
      <td>${r.lambdaH}</td>
      <td>${r.lambdaA}</td>
    </tr>`;
  }

  html += '</tbody></table>';
  el.innerHTML = html;
}

function saveToRegistry() {
  if (!currentMatch) return;
  const pred = currentMatch.prediction;

  const entry = {
    id: Date.now(),
    date: currentMatch.date,
    home: currentMatch.homeTeam,
    away: currentMatch.awayTeam,
    p1: pred.p1,
    px: pred.px,
    p2: pred.p2,
    pOver: pred.pOver25,
    pGG: pred.pGG,
    topExact: pred.topExact ? pred.topExact[0][0] : '',
    lambdaH: pred.lambdaH,
    lambdaA: pred.lambdaA,
    savedAt: new Date().toISOString()
  };

  registry.push(entry);
  localStorage.setItem('simRegistry', JSON.stringify(registry));
  renderRegistry();

  // Feedback visivo
  const btn = document.getElementById('saveBtn');
  const oldText = btn.textContent;
  btn.textContent = '✅ Salvata!';
  btn.style.background = 'var(--success)';
  setTimeout(() => { btn.textContent = oldText; btn.style.background = ''; }, 1500);
}

function exportCSV() {
  if (registry.length === 0) { alert('Registro vuoto'); return; }

  const headers = ['Data','Casa','Trasferta','P1','PX','P2','Over25','GG','TopEsatto','LambdaH','LambdaA','Salvata'];
  let csv = headers.join(';') + '\n';

  for (const r of registry) {
    csv += [
      r.date, r.home, r.away,
      (r.p1 * 100).toFixed(1), (r.px * 100).toFixed(1), (r.p2 * 100).toFixed(1),
      (r.pOver * 100).toFixed(1), (r.pGG * 100).toFixed(1),
      r.topExact, r.lambdaH, r.lambdaA, r.savedAt
    ].join(';') + '\n';
  }

  const blob = new Blob([csv], {type: 'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'registro_previsioni.csv';
  a.click();
  URL.revokeObjectURL(url);
}

// ===================== EVENT LISTENERS =====================
document.getElementById('compSelect').addEventListener('change', (e) => {
  populateMatches(e.target.value);
  document.getElementById('dataCard').style.display = 'none';
  document.getElementById('predictionCard').style.display = 'none';
});

document.getElementById('matchSelect').addEventListener('change', (e) => {
  const compId = document.getElementById('compSelect').value;
  const matchId = e.target.value;
  if (!compId || !matchId) return;

  const fixtures = allData.competitions[compId].fixtures;
  const fixture = fixtures.find(f => String(f.id) === matchId);
  if (fixture) showMatchData(fixture);
});

document.getElementById('saveBtn').addEventListener('click', saveToRegistry);
document.getElementById('exportBtn').addEventListener('click', exportCSV);
document.getElementById('clearBtn').addEventListener('click', () => {
  if (confirm('Svuotare tutto il registro?')) {
    registry = [];
    localStorage.removeItem('simRegistry');
    renderRegistry();
  }
});

// Modal manuale
const modal = document.getElementById('manualModal');
document.getElementById('manualBtn').addEventListener('click', () => {
  modal.style.display = 'block';
});
document.querySelector('.close').addEventListener('click', () => {
  modal.style.display = 'none';
});
window.addEventListener('click', (e) => {
  if (e.target === modal) modal.style.display = 'none';
});

document.getElementById('mCalcBtn').addEventListener('click', () => {
  const homeName = document.getElementById('mHomeName').value || 'Casa';
  const awayName = document.getElementById('mAwayName').value || 'Trasferta';
  const hGF = parseFloat(document.getElementById('mHomeGF').value) || 1.5;
  const hGA = parseFloat(document.getElementById('mHomeGA').value) || 1.2;
  const aGF = parseFloat(document.getElementById('mAwayGF').value) || 1.3;
  const aGA = parseFloat(document.getElementById('mAwayGA').value) || 1.4;
  const hForm = document.getElementById('mHomeForm').value;
  const aForm = document.getElementById('mAwayForm').value;

  const [lamH, lamA] = computeLambdasManual(hGF, hGA, aGF, aGA, hForm, aForm);

  // Calibrazione quote manuale (semplificata)
  const q1 = parseFloat(document.getElementById('mOdd1').value);
  const qX = parseFloat(document.getElementById('mOddX').value);
  const q2 = parseFloat(document.getElementById('mOdd2').value);

  let finalLamH = lamH, finalLamA = lamA;
  if (q1 && qX && q2) {
    const raw = [1/q1, 1/qX, 1/q2];
    const margin = raw.reduce((a, b) => a + b, 0);
    const [p1m, pxm, p2m] = raw.map(r => r / margin);

    // Ricerca semplice per adattare lambda alle quote
    let best = null, bestScore = Infinity;
    for (let sh = 0.7; sh <= 1.3; sh += 0.05) {
      for (let sa = 0.7; sa <= 1.3; sa += 0.05) {
        const test = dixonColesMatrix(lamH * sh, lamA * sa, RHO_DEFAULT);
        const score = Math.pow(test.p1 - p1m, 2) + Math.pow(test.px - pxm, 2) + Math.pow(test.p2 - p2m, 2);
        if (score < bestScore) { bestScore = score; best = [lamH * sh, lamA * sa]; }
      }
    }
    if (best) { finalLamH = best[0]; finalLamA = best[1]; }
  }

  const pred = dixonColesMatrix(finalLamH, finalLamA, RHO_DEFAULT);

  // Crea un fixture fittizio per la visualizzazione
  currentMatch = {
    date: new Date().toISOString().slice(0, 10),
    homeTeam: homeName,
    awayTeam: awayName,
    homeStats: { gf_pg: hGF, ga_pg: hGA, form: hForm, elo: 1500, played: 0 },
    awayStats: { gf_pg: aGF, ga_pg: aGA, form: aForm, elo: 1500, played: 0 },
    odds: null,
    prediction: {
      p1: pred.p1, px: pred.px, p2: pred.p2,
      pOver25: pred.pOver25, pUnder25: pred.pUnder25,
      pGG: pred.pGG, pNG: pred.pNG,
      topExact: pred.topExact.map(x => [x.score, x.prob]),
      totalGoalsDist: pred.totalGoalsDist,
      lambdaH: pred.lamH, lambdaA: pred.lamA, rho: pred.rho
    }
  };

  document.getElementById('dataCard').style.display = 'block';
  document.getElementById('predictionCard').style.display = 'block';

  // Aggiorna UI con dati manuali
  document.getElementById('homeName').textContent = homeName;
  document.getElementById('homeElo').textContent = 'Elo —';
  document.getElementById('homeGF').textContent = hGF;
  document.getElementById('homeGA').textContent = hGA;
  document.getElementById('homeForm').textContent = hForm || '—';
  document.getElementById('homePlayed').textContent = '—';

  document.getElementById('awayName').textContent = awayName;
  document.getElementById('awayElo').textContent = 'Elo —';
  document.getElementById('awayGF').textContent = aGF;
  document.getElementById('awayGA').textContent = aGA;
  document.getElementById('awayForm').textContent = aForm || '—';
  document.getElementById('awayPlayed').textContent = '—';

  document.getElementById('oddsRow').style.display = 'none';

  const mOver = parseFloat(document.getElementById('mOddOver').value);
  const mUnder = parseFloat(document.getElementById('mOddUnder').value);
  const manualOdds = (q1 && qX && q2) ? {'1': q1, 'X': qX, '2': q2, over25: mOver || null, under25: mUnder || null} : null;
  currentMatch.prediction.value = computeValueJS(currentMatch.prediction, manualOdds);

  currentMatch._basePrediction = JSON.parse(JSON.stringify(currentMatch.prediction));
  showPrediction(currentMatch.prediction);
  renderOddsInput(currentMatch);
  modal.style.display = 'none';
});

// ===================== INIT =====================
loadData();
renderRegistry();


// ===================== Crediti API =====================
function renderCreditsBadge(credits) {
  const row = document.querySelector('.badge-row');
  if (!row) return;
  let b = document.getElementById('creditsBadge');
  if (!b) {
    b = document.createElement('span');
    b.className = 'badge';
    b.id = 'creditsBadge';
    row.appendChild(b);
  }
  if (credits && credits.remaining != null) {
    const rem = parseInt(credits.remaining, 10);
    b.textContent = '\uD83E\uDE99 Crediti Odds API: ' + rem + '/500' + (credits.stale ? ' (ultimo dato)' : '');
    b.title = credits.stale
      ? 'Nessuna chiamata alle quote in questo aggiornamento: valore rilevato l\u2019ultima volta che l\u2019API \u00E8 stata interrogata.'
      : 'Crediti residui del mese, letti direttamente dalla risposta di The Odds API.';
    b.style.background = rem < 60 ? '#7a1f1f' : (rem < 150 ? '#7a5c1f' : '');
  } else {
    const w = (allData && allData.oddsWindowDays) ? allData.oddsWindowDays : 7;
    b.textContent = '\uD83E\uDE99 Quote: nessuna chiamata (nessuna partita entro ' + w + " giorni)";
    b.title = 'Le quote si scaricano solo per le competizioni che giocano entro ' + w +
              ' giorni, per non consumare crediti inutilmente. Il contatore torner\u00E0 appena si avvicina una giornata.';
    b.style.background = '';
  }
}

// ===================== Track record & calibrazione =====================
async function loadTrackRecord() {
  try {
    const res = await fetch('data/track_record.json?t=' + Date.now());
    if (!res.ok) return;
    renderTrackRecord(await res.json());
  } catch (e) { /* file non ancora generato: ok */ }
}

function renderTrackRecord(tr) {
  let card = document.getElementById('trackCard');
  if (!card) {
    card = document.createElement('section');
    card.className = 'card';
    card.id = 'trackCard';
    const footer = document.querySelector('footer');
    footer.parentNode.insertBefore(card, footer);
  }
  if (!tr || !tr.graded) {
    card.innerHTML = '<h2>\uD83D\uDCC8 Verifica del modello</h2>' +
      '<p class="note">Nessuna partita valutata ancora: le predizioni si accumulano a ogni aggiornamento e i risultati si agganciano da soli quando le partite finiscono. Torna dopo la prima giornata.</p>';
    return;
  }
  const vb = tr.valueBets || {};
  const roiPct = vb.roi != null ? (vb.roi * 100).toFixed(1) + '%' : '\u2014';
  const roiCls = vb.roi > 0 ? 'stat-good' : (vb.roi < 0 ? 'stat-bad' : '');
  let html = '<h2>\uD83D\uDCC8 Verifica del modello (esiti reali)</h2>';
  html += '<div class="track-summary">' +
    '<div><span class="stat-label">Partite valutate</span><span class="stat-big">' + tr.graded + '</span></div>' +
    '<div><span class="stat-label">In attesa</span><span class="stat-big">' + tr.pending + '</span></div>' +
    '<div><span class="stat-label">Brier score</span><span class="stat-big">' + (tr.brier != null ? tr.brier.toFixed(3) : '\u2014') + '</span></div>' +
    '<div><span class="stat-label">Value bet</span><span class="stat-big">' + (vb.n || 0) + '</span></div>' +
    '<div><span class="stat-label">P&amp;L (1u fissa)</span><span class="stat-big ' + roiCls + '">' + (vb.profitUnits >= 0 ? '+' : '') + (vb.profitUnits || 0).toFixed(2) + 'u</span></div>' +
    '<div><span class="stat-label">ROI</span><span class="stat-big ' + roiCls + '">' + roiPct + '</span></div>' +
    '</div>';

  // grafico di calibrazione: per ogni fascia, barra prevista vs barra reale
  html += '<div class="sub-card"><h3>\uD83C\uDFAF Calibrazione \u2014 prevista vs realta\u0300</h3>';
  html += '<p class="note">Se il modello \u00E8 onesto, le due barre di ogni fascia sono simili: quando dice 60%, deve succedere ~60% delle volte. Con poche partite le differenze sono normali.</p>';
  html += '<div class="calib-chart">';
  for (const b of tr.calibration) {
    const pred = b.avgPred != null ? b.avgPred * 100 : 0;
    const act = b.actualFreq != null ? b.actualFreq * 100 : 0;
    html += '<div class="calib-row">' +
      '<span class="calib-label">' + b.bin + ' <em>(n=' + b.n + ')</em></span>' +
      '<div class="calib-bars">' +
        '<div class="calib-bar pred" style="width:' + pred.toFixed(0) + '%"><span>' + (b.avgPred != null ? pred.toFixed(0) + '%' : '\u2014') + '</span></div>' +
        '<div class="calib-bar act" style="width:' + act.toFixed(0) + '%"><span>' + (b.actualFreq != null ? act.toFixed(0) + '%' : '\u2014') + '</span></div>' +
      '</div></div>';
  }
  html += '</div><div class="calib-legend"><span><i class="dot pred-dot"></i> Prevista dal modello</span><span><i class="dot act-dot"></i> Frequenza reale</span></div></div>';

  // storico value bet
  if (vb.history && vb.history.length) {
    html += '<div class="sub-card"><h3>\uD83D\uDCB0 Storico value bet</h3><div class="value-table">';
    html += '<div class="value-row value-head"><span>Data</span><span>Partita</span><span>Mercato</span><span>Quota</span><span>P&amp;L cum.</span></div>';
    for (const b of vb.history.slice(-15).reverse()) {
      html += '<div class="value-row ' + (b.won ? 'value-pos' : 'value-neg') + '">' +
        '<span>' + b.date + '</span><span>' + b.match + '</span><span>' + b.market + '</span>' +
        '<span>' + b.odds.toFixed(2) + '</span><span>' + (b.cum >= 0 ? '+' : '') + b.cum.toFixed(2) + 'u</span></div>';
    }
    html += '</div></div>';
  }
  card.innerHTML = html;
}


// ===================== Calibrazione con quote inserite a mano =====================
// Stessa logica del modello Python: le quote 1-X-2 fissano la differenza tra le
// squadre, le quote Over/Under la somma dei gol. Ricerca a griglia raffinata.
function calibrateOddsJS(lamH, lamA, odds, rho, weight) {
  if (!odds) return [lamH, lamA];
  let t1x2 = null, tOU = null;
  const q1 = odds['1'], qX = odds['X'], q2 = odds['2'];
  if (q1 > 1 && qX > 1 && q2 > 1) {
    const raw = [1/q1, 1/qX, 1/q2];
    const s = raw[0] + raw[1] + raw[2];
    t1x2 = raw.map(r => r / s);
  }
  const qo = odds.over25, qu = odds.under25;
  if (qo > 1 && qu > 1) { tOU = (1/qo) / (1/qo + 1/qu); }
  if (!t1x2 && !tOU) return [lamH, lamA];

  function loss(lh, la) {
    if (lh <= 0.1 || la <= 0.1 || lh > 6 || la > 6) return 1e3;
    const r = dixonColesMatrix(lh, la, rho);
    let e = 0;
    if (t1x2) e += Math.pow(r.p1 - t1x2[0], 2) + Math.pow(r.px - t1x2[1], 2) + Math.pow(r.p2 - t1x2[2], 2);
    if (tOU !== null) e += Math.pow(r.pOver25 - tOU, 2);
    return e;
  }

  // ricerca locale progressivamente piu' fine (equivalente pratico dell'ottimizzatore)
  let bh = lamH, ba = lamA, bs = loss(bh, ba);
  let step = 0.4;
  for (let it = 0; it < 6; it++) {
    let improved = true;
    while (improved) {
      improved = false;
      const cand = [[bh+step, ba], [bh-step, ba], [bh, ba+step], [bh, ba-step],
                    [bh+step, ba+step], [bh-step, ba-step], [bh+step, ba-step], [bh-step, ba+step]];
      for (const [ch, ca] of cand) {
        const sc = loss(ch, ca);
        if (sc < bs - 1e-9) { bs = sc; bh = ch; ba = ca; improved = true; }
      }
    }
    step /= 2.5;
  }
  bh = Math.max(0.3, Math.min(bh, 4.0));
  ba = Math.max(0.3, Math.min(ba, 3.5));
  const w = (weight == null ? 0.25 : weight);
  return [(1-w)*lamH + w*bh, (1-w)*lamA + w*ba];
}

// Pannello per inserire le quote a mano su una partita gia' selezionata
function renderOddsInput(fixture) {
  const card = document.getElementById('predictionCard');
  if (!card) return;
  let box = document.getElementById('manualOddsBox');
  if (!box) {
    box = document.createElement('div');
    box.className = 'sub-card';
    box.id = 'manualOddsBox';
    const vc = document.getElementById('valueCard');
    if (vc) card.insertBefore(box, vc); else card.appendChild(box);
  }
  const o = (fixture && fixture.odds) || {};
  const has = !!o['1'];
  box.innerHTML =
    '<h3>\u270F\uFE0F Quote tue (Eurobet, Sisal, o quelle che usi)</h3>' +
    '<p class="note">' + (has
      ? 'Sono gia\u0300 presenti quote automatiche. Inserendo le tue, il modello si ricalibra e ricalcola il valore su QUELLE quote.'
      : 'Per questa partita non ci sono quote automatiche: le statistiche ci sono, mancano solo le quote. Inseriscile qui e il modello le user\u00E0 per calibrarsi e cercare valore.') + '</p>' +
    '<div class="odds-inputs manual-odds">' +
      '<label>1<input type="number" step="0.01" id="uOdd1" placeholder="1" value="' + (o['1'] || '') + '"></label>' +
      '<label>X<input type="number" step="0.01" id="uOddX" placeholder="X" value="' + (o['X'] || '') + '"></label>' +
      '<label>2<input type="number" step="0.01" id="uOdd2" placeholder="2" value="' + (o['2'] || '') + '"></label>' +
      '<label>Over 2.5<input type="number" step="0.01" id="uOddOver" placeholder="O 2.5" value="' + (o.over25 || '') + '"></label>' +
      '<label>Under 2.5<input type="number" step="0.01" id="uOddUnder" placeholder="U 2.5" value="' + (o.under25 || '') + '"></label>' +
    '</div>' +
    '<div class="manual-odds-actions">' +
      '<button id="applyOddsBtn" class="btn-primary">\uD83C\uDFAF Ricalcola con queste quote</button>' +
      '<button id="resetOddsBtn" class="btn-secondary">\u21A9\uFE0F Torna al modello puro</button>' +
    '</div>';

  document.getElementById('applyOddsBtn').addEventListener('click', applyManualOdds);
  document.getElementById('resetOddsBtn').addEventListener('click', () => {
    if (!currentMatch || !currentMatch._basePrediction) return;
    currentMatch.prediction = JSON.parse(JSON.stringify(currentMatch._basePrediction));
    showPrediction(currentMatch.prediction);
  });
}

function applyManualOdds() {
  if (!currentMatch) return;
  const num = id => { const v = parseFloat(document.getElementById(id).value); return (v > 1) ? v : null; };
  const odds = {'1': num('uOdd1'), 'X': num('uOddX'), '2': num('uOdd2'),
                over25: num('uOddOver'), under25: num('uOddUnder')};
  const hasAny = odds['1'] || odds.over25;
  if (!hasAny) { alert('Inserisci almeno la tripla 1-X-2 oppure Over/Under 2.5.'); return; }

  const base = currentMatch._basePrediction || currentMatch.prediction;
  const rho = base.rho || RHO_DEFAULT;
  // Riparte SEMPRE dai lambda grezzi (pre-calibrazione), per non applicare due volte il mercato
  const lamH0 = base.lambdaHRaw != null ? base.lambdaHRaw : base.lambdaH;
  const lamA0 = base.lambdaARaw != null ? base.lambdaARaw : base.lambdaA;
  const w = base.marketWeight != null ? base.marketWeight : 0.25;

  const [lh, la] = calibrateOddsJS(lamH0, lamA0, odds, rho, w);
  const r = dixonColesMatrix(lh, la, rho);
  const pred = {
    p1: r.p1, px: r.px, p2: r.p2,
    pOver25: r.pOver25, pUnder25: r.pUnder25, pGG: r.pGG, pNG: r.pNG,
    topExact: r.topExact.map(x => [x.score, x.prob]),
    totalGoalsDist: r.totalGoalsDist,
    lambdaH: r.lamH, lambdaA: r.lamA, rho: rho,
    lambdaHRaw: lamH0, lambdaARaw: lamA0, marketWeight: w,
    manualOdds: true
  };
  pred.value = computeValueJS(pred, odds);
  currentMatch.prediction = pred;
  currentMatch.odds = Object.assign({}, currentMatch.odds || {}, odds);
  showPrediction(pred);

  // aggiorna anche il riquadro quote in alto
  const row = document.getElementById('oddsRow');
  if (row) {
    row.style.display = '';
    document.getElementById('odd1').textContent = formatOdd(odds['1']);
    document.getElementById('oddX').textContent = formatOdd(odds['X']);
    document.getElementById('odd2').textContent = formatOdd(odds['2']);
    document.getElementById('oddOver').textContent = formatOdd(odds.over25);
    document.getElementById('oddUnder').textContent = formatOdd(odds.under25);
    document.getElementById('oddsNote').textContent = '\u270F\uFE0F Quote inserite manualmente da te';
  }
}


// Il bottone "Ricalcola" nella pagina non aveva alcun handler: ora rietichetta
// e porta al pannello delle quote manuali.
(function () {
  const b = document.getElementById('simulateBtn');
  if (!b) return;
  b.textContent = '\u270F\uFE0F Usa le tue quote';
  b.addEventListener('click', () => {
    const box = document.getElementById('manualOddsBox');
    if (box) {
      box.scrollIntoView({behavior: 'smooth', block: 'center'});
      const f = document.getElementById('uOdd1');
      if (f) f.focus();
    }
  });
})();


// Il riquadro quota "GG" restava sempre vuoto: il mercato btts non viene
// scaricato (costerebbe crediti e farebbe sforare il tetto gratuito).
function removeUnusedOddsBoxes() {
  const el = document.getElementById('oddGG');
  if (el && el.parentElement) el.parentElement.remove();
}


// ===================== Legenda / note esplicative =====================
const GLOSSARY = [
  ['Elo', 'Punteggio di forza della squadra. Parte da 1500 e sale o scende dopo ogni partita: si guadagna battendo squadre forti, si perde cedendo alle deboli, e conta anche il divario di gol. Sopra 1500 = sopra la media della lega. Una differenza di ~100 punti \u00E8 uno scarto netto di livello. \u00C8 memoria permanente: si accumula run dopo run, non riparte da zero.'],
  ['\u03BB (lambda)', 'I gol attesi: \u03BB casa 1.60 significa che il modello si aspetta in media 1,60 gol dalla squadra di casa. Da questi due numeri nascono tutte le probabilit\u00E0.'],
  ['\u03C1 (rho)', 'Correzione Dixon-Coles sui risultati bassi (0-0, 1-0, 0-1, 1-1), che nel calcio reale capitano pi\u00F9 spesso di quanto direbbe una Poisson pura. \u00C8 sempre un numero negativo piccolo.'],
  ['Vantaggio (EV / edge)', 'Quanto guadagni in media per ogni euro puntato, SE il modello ha ragione. Si calcola: probabilit\u00E0 del modello \u00D7 quota \u2212 1. Esempio: il modello d\u00E0 40% e la quota \u00E8 3.00 \u2192 0,40 \u00D7 3,00 \u2212 1 = +20%. Sotto zero la quota \u00E8 pagata meno del giusto. Serve almeno +3% per essere segnalata.'],
  ['\u00BD Kelly', 'Quanto puntare, in percentuale del tuo bankroll totale (non della singola giocata). Il criterio di Kelly massimizza la crescita nel lungo periodo; io mostro la met\u00E0 e non oltre il 5%, perch\u00E9 il Kelly pieno \u00E8 troppo aggressivo quando le probabilit\u00E0 sono stimate e non certe.'],
  ['Brier score', 'Errore medio delle probabilit\u00E0 sugli esiti gi\u00E0 avvenuti: pi\u00F9 basso \u00E8, meglio il modello prevede. Come riferimento, 0,25 equivale a tirare a caso su un evento 50/50.'],
  ['Calibrazione', 'Il controllo di onest\u00E0 del modello: quando dice 60%, l\u2019evento deve succedere circa il 60% delle volte. Nel grafico, barra blu = probabilit\u00E0 prevista, barra verde = frequenza reale. Simili = modello affidabile.'],
  ['Forma', 'Esiti delle ultime 5 partite ufficiali, dalla pi\u00F9 recente: W vittoria, D pareggio, L sconfitta.']
];

function renderGlossary() {
  if (document.getElementById('glossaryCard')) return;
  const footer = document.querySelector('footer');
  if (!footer) return;
  const sec = document.createElement('section');
  sec.className = 'card';
  sec.id = 'glossaryCard';
  let html = '<h2 id="glossaryToggle" class="collapsible">\uD83D\uDCD6 Legenda \u2014 cosa significano i numeri <span class="chev">\u25BE</span></h2>';
  html += '<div id="glossaryBody" class="glossary-body">';
  for (const [term, desc] of GLOSSARY) {
    html += '<div class="gloss-item"><span class="gloss-term">' + term + '</span><span class="gloss-desc">' + desc + '</span></div>';
  }
  html += '<p class="note">Le probabilit\u00E0 sono stime statistiche: non tengono conto di infortuni, squalifiche, turnover o motivazioni. Gioca solo ci\u00F2 che puoi permetterti di perdere.</p>';
  html += '</div>';
  sec.innerHTML = html;
  footer.parentNode.insertBefore(sec, footer);
  document.getElementById('glossaryToggle').addEventListener('click', () => {
    const b = document.getElementById('glossaryBody');
    const open = b.classList.toggle('open');
    sec.querySelector('.chev').textContent = open ? '\u25B4' : '\u25BE';
  });
}

// Note brevi in linea, accanto alle sezioni a cui si riferiscono
function renderInlineHints() {
  const cmp = document.querySelector('.teams-comparison');
  if (cmp && !document.getElementById('eloHint')) {
    const p = document.createElement('p');
    p.className = 'note hint';
    p.id = 'eloHint';
    p.innerHTML = '\u2139\uFE0F <strong>Elo</strong>: forza della squadra, base 1500. Sopra = sopra la media; ~100 punti di differenza = uno scarto netto di livello. <strong>Forma</strong>: ultime 5 gare (W vittoria, D pari, L sconfitta), dalla pi\u00F9 recente.';
    cmp.parentNode.insertBefore(p, cmp.nextSibling);
  }
  const params = document.querySelector('.params-box');
  if (params && !document.getElementById('lambdaHint')) {
    const p = document.createElement('p');
    p.className = 'note hint';
    p.id = 'lambdaHint';
    p.innerHTML = '\u2139\uFE0F <strong>\u03BB</strong> = gol attesi da ciascuna squadra. <strong>\u03C1</strong> = correzione sui risultati bassi (0-0, 1-1), tipici del calcio reale.';
    params.parentNode.insertBefore(p, params.nextSibling);
  }
}


// ===================== Importa registro da CSV =====================
// Ripristina un registro esportato in precedenza (o dopo aver svuotato la cache),
// e permette di unire registri salvati da dispositivi diversi.
function renderImportControl() {
  const actions = document.querySelector('.registry-actions');
  if (!actions || document.getElementById('importBtn')) return;

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.csv,text/csv';
  input.id = 'importFile';
  input.style.display = 'none';

  const btn = document.createElement('button');
  btn.id = 'importBtn';
  btn.className = 'btn-secondary';
  btn.textContent = '\u2B06\uFE0F Importa CSV';
  btn.addEventListener('click', () => input.click());

  input.addEventListener('change', (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { importCSV(String(reader.result)); input.value = ''; };
    reader.onerror = () => alert('Impossibile leggere il file.');
    reader.readAsText(file, 'utf-8');
  });

  actions.insertBefore(btn, actions.firstChild.nextSibling);
  actions.appendChild(input);
}

function parseCSVLine(line, sep) {
  // gestisce i campi tra virgolette (nomi squadra con separatore dentro)
  const out = []; let cur = ''; let q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') {
      if (q && line[i+1] === '"') { cur += '"'; i++; } else { q = !q; }
    } else if (c === sep && !q) { out.push(cur); cur = ''; }
    else { cur += c; }
  }
  out.push(cur);
  return out.map(x => x.trim());
}

function importCSV(text) {
  const lines = text.split(/\r?\n/).filter(l => l.trim().length);
  if (lines.length < 2) { alert('Il file non contiene righe da importare.'); return; }

  // separatore: ';' (formato esportato) oppure ',' se il file arriva da Excel inglese
  const sep = (lines[0].split(';').length >= lines[0].split(',').length) ? ';' : ',';
  const head = parseCSVLine(lines[0], sep).map(h => h.toLowerCase());
  const idx = n => head.indexOf(n);
  const iDate = idx('data'), iHome = idx('casa'), iAway = idx('trasferta');
  if (iDate < 0 || iHome < 0 || iAway < 0) {
    alert('Intestazioni non riconosciute. Servono almeno le colonne: Data; Casa; Trasferta.');
    return;
  }
  const iP1 = idx('p1'), iPX = idx('px'), iP2 = idx('p2'),
        iOv = idx('over25'), iGG = idx('gg'), iTop = idx('topesatto'),
        iLH = idx('lambdah'), iLA = idx('lambdaa'), iSaved = idx('salvata');

  // percentuali salvate come "45.9" -> 0.459 ; accetta anche la virgola decimale
  const pct = v => { const n = parseFloat(String(v).replace(',', '.')); return isFinite(n) ? n/100 : null; };
  const num = v => { const n = parseFloat(String(v).replace(',', '.')); return isFinite(n) ? n : null; };

  // chiave anti-duplicati: stessa data + stesse squadre
  const key = r => (r.date + '|' + (r.home||'').toLowerCase() + '|' + (r.away||'').toLowerCase());
  const existing = new Set(registry.map(key));

  let added = 0, skipped = 0, bad = 0;
  for (let i = 1; i < lines.length; i++) {
    const c = parseCSVLine(lines[i], sep);
    if (c.length < 3) { bad++; continue; }
    const entry = {
      id: Date.now() + i,
      date: c[iDate], home: c[iHome], away: c[iAway],
      p1: iP1 >= 0 ? pct(c[iP1]) : null,
      px: iPX >= 0 ? pct(c[iPX]) : null,
      p2: iP2 >= 0 ? pct(c[iP2]) : null,
      pOver: iOv >= 0 ? pct(c[iOv]) : null,
      pGG: iGG >= 0 ? pct(c[iGG]) : null,
      topExact: iTop >= 0 ? c[iTop] : '',
      lambdaH: iLH >= 0 ? num(c[iLH]) : null,
      lambdaA: iLA >= 0 ? num(c[iLA]) : null,
      savedAt: (iSaved >= 0 && c[iSaved]) ? c[iSaved] : new Date().toISOString(),
      imported: true
    };
    if (!entry.date || !entry.home || !entry.away) { bad++; continue; }
    if (existing.has(key(entry))) { skipped++; continue; }
    existing.add(key(entry));
    registry.push(entry);
    added++;
  }

  try {
    localStorage.setItem('simRegistry', JSON.stringify(registry));
  } catch (e) {
    alert('Spazio del browser esaurito: esporta e ripulisci il registro prima di importare altro.');
    return;
  }
  renderRegistry();
  alert('Importate ' + added + ' righe.' +
        (skipped ? '\n' + skipped + ' gia\u0300 presenti (saltate).' : '') +
        (bad ? '\n' + bad + ' righe non leggibili (ignorate).' : ''));
}


// ===================== Calcolatore multipla e sistema =====================
let multiEvents = [];
let multiTypeTouched = false;
let multiRegistry = JSON.parse(localStorage.getItem('simMultiRegistry') || '[]');
let lastMultiResult = null;

function nCk(n, k) {
  if (k < 0 || k > n) return 0;
  let r = 1;
  for (let i = 1; i <= k; i++) r = r * (n - k + i) / i;
  return Math.round(r);
}

// polinomio simmetrico elementare: somma dei prodotti di tutti i sottoinsiemi di k quote
function esym(arr, k) {
  const e = new Array(k + 1).fill(0);
  e[0] = 1;
  for (const x of arr) {
    for (let j = Math.min(k, e.length - 1); j >= 1; j--) e[j] += e[j - 1] * x;
  }
  return e[k];
}

// Enumera tutti gli scenari possibili (2^N) e calcola il ritorno atteso esatto.
function computeSystem(events, K, unit, bonusPct) {
  const N = events.length;
  const nCombos = nCk(N, K);
  const stake = nCombos * unit;
  let ev = 0, pProfit = 0, pAnyReturn = 0;
  const byWins = {};
  for (let mask = 0; mask < (1 << N); mask++) {
    let p = 1, wins = 0;
    const winOdds = [];
    for (let i = 0; i < N; i++) {
      if (mask & (1 << i)) { p *= events[i].p; winOdds.push(events[i].odds); wins++; }
      else p *= (1 - events[i].p);
    }
    let payout = wins >= K ? unit * esym(winOdds, K) : 0;
    if (wins === N && bonusPct > 0) payout *= (1 + bonusPct);
    ev += p * payout;
    if (payout > stake + 1e-9) pProfit += p;
    if (payout > 1e-9) pAnyReturn += p;
    if (!byWins[wins]) byWins[wins] = {p: 0, pay: 0};
    byWins[wins].p += p;
    byWins[wins].pay += p * payout;
  }
  return {N, K, nCombos, stake, ev, net: ev - stake, roi: stake > 0 ? (ev - stake) / stake : 0,
          pProfit, pAnyReturn, byWins,
          totalOdds: events.reduce((a, e) => a * e.odds, 1),
          pAll: events.reduce((a, e) => a * e.p, 1)};
}

function renderMultiCalc() {
  if (document.getElementById('multiCard')) return;
  const footer = document.querySelector('footer');
  if (!footer) return;
  const sec = document.createElement('section');
  sec.className = 'card';
  sec.id = 'multiCard';
  sec.innerHTML =
    '<h2>\uD83C\uDFB0 Calcolatore multipla e sistema</h2>' +
    '<p class="note">Inserisci gli eventi con la probabilit\u00E0 stimata dal modello e la quota offerta. ' +
    'Il calcolo ti dice se la giocata ha senso <em>secondo il modello</em>, e quanto \u00E8 fragile a un suo errore.</p>' +
    '<div id="multiRows"></div>' +
    '<div class="multi-add">' +
      '<button id="multiAddRow" class="btn-secondary">\u2795 Aggiungi evento</button>' +
      '<button id="multiAddCurrent" class="btn-secondary">\uD83C\uDFAF Aggiungi partita selezionata</button>' +
      '<button id="multiClear" class="btn-danger">\uD83D\uDDD1\uFE0F Svuota</button>' +
    '</div>' +
    '<div class="multi-params">' +
      '<label>Tipo giocata<select id="multiType"></select></label>' +
      '<label>Puntata per combinazione (\u20AC)<input type="number" id="multiStake" value="2" step="0.5" min="0.1"></label>' +
      '<label>Bonus multipla (%)<input type="number" id="multiBonus" value="0" step="1" min="0" max="200"></label>' +
    '</div>' +
    '<div id="multiResult"></div>' +
    '<div class="multi-add" id="multiSaveRow">' +
      '<button id="multiSaveBtn" class="btn-primary">\uD83D\uDCBE Salva simulazione</button>' +
      '<button id="multiExportBtn" class="btn-secondary">\u2B07\uFE0F Esporta CSV</button>' +
      '<button id="multiImportBtn" class="btn-secondary">\u2B06\uFE0F Importa CSV</button>' +
      '<input type="file" id="multiImportFile" accept=".csv,text/csv" style="display:none">' +
    '</div>' +
    '<div id="multiRegistryBox"></div>';
  footer.parentNode.insertBefore(sec, footer);

  document.getElementById('multiSaveBtn').addEventListener('click', saveMultiSimulation);
  document.getElementById('multiExportBtn').addEventListener('click', exportMultiCSV);
  document.getElementById('multiImportBtn').addEventListener('click', () => document.getElementById('multiImportFile').click());
  document.getElementById('multiImportFile').addEventListener('change', ev => {
    const f = ev.target.files && ev.target.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => { importMultiCSV(String(rd.result)); ev.target.value = ''; };
    rd.readAsText(f, 'utf-8');
  });
  document.getElementById('multiAddRow').addEventListener('click', () => { addMultiRow(); });
  document.getElementById('multiAddCurrent').addEventListener('click', addCurrentToMulti);
  document.getElementById('multiClear').addEventListener('click', () => { multiEvents = []; multiTypeTouched = false; renderMultiRows(); });
  document.getElementById('multiType').addEventListener('change', () => {
    multiTypeTouched = true;
    recomputeMulti();
  });
  ['multiStake', 'multiBonus'].forEach(id => {
    document.getElementById(id).addEventListener('change', recomputeMulti);
    document.getElementById(id).addEventListener('input', recomputeMulti);
  });
  renderMultiRows();
  renderMultiRegistry();
}

function addMultiRow(prefill) {
  if (multiEvents.length >= 12) { alert('Massimo 12 eventi.'); return; }
  multiEvents.push(prefill || {label: 'Evento ' + (multiEvents.length + 1), p: 0.60, odds: 1.70});
  renderMultiRows();
}

function addCurrentToMulti() {
  if (!currentMatch || !currentMatch.prediction) {
    alert('Seleziona prima una partita.');
    return;
  }
  const p = currentMatch.prediction;
  const o = currentMatch.odds || {};
  const best = o.best || o;
  const opts = [
    ['1 (' + currentMatch.homeTeam + ')', p.p1, best['1']],
    ['X (pareggio)', p.px, best['X']],
    ['2 (' + currentMatch.awayTeam + ')', p.p2, best['2']],
    ['Over 2.5', p.pOver25, best.over25],
    ['Under 2.5', p.pUnder25, best.under25]
  ];
  let msg = 'Quale esito vuoi aggiungere?\n';
  opts.forEach((o2, i) => { msg += (i + 1) + ') ' + o2[0] + ' \u2014 modello ' + (o2[1] * 100).toFixed(1) + '%\n'; });
  const choice = prompt(msg + '\nScrivi il numero (1-5):', '1');
  const i = parseInt(choice, 10) - 1;
  if (isNaN(i) || i < 0 || i > 4) return;
  addMultiRow({
    label: currentMatch.homeTeam + '-' + currentMatch.awayTeam + ' \u00B7 ' + opts[i][0].split(' (')[0],
    p: opts[i][1],
    odds: opts[i][2] || Math.round((1 / opts[i][1]) * 100) / 100
  });
}

function renderMultiRows() {
  const box = document.getElementById('multiRows');
  if (!box) return;
  if (!multiEvents.length) {
    box.innerHTML = '<p class="note">Nessun evento. Aggiungine almeno due.</p>';
  } else {
    let html = '<div class="multi-head"><span>Evento</span><span>Prob. modello %</span><span>Quota</span><span></span></div>';
    multiEvents.forEach((e, i) => {
      html += '<div class="multi-row">' +
        '<input type="text" value="' + String(e.label).replace(/"/g, '&quot;') + '" data-i="' + i + '" data-f="label">' +
        '<input type="number" value="' + (e.p * 100).toFixed(1) + '" step="0.1" min="1" max="99" data-i="' + i + '" data-f="p">' +
        '<input type="number" value="' + e.odds + '" step="0.01" min="1.01" data-i="' + i + '" data-f="odds">' +
        '<button class="row-del" data-i="' + i + '">\u2715</button></div>';
    });
    box.innerHTML = html;
    box.querySelectorAll('input').forEach(inp => {
      inp.addEventListener('input', ev => {
        const i = +ev.target.dataset.i, f = ev.target.dataset.f;
        if (f === 'label') multiEvents[i].label = ev.target.value;
        else if (f === 'p') multiEvents[i].p = Math.min(0.99, Math.max(0.01, (parseFloat(ev.target.value) || 0) / 100));
        else multiEvents[i].odds = Math.max(1.01, parseFloat(ev.target.value) || 1.01);
        recomputeMulti();
      });
    });
    box.querySelectorAll('.row-del').forEach(b => {
      b.addEventListener('click', ev => { multiEvents.splice(+ev.target.dataset.i, 1); renderMultiRows(); });
    });
  }
  // opzioni tipo giocata
  const sel = document.getElementById('multiType');
  const N = multiEvents.length;
  const prev = sel.value;
  sel.innerHTML = '';
  for (let k = N; k >= 2; k--) {
    const opt = document.createElement('option');
    opt.value = k;
    opt.textContent = (k === N) ? ('Multipla (' + N + '/' + N + ')') : ('Sistema ' + k + '/' + N + ' \u2014 ' + nCk(N, k) + ' combinazioni');
    sel.appendChild(opt);
  }
  // Se l'utente non ha scelto esplicitamente un sistema, il default resta la multipla (N/N).
  if (multiTypeTouched && prev && sel.querySelector('option[value="' + prev + '"]')) sel.value = prev;
  else sel.value = String(N);
  recomputeMulti();
}

function recomputeMulti() {
  const out = document.getElementById('multiResult');
  if (!out) return;
  const N = multiEvents.length;
  if (N < 2) { out.innerHTML = ''; return; }
  const K = parseInt(document.getElementById('multiType').value, 10) || N;
  const unit = parseFloat(document.getElementById('multiStake').value) || 1;
  const bonus = (parseFloat(document.getElementById('multiBonus').value) || 0) / 100;

  const r = computeSystem(multiEvents, K, unit, bonus);
  lastMultiResult = {r: r, K: K, unit: unit, bonus: bonus,
                     events: multiEvents.map(e => ({label: e.label, p: e.p, odds: e.odds}))};

  // sensibilita': cosa succede se il modello sovrastima di 3 e 5 punti
  const shift = d => computeSystem(multiEvents.map(e => ({p: Math.max(0.01, e.p - d), odds: e.odds})), K, unit, bonus).roi;
  const roi3 = shift(0.03), roi5 = shift(0.05);
  // margine del bookmaker implicito
  const bookProb = multiEvents.reduce((a, e) => a * (1 / e.odds), 1); // prob. implicita nelle quote
  const modelProb = r.pAll;                                          // prob. combinata del modello
  const fairOdds = 1 / modelProb;                                    // quota "giusta" secondo il modello

  const cls = r.roi > 0 ? 'stat-good' : 'stat-bad';
  let html = '<div class="multi-summary">' +
    '<div><span class="stat-label">Combinazioni</span><span class="stat-big">' + r.nCombos + '</span></div>' +
    '<div><span class="stat-label">Puntata totale</span><span class="stat-big">' + r.stake.toFixed(2) + '\u20AC</span></div>' +
    '<div><span class="stat-label">Quota totale</span><span class="stat-big">' + r.totalOdds.toFixed(2) + '</span></div>' +
    '<div><span class="stat-label">Prob. tutti giusti</span><span class="stat-big">' + (r.pAll * 100).toFixed(2) + '%</span></div>' +
    '<div><span class="stat-label">Prob. di rientrare</span><span class="stat-big">' + (r.pProfit * 100).toFixed(1) + '%</span></div>' +
    '<div><span class="stat-label">Ritorno atteso</span><span class="stat-big">' + r.ev.toFixed(2) + '\u20AC</span></div>' +
    '<div><span class="stat-label">Rendimento</span><span class="stat-big ' + cls + '">' + (r.roi >= 0 ? '+' : '') + (r.roi * 100).toFixed(1) + '%</span></div>' +
    '</div>';

  // Confronto modello vs bookmaker
  html += '<div class="sub-card"><h3>\u2696\uFE0F Modello contro bookmaker</h3><div class="value-table">' +
    '<div class="value-row value-head"><span>Fonte</span><span>Prob. che vadano tutti bene</span><span>Quota "giusta"</span></div>' +
    '<div class="value-row"><span>Il tuo modello</span><span>' + (modelProb * 100).toFixed(2) + '%</span><span>' + (1 / modelProb).toFixed(2) + '</span></div>' +
    '<div class="value-row"><span>Il bookmaker (quote offerte)</span><span>' + (bookProb * 100).toFixed(2) + '%</span><span>' + r.totalOdds.toFixed(2) + '</span></div>' +
    '</div><p class="note">' +
    (r.totalOdds >= fairOdds
      ? 'La quota offerta (' + r.totalOdds.toFixed(2) + ') \u00E8 <strong>superiore</strong> a quella che il modello considera giusta (' + fairOdds.toFixed(2) + '): qui nasce il margine teorico.'
      : 'La quota offerta (' + r.totalOdds.toFixed(2) + ') \u00E8 <strong>inferiore</strong> a quella giusta secondo il modello (' + fairOdds.toFixed(2) + '): stai pagando pi\u00F9 del dovuto.') +
    ' Ricorda che il margine del banco si <strong>moltiplica</strong> a ogni evento aggiunto: ' +
    'per questo le multiple lunghe sono il prodotto pi\u00F9 redditizio per il bookmaker.</p></div>';

  // Sensibilita' all'errore del modello — il punto centrale
  const flip3 = roi3 < 0 && r.roi > 0;
  html += '<div class="sub-card"><h3>\uD83D\uDD0D Quanto regge se il modello sbaglia?</h3><div class="value-table">' +
    '<div class="value-row value-head"><span>Ipotesi</span><span>Rendimento</span></div>' +
    '<div class="value-row"><span>Probabilit\u00E0 esatte</span><span class="' + cls + '">' + (r.roi >= 0 ? '+' : '') + (r.roi * 100).toFixed(1) + '%</span></div>' +
    '<div class="value-row"><span>Modello sovrastima di 3 punti</span><span class="' + (roi3 >= 0 ? 'stat-good' : 'stat-bad') + '">' + (roi3 >= 0 ? '+' : '') + (roi3 * 100).toFixed(1) + '%</span></div>' +
    '<div class="value-row"><span>Modello sovrastima di 5 punti</span><span class="' + (roi5 >= 0 ? 'stat-good' : 'stat-bad') + '">' + (roi5 >= 0 ? '+' : '') + (roi5 * 100).toFixed(1) + '%</span></div>' +
    '</div>';
  if (flip3) {
    html += '<p class="note hint" style="border-left-color:#e0a800">\u26A0\uFE0F Bastano <strong>3 punti</strong> di errore del modello per far diventare negativa questa giocata. ' +
            'Finch\u00E9 la sezione "Verifica del modello" non conferma la calibrazione, quel margine \u00E8 teorico.</p>';
  }
  html += '</div>';

  // Distribuzione degli esiti
  html += '<div class="sub-card"><h3>\uD83D\uDCCA Cosa succede, esito per esito</h3><div class="value-table">' +
    '<div class="value-row value-head"><span>Eventi indovinati</span><span>Probabilit\u00E0</span><span>Incasso medio</span></div>';
  for (let w = N; w >= 0; w--) {
    const b = r.byWins[w];
    if (!b || b.p < 0.0005) continue;
    const avg = b.p > 0 ? b.pay / b.p : 0;
    html += '<div class="value-row ' + (avg > r.stake ? 'value-pos' : 'value-neg') + '">' +
      '<span>' + w + ' su ' + N + '</span><span>' + (b.p * 100).toFixed(1) + '%</span><span>' + avg.toFixed(2) + '\u20AC</span></div>';
  }
  html += '</div><p class="note">Righe verdi = incasso superiore alla puntata di ' + r.stake.toFixed(2) + '\u20AC.</p></div>';

  out.innerHTML = html;
}


// ============ Registro delle simulazioni multipla / sistema ============

function persistMultiRegistry() {
  try {
    localStorage.setItem('simMultiRegistry', JSON.stringify(multiRegistry));
    return true;
  } catch (e) {
    alert('Spazio del browser esaurito: esporta e ripulisci il registro.');
    return false;
  }
}

function saveMultiSimulation() {
  if (!lastMultiResult || lastMultiResult.events.length < 2) {
    alert('Aggiungi almeno due eventi prima di salvare.');
    return;
  }
  const L = lastMultiResult, r = L.r;
  const nome = prompt('Nome della simulazione (facoltativo):',
                      'Schedina ' + new Date().toLocaleDateString('it-IT'));
  if (nome === null) return;
  multiRegistry.push({
    id: Date.now(),
    name: nome || ('Schedina ' + new Date().toLocaleDateString('it-IT')),
    savedAt: new Date().toISOString(),
    type: (L.K === L.events.length) ? ('Multipla ' + L.K + '/' + L.events.length)
                                     : ('Sistema ' + L.K + '/' + L.events.length),
    K: L.K, N: L.events.length,
    unit: L.unit, bonus: L.bonus,
    stake: r.stake, totalOdds: r.totalOdds,
    pAll: r.pAll, pProfit: r.pProfit, ev: r.ev, roi: r.roi,
    events: L.events.map(e => ({label: e.label, p: e.p, odds: e.odds, won: null})),
    settled: false, actualReturn: null
  });
  if (persistMultiRegistry()) renderMultiRegistry();
}

// Segna quali eventi sono andati bene e calcola l'incasso reale
function settleMulti(id) {
  const sim = multiRegistry.find(x => x.id === id);
  if (!sim) return;
  const box = document.getElementById('settle-' + id);
  if (!box) return;
  const won = [...box.querySelectorAll('input[type=checkbox]')].map(c => c.checked);
  sim.events.forEach((e, i) => { e.won = won[i]; });
  const winOdds = sim.events.filter(e => e.won).map(e => e.odds);
  const nWins = winOdds.length;
  let ret = nWins >= sim.K ? sim.unit * esym(winOdds, sim.K) : 0;
  if (nWins === sim.N && sim.bonus > 0) ret *= (1 + sim.bonus);
  sim.actualReturn = ret;
  sim.nWins = nWins;
  sim.settled = true;
  if (persistMultiRegistry()) renderMultiRegistry();
}

function deleteMulti(id) {
  if (!confirm('Eliminare questa simulazione?')) return;
  multiRegistry = multiRegistry.filter(x => x.id !== id);
  if (persistMultiRegistry()) renderMultiRegistry();
}

function renderMultiRegistry() {
  const box = document.getElementById('multiRegistryBox');
  if (!box) return;
  if (!multiRegistry.length) {
    box.innerHTML = '<p class="note">Nessuna simulazione salvata. Componi una giocata e premi \uD83D\uDCBE Salva simulazione.</p>';
    return;
  }
  const settled = multiRegistry.filter(s => s.settled);
  let html = '<h3>\uD83D\uDCD2 Simulazioni salvate</h3>';

  if (settled.length) {
    const stakeTot = settled.reduce((a, s) => a + s.stake, 0);
    const retTot = settled.reduce((a, s) => a + (s.actualReturn || 0), 0);
    const evTot = settled.reduce((a, s) => a + s.ev, 0);
    const roiReal = stakeTot ? (retTot - stakeTot) / stakeTot : 0;
    const roiAtt = stakeTot ? (evTot - stakeTot) / stakeTot : 0;
    const cls = roiReal >= 0 ? 'stat-good' : 'stat-bad';
    html += '<div class="multi-summary">' +
      '<div><span class="stat-label">Giocate chiuse</span><span class="stat-big">' + settled.length + '</span></div>' +
      '<div><span class="stat-label">Puntato</span><span class="stat-big">' + stakeTot.toFixed(2) + '\u20AC</span></div>' +
      '<div><span class="stat-label">Incassato</span><span class="stat-big">' + retTot.toFixed(2) + '\u20AC</span></div>' +
      '<div><span class="stat-label">Risultato</span><span class="stat-big ' + cls + '">' + (retTot - stakeTot >= 0 ? '+' : '') + (retTot - stakeTot).toFixed(2) + '\u20AC</span></div>' +
      '<div><span class="stat-label">Rendimento reale</span><span class="stat-big ' + cls + '">' + (roiReal >= 0 ? '+' : '') + (roiReal * 100).toFixed(1) + '%</span></div>' +
      '<div><span class="stat-label">Era previsto</span><span class="stat-big">' + (roiAtt >= 0 ? '+' : '') + (roiAtt * 100).toFixed(1) + '%</span></div>' +
      '</div>';
    if (settled.length < 20) {
      html += '<p class="note hint">\u2139\uFE0F Con ' + settled.length + ' giocate chiuse questo confronto non dice ancora nulla: ' +
              'le multiple hanno esiti molto volatili e servono decine di giocate perch\u00E9 il rendimento reale ' +
              'si avvicini a quello previsto.</p>';
    }
  }

  for (const s of multiRegistry.slice().reverse()) {
    const d = new Date(s.savedAt).toLocaleDateString('it-IT');
    html += '<div class="multi-sim">';
    html += '<div class="sim-head"><strong>' + s.name + '</strong>' +
            '<span class="sim-tag">' + s.type + '</span>' +
            '<span class="sim-date">' + d + '</span>' +
            '<button class="row-del" onclick="deleteMulti(' + s.id + ')">\u2715</button></div>';
    html += '<div class="sim-meta">Puntata ' + s.stake.toFixed(2) + '\u20AC \u00B7 quota tot. ' + s.totalOdds.toFixed(2) +
            ' \u00B7 prob. tutti giusti ' + (s.pAll * 100).toFixed(2) + '%' +
            ' \u00B7 rendimento previsto <strong class="' + (s.roi >= 0 ? 'stat-good' : 'stat-bad') + '">' +
            (s.roi >= 0 ? '+' : '') + (s.roi * 100).toFixed(1) + '%</strong></div>';

    if (s.settled) {
      const net = (s.actualReturn || 0) - s.stake;
      html += '<div class="sim-result ' + (net >= 0 ? 'value-pos' : 'value-neg') + '">' +
              'Esito: <strong>' + s.nWins + '/' + s.N + '</strong> \u00B7 incassato ' + (s.actualReturn || 0).toFixed(2) + '\u20AC \u00B7 ' +
              '<strong>' + (net >= 0 ? '+' : '') + net.toFixed(2) + '\u20AC</strong></div>';
      html += '<div class="sim-events">';
      for (const e of s.events) {
        html += '<span class="ev-chip ' + (e.won ? 'ev-won' : 'ev-lost') + '">' + (e.won ? '\u2713' : '\u2717') + ' ' + e.label + '</span>';
      }
      html += '</div>';
    } else {
      html += '<div class="sim-settle" id="settle-' + s.id + '"><span class="note">Spunta gli eventi indovinati:</span>';
      s.events.forEach((e, i) => {
        html += '<label class="ev-check"><input type="checkbox" data-i="' + i + '"> ' + e.label +
                ' <em>(' + (e.p * 100).toFixed(0) + '% \u00B7 ' + e.odds.toFixed(2) + ')</em></label>';
      });
      html += '<button class="btn-primary sim-settle-btn" onclick="settleMulti(' + s.id + ')">\u2705 Registra esito</button></div>';
    }
    html += '</div>';
  }
  box.innerHTML = html;
}

// ---- Export / Import CSV delle simulazioni ----
function exportMultiCSV() {
  if (!multiRegistry.length) { alert('Nessuna simulazione da esportare.'); return; }
  const rows = ['Nome;Salvata;Tipo;K;N;Puntata;QuotaTot;ProbTutti;RendPrevisto;Esito;Incassato;Eventi'];
  for (const s of multiRegistry) {
    const evStr = s.events.map(e =>
      String(e.label).replace(/[;|]/g, ' ') + '|' + (e.p * 100).toFixed(1) + '|' + e.odds +
      '|' + (e.won === null ? '' : (e.won ? '1' : '0'))).join('~');
    rows.push([
      '"' + String(s.name).replace(/"/g, '""') + '"', s.savedAt, s.type, s.K, s.N,
      s.stake.toFixed(2), s.totalOdds.toFixed(3), (s.pAll * 100).toFixed(3), (s.roi * 100).toFixed(2),
      s.settled ? (s.nWins + '/' + s.N) : '', s.settled ? (s.actualReturn || 0).toFixed(2) : '',
      '"' + evStr + '"'
    ].join(';'));
  }
  const blob = new Blob(['\ufeff' + rows.join('\n')], {type: 'text/csv;charset=utf-8;'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'simulazioni_multiple_' + new Date().toISOString().slice(0, 10) + '.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

function importMultiCSV(text) {
  const lines = text.replace(/^\ufeff/, '').split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) { alert('File vuoto o non valido.'); return; }
  const sep = (lines[0].split(';').length >= lines[0].split(',').length) ? ';' : ',';
  const head = parseCSVLine(lines[0], sep).map(h => h.toLowerCase());
  const ix = n => head.indexOf(n);
  const iName = ix('nome'), iSaved = ix('salvata'), iK = ix('k'), iN = ix('n'),
        iStake = ix('puntata'), iEv = ix('eventi'), iBonus = ix('bonus');
  if (iEv < 0 || iK < 0) { alert('Intestazioni non riconosciute: servono almeno le colonne K ed Eventi.'); return; }

  const exist = new Set(multiRegistry.map(s => s.savedAt + '|' + s.name));
  let added = 0, skipped = 0, bad = 0;
  for (let i = 1; i < lines.length; i++) {
    const c = parseCSVLine(lines[i], sep);
    try {
      const events = String(c[iEv]).split('~').map(part => {
        const f = part.split('|');
        return {label: f[0], p: parseFloat(f[1]) / 100, odds: parseFloat(f[2]),
                won: (f[3] === '' || f[3] === undefined) ? null : f[3] === '1'};
      }).filter(e => isFinite(e.p) && isFinite(e.odds));
      if (events.length < 2) { bad++; continue; }
      const K = parseInt(c[iK], 10) || events.length;
      const unit = iStake >= 0 ? (parseFloat(String(c[iStake]).replace(',', '.')) / nCk(events.length, K)) : 1;
      const bonus = iBonus >= 0 ? (parseFloat(c[iBonus]) || 0) / 100 : 0;
      const r = computeSystem(events, K, unit, bonus);
      const savedAt = (iSaved >= 0 && c[iSaved]) ? c[iSaved] : new Date().toISOString();
      const name = (iName >= 0 && c[iName]) ? c[iName] : ('Importata ' + (i));
      if (exist.has(savedAt + '|' + name)) { skipped++; continue; }
      exist.add(savedAt + '|' + name);
      const allSettled = events.every(e => e.won !== null);
      const winOdds = events.filter(e => e.won).map(e => e.odds);
      let ret = null, nWins = null;
      if (allSettled) {
        nWins = winOdds.length;
        ret = nWins >= K ? unit * esym(winOdds, K) : 0;
        if (nWins === events.length && bonus > 0) ret *= (1 + bonus);
      }
      multiRegistry.push({
        id: Date.now() + i, name: name, savedAt: savedAt,
        type: (K === events.length) ? ('Multipla ' + K + '/' + events.length) : ('Sistema ' + K + '/' + events.length),
        K: K, N: events.length, unit: unit, bonus: bonus,
        stake: r.stake, totalOdds: r.totalOdds, pAll: r.pAll, pProfit: r.pProfit, ev: r.ev, roi: r.roi,
        events: events, settled: allSettled, actualReturn: ret, nWins: nWins
      });
      added++;
    } catch (e) { bad++; }
  }
  if (persistMultiRegistry()) renderMultiRegistry();
  alert('Importate ' + added + ' simulazioni.' +
        (skipped ? '\n' + skipped + ' gi\u00E0 presenti (saltate).' : '') +
        (bad ? '\n' + bad + ' righe non leggibili.' : ''));
}
