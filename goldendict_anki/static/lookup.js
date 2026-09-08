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

  async function promote(card, unsuspend) {
    if (!cfg.bridge) throw new Error('本地按钮服务不可用，请重新查词');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), (cfg.timeout * 6 + 5) * 1000);
    try {
      const response = await fetch(cfg.bridge.url + '/promote', {method:'POST',
        headers:{'Content-Type':'text/plain;charset=UTF-8'},
        body:JSON.stringify({token:cfg.bridge.token, params:{card_id:card.cardId,
          word:card.word, deck:card.deckName, unsuspend:unsuspend}}), signal:controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!data || !Object.prototype.hasOwnProperty.call(data, 'result') ||
          !Object.prototype.hasOwnProperty.call(data, 'error')) throw new Error('响应格式错误');
      if (data.error) throw new Error(data.error);
      if (!data.result || typeof data.result.message !== 'string') throw new Error('响应格式错误');
      return data.result;
    } finally { clearTimeout(timer); }
  }

  button.addEventListener('click', async function () {
    if (button.disabled || busy || !selected) return;
    const card = selected;
    const unsuspend = card.queue === -1 && consent.checked;
    busy = true;
    update();
    output.textContent = '正在设为今天到期的复习卡…';
    try {
      const result = await promote(card, unsuspend);
      completed.add(card.cardId);
      root.querySelector('.anki-card[data-card-id="' + card.cardId + '"] .anki-state').textContent = '复习 · 今天到期（绿卡）';
      output.textContent = 'card ' + card.cardId + '：' + result.message;
    } catch (error) {
      // A failed response does not prove a write failed: never enable a blind retry.
      uncertain = true;
      output.textContent = '提队未确认：' + error.message +
        '。设置到期日或解除暂停可能已生效，请重新查词并在 Anki 核对后再操作；页面长时间未使用时，本地按钮服务可能已退出。';
    } finally {
      busy = false;
      update();
    }
  });
}());
