(function () {
  const state = window.SF.loadState();

  const PLAN_COLOR_FIELDS = [
    { k: 'background', label: 'Фон' },
    { k: 'primary', label: 'Заголовки' },
    { k: 'accent', label: 'Акцент' },
    { k: 'text', label: 'Текст' },
    { k: 'muted', label: 'Второстеп.' },
  ];

  const SLIDE_OVERRIDE_FIELDS = [
    { k: 'background', label: 'Фон слайда' },
    { k: 'primary', label: 'Заголовки' },
    { k: 'text', label: 'Текст' },
    { k: 'accent', label: 'Акцент' },
  ];

  const listEl = document.getElementById('slide-list');
  const editorEmptyEl = document.getElementById('editor-empty');
  const editorContentEl = document.getElementById('editor-content');
  const editorTitleEl = document.getElementById('editor-title');
  const editorSubEl = document.getElementById('editor-sub');
  const activeSlideLabelEl = document.getElementById('active-slide-label');
  const deckEl = document.getElementById('slide-deck');

  const kindEl = document.getElementById('kind');
  const addSlideBtn = document.getElementById('add-slide');
  const moveUpBtn = document.getElementById('move-up');
  const moveDownBtn = document.getElementById('move-down');
  const duplicateBtn = document.getElementById('duplicate-slide');
  const deleteBtn = document.getElementById('delete-slide');
  const addBulletBtn = document.getElementById('add-bullet');
  const changeImageBtn = document.getElementById('change-image');
  const clearImageBtn = document.getElementById('clear-image');
  const imageFileEl = document.getElementById('image-file');
  const tableToolsEl = document.getElementById('table-tools');
  const tblAddRowBtn = document.getElementById('tbl-add-row');
  const tblDelRowBtn = document.getElementById('tbl-del-row');
  const tblAddColBtn = document.getElementById('tbl-add-col');
  const tblDelColBtn = document.getElementById('tbl-del-col');
  const engageBtn = document.getElementById('engage-check');
  const engageScoreEl = document.getElementById('engage-score');
  const engageSummaryEl = document.getElementById('engage-summary');
  const engageListEl = document.getElementById('engage-list');
  const webImagePanelEl = document.getElementById('web-image-panel');
  const webImageQueryEl = document.getElementById('web-image-query');
  const webImageStatusEl = document.getElementById('web-image-status');
  const webImageSearchBtn = document.getElementById('web-image-search');
  const webImageGridEl = document.getElementById('web-image-grid');

  const regenInstructionEl = document.getElementById('regen-instruction');
  const regenStatusEl = document.getElementById('regen-status');
  const regenBtn = document.getElementById('regen-slide');
  const exportBtn = document.getElementById('export-btn');

  function persist() {
    window.SF.saveState(state);
  }

  function setPlacement(side) {
    if (!ensureState()) return;
    const s = currentSlide();
    if (s.kind !== 'content') return;
    s.image_placement = side === 'left' ? 'left' : 'right';
    document.getElementById('img-place-left')?.classList.toggle('active', side === 'left');
    document.getElementById('img-place-right')?.classList.toggle('active', side === 'right');
    persist();
    renderActiveSlide();
  }

  let designToolbarBuilt = false;

  function buildDesignToolbar() {
    if (designToolbarBuilt) return;
    const planGrid = document.getElementById('plan-palette-colors');
    const slideGrid = document.getElementById('slide-override-colors');
    if (!planGrid || !slideGrid) return;
    designToolbarBuilt = true;

    PLAN_COLOR_FIELDS.forEach(({ k, label }) => {
      const lab = document.createElement('label');
      lab.className = 'color-field';
      const span = document.createElement('span');
      span.textContent = label;
      const inp = document.createElement('input');
      inp.type = 'color';
      inp.dataset.pk = k;
      lab.appendChild(span);
      lab.appendChild(inp);
      planGrid.appendChild(lab);
      inp.addEventListener('input', () => {
        if (!ensureState()) return;
        state.plan.palette[k] = inp.value;
        persist();
        refreshDesignToolbar();
        renderActiveSlide();
      });
    });

    SLIDE_OVERRIDE_FIELDS.forEach(({ k, label }) => {
      const lab = document.createElement('label');
      lab.className = 'color-field';
      const span = document.createElement('span');
      span.textContent = label;
      const inp = document.createElement('input');
      inp.type = 'color';
      inp.dataset.sk = k;
      lab.appendChild(span);
      lab.appendChild(inp);
      slideGrid.appendChild(lab);
      inp.addEventListener('input', () => {
        if (!ensureState()) return;
        const s = currentSlide();
        if (!s.style) s.style = {};
        s.style[k] = inp.value;
        persist();
        renderActiveSlide();
      });
    });

    document.getElementById('reset-slide-style')?.addEventListener('click', () => {
      if (!ensureState()) return;
      currentSlide().style = {};
      persist();
      render();
    });

    document.getElementById('img-place-left')?.addEventListener('click', () => setPlacement('left'));
    document.getElementById('img-place-right')?.addEventListener('click', () => setPlacement('right'));
  }

  function refreshDesignToolbar() {
    if (!state?.plan?.palette) return;
    const note = document.getElementById('design-preset-note');
    if (note) {
      const pid = state.plan.design_preset || 'fresh';
      const title = window.SF.DESIGN_PRESET_LABELS[pid] || pid;
      note.textContent = `Активный пресет: ${title}`;
    }

    document.querySelectorAll('#plan-palette-colors input[data-pk]').forEach((el) => {
      const k = el.dataset.pk;
      if (!k) return;
      el.value = window.SF.normalizeHex(state.plan.palette[k], window.SF.DEFAULT_PALETTE[k]);
    });

    const slide = currentSlide();
    const merged = window.SF.mergeSlidePalette(state.plan.palette, slide?.style);

    document.querySelectorAll('#slide-override-colors input[data-sk]').forEach((el) => {
      const k = el.dataset.sk;
      if (!k) return;
      el.value = merged[k];
    });

    const placeRow = document.getElementById('image-placement-row');
    const showPlacement = slide && slide.kind === 'content';
    if (placeRow) placeRow.classList.toggle('hide', !showPlacement);

    const pl = slide?.image_placement === 'left' ? 'left' : 'right';
    document.getElementById('img-place-left')?.classList.toggle('active', pl === 'left');
    document.getElementById('img-place-right')?.classList.toggle('active', pl === 'right');
  }

  function normalizeSlide(slide, idx) {
    const rawHeaders = Array.isArray(slide?.headers) ? slide.headers.map(String) : [];
    let rows = Array.isArray(slide?.rows)
      ? slide.rows.map((r) => (Array.isArray(r) ? r.map(String) : []))
      : [];
    if (rawHeaders.length) {
      const n = rawHeaders.length;
      rows = rows.map((r) => {
        const out = r.slice(0, n);
        while (out.length < n) out.push('');
        return out;
      });
    }
    const placing = String(slide?.image_placement || 'right').toLowerCase();

    const rawStyle =
      slide?.style && typeof slide.style === 'object' && !Array.isArray(slide.style)
        ? { ...slide.style }
        : {};

    return {
      kind: String(slide?.kind || (idx === 0 ? 'title' : 'content')),
      title: String(slide?.title || `Слайд ${idx + 1}`),
      subtitle: String(slide?.subtitle || ''),
      bullets: Array.isArray(slide?.bullets) ? slide.bullets.map(String) : [],
      body: String(slide?.body || ''),
      image_prompt: String(slide?.image_prompt || ''),
      image_data_url: String(slide?.image_data_url || ''),
      notes: String(slide?.notes || ''),
      headers: rawHeaders,
      rows,
      style: rawStyle,
      image_placement: placing === 'left' ? 'left' : 'right',
    };
  }

  function ensureState() {
    if (!state || !state.plan || !Array.isArray(state.plan.slides) || !state.plan.slides.length) {
      editorEmptyEl.classList.remove('hide');
      editorContentEl.classList.add('hide');
      return false;
    }
    state.plan.slides = state.plan.slides.map(normalizeSlide);
    const D = window.SF.DEFAULT_PALETTE;
    if (!state.plan.palette || typeof state.plan.palette !== 'object') {
      state.plan.palette = { ...D };
    } else {
      Object.keys(D).forEach((k) => {
        if (!state.plan.palette[k]) state.plan.palette[k] = D[k];
      });
    }
    if (!state.plan.design_preset) state.plan.design_preset = 'fresh';
    if (state.engagement && Array.isArray(state.engagement.slides)) {
      if (state.engagement.slides.length !== state.plan.slides.length) state.engagement = null;
    }

    if (state.selectedIndex == null || state.selectedIndex < 0) state.selectedIndex = 0;
    if (state.selectedIndex > state.plan.slides.length - 1) state.selectedIndex = state.plan.slides.length - 1;
    editorEmptyEl.classList.add('hide');
    editorContentEl.classList.remove('hide');
    return true;
  }

  function currentSlide() {
    return state.plan.slides[state.selectedIndex];
  }

  function getSlideRisk(idx) {
    const rows = state?.engagement?.slides;
    if (!Array.isArray(rows)) return '';
    const item = rows.find((x) => Number(x.slide_index) === idx);
    return item?.risk_level || '';
  }

  function renderEngagementPanel() {
    if (!engageScoreEl || !engageSummaryEl || !engageListEl) return;
    const e = state?.engagement;
    if (!e || !Array.isArray(e.slides) || !e.slides.length) {
      engageScoreEl.textContent = 'Пока нет анализа.';
      engageSummaryEl.textContent = 'Запустите проверку, чтобы найти самые скучные слайды и получить улучшения.';
      engageListEl.innerHTML = '';
      return;
    }
    engageScoreEl.textContent = `Индекс скуки: ${e.deck_score}% · критичных: ${e.critical_slides}, высоких: ${e.high_slides}`;
    engageSummaryEl.textContent = e.summary || '';
    const top = Array.isArray(e.top_risks) ? e.top_risks : [];
    engageListEl.innerHTML = '';
    top.forEach((item) => {
      const card = document.createElement('article');
      card.className = 'engage-card';
      const risk = String(item.risk_level || 'low');
      const rec = Array.isArray(item.recommendations) ? item.recommendations.slice(0, 2) : [];
      card.innerHTML = `
        <div><strong>#${Number(item.slide_index) + 1} ${window.SF.escapeHtml(item.title || '')}</strong></div>
        <div class="risk risk-${risk}">${window.SF.escapeHtml(item.verdict || '')}</div>
        <div class="hint">${window.SF.escapeHtml(rec.join(' / ') || 'Добавьте интерактив и сократите текст.')}</div>
      `;
      engageListEl.appendChild(card);
    });
  }

  function renderWebImagePanel() {
    if (!webImagePanelEl || !webImageGridEl) return;
    const s = currentSlide();
    const canUse = s && (s.kind === 'content' || s.kind === 'two_column');
    webImagePanelEl.classList.toggle('hide', !canUse);
    if (!canUse) return;
    if (webImageQueryEl && !webImageQueryEl.value.trim()) {
      webImageQueryEl.value = s.image_prompt || s.title || '';
    }
  }

  function refreshHeader() {
    editorTitleEl.textContent = state.plan.title || 'Визуальный редактор';
    editorSubEl.textContent = `${state.plan.slides.length} слайдов · редактируйте напрямую в макете`;
    activeSlideLabelEl.textContent = `${state.selectedIndex + 1}`;
  }

  function refreshKindControl() {
    kindEl.value = currentSlide().kind;
    refreshKindToolbar();
  }

  function refreshKindToolbar() {
    const k = currentSlide().kind;
    const isTable = k === 'table';
    if (tableToolsEl) tableToolsEl.style.display = isTable ? '' : 'none';
    if (addBulletBtn) addBulletBtn.style.display = isTable || k === 'title' || k === 'section' ? 'none' : '';
    const showImage = !isTable && k !== 'title' && k !== 'section' && k !== 'conclusion';
    if (changeImageBtn) changeImageBtn.style.display = showImage ? '' : 'none';
    if (clearImageBtn) clearImageBtn.style.display = showImage ? '' : 'none';
  }

  function makeEditable(tag, className, value, onInput, placeholder) {
    const el = document.createElement(tag);
    el.className = `${className} editable`;
    el.contentEditable = 'true';
    el.spellcheck = true;
    el.textContent = value || '';
    if (placeholder) el.setAttribute('data-placeholder', placeholder);
    el.addEventListener('input', () => {
      onInput(el.textContent.replace(/\u00a0/g, ' ').trim());
      persist();
      renderSlideList();
    });
    return el;
  }

  function renderSlideList() {
    listEl.innerHTML = '';
    state.plan.slides.forEach((slide, idx) => {
      const risk = getSlideRisk(idx);
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `slide-chip${idx === state.selectedIndex ? ' active' : ''}${risk ? ` risk-${risk}` : ''}`;
      chip.innerHTML = `
        <div class="chip-thumb kind-${slide.kind}">
          ${slide.image_data_url ? `<img src="${slide.image_data_url}" alt="thumb" />` : ''}
          <div class="chip-overlay">
            <span class="chip-num">${idx + 1}</span>
            <div class="chip-title">${window.SF.escapeHtml(slide.title || `Слайд ${idx + 1}`)}</div>
          </div>
        </div>
      `;
      chip.addEventListener('click', () => {
        state.selectedIndex = idx;
        persist();
        render();
      });
      listEl.appendChild(chip);
    });
  }

  function makeImagePane(slide, idx, extraClass = '') {
    const image = document.createElement('div');
    image.className = `slide-image-pane${extraClass ? ' ' + extraClass : ''}`;
    image.setAttribute('title', 'Нажмите для замены изображения');

    if (slide.image_data_url) {
      const img = document.createElement('img');
      img.src = slide.image_data_url;
      img.alt = 'slide visual';
      image.appendChild(img);
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'slide-image-placeholder';
      placeholder.textContent = slide.image_prompt ? `AI: ${slide.image_prompt}` : 'Нажмите, чтобы добавить изображение';
      image.appendChild(placeholder);
    }

    const hint = document.createElement('div');
    hint.className = 'image-edit-hint';
    hint.textContent = 'Сменить фото';
    image.appendChild(hint);

    image.addEventListener('click', (e) => {
      e.stopPropagation();
      state.selectedIndex = idx;
      persist();
      renderSlideList();
      refreshHeader();
      refreshKindControl();
      imageFileEl.click();
    });

    return image;
  }

  function makeBulletList(slide, idx, items, startOffset, twoCol) {
    const wrap = document.createElement('div');
    wrap.className = twoCol ? 'canvas-bullets two-col' : 'canvas-bullets';
    items.forEach((b, i) => {
      const realIdx = startOffset + i;
      wrap.appendChild(makeBulletItem(slide, idx, realIdx, b));
    });
    return wrap;
  }

  function applyPalette(canvas, slide) {
    const merged = window.SF.mergeSlidePalette(state.plan.palette, slide.style);
    const presetStyle = window.SF.styleForPreset(state.plan.design_preset || 'fresh');
    const map = {
      '--p-bg': merged.background,
      '--p-primary': merged.primary,
      '--p-accent': merged.accent,
      '--p-accent2': merged.accent2,
      '--p-surface': merged.surface,
      '--p-text': merged.text,
      '--p-muted': merged.muted,
      '--p-font-title': presetStyle.titleFont,
      '--p-font-body': presetStyle.bodyFont,
      '--p-underline-ratio': String(presetStyle.underlineRatio || 0.09),
    };
    Object.entries(map).forEach(([k, v]) => canvas.style.setProperty(k, v));
  }

  function makeBulletItem(slide, idx, bulletIndex, value) {
    const row = document.createElement('div');
    row.className = 'canvas-bullet-item';

    const dot = document.createElement('span');
    dot.className = 'canvas-bullet-dot';
    dot.textContent = '•';

    const txt = makeEditable('div', 'canvas-bullet-text', value, (v) => {
      slide.bullets[bulletIndex] = v;
    }, 'Пункт');

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'canvas-mini-delete';
    del.textContent = '×';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      state.selectedIndex = idx;
      slide.bullets.splice(bulletIndex, 1);
      persist();
      render();
    });

    row.appendChild(dot);
    row.appendChild(txt);
    row.appendChild(del);
    return row;
  }

  function renderSlideFrame(slide, idx) {
    const wrapper = document.createElement('article');
    wrapper.className = 'deck-slide-wrap active single';
    wrapper.dataset.slideIndex = String(idx);

    const canvas = document.createElement('div');
    canvas.className = `slide-canvas kind-${slide.kind}`;
    applyPalette(canvas, slide);

    if (slide.kind === 'title') {
      const barTop = document.createElement('div');
      barTop.className = 'cap-bar cap-top';
      const barBot = document.createElement('div');
      barBot.className = 'cap-bar cap-bot';

      const cover = document.createElement('div');
      cover.className = 'cover-center';
      cover.appendChild(makeEditable('h1', 'cover-title', slide.title, (v) => { slide.title = v; }, 'Заголовок'));
      cover.appendChild(makeEditable('p', 'cover-subtitle', slide.subtitle, (v) => { slide.subtitle = v; }, 'Подзаголовок'));

      canvas.appendChild(barTop);
      canvas.appendChild(cover);
      canvas.appendChild(barBot);
      wrapper.appendChild(canvas);
      return wrapper;
    }

    if (slide.kind === 'section') {
      const center = document.createElement('div');
      center.className = 'section-center';
      center.appendChild(makeEditable('h1', 'section-title', slide.title, (v) => { slide.title = v; }, 'Заголовок'));
      center.appendChild(makeEditable('p', 'section-sub', slide.subtitle, (v) => { slide.subtitle = v; }, 'Подзаголовок'));
      canvas.appendChild(center);
      wrapper.appendChild(canvas);
      return wrapper;
    }

    if (slide.kind === 'conclusion') {
      const barTop = document.createElement('div');
      barTop.className = 'cap-bar cap-top';

      const concl = document.createElement('div');
      concl.className = 'concl-frame';
      concl.appendChild(makeEditable('h1', 'concl-title', slide.title, (v) => { slide.title = v; }, 'Заголовок'));

      if (slide.bullets && slide.bullets.length) {
        concl.appendChild(makeBulletList(slide, idx, slide.bullets, 0, false));
      } else {
        concl.appendChild(makeEditable('div', 'concl-body', slide.body, (v) => { slide.body = v; }, 'Текст вывода'));
      }

      concl.appendChild(makeEditable('p', 'concl-foot', slide.subtitle, (v) => { slide.subtitle = v; }, 'Подпись внизу'));

      canvas.appendChild(barTop);
      canvas.appendChild(concl);
      wrapper.appendChild(canvas);
      return wrapper;
    }

    if (slide.kind === 'table') {
      const accent = document.createElement('div');
      accent.className = 'left-accent';

      const frame = document.createElement('div');
      frame.className = 'content-frame';

      const head = document.createElement('div');
      head.className = 'content-head';
      head.appendChild(makeEditable('h1', 'content-title', slide.title, (v) => { slide.title = v; }, 'Заголовок'));
      const underline = document.createElement('div');
      underline.className = 'title-underline';
      head.appendChild(underline);
      head.appendChild(makeEditable('p', 'content-subtitle', slide.subtitle, (v) => { slide.subtitle = v; }, 'Подзаголовок (необязательно)'));
      frame.appendChild(head);

      const tableWrap = document.createElement('div');
      tableWrap.className = 'canvas-table-wrap';

      const headers = slide.headers && slide.headers.length ? slide.headers : ['Колонка 1', 'Колонка 2'];
      if (!slide.headers || !slide.headers.length) slide.headers = [...headers];
      const rows = slide.rows && slide.rows.length ? slide.rows : [['', ''], ['', '']];
      if (!slide.rows || !slide.rows.length) slide.rows = rows.map((r) => [...r]);

      const table = document.createElement('table');
      table.className = 'canvas-table';

      const thead = document.createElement('thead');
      const trh = document.createElement('tr');
      slide.headers.forEach((h, ci) => {
        const th = document.createElement('th');
        th.appendChild(makeEditable('span', 'table-cell-h', h, (v) => { slide.headers[ci] = v; }, 'Заголовок'));
        trh.appendChild(th);
      });
      thead.appendChild(trh);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      slide.rows.forEach((row, ri) => {
        const tr = document.createElement('tr');
        for (let ci = 0; ci < slide.headers.length; ci += 1) {
          const td = document.createElement('td');
          const value = row[ci] != null ? row[ci] : '';
          td.appendChild(makeEditable('span', 'table-cell', value, (v) => {
            if (!slide.rows[ri]) slide.rows[ri] = [];
            slide.rows[ri][ci] = v;
          }, ''));
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      tableWrap.appendChild(table);
      frame.appendChild(tableWrap);

      canvas.appendChild(accent);
      canvas.appendChild(frame);
      wrapper.appendChild(canvas);
      return wrapper;
    }

    if (slide.kind === 'two_column') {
      const accent = document.createElement('div');
      accent.className = 'left-accent';

      const frame = document.createElement('div');
      frame.className = 'two-frame';

      const head = document.createElement('div');
      head.className = 'content-head';
      head.appendChild(makeEditable('h1', 'content-title', slide.title, (v) => { slide.title = v; }, 'Заголовок'));
      const underline = document.createElement('div');
      underline.className = 'title-underline';
      head.appendChild(underline);
      frame.appendChild(head);

      const bullets = slide.bullets || [];
      const splitAt = Math.max(1, Math.floor(bullets.length / 2)) || 1;
      const leftB = bullets.length ? bullets.slice(0, splitAt) : [];
      const rightB = bullets.length ? bullets.slice(splitAt) : [];

      const cols = document.createElement('div');
      cols.className = 'two-cols';

      const colL = document.createElement('div');
      colL.className = 'two-col';
      if (leftB.length) {
        colL.appendChild(makeBulletList(slide, idx, leftB, 0, false));
      } else {
        colL.appendChild(makeEditable('div', 'content-body', slide.body, (v) => { slide.body = v; }, 'Текст слайда'));
      }
      cols.appendChild(colL);

      const colR = document.createElement('div');
      colR.className = 'two-col';
      if (rightB.length) {
        colR.appendChild(makeBulletList(slide, idx, rightB, splitAt, false));
      } else {
        colR.appendChild(makeImagePane(slide, idx, 'inline-pane'));
      }
      cols.appendChild(colR);

      frame.appendChild(cols);
      canvas.appendChild(accent);
      canvas.appendChild(frame);
      wrapper.appendChild(canvas);
      return wrapper;
    }

    const accent = document.createElement('div');
    accent.className = 'left-accent';

    const frame = document.createElement('div');
    frame.className = 'content-frame';

    const head = document.createElement('div');
    head.className = 'content-head';
    head.appendChild(makeEditable('h1', 'content-title', slide.title, (v) => { slide.title = v; }, 'Заголовок'));
    const underline = document.createElement('div');
    underline.className = 'title-underline';
    head.appendChild(underline);
    frame.appendChild(head);

    const body = document.createElement('div');
    const hasImage = !!(slide.image_data_url || slide.image_prompt);
    const imageLeft =
      slide.kind === 'content' && hasImage && (slide.image_placement || 'right') === 'left';
    body.className = `content-body-row${hasImage ? ' with-image' : ''}${imageLeft ? ' image-left' : ''}`;

    const text = document.createElement('div');
    text.className = 'content-text';
    if (slide.subtitle) {
      text.appendChild(makeEditable('p', 'content-subtitle', slide.subtitle, (v) => { slide.subtitle = v; }, 'Подзаголовок'));
    } else {
      text.appendChild(makeEditable('p', 'content-subtitle empty-sub', slide.subtitle, (v) => { slide.subtitle = v; }, 'Подзаголовок'));
    }
    if (slide.bullets && slide.bullets.length) {
      text.appendChild(makeBulletList(slide, idx, slide.bullets, 0, false));
    }
    text.appendChild(makeEditable('div', 'content-body', slide.body, (v) => { slide.body = v; }, 'Текст слайда'));
    body.appendChild(text);

    if (hasImage) {
      body.appendChild(makeImagePane(slide, idx, 'inline-pane'));
    }

    frame.appendChild(body);
    canvas.appendChild(accent);
    canvas.appendChild(frame);
    wrapper.appendChild(canvas);
    return wrapper;
  }

  function renderActiveSlide() {
    deckEl.innerHTML = '';
    const idx = state.selectedIndex;
    const slide = state.plan.slides[idx];
    if (!slide) return;
    deckEl.appendChild(renderSlideFrame(slide, idx));
  }

  function render() {
    buildDesignToolbar();
    if (!ensureState()) return;
    refreshHeader();
    refreshKindControl();
    refreshDesignToolbar();
    renderEngagementPanel();
    renderWebImagePanel();
    renderSlideList();
    renderActiveSlide();
  }

  function moveSlide(delta) {
    if (!ensureState()) return;
    const idx = state.selectedIndex;
    const next = idx + delta;
    if (next < 0 || next >= state.plan.slides.length) return;
    const tmp = state.plan.slides[next];
    state.plan.slides[next] = state.plan.slides[idx];
    state.plan.slides[idx] = tmp;
    state.selectedIndex = next;
    persist();
    render();
  }

  addSlideBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    const next = normalizeSlide(
      {
        kind: 'content',
        title: `Новый слайд ${state.plan.slides.length + 1}`,
        bullets: ['Новый пункт'],
        style: {},
        image_placement: 'right',
      },
      state.plan.slides.length,
    );
    state.plan.slides.push(next);
    state.selectedIndex = state.plan.slides.length - 1;
    persist();
    render();
  });

  moveUpBtn.addEventListener('click', () => moveSlide(-1));
  moveDownBtn.addEventListener('click', () => moveSlide(1));

  duplicateBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    const clone = JSON.parse(JSON.stringify(currentSlide()));
    clone.title = `${clone.title} (копия)`;
    state.plan.slides.splice(state.selectedIndex + 1, 0, clone);
    state.selectedIndex += 1;
    persist();
    render();
  });

  deleteBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    if (state.plan.slides.length <= 1) return;
    state.plan.slides.splice(state.selectedIndex, 1);
    if (state.selectedIndex >= state.plan.slides.length) state.selectedIndex = state.plan.slides.length - 1;
    persist();
    render();
  });

  kindEl.addEventListener('change', () => {
    if (!ensureState()) return;
    const slide = currentSlide();
    slide.kind = kindEl.value;
    if (slide.kind === 'table' && (!slide.headers || !slide.headers.length)) {
      slide.headers = ['Параметр', 'Значение'];
      slide.rows = [['', ''], ['', ''], ['', '']];
    }
    persist();
    render();
  });

  addBulletBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    currentSlide().bullets.push('Новый пункт');
    persist();
    render();
  });

  if (tblAddRowBtn) {
    tblAddRowBtn.addEventListener('click', () => {
      if (!ensureState()) return;
      const s = currentSlide();
      if (s.kind !== 'table') return;
      const n = (s.headers && s.headers.length) || 2;
      if (!s.rows) s.rows = [];
      if (s.rows.length >= 8) return;
      s.rows.push(new Array(n).fill(''));
      persist();
      render();
    });
  }
  if (tblDelRowBtn) {
    tblDelRowBtn.addEventListener('click', () => {
      if (!ensureState()) return;
      const s = currentSlide();
      if (s.kind !== 'table' || !s.rows || s.rows.length <= 1) return;
      s.rows.pop();
      persist();
      render();
    });
  }
  if (tblAddColBtn) {
    tblAddColBtn.addEventListener('click', () => {
      if (!ensureState()) return;
      const s = currentSlide();
      if (s.kind !== 'table') return;
      if (!s.headers) s.headers = [];
      if (s.headers.length >= 6) return;
      s.headers.push(`Колонка ${s.headers.length + 1}`);
      s.rows = (s.rows || []).map((r) => [...r, '']);
      persist();
      render();
    });
  }
  if (tblDelColBtn) {
    tblDelColBtn.addEventListener('click', () => {
      if (!ensureState()) return;
      const s = currentSlide();
      if (s.kind !== 'table' || !s.headers || s.headers.length <= 2) return;
      s.headers.pop();
      s.rows = (s.rows || []).map((r) => r.slice(0, s.headers.length));
      persist();
      render();
    });
  }

  changeImageBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    imageFileEl.click();
  });

  clearImageBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    currentSlide().image_data_url = '';
    imageFileEl.value = '';
    persist();
    render();
  });

  imageFileEl.addEventListener('change', (e) => {
    if (!ensureState()) return;
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      alert('Фото слишком большое. Максимум 4 МБ.');
      e.target.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      currentSlide().image_data_url = String(reader.result || '');
      persist();
      render();
    };
    reader.readAsDataURL(file);
  });

  webImageSearchBtn?.addEventListener('click', async () => {
    if (!ensureState()) return;
    const slide = currentSlide();
    if (!(slide.kind === 'content' || slide.kind === 'two_column')) return;
    const query = (webImageQueryEl?.value || '').trim() || slide.image_prompt || slide.title || '';
    if (!query) return;
    webImageSearchBtn.disabled = true;
    if (webImageStatusEl) webImageStatusEl.textContent = 'Ищем картинки...';
    if (webImageGridEl) webImageGridEl.innerHTML = '';
    try {
      const data = await window.SF.apiJson('/api/web-images', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, count: 6, aspect: '16:9' }),
      });
      const items = Array.isArray(data.items) ? data.items : [];
      if (webImageStatusEl) webImageStatusEl.textContent = `Найдено: ${items.length}`;
      items.forEach((src, idx) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'web-image-item';
        b.innerHTML = `<img src="${src}" alt="web-${idx}" /><div class="cap">Выбрать</div>`;
        b.addEventListener('click', () => {
          slide.image_data_url = src;
          slide.image_prompt = query;
          persist();
          render();
        });
        webImageGridEl?.appendChild(b);
      });
    } catch (e) {
      if (webImageStatusEl) webImageStatusEl.textContent = e.message || String(e);
    } finally {
      webImageSearchBtn.disabled = false;
    }
  });

  engageBtn?.addEventListener('click', async () => {
    if (!ensureState()) return;
    engageBtn.disabled = true;
    engageBtn.textContent = 'Считаем риск скуки...';
    if (engageSummaryEl) engageSummaryEl.textContent = 'Анализируем перегруженные слайды...';
    try {
      const data = await window.SF.apiJson('/api/engagement-heatmap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: state.plan }),
      });
      state.engagement = data;
      persist();
      render();
    } catch (e) {
      if (engageSummaryEl) engageSummaryEl.textContent = e.message || String(e);
    } finally {
      engageBtn.disabled = false;
      engageBtn.textContent = 'Анти‑Душнила анализ';
    }
  });

  regenBtn.addEventListener('click', async () => {
    if (!ensureState()) return;
    const instruction = regenInstructionEl.value.trim();
    if (!instruction) {
      regenStatusEl.textContent = 'Введите инструкцию для перегенерации.';
      return;
    }
    regenBtn.disabled = true;
    regenStatusEl.textContent = 'Перегенерируем слайд...';
    try {
      const resp = await window.SF.apiJson('/api/regenerate-slide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan: state.plan,
          slide_index: state.selectedIndex,
          instruction,
          images_mode: state.payload?.images_mode || 'with-images',
        }),
      });
      const oldImage = currentSlide().image_data_url;
      const next = normalizeSlide(resp.slide || {}, state.selectedIndex);
      if (oldImage && !next.image_data_url) next.image_data_url = oldImage;
      state.plan.slides[state.selectedIndex] = next;
      persist();
      render();
      regenStatusEl.textContent = 'Слайд обновлен.';
    } catch (e) {
      regenStatusEl.textContent = e.message || String(e);
    } finally {
      regenBtn.disabled = false;
    }
  });

  exportBtn.addEventListener('click', async () => {
    if (!ensureState()) return;
    exportBtn.disabled = true;
    exportBtn.textContent = 'Подготовка экспорта...';
    try {
      const payload = {
        plan: state.plan,
        images_mode: state.payload?.images_mode || 'with-images',
        image_backend: state.payload?.image_backend || 'yandex-art',
        output_format: state.payload?.output_format || 'both',
      };
      const data = await window.SF.apiJson('/api/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      state.currentJobId = data.job_id;
      persist();
      location.href = `/export.html?job=${encodeURIComponent(data.job_id)}`;
    } catch (e) {
      alert(e.message || String(e));
      exportBtn.disabled = false;
      exportBtn.textContent = 'Скачать презентацию';
    }
  });

  render();
})();
