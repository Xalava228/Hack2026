(function () {
  const form = document.getElementById('create-form');
  const promptEl = document.getElementById('prompt');
  const slidesEl = document.getElementById('n_slides');
  const hintEl = document.getElementById('form-hint');
  const buildBtn = document.getElementById('build-plan-btn');
  const sampleFileEl = document.getElementById('sample-file');
  const sampleClearBtn = document.getElementById('sample-clear');
  const sampleStatusEl = document.getElementById('sample-status');
  const suggestionsEl = document.getElementById('suggestion-grid');
  const shuffleBtn = document.getElementById('shuffle-btn');

  window.SF.setupSeg();

  const densityHintEl = document.getElementById('density-hint');
  function refreshDensityHint() {
    const seg = document.querySelector('.seg[data-name="text_density"] button.active');
    if (seg && densityHintEl) {
      const h = seg.getAttribute('data-hint') || '';
      if (h) densityHintEl.textContent = h;
    }
  }
  document.querySelectorAll('.seg[data-name="text_density"] button').forEach((b) => {
    b.addEventListener('click', () => setTimeout(refreshDensityHint, 0));
  });
  refreshDensityHint();

  const baseSuggestions = [
    'Лекция о лягушках для познавательных второклассников',
    'Семинар по психологии принятия решений в команде',
    'Питч-дек для новой платформы обучения',
    'Разработка и реализация стратегии продаж для B2B',
    'Основы кибербезопасности для сотрудников офиса',
    'Лучший и худший слеп поколения Z для маркетинга',
    'Презентация ВКР: анализ и результаты исследования',
    'План внедрения ИИ-инструментов в отдел маркетинга',
    'История развития атомной энергетики в России',
    'Сайт про энергетику: структура и контентный план',
  ];

  let currentSample = null;

  function setSampleStatus(text, isError) {
    sampleStatusEl.classList.remove('hide', 'error');
    if (isError) sampleStatusEl.classList.add('error');
    sampleStatusEl.textContent = text;
  }

  function clearSampleStatus() {
    sampleStatusEl.classList.add('hide');
    sampleStatusEl.classList.remove('error');
    sampleStatusEl.textContent = '';
  }

  function renderSuggestions() {
    const items = [...baseSuggestions].sort(() => Math.random() - 0.5).slice(0, 6);
    suggestionsEl.innerHTML = '';
    items.forEach((s) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'suggestion';
      item.textContent = s;
      item.addEventListener('click', () => {
        promptEl.value = s;
      });
      suggestionsEl.appendChild(item);
    });
  }

  async function uploadSample(file) {
    if (!file) return;
    if (!/\.(pptx|pdf)$/i.test(file.name)) {
      setSampleStatus('Поддерживаются только файлы .pptx и .pdf', true);
      return;
    }
    if (file.size > 30 * 1024 * 1024) {
      setSampleStatus('Файл слишком большой. Максимум 30 МБ.', true);
      return;
    }
    setSampleStatus(`Анализируем ${file.name}...`, false);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/analyze', { method: 'POST', body: fd });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      currentSample = data;
      setSampleStatus(`Образец подключен: ${data.file_name}, ${data.n_slides} слайдов.`, false);
    } catch (e) {
      currentSample = null;
      setSampleStatus(e.message || String(e), true);
    }
  }

  async function clearSample() {
    if (currentSample?.sample_id) {
      try {
        await fetch(`/api/samples/${currentSample.sample_id}`, { method: 'DELETE' });
      } catch (_) {
        // ignore
      }
    }
    currentSample = null;
    sampleFileEl.value = '';
    clearSampleStatus();
  }

  sampleFileEl.addEventListener('change', (e) => uploadSample(e.target.files?.[0]));
  sampleClearBtn.addEventListener('click', clearSample);
  shuffleBtn.addEventListener('click', renderSuggestions);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      prompt: promptEl.value.trim(),
      n_slides: Math.max(3, Math.min(20, Number(slidesEl.value) || 10)),
      text_density: window.SF.parseSeg('text_density'),
      images_mode: window.SF.parseSeg('images_mode'),
      research_mode: window.SF.parseSeg('research_mode') || 'off',
      image_backend: window.SF.parseSeg('image_backend'),
      output_format: window.SF.parseSeg('output_format'),
      design_preset: (document.getElementById('design_preset') || {}).value || 'fresh',
    };
    if (!payload.prompt || payload.prompt.length < 3) {
      hintEl.textContent = 'Введите более подробный запрос (минимум 3 символа).';
      return;
    }
    if (currentSample?.sample_id) payload.sample_id = currentSample.sample_id;

    buildBtn.disabled = true;
    hintEl.textContent = 'Генерируем черновик структуры...';

    try {
      const data = await window.SF.apiJson('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      window.SF.updateRecentPrompt(payload.prompt);
      window.SF.saveState({
        payload,
        plan: data.plan,
        selectedIndex: 0,
        createdAt: Date.now(),
      });
      location.href = '/editor.html';
    } catch (err) {
      hintEl.textContent = err.message || String(err);
    } finally {
      buildBtn.disabled = false;
    }
  });

  const prefill = sessionStorage.getItem('sf.prefill.prompt');
  if (prefill) {
    promptEl.value = prefill;
    sessionStorage.removeItem('sf.prefill.prompt');
  }

  renderSuggestions();
})();
