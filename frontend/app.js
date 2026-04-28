/* SlideForge.AI — клиентская логика. */
(function () {
  const form = document.getElementById('gen-form');
  const submitBtn = document.getElementById('submit-btn');
  const slidesInput = document.getElementById('n_slides');
  const slidesVal = document.getElementById('n_slides_val');
  const progressCard = document.getElementById('progress-card');
  const progressMsg = document.getElementById('progress-msg');
  const progressTitle = document.getElementById('progress-title');
  const barFill = document.getElementById('bar-fill');
  const stepsEl = document.getElementById('steps');
  const resultCard = document.getElementById('result-card');
  const resultTitle = document.getElementById('result-title');
  const resultSub = document.getElementById('result-sub');
  const downloadsEl = document.getElementById('downloads');
  const outlineEl = document.getElementById('outline');
  const restartBtn = document.getElementById('restart-btn');
  const errorCard = document.getElementById('error-card');
  const errorMsg = document.getElementById('error-msg');
  const retryBtn = document.getElementById('retry-btn');

  slidesInput.addEventListener('input', () => {
    slidesVal.textContent = slidesInput.value;
  });

  document.querySelectorAll('.seg').forEach((seg) => {
    seg.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      seg.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  function readSeg(name) {
    const seg = document.querySelector(`.seg[data-name="${name}"]`);
    const active = seg?.querySelector('button.active');
    return active?.dataset.value;
  }

  function setActiveStep(stage) {
    const order = ['planning', 'planned', 'images', 'rendering', 'done'];
    const stageMap = {
      planning: 'planning',
      planned: 'planning',
      images: 'images',
      rendering: 'rendering',
      done: 'done',
    };
    const cur = stageMap[stage] || 'planning';
    const idx = ['planning', 'images', 'rendering', 'done'].indexOf(cur);
    stepsEl.querySelectorAll('li').forEach((li, i) => {
      li.classList.remove('active', 'done');
      if (i < idx) li.classList.add('done');
      else if (i === idx) li.classList.add('active');
    });
  }

  function show(el) { el.classList.remove('hidden'); }
  function hide(el) { el.classList.add('hidden'); }

  function reset() {
    hide(progressCard);
    hide(resultCard);
    hide(errorCard);
    submitBtn.disabled = false;
    submitBtn.querySelector('.btn-text').textContent = 'Сгенерировать ✨';
  }

  restartBtn?.addEventListener('click', () => {
    reset();
    document.getElementById('generator').scrollIntoView({ behavior: 'smooth' });
  });
  retryBtn?.addEventListener('click', reset);

  async function pollJob(jobId) {
    let lastStage = '';
    while (true) {
      let resp;
      try {
        resp = await fetch(`/api/jobs/${jobId}`);
      } catch (e) {
        await sleep(1500);
        continue;
      }
      if (!resp.ok) {
        throw new Error('Не удалось получить статус задачи');
      }
      const data = await resp.json();
      if (data.stage !== lastStage) {
        setActiveStep(data.stage);
        lastStage = data.stage;
      }
      barFill.style.width = `${Math.round((data.progress || 0) * 100)}%`;
      progressMsg.textContent = data.message || '';
      if (data.status === 'done') return data;
      if (data.status === 'error') throw new Error(data.error || 'Ошибка генерации');
      await sleep(1200);
    }
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function renderResult(data, jobId) {
    const r = data.result;
    resultTitle.textContent = `«${r.title}» готова!`;
    resultSub.textContent = `${r.slides} слайдов · ${r.images_used} картинок · ${r.elapsed_sec} сек`;

    downloadsEl.innerHTML = '';
    if (r.pptx) {
      const a = document.createElement('a');
      a.className = 'dl';
      a.href = `/api/jobs/${jobId}/file/pptx`;
      a.innerHTML = `<span class="ext">PPTX</span> Скачать ${r.pptx}`;
      a.download = r.pptx;
      downloadsEl.appendChild(a);
    }
    if (r.pdf) {
      const a = document.createElement('a');
      a.className = 'dl';
      a.href = `/api/jobs/${jobId}/file/pdf`;
      a.innerHTML = `<span class="ext">PDF</span> Скачать ${r.pdf}`;
      a.download = r.pdf;
      downloadsEl.appendChild(a);
    }

    outlineEl.innerHTML = '';
    (r.outline || []).forEach((s, i) => {
      const row = document.createElement('div');
      row.className = 'outline-row';
      row.innerHTML = `
        <span class="num">${i + 1}.</span>
        <span class="kind">${s.kind}</span>
        <span class="ttl">${escapeHtml(s.title)}</span>
      `;
      outlineEl.appendChild(row);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hide(errorCard);
    hide(resultCard);
    show(progressCard);
    progressTitle.textContent = 'Готовим вашу презентацию…';
    progressMsg.textContent = 'Отправляем запрос…';
    barFill.style.width = '4%';
    setActiveStep('planning');

    submitBtn.disabled = true;
    submitBtn.querySelector('.btn-text').textContent = 'Идёт генерация…';

    const payload = {
      prompt: document.getElementById('prompt').value.trim(),
      n_slides: parseInt(slidesInput.value, 10),
      text_density: readSeg('text_density'),
      images_mode: readSeg('images_mode'),
      image_backend: readSeg('image_backend'),
      output_format: readSeg('output_format'),
    };

    try {
      const r = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`Сервер ответил ${r.status}: ${txt}`);
      }
      const { job_id } = await r.json();
      const data = await pollJob(job_id);
      hide(progressCard);
      renderResult(data, job_id);
      show(resultCard);
      resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      hide(progressCard);
      errorMsg.textContent = err.message || String(err);
      show(errorCard);
    } finally {
      submitBtn.disabled = false;
      submitBtn.querySelector('.btn-text').textContent = 'Сгенерировать ✨';
    }
  });
})();
