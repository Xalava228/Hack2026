(function () {
  const statusMsgEl = document.getElementById('status-msg');
  const progressFillEl = document.getElementById('progress-fill');
  const resultWrapEl = document.getElementById('result-wrap');
  const errorWrapEl = document.getElementById('error-wrap');
  const resultTitleEl = document.getElementById('result-title');
  const resultSubEl = document.getElementById('result-sub');
  const resultLinksEl = document.getElementById('result-links');
  const outlineEl = document.getElementById('outline');

  const stepEls = Array.from(document.querySelectorAll('#step-list [data-s]'));

  function setStep(stage) {
    const order = ['planning', 'images', 'rendering', 'done'];
    const map = { planned: 'planning', queued: 'planning' };
    const current = map[stage] || stage || 'planning';
    const idx = order.indexOf(current);
    stepEls.forEach((el, i) => {
      el.classList.remove('active', 'done');
      if (i < idx) el.classList.add('done');
      else if (i === idx) el.classList.add('active');
    });
  }

  function renderResult(jobId, result) {
    resultWrapEl.classList.remove('hide');
    resultTitleEl.textContent = `Готово: ${result.title}`;
    resultSubEl.textContent = `${result.slides} слайдов · ${result.images_used} картинок · ${result.elapsed_sec} сек`;
    resultLinksEl.innerHTML = '';

    if (result.pptx) {
      const a = document.createElement('a');
      a.className = 'result-link';
      a.href = `/api/jobs/${jobId}/file/pptx`;
      a.textContent = `Скачать PPTX (${result.pptx})`;
      a.download = result.pptx;
      resultLinksEl.appendChild(a);
    }
    if (result.pdf) {
      const a = document.createElement('a');
      a.className = 'result-link';
      a.href = `/api/jobs/${jobId}/file/pdf`;
      a.textContent = `Скачать PDF (${result.pdf})`;
      a.download = result.pdf;
      resultLinksEl.appendChild(a);
    }

    outlineEl.innerHTML = '';
    (result.outline || []).forEach((s, i) => {
      const row = document.createElement('div');
      row.className = 'outline-row';
      row.innerHTML = `<div>${i + 1}.</div><div class="kind">${window.SF.escapeHtml(s.kind)}</div><div>${window.SF.escapeHtml(s.title || '')}</div>`;
      outlineEl.appendChild(row);
    });
  }

  async function start() {
    const state = window.SF.loadState() || {};
    const params = new URLSearchParams(location.search);
    const jobId = params.get('job') || state.currentJobId;
    if (!jobId) {
      statusMsgEl.textContent = 'Нет задачи экспорта. Вернитесь в редактор и запустите экспорт.';
      return;
    }

    try {
      const job = await window.SF.pollJob(jobId, (data) => {
        setStep(data.stage);
        progressFillEl.style.width = `${Math.round((data.progress || 0) * 100)}%`;
        statusMsgEl.textContent = data.message || 'Выполняется...';
      });
      setStep('done');
      progressFillEl.style.width = '100%';
      statusMsgEl.textContent = 'Экспорт завершен.';
      if (job.result) renderResult(jobId, job.result);
    } catch (e) {
      errorWrapEl.classList.remove('hide');
      errorWrapEl.textContent = e.message || String(e);
      statusMsgEl.textContent = 'Экспорт завершился с ошибкой.';
    }
  }

  start();
})();
