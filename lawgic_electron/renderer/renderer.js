'use strict';

const $ = (id) => document.getElementById(id);
const counts = { pending: 0, processing: 0, done: 0, review: 0, error: 0 };
let folder = null;

// ---- tabs ----
document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.view').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    $(t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'review') loadReview();
    if (t.dataset.tab === 'settings') loadSettings();
  });
});

// ---- connection pill ----
function setPill(state, text) {
  const p = $('connPill');
  p.className = 'pill' + (state ? ' ' + state : '');
  $('connText').textContent = text;
}

// ---- counts ----
function renderCounts() {
  document.querySelectorAll('.chip').forEach((c) => {
    c.querySelector('b').textContent = counts[c.dataset.k] ?? 0;
  });
  const n = counts.review || 0;
  $('reviewBadge').textContent = n ? n : '';
}
function applyCounts(obj) {
  for (const k of Object.keys(counts)) counts[k] = obj[k] || 0;
  renderCounts();
}

// ---- log ----
function logLine({ stage, doc, msg, cls }) {
  const el = document.createElement('div');
  el.className = 'line';
  el.innerHTML =
    `<span class="stage">${stage || ''}</span>` +
    `<span class="doc">${doc || ''}</span>` +
    `<span class="msg ${cls || ''}">${msg || ''}</span>`;
  const log = $('log');
  log.prepend(el);
  while (log.children.length > 300) log.removeChild(log.lastChild);
}

// ---- ingest ----
$('chooseBtn').addEventListener('click', async () => {
  const f = await window.api.selectFolder();
  if (f) { folder = f; $('folderPath').textContent = f; $('startBtn').disabled = false; }
});

$('startBtn').addEventListener('click', () => {
  if (!folder) return;
  $('log').innerHTML = '';
  $('startBtn').disabled = true; $('cancelBtn').disabled = false;
  setPill('busy', 'ingesting');
  window.api.startIngest(folder);
});

$('cancelBtn').addEventListener('click', () => window.api.cancel());

let total = 0, doneCount = 0;
window.api.onPipelineEvent((o) => {
  switch (o.type) {
    case 'scan':
      total = o.total; doneCount = 0;
      $('bar').style.width = '0%';
      $('progressLabel').textContent = `0 / ${total}`;
      logLine({ stage: 'scan', doc: `${o.total} files`, msg: o.folder });
      break;
    case 'doc_start':
      $('progressLabel').textContent = `${o.index} / ${o.total} — ${o.doc}`;
      break;
    case 'stage':
      logLine({ stage: o.stage, doc: o.doc, msg: o.msg });
      break;
    case 'doc_done': {
      doneCount++;
      if (total) $('bar').style.width = `${Math.round((doneCount / total) * 100)}%`;
      const cls = o.status === 'done' ? 'ok' : (o.status === 'error' ? 'bad' : '');
      logLine({ stage: o.status, doc: o.doc, msg: '', cls });
      break;
    }
    case 'summary': applyCounts(o.counts); break;
    case 'log': logLine({ stage: '', doc: '', msg: o.msg }); break;
  }
});

window.api.onPipelineDone(({ code, error }) => {
  $('startBtn').disabled = !folder; $('cancelBtn').disabled = true;
  if (code === 0) { setPill('ok', 'finished'); }
  else { setPill('err', 'failed'); logLine({ stage: 'error', doc: '', msg: error, cls: 'bad' }); }
  refreshStatus();
});

async function refreshStatus() {
  const r = await window.api.getStatus();
  if (r && r.counts) applyCounts(r.counts);
}

// ---- review ----
$('refreshReview').addEventListener('click', loadReview);
$('retryAll').addEventListener('click', () => {
  setPill('busy', 'retrying');
  document.querySelector('.tab[data-tab="ingest"]').click();
  window.api.retry();
});

async function loadReview() {
  const r = await window.api.getReview();
  const body = $('reviewBody');
  const docs = (r && r.docs) || [];
  if (!docs.length) { body.innerHTML = '<tr><td colspan="3" class="empty">— queue empty —</td></tr>'; return; }
  body.innerHTML = docs.map((d) =>
    `<tr><td>${d.doc_id}</td><td>${d.stage || '—'}</td><td>${d.error || ''}</td></tr>`).join('');
}

// ---- settings ----
const FIELDS = ['pythonPath', 'coreDir', 'stateDb', 'jurisdiction', 'weaviateUrl',
  'weaviateApiKey', 'voyageApiKey', 'diEndpoint', 'diKey', 'anthropicKey',
  'deepseekKey', 'openaiKey'];

async function loadSettings() {
  const s = await window.api.getSettings();
  FIELDS.forEach((f) => { if ($(f)) $(f).value = s[f] || ''; });
  $('llmChoice').value = `${s.llmProvider || 'anthropic'}|${s.llmModel || 'claude-haiku-4-5'}`;
  $('llmThinking').checked = !!s.llmThinking;
  $('encNote').textContent = s.encryptionAvailable
    ? '· keys encrypted at rest' : '· plaintext (no OS keychain)';
}

$('saveSettings').addEventListener('click', async () => {
  const obj = {};
  FIELDS.forEach((f) => { if ($(f)) obj[f] = $(f).value.trim(); });
  const [provider, model] = $('llmChoice').value.split('|');
  obj.llmProvider = provider;
  obj.llmModel = model;
  obj.llmThinking = $('llmThinking').checked;
  await window.api.saveSettings(obj);
  $('savedNote').textContent = 'saved ✓';
  setTimeout(() => ($('savedNote').textContent = ''), 2000);
});

// ---- init ----
renderCounts();
refreshStatus();
