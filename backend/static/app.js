const API = '/api/v1/builds';

const PHASES = [
  { key: 'scraping',   label: 'Scraping' },
  { key: 'analysing',  label: 'Analyse' },
  { key: 'building',   label: 'Build' },
  { key: 'evaluating', label: 'Evaluierung' },
  { key: 'done',       label: 'Fertig' },
];

const PHASE_ORDER = PHASES.map(p => p.key);

let currentWs = null;
let refineTargetId = null;

// --- Generate Demo ---
async function generateDemo() {
  const domain = document.getElementById('domain').value.trim();
  if (!domain) return alert('Bitte Domain eingeben.');

  const userPrompt = document.getElementById('user_prompt').value.trim();

  document.getElementById('generate-btn').disabled = true;
  showProgress();

  const res = await fetch(`${API}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ domain, user_prompt: userPrompt || null }),
  });
  const data = await res.json();
  if (!data.build_id) {
    alert('Fehler beim Starten.');
    document.getElementById('generate-btn').disabled = false;
    return;
  }

  openWebSocket(data.build_id);
}

function showProgress() {
  const card = document.getElementById('progress-card');
  card.classList.add('visible');
  document.getElementById('result-link').classList.remove('visible');
  renderPhases('pending');
  document.getElementById('status-detail').textContent = '';
}

function renderPhases(currentStatus) {
  const list = document.getElementById('phase-list');
  const currentIdx = PHASE_ORDER.indexOf(currentStatus);

  list.innerHTML = PHASES.map((phase, i) => {
    const phaseIdx = PHASE_ORDER.indexOf(phase.key);
    let cls = '';
    let icon = (i + 1).toString();

    if (phaseIdx < currentIdx || currentStatus === 'done') {
      cls = 'done';
      icon = '✓';
    } else if (phaseIdx === currentIdx) {
      cls = 'active';
      icon = '<span class="spinner"></span>';
    }

    return `<li class="phase-item ${cls}">
      <span class="phase-icon">${icon}</span>
      <span>${phase.label}</span>
    </li>`;
  }).join('');
}

function openWebSocket(buildId) {
  if (currentWs) currentWs.close();

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}${API}/ws/${buildId}`);
  currentWs = ws;

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    const status = data.status || 'pending';

    renderPhases(status);
    document.getElementById('status-detail').textContent = data.status_detail || '';

    if (status === 'done' && data.public_url) {
      const resultEl = document.getElementById('result-link');
      resultEl.classList.add('visible');
      resultEl.innerHTML = `<a href="${data.public_url}" target="_blank">&#x1F517; ${data.public_url}</a>`;
      document.getElementById('generate-btn').disabled = false;
      loadBuilds();
    }

    if (status === 'error') {
      document.getElementById('status-detail').textContent = 'Fehler aufgetreten — Details in der Liste.';
      document.getElementById('generate-btn').disabled = false;
      loadBuilds();
    }
  };

  ws.onerror = () => {
    document.getElementById('generate-btn').disabled = false;
  };
}

// --- Load Builds ---
async function loadBuilds() {
  const res = await fetch(API);
  const builds = await res.json();
  const container = document.getElementById('builds-list');

  if (!builds.length) {
    container.innerHTML = '<div class="empty-state">Noch keine Demos generiert.</div>';
    return;
  }

  container.innerHTML = builds.map(b => {
    const date = b.created_at ? new Date(b.created_at).toLocaleDateString('de-CH', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
    }) : '';

    const versionLabel = b.current_version ? `v${b.current_version}` : '';
    const badgeCls = `badge badge-${b.status}`;
    const statusLabel = b.status;

    const openBtn = b.public_url
      ? `<a href="${b.public_url}" target="_blank" class="btn btn-sm btn-outline">Öffnen</a>`
      : '';

    const refineBtn = b.status === 'done'
      ? `<button onclick="openRefineModal(${b.id}, '${b.domain}')" class="btn btn-sm btn-outline">Anpassen</button>`
      : '';

    const deleteBtn = `<button onclick="deleteBuild(${b.id})" class="btn btn-sm btn-ghost" title="Löschen">✕</button>`;

    return `<div class="build-item">
      <div class="build-top">
        <span class="build-domain">${b.domain}</span>
        <span class="${badgeCls}">${statusLabel}${versionLabel ? ' · ' + versionLabel : ''}</span>
      </div>
      <div class="build-meta">${date}</div>
      <div class="build-actions">${openBtn}${refineBtn}${deleteBtn}</div>
    </div>`;
  }).join('');
}

// --- Refine Modal ---
function openRefineModal(buildId, domain) {
  refineTargetId = buildId;
  document.getElementById('modal-domain').textContent = domain;
  document.getElementById('refine-prompt').value = '';
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  refineTargetId = null;
}

async function submitRefinement() {
  const prompt = document.getElementById('refine-prompt').value.trim();
  if (!prompt) return alert('Bitte Anpassungswunsch eingeben.');

  document.getElementById('refine-btn').disabled = true;
  closeModal();

  await fetch(`${API}/${refineTargetId}/refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });

  showProgress();
  openWebSocket(refineTargetId);
}

// --- Delete ---
async function deleteBuild(buildId) {
  if (!confirm('Demo wirklich löschen?')) return;
  await fetch(`${API}/${buildId}`, { method: 'DELETE' });
  loadBuilds();
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
  loadBuilds();

  document.getElementById('generate-btn').addEventListener('click', generateDemo);
  document.getElementById('refine-btn').addEventListener('click', submitRefinement);
  document.getElementById('modal-cancel').addEventListener('click', closeModal);
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  document.getElementById('domain').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') generateDemo();
  });
});
