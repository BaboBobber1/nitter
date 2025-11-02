const state = {
  config: null,
  targets: [],
  tweets: [],
  eventLog: [],
  connected: true,
};

const dom = {
  targetList: document.querySelector('#targetList'),
  targetForm: document.querySelector('#targetForm'),
  targetType: document.querySelector('#targetType'),
  targetValue: document.querySelector('#targetValue'),
  targetInterval: document.querySelector('#targetInterval'),
  formError: document.querySelector('#formError'),
  connectionStatus: document.querySelector('#connectionStatus'),
  fetchOnceBtn: document.querySelector('#fetchOnceBtn'),
  exportBtn: document.querySelector('#exportBtn'),
  healthBtn: document.querySelector('#healthBtn'),
  timelineList: document.querySelector('#timelineList'),
  timelineTargetFilter: document.querySelector('#timelineTargetFilter'),
  timelineLimit: document.querySelector('#timelineLimit'),
  timelineSearch: document.querySelector('#timelineSearch'),
  instanceStatus: document.querySelector('#instanceStatus'),
  eventLog: document.querySelector('#eventLog'),
  settingsInstances: document.querySelector('#settingsInstances'),
  settingsUA: document.querySelector('#settingsUA'),
};

function logEvent(message, level = 'info') {
  const timestamp = new Date().toLocaleTimeString();
  state.eventLog.unshift({ timestamp, message, level });
  state.eventLog = state.eventLog.slice(0, 50);
  dom.eventLog.innerHTML = state.eventLog
    .map(
      (item) => `
        <li class="flex justify-between gap-2">
          <span class="text-${item.level === 'error' ? 'rose' : 'emerald'}-400">${item.level.toUpperCase()}</span>
          <span class="flex-1 text-right text-slate-300">${item.message}</span>
          <span class="text-slate-500">${item.timestamp}</span>
        </li>
      `,
    )
    .join('');
}

async function loadConfig() {
  const response = await fetch('/api/config');
  state.config = await response.json();
  dom.settingsInstances.textContent = state.config.nitter_instances.join(', ');
  dom.settingsUA.textContent = state.config.user_agent;
}

async function loadTargets() {
  const response = await fetch('/api/targets');
  state.targets = await response.json();
  renderTargets();
  renderTargetFilter();
}

async function loadTweets() {
  const params = new URLSearchParams();
  const target = dom.timelineTargetFilter.value;
  const limit = dom.timelineLimit.value;
  const query = dom.timelineSearch.value;
  if (target) params.set('target', target);
  if (limit) params.set('limit', limit);
  if (query) params.set('q', query);
  const response = await fetch(`/api/tweets?${params.toString()}`);
  state.tweets = await response.json();
  renderTimeline();
}

function renderTargets() {
  dom.targetList.innerHTML = state.targets
    .map(
      (target) => `
        <li class="flex items-center justify-between gap-2 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2">
          <div>
            <p class="font-medium text-slate-100">${target.type === 'user' ? '@' : '#'}${target.value}</p>
            <p class="text-xs text-slate-400">${target.poll_interval_seconds}s Intervall</p>
          </div>
          <button data-id="${target.id}" class="delete-target text-rose-400 hover:text-rose-300">Entfernen</button>
        </li>
      `,
    )
    .join('');
  dom.targetList.querySelectorAll('.delete-target').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const confirmed = confirm('Target wirklich löschen?');
      if (!confirmed) return;
      const res = await fetch(`/api/targets/${id}`, { method: 'DELETE' });
      if (res.ok) {
        logEvent(`Target ${id} entfernt.`);
        await loadTargets();
        await loadTweets();
      } else {
        const data = await res.json();
        logEvent(data.error || 'Fehler beim Löschen', 'error');
      }
    });
  });
}

function renderTargetFilter() {
  const options = ['<option value="">Alle</option>']
    .concat(
      state.targets.map(
        (target) =>
          `<option value="${target.type}:${target.value}">${target.type === 'user' ? '@' : '#'}${target.value}</option>`,
      ),
    )
    .join('');
  dom.timelineTargetFilter.innerHTML = options;
}

function renderTimeline() {
  if (!state.tweets.length) {
    dom.timelineList.innerHTML = '<li class="text-slate-500 text-sm">Keine Tweets gefunden.</li>';
    return;
  }
  dom.timelineList.innerHTML = state.tweets
    .map((tweet) => {
      const created = tweet.created_at ? new Date(tweet.created_at).toLocaleString() : 'unbekannt';
      const content = (tweet.content || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      return `
        <li class="bg-slate-950 border border-slate-800 rounded-lg p-4 shadow">
          <div class="flex justify-between text-xs text-slate-500">
            <span>${tweet.target}</span>
            <span>${created}</span>
          </div>
          <p class="mt-2 text-sm text-slate-100 leading-relaxed">${content}</p>
          <div class="mt-3 text-xs text-slate-500">Quelle: ${tweet.instance || 'unbekannt'}</div>
        </li>
      `;
    })
    .join('');
}

function setupTabs() {
  const buttons = document.querySelectorAll('.tab-button');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.add('hidden'));
      btn.classList.add('active');
      document.querySelector(`#tab-${btn.dataset.tab}`).classList.remove('hidden');
    });
  });
}

function setupForm() {
  dom.targetForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    dom.formError.textContent = '';
    const payload = {
      type: dom.targetType.value,
      value: dom.targetValue.value.trim(),
      poll_interval_seconds: Number(dom.targetInterval.value),
    };
    if (!payload.value) {
      dom.formError.textContent = 'Bitte einen Wert angeben.';
      return;
    }
    if (payload.poll_interval_seconds < 60) {
      dom.formError.textContent = 'Intervall mindestens 60 Sekunden.';
      return;
    }
    const response = await fetch('/api/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const data = await response.json();
      dom.formError.textContent = data.error || 'Fehler beim Speichern.';
      return;
    }
    dom.targetValue.value = '';
    logEvent(`Target ${payload.type}:${payload.value} angelegt.`);
    await loadTargets();
    await loadTweets();
  });
}

function setupControls() {
  dom.fetchOnceBtn.addEventListener('click', async () => {
    dom.fetchOnceBtn.disabled = true;
    await fetch('/api/fetch/once', { method: 'POST' })
      .then((res) => res.json())
      .then((data) => {
        Object.entries(data.newCountsByTarget || {}).forEach(([key, value]) => {
          logEvent(`${value} neue Einträge für ${key}.`);
        });
        if ((data.failedInstances || []).length) {
          data.failedInstances.forEach((fail) =>
            logEvent(`${fail.instance || 'Unbekannte Instanz'}: ${fail.error}`, 'error'),
          );
        }
      })
      .catch((err) => logEvent(err.message, 'error'))
      .finally(async () => {
        dom.fetchOnceBtn.disabled = false;
        await loadTweets();
      });
  });

  dom.exportBtn.addEventListener('click', () => {
    window.open('/api/export.jsonl', '_blank');
  });

  dom.healthBtn.addEventListener('click', async () => {
    const response = await fetch('/api/health');
    if (!response.ok) {
      logEvent('Health-Endpunkt nicht erreichbar', 'error');
      return;
    }
    const data = await response.json();
    renderHealth(data);
    logEvent('Health-Check aktualisiert.');
  });

  dom.timelineTargetFilter.addEventListener('change', loadTweets);
  dom.timelineLimit.addEventListener('change', loadTweets);
  dom.timelineSearch.addEventListener('input', debounce(loadTweets, 400));
}

function renderHealth(data) {
  dom.instanceStatus.innerHTML = (data.rttByInstance || [])
    .map((instance) => {
      const backoffSeconds = Math.max(0, Math.round(instance.backoff_remaining || 0));
      return `
        <li class="border border-slate-800 rounded-md px-3 py-2">
          <div class="flex justify-between text-xs text-slate-400">
            <span>${instance.base_url}</span>
            <span>${instance.last_rtt ? `${instance.last_rtt.toFixed(2)}s` : 'n/a'}</span>
          </div>
          <div class="text-xs text-slate-500">Tokens: ${instance.tokens}</div>
          <div class="text-xs text-${instance.last_error ? 'rose' : 'emerald'}-400">${
        instance.last_error || 'OK'
      }</div>
          <div class="text-xs text-slate-500">Cooldown: ${backoffSeconds}s</div>
        </li>
      `;
    })
    .join('');
  const status = data.status === 'ok' ? 'emerald' : 'rose';
  dom.connectionStatus.className = `px-3 py-1 rounded-full text-sm font-medium bg-${status}-500/10 text-${status}-300 border border-${status}-400/40`;
  dom.connectionStatus.textContent = data.status === 'ok' ? 'Verbunden' : 'Probleme';
}

function debounce(fn, delay) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), delay);
  };
}

function setupSSE() {
  try {
    const source = new EventSource('/api/stream');
    source.onopen = () => {
      state.connected = true;
      dom.connectionStatus.classList.remove('bg-rose-500/10');
      dom.connectionStatus.classList.add('bg-emerald-500/10');
      dom.connectionStatus.textContent = 'Verbunden';
      logEvent('SSE Verbindung aktiv.');
    };
    source.onerror = () => {
      state.connected = false;
      dom.connectionStatus.classList.remove('bg-emerald-500/10');
      dom.connectionStatus.classList.add('bg-rose-500/10');
      dom.connectionStatus.textContent = 'Getrennt';
      logEvent('SSE Verbindung getrennt.', 'error');
    };
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'new_tweet') {
          logEvent(`Neuer Tweet für ${payload.data.target}.`);
          loadTweets();
        }
        if (payload.type === 'error') {
          logEvent(`${payload.data.target || 'Allgemein'}: ${payload.data.message}`, 'error');
        }
        if (payload.type === 'cooldown') {
          logEvent(`Cooldown für ${payload.data.target}: ${payload.data.next_run_in}s.`);
        }
      } catch (err) {
        console.debug('SSE parse error', err);
      }
    };
  } catch (err) {
    logEvent('SSE nicht verfügbar', 'error');
  }
}

async function bootstrap() {
  setupTabs();
  setupForm();
  setupControls();
  setupSSE();
  await loadConfig();
  await loadTargets();
  await loadTweets();
  const health = await fetch('/api/health').then((res) => res.json());
  renderHealth(health);
}

document.addEventListener('DOMContentLoaded', bootstrap);
