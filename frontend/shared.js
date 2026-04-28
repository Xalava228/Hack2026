(function () {
  const STATE_KEY = 'sf.editor.state.v2';
  const RECENT_KEY = 'sf.recent.prompts.v2';

  function saveState(state) {
    localStorage.setItem(STATE_KEY, JSON.stringify(state));
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STATE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function clearState() {
    localStorage.removeItem(STATE_KEY);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function updateRecentPrompt(prompt) {
    if (!prompt) return;
    let list = [];
    try {
      list = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
      if (!Array.isArray(list)) list = [];
    } catch (_) {
      list = [];
    }
    list = [prompt, ...list.filter((x) => x !== prompt)].slice(0, 8);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  }

  function loadRecentPrompts() {
    try {
      const list = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
      return Array.isArray(list) ? list : [];
    } catch (_) {
      return [];
    }
  }

  async function apiJson(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      let msg = `HTTP ${resp.status}`;
      try {
        const text = await resp.text();
        if (text) msg = text;
      } catch (_) {
        // ignore
      }
      throw new Error(msg);
    }
    return resp.json();
  }

  function parseSeg(name) {
    const seg = document.querySelector(`.seg[data-name="${name}"]`);
    const active = seg?.querySelector('button.active');
    return active?.dataset.value;
  }

  function setupSeg() {
    document.querySelectorAll('.seg').forEach((seg) => {
      seg.addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        seg.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  }

  async function pollJob(jobId, onUpdate) {
    while (true) {
      const data = await apiJson(`/api/jobs/${jobId}`);
      if (onUpdate) onUpdate(data);
      if (data.status === 'done') return data;
      if (data.status === 'error') throw new Error(data.error || 'Ошибка генерации');
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  }

  window.SF = {
    saveState,
    loadState,
    clearState,
    escapeHtml,
    updateRecentPrompt,
    loadRecentPrompts,
    apiJson,
    parseSeg,
    setupSeg,
    pollJob,
  };
})();
