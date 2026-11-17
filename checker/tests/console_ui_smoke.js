/* 콘솔 화면 스모크: 가짜 DOM 위에서 app.js 를 실제로 돌려 세션·질문·승인·새 작업 화면이 오류 없이 그려지는지 본다. */
const path = require('path');
const dir = process.argv[2];
const scenario = process.argv[3];

function Text(s) { this.nodeType = 3; this.text = String(s); this.parentNode = null; }
// app.js patchChildren(#793)이 쓰는 DOM 속성: 글 노드의 이름·값·자식
Text.prototype = { nodeName: '#text', namespaceURI: null, childNodes: [], get nodeValue() { return this.text; }, set nodeValue(v) { this.text = String(v); },
  isEqualNode(o) { return !!o && o.nodeType === 3 && o.text === this.text; } };
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
/* 진짜 NodeList 처럼 length·인덱스·item·forEach·for-of 만 있고 filter·map 은 없다. app.js 가 배열 메서드를 바로 쓰면 시험이 TypeError 로 잡는다. */
function nodeList(arr) {
  const nl = { length: arr.length, item: i => arr[i] || null, forEach: (f, t) => arr.forEach(f, t), [Symbol.iterator]: () => arr[Symbol.iterator]() };
  arr.forEach((e, i) => { nl[i] = e; });
  return nl;
}
function El(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.parentNode = null; this._text = null; this.listeners = {}; this.dataset = {}; this.style = {}; this.value = ''; this.checked = false; this.open = false; this.readOnly = false; }
El.prototype = {
  nodeType: 1,
  get tagName() { return this.tag.toUpperCase(); },
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); this._text = null; return c; },
  insertBefore(c, ref) { if (c.parentNode) c.parentNode.removeChild(c); const i = ref ? this.children.indexOf(ref) : -1; c.parentNode = this; if (i < 0) this.children.push(c); else this.children.splice(i, 0, c); this._text = null; return c; },
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; },
  get firstChild() { return this.children[0] || null; },
  get lastChild() { return this.children[this.children.length - 1] || null; },
  replaceChildren() { this.children.forEach(c => { c.parentNode = null; }); this.children = []; this._text = null; for (const c of arguments) this.appendChild(c); },
  setAttribute(k, v) { this.attrs[k] = String(v); },
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  hasAttribute(k) { return k in this.attrs; },
  removeAttribute(k) { delete this.attrs[k]; },
  get attributes() { return Object.keys(this.attrs).map(name => ({ name, value: this.attrs[name] })); },
  get childNodes() { return this.children; },
  get nodeName() { return this.tag.toUpperCase(); },
  namespaceURI: null, nodeValue: null,
  replaceChild(nu, old) { const i = this.children.indexOf(old); if (nu.parentNode) nu.parentNode.removeChild(nu); const j = this.children.indexOf(old); this.children.splice(j, 1, nu); nu.parentNode = this; old.parentNode = null; this._text = null; return old; },
  isEqualNode(o) {
    if (!o || o.nodeType !== 1 || o.tag !== this.tag || o.children.length !== this.children.length) return false;
    const a = Object.keys(this.attrs), b = Object.keys(o.attrs);
    if (a.length !== b.length || a.some(k => this.attrs[k] !== o.attrs[k])) return false;
    return this.children.every((c, i) => c.isEqualNode(o.children[i]));
  },
  get className() { return this.attrs['class'] || ''; }, set className(v) { this.attrs['class'] = v; },
  get disabled() { return 'disabled' in this.attrs; }, set disabled(v) { if (v) this.attrs.disabled = ''; else delete this.attrs.disabled; },  // 진짜 DOM 처럼 속성과 같이 움직인다(patchChildren 이 달라진 단추를 알아채게)
  get hidden() { return 'hidden' in this.attrs; }, set hidden(v) { if (v) this.attrs.hidden = ''; else delete this.attrs.hidden; },
  set textContent(v) { this.children.forEach(c => { c.parentNode = null; }); this.children = []; this._text = null; if (String(v) !== '') this.appendChild(new Text(v)); },  // 진짜 DOM 처럼 글 노드 하나를 자식으로 둔다(patchChildren 이 고칠 수 있게)
  get textContent() { return this._text !== null ? this._text : this.children.map(t => t.nodeType === 3 ? t.text : t.textContent).join(''); },
  addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); },
  get isConnected() { let e = this; while (e.parentNode) e = e.parentNode; return e === document.body || e === root; },
  focus() { document.activeElement = this; }, setSelectionRange() {}, dispatchEvent(e) { (this.listeners[e && e.type] || []).forEach(f => f({ target: this, currentTarget: this })); }, scrollIntoView(o) { scrolled.push([this.attrs['class'] || this.tag, JSON.stringify(o || {})]); },
  contains(o) { while (o) { if (o === this) return true; o = o.parentNode; } return false; },
  get clientWidth() { return 1200; },
  querySelectorAll(sel) {
    if (sel.includes(',')) { const seen = new Set(); return nodeList(sel.split(',').flatMap(s => Array.from(this.querySelectorAll(s.trim()))).filter(e => !seen.has(e) && seen.add(e))); }  // 쉼표로 이은 목록
    const chain = sel.split(/\s+/).filter(Boolean), out = [];
    const walk = (e, anc) => { e.children.forEach(c => { if (c.nodeType !== 1) return; if (matches(c, chain, anc)) out.push(c); walk(c, anc.concat(c)); }); };
    walk(this, []); return nodeList(out);
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
const DOC_LISTENERS = {};  // document 에 건 리스너(팝업의 Esc·Tab 시험용: {"key": "Escape"} 동작이 부른다)
const root = new El('div'); root.attrs.id = 'root';
global.document = { createElement: t => new El(t), createElementNS: (n, t) => new El(t), createTextNode: s => new Text(s), body: new El('body'),
  documentElement: new El('html'), activeElement: null, hidden: false,
  getElementById: id => { const all = root.querySelectorAll('#' + id); return all[0] || (id === 'root' ? root : null); },
  addEventListener(n, f) { (DOC_LISTENERS[n] = DOC_LISTENERS[n] || []).push(f); }, removeEventListener(n, f) { DOC_LISTENERS[n] = (DOC_LISTENERS[n] || []).filter(x => x !== f); }, set title(v) { this._t = v; }, get title() { return this._t; } };
document.body.appendChild(root);
root.parentNode = document.body;
global.window = global; window.scrollTo = () => {};
const LS = {};  // 시험이 data.json 의 "__ls" 로 미리 넣어 두고 out.ls 로 읽는다(새로고침 흉내)
global.localStorage = { getItem: k => (k in LS ? LS[k] : null), setItem: (k, v) => { LS[k] = String(v); }, removeItem: k => { delete LS[k]; } };
const SS = {};  // sessionStorage 흉내(닫은 알림 표시). 시험이 data.json 의 "__ss" 로 미리 넣고 out.ss 로 읽는다
global.sessionStorage = { getItem: k => (k in SS ? SS[k] : null), setItem: (k, v) => { SS[k] = String(v); }, removeItem: k => { delete SS[k]; } };
global.location = { pathname: '/', search: '' };
global.history = { pushState(_, __, p) { const u = new URL(p, 'http://x'); location.pathname = u.pathname; location.search = u.search; }, replaceState(_, __, p) { this.pushState(_, __, p); } };
global.addEventListener = () => {};
global.requestAnimationFrame = f => setTimeout(f, 0);
const ES_LISTENERS = {};  // 시험이 서버 이벤트(SSE)를 흉내 내려고 모아 둔다
let ES_LAST = null;
global.EventSource = function () { ES_LAST = this; this.addEventListener = (n, f) => { ES_LISTENERS[n] = f; }; this.close = () => {}; };
global.AbortController = AbortController;
global.Event = function (type) { this.type = type; };
global.CSS = { escape: s => String(s).replace(/[^\w-]/g, c => '\\' + c) };  // 브라우저 CSS.escape 흉내(선택자 해석기는 \ 를 풀지 않으니 시험은 글자·숫자·-·_ 만 쓴다)

const DATA = JSON.parse(require('fs').readFileSync(process.argv[4], 'utf8'));
Object.assign(LS, DATA['__ls'] || {});
Object.assign(SS, DATA['__ss'] || {});
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
// 브라우저 알림 가짜. DATA.__env = {notification: granted|denied|default|absent, ask: 물었을 때 답, visible: bool}
const ENV = DATA.__env || {};
const notes = [], noteObjs = [], asked = [];
if (ENV.notification && ENV.notification !== 'absent') {
  global.Notification = function (title, opts) { notes.push(Object.assign({ title }, opts)); noteObjs.push(this); this.close = () => {}; };
  Notification.permission = ENV.notification;
  Notification.requestPermission = () => { asked.push(1); Notification.permission = ENV.ask || 'denied'; return Promise.resolve(Notification.permission); };
}
const focused = [], scrolled = [];  // scrolled: scrollIntoView 호출 기록
global.focus = () => { focused.push(1); };
document.visibilityState = ENV.visible ? 'visible' : 'hidden';
document.hasFocus = () => !!ENV.visible;
const errors = [];
console.error = (...a) => errors.push(a.join(' '));
console.warn = () => {};
process.on('unhandledRejection', e => errors.push('unhandled ' + (e && e.stack || e)));
{ const parts = (process.argv[5] || '').split('?'); location.pathname = '/' + parts[0]; location.search = parts[1] ? '?' + parts[1] : ''; }

for (const f of ['theme.js', 'md.js', 'flow-logic.js', 'api-notice.js', 'notice-logic.js', 'flow-ui.js', 'trouble.js', 'attach.js', 'app.js']) { const m = require(path.join(dir, f)); if (f === 'flow-logic.js') window.BHLogic = m; if (f === 'api-notice.js') window.BHApiNotice = m; if (f === 'notice-logic.js') window.BHNotice = m; if (f === 'attach.js') window.BHAttach = m; }
const tick = (n) => new Promise(r => setTimeout(r, n || 20));
(async () => {
  await tick(80);
  // 선택: argv[7] 의 동작 목록을 차례로 실행한다. [{"click": "선택자", "index": 0}] — 누른 뒤 화면이 다시 그려지기를 기다린다.
  // 그 밖의 동작: {"set": {"GET /api/...": 본문}} 서버 답 바꾸기, {"emit": ["session", {"id": "s1"}]} 서버 이벤트 보내기(뒤이어 기다림),
  // {"es": "error"} 서버 연결 끊김, {"es": "open"} 다시 붙음.
  // {"clickNote": 0} 알림 누르기, {"visible": true} 탭 보임 바꾸기.
  const out_values = [];  // type 동작 뒤 입력칸에 남은 값(가림 확인용)
  for (const act of JSON.parse(process.argv[7] || '[]')) {
    if (act.set) { Object.assign(DATA, act.set); continue; }
    if (act.wait) { await tick(act.wait); continue; }  // {"wait": 밀리초} 시간이 지나기를 기다린다(다시 묻기 시험)
    if (act.es) { if (!ES_LAST) errors.push('EventSource 없음'); else { const f = ES_LAST['on' + act.es]; if (f) f(); } await tick(200); continue; }  // {"es": "error"|"open"} 연결 끊김·다시 붙음 흉내
    if (act.key) { (DOC_LISTENERS.keydown || []).slice().forEach(f => f({ key: act.key, shiftKey: !!act.shift, preventDefault() {} })); await tick(80); continue; }  // {"key": "Escape"|"Tab", "shift": bool} 키보드
    if (act.focus) { const f = document.body.querySelector(act.focus); if (f) f.focus(); else errors.push('초점 줄 곳이 없음 ' + act.focus); continue; }  // {"focus": 선택자}
    if (act.visible !== undefined) { document.visibilityState = act.visible ? 'visible' : 'hidden'; document.hasFocus = () => !!act.visible; continue; }
    if (act.emit) { const f = ES_LISTENERS[act.emit[0]]; if (f) f({ data: JSON.stringify(act.emit[1]) }); else errors.push('이벤트 구독 없음 ' + act.emit[0]); await tick(400); continue; }
    if (act.clickNote !== undefined) { const o = noteObjs[act.clickNote]; if (o && o.onclick) o.onclick(); else errors.push('누를 알림이 없음'); await tick(80); continue; }
    if (act.theme) { window.BH.setTheme(act.theme); (DOC_LISTENERS['bh-theme'] || []).slice().forEach(f => f({ detail: act.theme })); await tick(80); continue; }  // {"theme": "post"|"sauce"} 테마 바꾸기(가짜 document 는 이벤트를 안 쏘니 리스너를 직접 부른다)
    if (act.read) { const el = root.querySelectorAll(act.read)[act.index || 0]; out_values.push(el ? el.value : null); continue; }  // {"read": 선택자} 입력칸의 지금 값
    if (act.type) {  // {"type": 선택자, "value": 글, "index": n} 입력칸에 글을 넣고 input 이벤트를 보낸다(붙여 넣기 흉내)
      const el = root.querySelectorAll(act.type)[act.index || 0];
      if (!el) { errors.push('입력칸이 없음 ' + act.type); continue; }
      el.value = act.value; (el.listeners.input || []).forEach(f => f({ target: el, currentTarget: el })); await tick(80);
      out_values.push(el.value); continue;
    }
    const hit = document.body.querySelectorAll(act.click)[act.index || 0];  // 알림 팝업은 body 바로 밑에 붙는다
    if (!hit) { errors.push('누를 곳이 없음 ' + act.click); continue; }
    hit.click(); await tick(80);
  }
  const main = root.querySelector('main');
  const out = { text: main ? main.textContent : '(no main)', errors, calls: calls.map(c => c[0] + ' ' + c[1]), values: out_values };
  const dump = (e, d) => { if (e.nodeType === 3) return e.text; return '<' + e.tag + (e.open ? '[open]' : '') + (e.attrs['class'] ? '.' + e.attrs['class'].replace(/ /g, '.') : '') + '>' + e.children.map(c => dump(c, d + 1)).join('') + '</' + e.tag + '>'; };
  out.dump = main ? dump(main, 0) : '';
  out.notes = notes; out.asked = asked.length; out.focused = focused.length; out.path = location.pathname; out.ls = Object.assign({}, LS);
  out.posts =calls.filter(c => c[0] !== 'GET').map(c => [c[0], c[1], c[2] || '']);
  out.scrolled = scrolled; out.active = document.activeElement ? [document.activeElement.tag, document.activeElement.attrs['data-flow'] || ''] : null;
  out.ariaDisabled = Array.from(root.querySelectorAll('button')).filter(b => b.attrs['aria-disabled'] === 'true').map(b => b.textContent);
  out.disabledButtons = Array.from(root.querySelectorAll('button')).filter(b => b.disabled).map(b => b.textContent);  // 눌러도 되는지(#885)
  out.links = Array.from(root.querySelectorAll('a')).map(a => [a.attrs.href || '', a.attrs.target || '', a.attrs.rel || '']);
  out.side = root.querySelector('.side') ? root.querySelector('.side').textContent : '';
  out.sideDump = root.querySelector('.side') ? dump(root.querySelector('.side'), 0) : '';
  out.ann = root.querySelector('.ann-slot') ? root.querySelector('.ann-slot').textContent : '';
  const back = document.body.querySelector('.nb-back');  // 알림 팝업(열려 있을 때)
  out.dialog = back ? back.textContent : ''; out.dialogDisabled = back ? Array.from(back.querySelectorAll('button')).filter(b => b.disabled).map(b => b.textContent) : []; out.annBubble = root.querySelector('.ann-slot') ? root.querySelector('.ann-slot').attrs['data-bubble'] || '' : ''; out.dialogDump = back ? dump(back, 0) : ''; out.activeK = document.activeElement && document.activeElement.attrs ? (document.activeElement.attrs['data-k'] || document.activeElement.attrs['class'] || document.activeElement.attrs.id || '') : ''; out.ss = Object.assign({}, SS);
  out.bubble = root.querySelector('.nb-bubble') ? root.querySelector('.nb-bubble').textContent : '';
  out.dot = root.querySelectorAll('.nb-dot').length;
  out.limits = root.querySelector('.lim') ? root.querySelector('.lim').textContent : '';
  out.limitsTitle = root.querySelector('.lim') ? root.querySelector('.lim').attrs.title : '';
  out.activeId = document.activeElement && document.activeElement.attrs ? document.activeElement.attrs.id || '' : '';
  out.pressed =Array.from(root.querySelectorAll('.qopt')).map(b => b.attrs['aria-pressed']);
  out.head =root.querySelector('header') ? root.querySelector('header').textContent : '';
  
  require('fs').writeFileSync(process.argv[6], JSON.stringify(out, null, 1), 'utf8');
  process.exit(0);
})();
