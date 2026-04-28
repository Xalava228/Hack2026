(function () {
  const state = window.SF.loadState();

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

  const regenInstructionEl = document.getElementById('regen-instruction');
  const regenStatusEl = document.getElementById('regen-status');
  const regenBtn = document.getElementById('regen-slide');
  const exportBtn = document.getElementById('export-btn');

  function persist() {
    window.SF.saveState(state);
  }

  function normalizeSlide(slide, idx) {
    return {
      kind: String(slide?.kind || (idx === 0 ? 'title' : 'content')),
      title: String(slide?.title || `Слайд ${idx + 1}`),
      subtitle: String(slide?.subtitle || ''),
      bullets: Array.isArray(slide?.bullets) ? slide.bullets.map(String) : [],
      body: String(slide?.body || ''),
      image_prompt: String(slide?.image_prompt || ''),
      image_data_url: String(slide?.image_data_url || ''),
      notes: String(slide?.notes || ''),
    };
  }

  function ensureState() {
    if (!state || !state.plan || !Array.isArray(state.plan.slides) || !state.plan.slides.length) {
      editorEmptyEl.classList.remove('hide');
      editorContentEl.classList.add('hide');
      return false;
    }
    state.plan.slides = state.plan.slides.map(normalizeSlide);
    if (state.selectedIndex == null || state.selectedIndex < 0) state.selectedIndex = 0;
    if (state.selectedIndex > state.plan.slides.length - 1) state.selectedIndex = state.plan.slides.length - 1;
    editorEmptyEl.classList.add('hide');
    editorContentEl.classList.remove('hide');
    return true;
  }

  function currentSlide() {
    return state.plan.slides[state.selectedIndex];
  }

  function refreshHeader() {
    editorTitleEl.textContent = state.plan.title || 'Визуальный редактор';
    editorSubEl.textContent = `${state.plan.slides.length} слайдов · редактируйте напрямую в макете`;
    activeSlideLabelEl.textContent = `${state.selectedIndex + 1}`;
  }

  function refreshKindControl() {
    kindEl.value = currentSlide().kind;
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
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `slide-chip${idx === state.selectedIndex ? ' active' : ''}`;
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

  function applyPalette(canvas, palette) {
    const p = palette || {};
    const map = {
      '--p-bg': p.background || '#FFFFFF',
      '--p-primary': p.primary || '#1F2937',
      '--p-accent': p.accent || '#6366F1',
      '--p-text': p.text || '#111827',
      '--p-muted': p.muted || '#6B7280',
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
    applyPalette(canvas, state.plan.palette);

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
    body.className = `content-body-row${hasImage ? ' with-image' : ''}`;

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
    if (!ensureState()) return;
    refreshHeader();
    refreshKindControl();
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
    const next = normalizeSlide({ kind: 'content', title: `Новый слайд ${state.plan.slides.length + 1}`, bullets: ['Новый пункт'] }, state.plan.slides.length);
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
    currentSlide().kind = kindEl.value;
    persist();
    render();
  });

  addBulletBtn.addEventListener('click', () => {
    if (!ensureState()) return;
    currentSlide().bullets.push('Новый пункт');
    persist();
    render();
  });

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
