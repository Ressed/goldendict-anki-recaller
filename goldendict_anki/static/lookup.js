(function () {
  'use strict';
  // Each execution binds only its own article, even with several dictionary results.
  const root = document.currentScript.parentElement;
  if (root.dataset.ankiBound) return;
  root.dataset.ankiBound = 'true';
  const cfg = JSON.parse(root.querySelector('.anki-config').textContent);
  const button = root.querySelector('.anki-promote');
  if (!button) return;
  const output = root.querySelector('.anki-result');
  const consent = root.querySelector('.anki-unsuspend');
  const consentLabel = root.querySelector('.anki-unsuspend-label');
  const radios = Array.from(root.querySelectorAll('input[type=radio]'));
  const completed = new Set();
  let selected = null, busy = false, uncertain = false;

  function update() {
    consentLabel.hidden = !selected || selected.type !== 0 || selected.queue !== -1;
    const eligible = selected && selected.type === 0 &&
      (selected.queue === 0 || (selected.queue === -1 && consent.checked));
    button.disabled = busy || uncertain || !eligible || completed.has(selected.cardId);
    radios.forEach(r => { r.disabled = busy || uncertain; });
    consent.disabled = busy || uncertain;
  }
  radios.forEach(radio => radio.addEventListener('change', function () {
    selected = cfg.cards.find(c => String(c.cardId) === radio.value);
    consent.checked = false;
    root.querySelectorAll('.anki-card').forEach(el => {
      el.classList.toggle('is-selected', el.dataset.cardId === radio.value);
    });
    output.textContent = completed.has(selected.cardId) ? '这张卡已提队。' :
      selected.type !== 0 ? '这张卡已进入学习，保留当前复习安排。' :
      selected.queue === -1 ? '如需提队，请先勾选解除暂停。' :
      selected.queue !== 0 ? '这张卡当前不可提队，请在 Anki 中检查状态。' :
      '已选 card ' + selected.cardId + '；点击按钮才会提队。';
    update();
  }));
  consent.addEventListener('change', update);
  // A non-empty result always starts with the first sense selected. Dispatching
  // the normal change path keeps button/status rules identical to later choices.
  if (radios.length) {
    radios[0].checked = true;
    radios[0].dispatchEvent(new Event('change'));
  }

  async function call(action, params) {
    const body = {action: action, version: 6, params: params || {}};
    // GoldenDict rewrites the HTTP Origin of POSTs. The add-on repairs CORS
    // only for these marked actions when gdlookup://localhost is whitelisted.
    if (window.location.protocol === 'gdlookup:' && window.location.hostname === 'localhost') {
      body.gdBridgeOrigin = 'gdlookup://localhost';
    }
    if (cfg.key) body.key = cfg.key;
    const controller = new AbortController();
    // First-time permission is a human dialog; allow time to switch to Anki.
    const timeout = action === 'requestPermission' ? Math.max(120, cfg.timeout) : cfg.timeout;
    const timer = setTimeout(() => controller.abort(), timeout * 1000);
    try {
      const response = await fetch(cfg.url, {method:'POST',
        headers:{'Content-Type':'text/plain;charset=UTF-8'},
        body:JSON.stringify(body), signal:controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!data || !Object.prototype.hasOwnProperty.call(data, 'result') ||
          !Object.prototype.hasOwnProperty.call(data, 'error')) throw new Error('响应格式错误');
      if (data.error) throw new Error(data.error);
      return data.result;
    } finally { clearTimeout(timer); }
  }

  button.addEventListener('click', async function () {
    if (button.disabled || busy || !selected) return;
    const card = selected;
    const unsuspend = card.queue === -1 && consent.checked;
    busy = true;
    update();
    let submitted = false;
    output.textContent = '正在连接 Anki；如出现访问授权，请在 Anki 窗口处理。';
    try {
      const permission = await call('requestPermission');
      if (!permission || permission.permission !== 'granted') throw new Error('未授权 GoldenDict 访问 Anki');
      if (permission.requireApikey && !cfg.key) throw new Error('请在 config.json 配置 AnkiConnect API key');
      submitted = true;
      const result = await call('gdPromoteNew', {cardId:card.cardId, word:card.word,
        field:cfg.field, deck:card.deckName, caseSensitive:cfg.caseSensitive, unsuspend:unsuspend,
        studyDeck:cfg.studyDeck});
      if (!result || typeof result.message !== 'string' || result.mode !== 'queue-first') {
        throw new Error('插队插件版本不匹配，请安装新版插件并重启 Anki');
      }
      completed.add(card.cardId);
      root.querySelector('.anki-card[data-card-id="' + card.cardId + '"] .anki-state').textContent = '新卡 · 已加入当前学习队列首位';
      output.textContent = 'card ' + card.cardId + '：' + result.message;
    } catch (error) {
      // A failed response does not prove a write failed: never enable a blind retry.
      uncertain = submitted;
      output.textContent = submitted ?
        '提队未确认：' + error.message + '。可能已生效或部分生效，请重新查词并在 Anki 核对后再操作。' :
        '连接或授权失败（requestPermission，尚未发送提队请求）：' + error.message +
        '。页面来源：' + window.location.origin + '；页面协议：' + window.location.protocol +
        '；目标：' + cfg.url +
        '。请在 GoldenDict 按 F12 查看 Console 中的网络/CORS 错误；仅凭此提示不能确定是否为来源授权问题。';
    } finally {
      busy = false;
      update();
    }
  });
}());
