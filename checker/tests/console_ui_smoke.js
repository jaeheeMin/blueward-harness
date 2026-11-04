/* 콘솔 화면 스모크: 가짜 DOM 위에서 app.js 를 실제로 돌려 세션·질문·승인·새 작업 화면이 오류 없이 그려지는지 본다. */
const path = require('path');
const dir = process.argv[2];
const scenario = process.argv[3];

function Text(s) { this.nodeType = 3; this.text = String(s); this.parentNode = null; }
function matchSimple(el, sel) {
  // 한 덩어리: tag#id.class[attr][attr=v]
  const re = /^([a-zA-Z0-9]*)((?:[#.][\w-]+|\[[^\]]+\])*)$/;
  const m = re.exec(sel); if (!m) throw new Error('selector ' + sel);
  if (m[1] && el.tag.toLowerCase() !== m[1].toLowerCase()) return false;
  const parts = m[2].match(/[#.][\w-]+|\[[^\]]+\]/g) || [];
  return parts.every(p => {
    if (p[0] === '#') return el.attrs.id === p.slice(1);
    if (p[0] === '.') return (el.attrs['class'] || '').split(/\s+/).includes(p.slice(1));
    const q = /^\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]$/.exec(p);
    if (!(q[1] in el.attrs) && !(q[1] === 'hidden' && el.hidden)) return false;
    return q[2] === undefined || el.attrs[q[1]] === q[2];
  });
}
function El(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.parentNode = null; this._text = null; this.listeners = {}; this.dataset = {}; this.style = {}; this.value = ''; this.disabled = false; this.checked = false; this.open = false; this.readOnly = false; }
El.prototype = {
  nodeType: 1,
  get tagName() { return this.tag.toUpperCase(); },
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); this._text = null; return c; },
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; },
  get firstChild() { return this.children[0] || null; },
  get lastChild() { return this.children[this.children.length - 1] || null; },
  replaceChildren() { this.children.forEach(c => { c.parentNode = null; }); this.children = []; this._text = null; for (const c of arguments) this.appendChild(c); },
  setAttribute(k, v) { this.attrs[k] = String(v); },
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  get className() { return this.attrs['class'] || ''; }, set className(v) { this.attrs['class'] = v; },
  get hidden() { return 'hidden' in this.attrs; }, set hidden(v) { if (v) this.attrs.hidden = ''; else delete this.attrs.hidden; },
  set textContent(v) { this.children.forEach(c => { c.parentNode = null; }); this.children = []; this._text = String(v); },
  get textContent() { return this._text !== null ? this._text : this.children.map(t => t.nodeType === 3 ? t.text : t.textContent).join(''); },
  addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); },
  get isConnected() { let e = this; while (e.parentNode) e = e.parentNode; return e === document.body || e === root; },
  focus() { document.activeElement = this; }, setSelectionRange() {}, dispatchEvent() {},
  contains(o) { while (o) { if (o === this) return true; o = o.parentNode; } return false; },
  get clientWidth() { return 1200; },
  querySelectorAll(sel) {
    const chain = sel.split(/\s+/).filter(Boolean), out = [];
    const walk = (e, anc) => { e.children.forEach(c => { if (c.nodeType !== 1) return; if (matches(c, chain, anc)) out.push(c); walk(c, anc.concat(c)); }); };
    walk(this, []); return out;
  },
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
  click() { (this.listeners.click || []).forEach(f => f({ preventDefault() {}, target: this, currentTarget: this, button: 0 })); }
};
function matches(el, chain, anc) {
  if (!matchSimple(el, chain[chain.length - 1])) return false;
  let i = chain.length - 2, a = anc.length - 2;
  while (i >= 0) { while (a >= 0 && !matchSimple(anc[a], chain[i])) a--; if (a < 0) return false; i--; a--; }
  return true;
}
const root = new El('div'); root.attrs.id = 'root';
global.document = { createElement: t => new El(t), createElementNS: (n, t) => new El(t), createTextNode: s => new Text(s), body: new El('body'),
  documentElement: new El('html'), activeElement: null, hidden: false,
  getElementById: id => { const all = root.querySelectorAll('#' + id); return all[0] || (id === 'root' ? root : null); },
  addEventListener() {}, removeEventListener() {}, set title(v) { this._t = v; }, get title() { return this._t; } };
document.body.appendChild(root);
root.parentNode = document.body;
global.window = global; window.scrollTo = () => {};
global.localStorage = { getItem: () => null, setItem: () => {} };
global.location = { pathname: '/', search: '' };
global.history = { pushState(_, __, p) { const u = new URL(p, 'http://x'); location.pathname = u.pathname; location.search = u.search; }, replaceState(_, __, p) { this.pushState(_, __, p); } };
global.addEventListener = () => {};
global.requestAnimationFrame = f => setTimeout(f, 0);
global.EventSource = function () { this.addEventListener = () => {}; this.close = () => {}; };
global.AbortController = AbortController;
global.Event = function () {};

const DATA = JSON.parse(require('fs').readFileSync(process.argv[4], 'utf8'));
const calls = [];
global.fetch = (url, opts) => {
  const method = (opts && opts.method) || 'GET', p = url.split('?')[0];
  calls.push([method, url, opts && opts.body]);
  const key = method + ' ' + p;
  let body = DATA[key];
  if (body === undefined) body = DATA['*'] === undefined ? undefined : (typeof DATA['*'] === 'function' ? DATA['*'](key) : DATA['*']);
  const status = body === undefined ? 404 : 200;
  return Promise.resolve({ status, ok: status < 400, text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)) });
};
const errors = [];
console.error = (...a) => errors.push(a.join(' '));
console.warn = () => {};
process.on('unhandledRejection', e => errors.push('unhandled ' + (e && e.stack || e)));
{ const parts = (process.argv[5] || '').split('?'); location.pathname = '/' + parts[0]; location.search = parts[1] ? '?' + parts[1] : ''; }

for (const f of ['theme.js', 'md.js', 'flow-logic.js', 'flow-ui.js', 'app.js']) { const m = require(path.join(dir, f)); if (f === 'flow-logic.js') window.BHLogic = m; }
const tick = (n) => new Promise(r => setTimeout(r, n || 20));
(async () => {
  await tick(80);
  // 선택: argv[7] 의 동작 목록을 차례로 실행한다. [{"click": "선택자", "index": 0}] — 누른 뒤 화면이 다시 그려지기를 기다린다.
  for (const act of JSON.parse(process.argv[7] || '[]')) {
    const hit = root.querySelectorAll(act.click)[act.index || 0];
    if (!hit) { errors.push('누를 곳이 없음 ' + act.click); continue; }
    hit.click(); await tick(80);
  }
  const main = root.querySelector('main');
  const out = { text: main ? main.textContent : '(no main)', errors, calls: calls.map(c => c[0] + ' ' + c[1]) };
  const dump = (e, d) => { if (e.nodeType === 3) return e.text; return '<' + e.tag + (e.open ? '[open]' : '') + (e.attrs['class'] ? '.' + e.attrs['class'].replace(/ /g, '.') : '') + '>' + e.children.map(c => dump(c, d + 1)).join('') + '</' + e.tag + '>'; };
  out.dump = main ? dump(main, 0) : '';
  out.posts = calls.filter(c => c[0] !== 'GET').map(c => [c[0], c[1], c[2] || '']);
  out.side = root.querySelector('.side') ? root.querySelector('.side').textContent : '';
  out.sideDump = root.querySelector('.side') ? dump(root.querySelector('.side'), 0) : '';
  out.ann = root.querySelector('.ann-slot') ? root.querySelector('.ann-slot').textContent : '';
  out.head =root.querySelector('header') ? root.querySelector('header').textContent : '';
  
  require('fs').writeFileSync(process.argv[6], JSON.stringify(out, null, 1), 'utf8');
  process.exit(0);
})();
