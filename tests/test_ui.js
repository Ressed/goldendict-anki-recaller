// Run with: node tests/test_ui.js. All HTTP requests are mocked; no Anki writes.
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {JSDOM} = require('../.test-tools/node_modules/jsdom');
const html = execFileSync('python', ['-X', 'utf8', '-c', `
import anki_lookup as a
from tests.test_bridge import card
cs=[card(1),card(2)|{'_matched_word':'lemma'},card(3,queue=-1),card(4,kind=2,queue=2),card(5,queue=-2)]
print(a.render('first',cs)+a.render('second',[card(6)]))
`], {encoding:'utf8', cwd:require('node:path').resolve(__dirname, '..')});

function page(mode = 'success') {
  const requests = [];
  const dom = new JSDOM(html, {url:'gdlookup://localhost/', runScripts:'dangerously', beforeParse(w) {
    w.fetch = async (url, options) => {
      const request = JSON.parse(options.body); requests.push(request);
      if (request.action === 'gdPromoteNew' && mode === 'fail') throw Error('lost response');
      const result = request.action === 'requestPermission' ?
        {permission:mode === 'denied' ? 'denied' : 'granted'} : {message:'已提队', mode:'queue-first'};
      return {ok:true, json:async () => ({result, error:null})};
    };
  }});
  return {dom, requests, roots:dom.window.document.querySelectorAll('.anki-lookup')};
}
function select(root, id) { root.querySelector('input[value="' + id + '"]').click(); }
function button(root) { return root.querySelector('button'); }
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  let p = page(); let [first, second] = p.roots;
  assert.equal(p.requests.length, 0, 'query performs no HTTP');
  assert.equal(first.querySelector('input[value="1"]').checked, true);
  assert.equal(first.querySelectorAll('input[type=radio]:checked').length, 1);
  assert.equal(first.querySelector('.anki-card').classList.contains('is-selected'), true);
  assert.equal(button(first).disabled, false);
  assert.match(first.querySelector('.anki-result').textContent, /已选 card 1/);
  assert.equal(second.querySelector('input[value="6"]').checked, true);
  assert.equal(button(second).disabled, false);
  select(first, 2);
  assert.equal(p.requests.length, 0, 'selection performs no HTTP');
  button(first).click(); button(first).click();
  await settle();
  assert.equal(p.requests.filter(r => r.action === 'gdPromoteNew').length, 1);
  assert.equal(p.requests[0].gdBridgeOrigin, 'gdlookup://localhost');
  assert.equal(p.requests[1].gdBridgeOrigin, 'gdlookup://localhost');
  assert.deepEqual(p.requests[1].params, {cardId:2, word:'lemma', field:'Word',
    deck:'English', caseSensitive:false, unsuspend:false, studyDeck:null});
  assert.equal(button(first).disabled, true, 'success cannot be repeated');
  assert.match(first.querySelector('.anki-result').textContent, /已提队/);
  select(second, 6); button(second).click(); await settle();
  assert.equal(p.requests[3].params.word, 'second');
  assert.equal(p.requests[3].params.cardId, 6);
  select(first, 4); assert.equal(button(first).disabled, true);
  select(first, 5); assert.equal(button(first).disabled, true);
  select(first, 3); assert.equal(button(first).disabled, true);
  first.querySelector('.anki-unsuspend').click();
  assert.equal(button(first).disabled, false);
  select(first, 1); select(first, 3);
  assert.equal(first.querySelector('.anki-unsuspend').checked, false, 'consent resets per selection');
  first.querySelector('.anki-unsuspend').click(); button(first).click(); await settle();
  assert.equal(p.requests.at(-1).params.unsuspend, true);
  p.dom.window.close();

  p = page('fail'); first = p.roots[0];
  select(first, 1); button(first).click(); await settle();
  assert.equal(button(first).disabled, true);
  assert.match(first.querySelector('.anki-result').textContent, /可能已生效/);
  assert.equal(first.querySelector('input[type=radio]').disabled, true);
  button(first).click(); await settle();
  assert.equal(p.requests.length, 2, 'uncertain write never retried');
  p.dom.window.close();

  p = page('denied'); first = p.roots[0];
  select(first, 1); button(first).click(); await settle();
  assert.equal(p.requests.length, 1, 'denial prevents write');
  assert.equal(button(first).disabled, false);
  p.dom.window.close();
  console.log('UI checks passed: selection, isolation, double-click, states, consent, success, uncertainty, denial.');
})().catch(error => {console.error(error); process.exitCode = 1;});
