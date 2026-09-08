(() => {
  const fileInput = document.getElementById('fileInput');
  const fileDrop = document.getElementById('fileDrop');
  const fileLabel = document.getElementById('fileLabel');
  const layoutSelect = document.getElementById('layoutSelect');
  const translateBtn = document.getElementById('translateBtn');
  const statusMsg = document.getElementById('statusMsg');
  const resultPanel = document.getElementById('resultPanel');
  const bodyEn = document.getElementById('bodyEn');
  const bodyZh = document.getElementById('bodyZh');

  let docId = null;

  function setStatus(text, isError = false) {
    statusMsg.textContent = text;
    statusMsg.classList.toggle('error', isError);
  }

  async function handleFile(file) {
    if (!file) return;
    fileLabel.textContent = file.name;
    translateBtn.disabled = true;
    setStatus('正在上传...');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '上传失败');
      docId = data.doc_id;
      translateBtn.disabled = false;
      setStatus(`已上传：${data.filename}，可以点击"开始翻译"`);
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  fileInput.addEventListener('change', () => handleFile(fileInput.files[0]));

  fileDrop.addEventListener('dragover', (e) => {
    e.preventDefault();
    fileDrop.classList.add('dragover');
  });
  fileDrop.addEventListener('dragleave', () => fileDrop.classList.remove('dragover'));
  fileDrop.addEventListener('drop', (e) => {
    e.preventDefault();
    fileDrop.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) {
      fileInput.files = e.dataTransfer.files;
      handleFile(file);
    }
  });

  translateBtn.addEventListener('click', async () => {
    if (!docId) return;
    translateBtn.disabled = true;
    setStatus('正在翻译，请稍候...');

    try {
      const res = await fetch('/api/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: docId, layout: layoutSelect.value }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '翻译失败');
      renderResult(data);
      setStatus(`翻译完成，共 ${data.sentence_count} 句`);
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      translateBtn.disabled = false;
    }
  });

  function renderResult(data) {
    bodyEn.innerHTML = '';
    bodyZh.innerHTML = '';

    data.paragraphs.forEach((para) => {
      const pEn = document.createElement('p');
      const pZh = document.createElement('p');

      para.sentences.forEach((s, i) => {
        const spanEn = document.createElement('span');
        spanEn.className = 'sentence';
        spanEn.dataset.id = s.id;
        spanEn.textContent = s.en + (i < para.sentences.length - 1 ? ' ' : '');

        const spanZh = document.createElement('span');
        spanZh.className = 'sentence';
        spanZh.dataset.id = s.id;
        spanZh.textContent = s.zh + (i < para.sentences.length - 1 ? ' ' : '');

        pEn.appendChild(spanEn);
        pZh.appendChild(spanZh);
      });

      bodyEn.appendChild(pEn);
      bodyZh.appendChild(pZh);
    });

    resultPanel.hidden = false;
  }

  function clearHighlights() {
    document.querySelectorAll('.sentence.highlight').forEach((el) => el.classList.remove('highlight'));
  }

  function highlightId(id) {
    clearHighlights();
    document.querySelectorAll(`.sentence[data-id="${id}"]`).forEach((el) => {
      el.classList.add('highlight');
    });
  }

  function isInView(el, container) {
    const r = el.getBoundingClientRect();
    const cr = container.getBoundingClientRect();
    return r.top >= cr.top && r.bottom <= cr.bottom;
  }

  function scrollToMatch(id, sourcePane) {
    const targetPane = sourcePane === bodyEn ? bodyZh : bodyEn;
    const target = targetPane.querySelector(`.sentence[data-id="${id}"]`);
    if (target && !isInView(target, targetPane)) {
      target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  function attachHoverSync(pane) {
    pane.addEventListener('mouseover', (e) => {
      const span = e.target.closest('.sentence');
      if (!span) return;
      highlightId(span.dataset.id);
      scrollToMatch(span.dataset.id, pane);
    });
  }

  [bodyEn, bodyZh].forEach(attachHoverSync);

  resultPanel.addEventListener('mouseleave', clearHighlights);
})();
