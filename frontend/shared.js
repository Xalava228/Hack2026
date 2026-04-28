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

  /** Совпадает с backend/design_presets.PRESET_PALETTES[fresh]. */
  const DEFAULT_PALETTE = {
    primary: '#1E293B',
    accent: '#6366F1',
    accent2: '#8B5CF6',
    background: '#F1F5F9',
    surface: '#FFFFFF',
    text: '#334155',
    muted: '#64748B',
  };

  function normalizeHex(raw, fallback) {
    let s = String(raw || '').trim().replace(/^#/, '');
    if (!/^[0-9A-Fa-f]{6}$/.test(s)) return fallback.startsWith('#') ? fallback : `#${fallback}`;
    return `#${s.toUpperCase()}`;
  }

  function mergeSlidePalette(planPalette, slideStyle) {
    const out = { ...DEFAULT_PALETTE, ...(planPalette || {}) };
    Object.keys(DEFAULT_PALETTE).forEach((k) => {
      if (out[k]) out[k] = normalizeHex(out[k], DEFAULT_PALETTE[k]);
    });
    if (!slideStyle || typeof slideStyle !== 'object') return out;
    const keyMap = {
      primary: 'primary',
      accent: 'accent',
      accent2: 'accent2',
      background: 'background',
      surface: 'surface',
      text: 'text',
      muted: 'muted',
      bg: 'background',
      title_color: 'primary',
      body_color: 'text',
    };
    Object.keys(slideStyle).forEach((k) => {
      const target = keyMap[k] || (k in out ? k : '');
      if (!target) return;
      const cur = out[target] || DEFAULT_PALETTE[target];
      const next = normalizeHex(slideStyle[k], cur);
      if (next.length === 7) out[target] = next;
    });
    return out;
  }

  /** Подписи пресетов (как в backend/design_presets.PRESET_LABELS_RU). */
  const DESIGN_PRESET_LABELS = {
    fresh: 'Свежее (slate / indigo)',
    ocean: 'Океан (голубой)',
    sunrise: 'Рассвет (оранж / розовый)',
    midnight: 'Полночь (тёмный)',
    pastel: 'Пастель (лаванда)',
    forest: 'Лес (зелёный)',
  };

  const PRESET_STYLE_TOKENS = {
    fresh: { titleFont: '"Calibri", "Segoe UI", sans-serif', bodyFont: '"Calibri", "Segoe UI", sans-serif', underlineRatio: 0.09 },
    ocean: { titleFont: '"Segoe UI", "Trebuchet MS", sans-serif', bodyFont: '"Segoe UI", "Arial", sans-serif', underlineRatio: 0.12 },
    sunrise: { titleFont: '"Trebuchet MS", "Verdana", sans-serif', bodyFont: '"Verdana", "Arial", sans-serif', underlineRatio: 0.1 },
    midnight: { titleFont: '"Bahnschrift", "Segoe UI", sans-serif', bodyFont: '"Bahnschrift", "Segoe UI", sans-serif', underlineRatio: 0.14 },
    pastel: { titleFont: '"Candara", "Segoe UI", sans-serif', bodyFont: '"Candara", "Segoe UI", sans-serif', underlineRatio: 0.11 },
    forest: { titleFont: '"Cambria", "Times New Roman", serif', bodyFont: '"Cambria", "Georgia", serif', underlineRatio: 0.08 },
  };

  function styleForPreset(presetId) {
    const pid = Object.prototype.hasOwnProperty.call(PRESET_STYLE_TOKENS, presetId) ? presetId : 'fresh';
    return { ...PRESET_STYLE_TOKENS.fresh, ...(PRESET_STYLE_TOKENS[pid] || {}) };
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
    DEFAULT_PALETTE,
    normalizeHex,
    mergeSlidePalette,
    DESIGN_PRESET_LABELS,
    styleForPreset,
  };
})();
