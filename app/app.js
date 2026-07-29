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
  if (value.bestBet) {
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
  html += '</div><p class="note">Vantaggio = prob. modello \u00D7 quota \u2212 1. Kelly dimezzato e limitato al 5% del bankroll. Gioca responsabilmente.</p>';
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
    document.getElementById('oddGG').textContent = formatOdd(odds.gg);
    document.getElementById('oddsNote').textContent = 'Quote recuperate automaticamente da The Odds API';
  } else {
    document.getElementById('odd1').textContent = '—';
    document.getElementById('oddX').textContent = '—';
    document.getElementById('odd2').textContent = '—';
    document.getElementById('oddOver').textContent = '—';
    document.getElementById('oddUnder').textContent = '—';
    document.getElementById('oddGG').textContent = '—';
    document.getElementById('oddsNote').textContent = 'Quote non disponibili per questa partita — il modello usa solo dati statistici';
  }

  // Predizioni
  showPrediction(fixture.prediction);
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

  showPrediction(currentMatch.prediction);
  modal.style.display = 'none';
});

// ===================== INIT =====================
loadData();
renderRegistry();
