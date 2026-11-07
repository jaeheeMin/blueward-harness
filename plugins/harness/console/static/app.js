/* Blueward Harness 콘솔. 순수 JS, 빌드 없음(화면 규칙 계산은 flow-logic.js, 갈래 화면은 flow-ui.js). 세션에서 온 문자열은 모두 textContent 로만 넣는다. */
(function () {
  'use strict';

  /* ---------- 작은 도구 ---------- */
  function h(tag, props) {
    var el = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v == null || v === false) return;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'open') el[k] = v;
        else if (v === true) el.setAttribute(k, '');
        else el.setAttribute(k, String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(parent, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(parent, x); }); return; }
    parent.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  var SVGNS = 'http://www.w3.org/2000/svg';
  var ICONS = {
    chev: { d: 'M9 5l7 7-7 7', w: 2 }, back: { d: 'M15 5l-7 7 7 7', w: 2 }, close: { d: 'M6 6l12 12M18 6L6 18', w: 2 },
    brand: { d: 'M4 6l7 6-7 6M13 6l7 6-7 6', w: 2.2 },
    settings: { d: 'M4 7h10M18 7h2M4 17h2M10 17h10', w: 1.8, extra: [['circle', { cx: 16, cy: 7, r: 2 }], ['circle', { cx: 8, cy: 17, r: 2 }]] },
    folder: { d: 'M3 6h6l2 2h10v11H3z', w: 1.8 }, plus: { d: 'M12 5v14M5 12h14', w: 2 },
    panel: { d: 'M4 5h16v14H4zM9 5v14', w: 1.8 }, warn: { d: 'M12 4l9 16H3zM12 10v4M12 17v.5', w: 1.6 },
    plug: { d: 'M9 3v5M15 3v5M6 8h12v3a6 6 0 01-12 0zM12 17v4', w: 1.6 }
  };
  function icon(name, size) {
    var def = ICONS[name], s = document.createElementNS(SVGNS, 'svg');
    s.setAttribute('aria-hidden', 'true'); s.setAttribute('width', size || 16); s.setAttribute('height', size || 16);
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', def.w); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
    var p = document.createElementNS(SVGNS, 'path'); p.setAttribute('d', def.d); s.appendChild(p);
    (def.extra || []).forEach(function (e) {
      var n = document.createElementNS(SVGNS, e[0]);
      Object.keys(e[1]).forEach(function (k) { n.setAttribute(k, e[1][k]); });
      s.appendChild(n);
    });
    return s;
  }
  function toDate(v) {
    if (v == null || v === '') return null;
    if (typeof v === 'number') return new Date(v < 1e12 ? v * 1000 : v);
    var d = new Date(v);
    return isNaN(d.getTime()) ? null : d;
  }
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function clock(v) { var d = toDate(v); return d ? pad(d.getHours()) + ':' + pad(d.getMinutes()) : String(v == null ? '' : v); }
  function minutesSince(v) { var d = toDate(v); return d ? Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000)) : null; }
  function elapsedParts(v) {
    var m = minutesSince(v);
    if (m == null) return null;
    if (m < 1) return [['방금', '']];
    if (m < 60) return [[String(m), '분']];
    var hr = Math.floor(m / 60), mm = m % 60;
    return mm ? [[String(hr), '시간'], [String(mm), '분']] : [[String(hr), '시간']];
  }
  function waitedText(v) { var m = minutesSince(v); return m == null ? '' : m < 1 ? ' · 방금' : ' · ' + (m < 60 ? m + '분째' : Math.floor(m / 60) + '시간째'); }
  function baseName(p) { var s = String(p || '').replace(/[\\/]+$/, ''); var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\')); return i >= 0 ? s.slice(i + 1) : s; }
  function fmtSize(n) {
    if (typeof n === 'string') return n;
    if (typeof n !== 'number') return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return Math.max(1, Math.round(n / 1024)) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }
  function safeHttp(u) {
    try { var p = new URL(u); return p.protocol === 'http:' || p.protocol === 'https:' ? p.href : null; } catch (e) { return null; }
  }
  function str(v) { return v == null ? '' : typeof v === 'string' ? v : JSON.stringify(v); }

  /* ---------- API ---------- */
  function ApiError(status, message, data) { this.status = status; this.message = message; this.data = data; }
  var conn = { state: 'loading' };
  function setConn(s) { if (conn.state !== s) { conn.state = s; onConn(); } }
  function errMessage(data, status) {
    if (data) {
      var m = data.error || data.message || data.detail;
      if (m && typeof m === 'object') m = m.message || JSON.stringify(m);
      if (m) return String(m);
    }
    return '요청을 처리하지 못했습니다 (' + status + ')';
  }
  /* 브라우저는 한 서버에 HTTP/1.x 연결을 6개까지만 연다(SSE 가 1개씩 차지한다). 읽기(GET)는 동시에 MAX_GETS 개까지만 보내고
     나머지는 줄 세워, 느린 응답 몇 개가 연결을 다 쓰고 다른 요청을 막지 않게 한다. 쓰기(POST 등)는 줄 세우지 않는다. */
  var MAX_GETS = 3, getsActive = 0, getsWaiting = [], GET_TIMEOUT_MS = 45000;
  function api(method, path, body) {
    if (method !== 'GET') return send(method, path, body);
    return new Promise(function (resolve, reject) {
      function go() {
        getsActive++;
        send(method, path, body).then(resolve, reject).then(function () {
          getsActive--;
          var next = getsWaiting.shift();
          if (next) next();
        });
      }
      if (getsActive < MAX_GETS) go(); else getsWaiting.push(go);
    });
  }
  function send(method, path, body) {
    var opts = { method: method, credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    var timer = null;
    if (method === 'GET' && typeof AbortController === 'function') {  // 끝나지 않는 읽기가 줄을 영영 막지 않게 한다
      var ac = new AbortController();
      opts.signal = ac.signal;
      timer = setTimeout(function () { ac.abort(); }, GET_TIMEOUT_MS);
    }
    return fetch(path, opts).then(function (res) {
      clearTimeout(timer);
      if (res.status === 401) { setConn('auth'); throw new ApiError(401, '콘솔을 다시 여세요.'); }
      setConn('ok');
      return res.text().then(function (t) {
        var data = null;
        if (t) { try { data = JSON.parse(t); } catch (e) { data = null; } }
        if (!res.ok) throw new ApiError(res.status, errMessage(data, res.status), data);
        return data;
      });
    }, function () {
      clearTimeout(timer);
      setConn('down');
      throw new ApiError(0, '서버에 연결할 수 없습니다.');
    });
  }
  function qs(obj) {
    var p = new URLSearchParams();
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (Array.isArray(v)) v.forEach(function (x) { p.append(k, x); });
      else if (v != null && v !== '') p.append(k, v);
    });
    var s = p.toString(); return s ? '?' + s : '';
  }
  function listOf(data, key) { return Array.isArray(data) ? data : (data && Array.isArray(data[key]) ? data[key] : []); }

  /* ---------- 상태 ---------- */
  var sessions = new Map();   // id -> session
  var requests = new Map();   // rid -> request
  var loadedOnce = false;
  var reqFetching = {};
  var SKILL_LABELS = {
    start: '작업 시작', sync: '최신 받기', deliver: '제출하기', wrapup: '이슈로 남기기', srs: '요구사항 문서',
    spec: '개발 Spec', scaffold: '구조 만들기', atc: 'ATC 고치기', prs: '내 PR', approvals: '승인 대기',
    version: '버전 보기', update: '업데이트', open: '콘솔 열기'
  };
  function skillLabel(id, obj) {
    if (obj && (obj.label || obj.name)) return obj.label || obj.name;
    return SKILL_LABELS[id] || id || '';
  }

  /* ---------- 브라우저 알림(#651) ---------- */
  var askCfg = null;  // 서버에 저장된 {level}. 읽기 전엔 null
  var notifyCfg = null, notifyAsked = false;  // notifyCfg: 서버에 저장된 {turn, blocked, done}. 읽기 전엔 null
  function notifySupported() { return typeof window.Notification === 'function'; }
  function notifyPerm() { return notifySupported() ? window.Notification.permission : 'unsupported'; }
  function notifyActive() { return !!(notifyCfg && (notifyCfg.turn || notifyCfg.blocked || notifyCfg.done) && notifyPerm() === 'granted'); }
  function loadNotify() {
    if (notifyAsked) return;
    notifyAsked = true;
    api('GET', '/api/settings/notify').then(function (d) { notifyCfg = d || null; }, function () { notifyAsked = false; });
  }
  function pageVisible() { return document.visibilityState === 'visible' && (typeof document.hasFocus !== 'function' || document.hasFocus()); }
  function notifyChange(prev, next) {
    if (!notifyActive() || !prev) return;
    // 질문인지 승인인지는 요청을 받아 와야 안다. 받는 중이면 받은 뒤에 보낸다.
    var wait = (next.pendingRequestIds || []).map(function (r) { return reqFetching[r]; }).filter(Boolean);
    if (wait.length) Promise.all(wait).then(function () { notifySend(prev, next); }); else notifySend(prev, next);
  }
  function notifySend(prev, next) {
    if (!notifyActive()) return;
    var evs = window.BHLogic.notifyEvents(prev, next, notifyCfg, {
      visible: pageVisible(), name: sessionTitle(next),
      reqKind: function (rid) { return requests.has(rid) ? kindOf(requests.get(rid)) : ''; }
    });
    evs.forEach(function (e) {
      try {
        var n = new window.Notification(e.title, { body: e.body, tag: e.tag, renotify: true });
        n.onclick = function () {
          try { window.focus(); n.close(); } catch (x) { console.warn('알림 창을 앞으로 가져오지 못했습니다', x); }
          go(e.path);
        };
      } catch (x) { console.warn('알림을 띄우지 못했습니다', x); }
    });
  }

  function mergeSession(s) {
    if (!s || !s.id) return null;
    var prev = sessions.get(s.id);
    var old = prev || {};
    var m = Object.assign({}, old, s);
    sessions.set(s.id, m);
    (m.pendingRequestIds || []).forEach(ensureRequest);
    if (loadedOnce) notifyChange(prev, m);  // 첫 목록은 비교 기준만 잡는다
    return m;
  }
  function ensureRequest(rid) {
    if (requests.has(rid) || reqFetching[rid]) return;
    reqFetching[rid] = api('GET', '/api/requests/' + encodeURIComponent(rid)).then(function (r) {
      if (r) { r = r.request || r; if (!r.id) r.id = rid; requests.set(rid, r); scheduleSide(); if (view && view.onRequest) view.onRequest(rid); }
    }, function () {}).then(function () { delete reqFetching[rid]; });
  }
  var sessTimers = {};
  function refreshSession(id) {
    clearTimeout(sessTimers[id]);
    sessTimers[id] = setTimeout(function () {
      var open = route.name === 'session' && route.id === id;  // 대화(chat)는 지금 열어 본 세션만 받는다. 목록 갱신은 받아 둔 대화를 지우지 않는다
      api('GET', '/api/sessions/' + encodeURIComponent(id) + (open ? '' : '?chat=0')).then(function (d) {
        d = d && d.session ? d.session : d;
        if (d && d.id) { mergeSession(d); scheduleSide(); if (view && view.onSession) view.onSession(d.id); }
      }, function (e) { if (e.status === 404) { sessions.delete(id); scheduleSide(); if (view && view.onRemoved) view.onRemoved(id); } });
    }, 120);
  }
  function refreshRequest(rid) {
    api('GET', '/api/requests/' + encodeURIComponent(rid)).then(function (r) {
      r = r && r.request ? r.request : r; if (!r.id) r.id = rid;
      requests.set(rid, Object.assign({}, requests.get(rid) || {}, r));
      scheduleSide(); if (view && view.onRequest) view.onRequest(rid);
    }, function () {});
  }
  function loadSessions() {
    loadNotify();
    return api('GET', '/api/sessions').then(function (data) {
      var list = listOf(data, 'sessions'), seen = {};
      list.forEach(function (s) { if (s && s.id) { var rs = requests; (s.pendingRequestIds || []).forEach(function (rid) { var r = rs.get(rid); if (r && r.status && r.status !== 'pending') rs.delete(rid); }); } });
      list.forEach(function (s) { if (s && s.id) { seen[s.id] = true; mergeSession(s); } });
      Array.from(sessions.keys()).forEach(function (id) { if (!seen[id]) sessions.delete(id); });
      loadedOnce = true;
      scheduleSide();
      if (view && view.onData) view.onData();
    });
  }

  /* ---------- SSE ---------- */
  var es = null, retry = 0, retryTimer = null;
  function connectEvents() {
    if (es) { es.close(); es = null; }
    clearTimeout(retryTimer);
    if (document.hidden && !notifyActive()) { eventsPaused = true; return; }  // 숨겨진 탭은 붙지 않는다(보이면 붙는다). 알림을 켰으면 숨겨져도 붙어 있어야 알림이 온다
    try { es = new EventSource('/api/events'); } catch (e) { return scheduleRetry(); }
    es.onopen = function () { retry = 0; setConn('ok'); loadSessions().catch(function (e) { console.warn('세션 목록을 불러오지 못했습니다', e); }); };
    es.addEventListener('session', function (ev) {
      var d = parse(ev.data); if (!d) return;
      d = d.session || d;
      if (d.id) refreshSession(d.id);
    });
    es.addEventListener('request', function (ev) {
      var d = parse(ev.data); if (!d) return;
      d = d.request || d;
      if (d.id) refreshRequest(d.id);
    });
    es.addEventListener('removed', function (ev) {
      var d = parse(ev.data) || {};
      var id = d.id || d.sessionId || d.requestId || (typeof d === 'string' ? d : null);
      if (id) {
        sessions.delete(id);
        var wasRequest = requests.has(id);
        if (wasRequest) {
          var r = requests.get(id);
          requests.set(id, Object.assign({}, r, { status: r.status === 'pending' || !r.status ? 'closed' : r.status }));
        }
        scheduleSide();
        if (view && view.onRemoved) view.onRemoved(id);
      }
    });
    es.onerror = function () {
      if (es && es.readyState === 2) { es.close(); es = null; scheduleRetry(); }
      else if (conn.state === 'ok') setConn('down');
    };
  }
  function scheduleRetry() {
    setConn(conn.state === 'auth' ? 'auth' : 'down');
    retry = Math.min(retry + 1, 6);
    clearTimeout(retryTimer);
    retryTimer = setTimeout(function () {
      loadSessions().then(connectEvents, function (e) { if (e.status === 401) return; scheduleRetry(); });
    }, Math.min(1000 * Math.pow(2, retry - 1), 15000));
  }
  /* 숨겨진 탭은 SSE 를 닫는다. 탭을 여러 개 열어 둬도 브라우저의 서버당 연결 6개를 SSE 가 다 차지하지 않는다. 다시 보이면 붙는다. */
  var eventsPaused = false;
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (notifyActive()) return;  // 알림을 켠 탭은 숨겨져도 SSE 를 닫지 않는다
      eventsPaused = true;
      if (es) { es.close(); es = null; }
      clearTimeout(retryTimer);
    } else if (eventsPaused) {
      eventsPaused = false;
      connectEvents();
    }
  });
  function parse(s) { try { return JSON.parse(s); } catch (e) { return null; } }

  /* ---------- 라우팅 ---------- */
  var view = null, tick = null;
  var mainEl = null, sideEl = null, appEl = null;

  function parseRoute() {
    var p = location.pathname.replace(/\/+$/, '') || '/', m;
    if (p === '/') return { name: 'home' };
    if ((m = /^\/s\/([^/]+)$/.exec(p))) return { name: 'session', id: decodeURIComponent(m[1]) };
    if ((m = /^\/r\/([^/]+)$/.exec(p))) return { name: 'request', id: decodeURIComponent(m[1]) };
    if (p === '/new') return { name: 'new' };
    if (p === '/settings') return { name: 'settings' };
    if (p === '/docs') return { name: 'docs' };
    return { name: 'missing' };
  }
  var route = parseRoute();
  function go(path, replace) {
    if (path === location.pathname + location.search) return;
    history[replace ? 'replaceState' : 'pushState'](null, '', path);
    renderRoute();
  }
  function onLinkClick(e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.currentTarget;
    if (a.target === '_blank') return;
    e.preventDefault();
    go(a.getAttribute('href'));
  }
  function link(href, props) {
    var a = h.apply(null, ['a', Object.assign({ href: href, onClick: onLinkClick }, props)].concat([].slice.call(arguments, 2)));
    return a;
  }
  window.addEventListener('popstate', renderRoute);

  function renderRoute() {
    route = parseRoute();
    if (view && view.destroy) view.destroy();
    clearInterval(tick); tick = null;
    view = null;
    if (conn.state === 'auth') return renderAuth();
    renderedOnce = true;
    if (introWanted()) {  // 헤더 · 목록 없이 가운데 밝은 판 하나(시안 01)
      appEl.setAttribute('data-intro', '1');
      clear(mainEl);
      mainEl.appendChild(introView());
      setTitle('처음 화면');
      return;
    }
    appEl.setAttribute('data-intro', '0');
    clear(mainEl);
    mainEl.scrollTop = 0; window.scrollTo(0, 0);
    var root = h('div');
    mainEl.appendChild(connBanner());
    mainEl.appendChild(root);
    var v = ({ home: homeView, session: sessionView, request: requestView, 'new': newView, settings: settingsView, docs: docsView, missing: missingView })[route.name](root);
    view = v || null;
    if (v && v.tick) tick = setInterval(v.tick, 15000);
    scheduleSide();
    setTitle(v && v.title ? v.title() : '');
  }
  function setTitle(t) { document.title = (t ? t + ' · ' : '') + 'Blueward Harness'; }

  /* ---------- 연결 상태 ---------- */
  function connBanner() {
    var b = h('div', { class: 'conn', role: 'status', 'data-conn': '1' });
    b.hidden = true; fillConn(b); return b;
  }
  function fillConn(b) {
    clear(b);
    if (conn.state === 'down') {
      b.hidden = false;
      b.appendChild(h('span', { text: '서버와 연결이 끊겼습니다. 다시 연결하는 중입니다. 화면의 내용은 최신이 아닐 수 있습니다.' }));
      b.appendChild(h('button', { type: 'button', class: 'btn sm', text: '지금 다시 시도', onClick: function () { retry = 0; scheduleRetry(); } }));
    } else b.hidden = true;
  }
  function onConn() {
    if (!appEl) return;
    if (conn.state === 'auth') { renderAuth(); return; }
    var b = mainEl && mainEl.querySelector('[data-conn]');
    if (b) fillConn(b);
    if (conn.state === 'ok' && appEl.dataset.auth === '1') { appEl.dataset.auth = ''; renderRoute(); }
  }
  function renderAuth() {
    appEl.dataset.auth = '1';
    clear(mainEl);
    mainEl.appendChild(stateBox('plug', '콘솔을 다시 여세요',
      [h('span', { text: '이 화면은 연결이 끊겼습니다. Claude Code 에서 ' }), h('code', { text: '/harness:open' }), h('span', { text: ' 을 실행하면 새로 열립니다.' })]));
    if (es) { es.close(); es = null; }
    clearTimeout(retryTimer);
  }
  function stateBox(glyph, title, body, action) {
    return h('div', { class: 'state' },
      h('div', { class: 'glyph' }, icon(glyph, 28)),
      h('h1', { text: title }),
      h('p', null, body),
      action || null);
  }
  function loadingBox(label) {
    return h('div', { class: 'state', role: 'status' }, h('p', { text: label || '불러오는 중입니다.' }), h('div', { class: 'progress' }, h('i')));
  }

  /* ---------- 사이드바 ---------- */
  var collapsed = (function () {
    var v = window.BH.read('bh-side');
    if (v === '1') return true;
    if (v === '0') return false;
    return null;   // 아직 정하지 않음. 좁은 화면이면 접는다.
  })();
  function isCollapsed() {
    if (collapsed !== null) return collapsed;
    return appEl ? appEl.parentNode.clientWidth <= 760 : false;
  }
  function setCollapsed(v) { collapsed = v; window.BH.write('bh-side', v ? '1' : '0'); scheduleSide(); }
  var sideQueued = false;
  function scheduleSide() {
    if (sideQueued) return;
    sideQueued = true;
    requestAnimationFrame(function () { sideQueued = false; renderSide(); });
  }
  function groupOf(s) {
    if (s.group === 'todo' || s.group === 'running' || s.group === 'idle') return s.group;
    if ((s.pendingRequestIds || []).length || s.turnSkill || s.askedInText) return 'todo';
    return s.status === 'running' || s.status === 'starting' ? 'running' : 'idle';
  }
  function requestTitle(r) {
    if (!r) return '요청을 확인하세요';
    if (r.title) return r.title;
    var qs_ = questionsOf(r);
    if (kindOf(r) === 'question') return qs_.length ? (qs_[0].question || qs_[0].header || '질문이 있습니다') : '질문이 있습니다';
    return (r.toolName || r.tool_name || '도구') + ' 사용을 허용할까요?';
  }
  function kindOf(r) { return (r && (r.kind || r.type)) === 'question' ? 'question' : (r && (r.kind || r.type)) === 'permission' ? 'permission' : (questionsOf(r).length ? 'question' : 'permission'); }
  function questionsOf(r) {
    if (!r) return [];
    var q = r.questions || (r.toolInput && r.toolInput.questions) || (r.tool_input && r.tool_input.questions) || (r.input && r.input.questions);
    return Array.isArray(q) ? q : [];
  }
  function runningSubagents(s) { return (s.subagents || []).filter(function (a) { return a && a.state === 'running'; }); }
  function subagentSummary(s) { var n = runningSubagents(s).length; return n ? ' · 서브에이전트 ' + n + '개 실행 중' : ''; }
  function sideData() {
    var todo = [], run = [], idle = [];
    sessions.forEach(function (s) {
      var g = groupOf(s), sub = s.branch || baseName(s.cwd) || '';
      var title = s.title || baseName(s.cwd) || '이름 없는 세션';
      if (g === 'todo') {
        var ids = s.pendingRequestIds || [];
        if (ids.length) {
          ids.forEach(function (rid) {
            var r = requests.get(rid);
            if (r && r.status && r.status !== 'pending') return;
            todo.push({ sname: title, href: '/r/' + encodeURIComponent(rid), verb: !r ? '요청 확인하기' : kindOf(r) === 'question' ? '답하기' : '승인하기', title: requestTitle(r), sub: title, t: s.updatedAt });
          });
        } else {
          todo.push({ sname: title, href: '/s/' + encodeURIComponent(s.id), verb: s.askedInText ? '답하기(추정)' : s.turnSkill ? skillLabel(s.turnSkill) : '확인하기', title: title, sub: sub, t: s.updatedAt });
        }
      } else if (g === 'running') {
        run.push({ href: '/s/' + encodeURIComponent(s.id), title: title, sub: (s.currentAction || (s.currentSkill ? skillLabel(s.currentSkill) : '작업 중')) + subagentSummary(s), t: s.updatedAt });
      } else {
        idle.push({ href: '/s/' + encodeURIComponent(s.id), title: title, sub: s.status === 'ended' ? '끝난 세션' : sub, t: s.updatedAt });
      }
    });
    return { todo: todo, run: run, idle: idle };
  }
  var annEl = null, headEl = null;
  var SIDE_ORDER = { todo: 0, running: 1, idle: 2 };
  function sessionRank(s) { return s.status === 'ended' ? 3 : SIDE_ORDER[groupOf(s)]; }
  function sessionTitle(s) { return s.title || baseName(s.cwd) || '이름 없는 세션'; }
  function sortedSessions() {
    var arr = [];
    sessions.forEach(function (s) { arr.push(s); });
    arr.sort(function (a, b) { return (sessionRank(a) - sessionRank(b)) || ((b.updatedAt || 0) - (a.updatedAt || 0)); });
    return arr;
  }
  function firstPending(s) {
    var ids = s.pendingRequestIds || [];
    for (var i = 0; i < ids.length; i++) {
      var r = requests.get(ids[i]);
      if (!(r && r.status && r.status !== 'pending')) return { rid: ids[i], r: r };
    }
    return null;
  }
  /* 세션 한 줄 상태. 내 차례면 tone 이 attn 이다. */
  function sideStatus(s) {
    var g = groupOf(s);
    if (g === 'todo') {
      var p = firstPending(s);
      var verb = p ? (!p.r ? '요청 확인하기' : kindOf(p.r) === 'question' ? '답하기' : '승인하기') : s.askedInText ? '답하기(추정)' : s.turnSkill ? skillLabel(s.turnSkill) : '확인하기';
      return { tone: 'attn', text: '내 차례 · ' + verb };
    }
    if (s.status === 'ended') return { tone: '', text: '끝난 세션' };
    if (g === 'running') return { tone: '', text: (s.currentAction || (s.currentSkill ? skillLabel(s.currentSkill) : '작업 중')) + subagentSummary(s) };
    return { tone: '', text: '쉬는 중' };
  }
  /* 맨 위 띠: 내 차례(대기 중인 질문·승인, 답을 기다리는 세션)가 있을 때만 있다. */
  function renderAnn(d) {
    clear(annEl);
    if (d.todo.length) {
      var first = d.todo[0];
      annEl.appendChild(link(first.href, { class: 'ann', role: 'status' },
        h('span', { text: '내 차례 ' + d.todo.length + '건 — ' + first.sname + '에서 답이 필요해' })));
    }
    // 막지 않는 문제(하네스 새 판)는 홈을 그대로 열고 띠 한 줄로만 알린다. 내 차례 띠와 같이 있으면 둘 다 보인다.
    if (startData && startData.newVersion) {
      annEl.appendChild(link('/settings', { class: 'ann note', role: 'status' },
        h('span', { text: '하네스 새 판 ' + startData.newVersion + '이 있어 — 터미널에서 /harness:update 를 해 줘' })));
    }
  }

  /* ---------- 첫 화면 · 자동 점검 (시안 01) ----------
     첫 실행(이 PC 에서 시작하기를 아직 안 눌렀다: 서버가 상태 폴더에 표시를 둔다)이거나 막는 문제(GitHub 연결 등)가 있으면 01 화면을 띄운다.
     막지 않는 문제(옛 판)는 띠만. 점검은 서버가 백그라운드로 하고, 첫 실행이 아니면 홈을 막지 않는다. */
  var startData = null, introForce = false, introSkip = false, startPolls = 0, startTimer = null;
  function introWanted() { return !!startData && !introSkip && (introForce || startData.firstRun || startData.blocking); }
  function loadStart(refresh) {
    return api('GET', '/api/start-checks' + (refresh ? '?refresh=1' : '')).then(function (d) {
      startData = d && typeof d === 'object' ? d : null;
      clearTimeout(startTimer);
      if (startData && startData.loading && startPolls++ < 40) startTimer = setTimeout(function () { loadStart(false); }, 1500);
      if (renderedOnce) applyStart();
    }, function () { /* 점검을 못 읽으면 홈을 막지 않는다(검사 불능) */ });
  }
  var renderedOnce = false;
  function applyStart() {
    var on = !!(appEl && appEl.getAttribute('data-intro') === '1');
    if (on && introPage === 'project') return;  // 02 에서 고르는 중이면 점검 결과가 와도 다시 그리지 않는다(고른 것이 사라진다)
    if (on || introWanted()) renderRoute(); else renderAnn(sideData());
  }
  // 폴더 카드 칩: 준비됨(세션이 있으면 수) / 준비 필요 / 읽는 중 / 확인 못 함. 읽지 못한 것을 준비됨이나 준비 필요로 뭉개지 않는다.
  function readyChip(f) {
    if (f.ready === 'yes') return { cls: 'ok', text: typeof f.sessions === 'number' && f.sessions > 0 ? '준비됨 · 세션 ' + f.sessions : '준비됨' };
    if (f.ready === 'no') return { cls: 'warn', text: '준비 필요' };
    if (f.checking) return { cls: '', text: '확인하는 중' };
    return { cls: 'unk', text: '확인 못 함' };
  }
  var introPage = 'welcome', firstPickFolder = null;  // 첫 화면 두 쪽(01 환영 → 02 프로젝트 고르기) · 02 에서 준비 안 된 폴더를 골랐을 때 새 작업 화면이 03 을 띄울 폴더

  /* 시안 G-02 프로젝트 고르기. 카드는 고름 표시만 하고, [이 프로젝트로] 가 서버에 마지막 폴더로 기억시키고 첫 실행 표시를 남긴다.
     준비 안 됨이고 안내를 아직 안 봤으면 03(새 작업 화면의 프로젝트 준비), 아니면 홈(04). */
  function projectPickView() {
    var wrap = h('div', { class: 'intro' }), recent = null, sel = '', custom = '', msg = '', busy = false, browseBusy = false, customBusy = false, tries = 0, timer = null;
    var typing = false;  // OS 선택 창을 못 열었을 때만 경로 입력칸을 보인다
    function nameOf(p) { return baseName(p) || p; }
    // 시안처럼 긴 경로는 앞(드라이브·첫 칸) … 끝 두 칸으로 줄여 한 줄로. 전체 경로는 카드 title.
    function shortPath(p) {
      var sep = p.indexOf('\\') >= 0 ? '\\' : '/', parts = p.split(/[\\/]+/);
      if (parts.length <= 4) return p;
      return parts.slice(0, 2).join(sep) + sep + '…' + sep + parts.slice(-2).join(sep);
    }
    function parse(d) { return listOf(d, 'folders').map(function (f) { return typeof f === 'string' ? { path: f } : f; }).filter(function (f) { return f && f.path; }); }
    function load() {
      clearTimeout(timer);
      api('GET', '/api/folders/recent').then(function (d) {
        var next = parse(d), keep = (recent || []).filter(function (f) { return f.extra && !next.some(function (n) { return n.path === f.path; }); });
        recent = keep.concat(next);
        if (wrap.isConnected) draw();
        if (tries++ < 6 && next.some(function (f) { return f.checking; })) timer = setTimeout(load, 1500);
      }, function () { recent = recent || []; if (wrap.isConnected) draw(); });
    }
    function choose(p) {  // 직접 고른 폴더는 최근 목록에 없을 수 있어 맨 위에 더한다
      msg = ''; sel = p;
      if (!(recent || []).some(function (f) { return f.path === p; })) recent = [{ path: p, extra: true }].concat(recent || []);
      draw(); tries = 0; load();
    }
    function validated(p) {
      return api('POST', '/api/folders/validate', { path: p }).then(function (v) {
        if (v && (v.ok === true || v.valid === true)) choose(v.path || v.realpath || p);
        else msg = (v && (v.error || v.reason || v.message)) || '이 폴더를 사용할 수 없습니다.';
      });
    }
    function browse() {
      if (browseBusy) return;
      browseBusy = true; msg = ''; draw();
      api('POST', '/api/folders/pick', { path: sel || '' }).then(function (d) {
        if (d && d.cancelled) return null;
        var p = d && d.path;
        if (!p) { msg = '고른 폴더를 받지 못했습니다. 경로를 직접 적어 주세요.'; typing = true; return null; }
        return validated(p);
      }).then(null, function (e) { msg = e.message; typing = true; }).then(function () { browseBusy = false; if (wrap.isConnected) draw(); });
    }
    function typed() {
      var p = custom.trim(); if (!p || customBusy) return;
      customBusy = true; msg = ''; draw();
      validated(p).then(function () { custom = ''; }, function (e) { msg = e.message; }).then(function () { customBusy = false; if (wrap.isConnected) draw(); });
    }
    function confirmPick() {
      if (!sel || busy) return;
      busy = true; msg = ''; draw();
      var f = (recent || []).filter(function (x) { return x.path === sel; })[0] || {};
      api('POST', '/api/folders/last', { path: sel }).then(function (d) {
        var p = (d && d.path) || sel;
        function leave(path) { if (path === location.pathname + location.search) renderRoute(); else go(path); }
        return api('POST', '/api/start-checks/seen', {}).then(function () { if (startData) startData.firstRun = false; }, function () { introSkip = true; /* 표시를 못 남겨도 홈으로 간다 */ }).then(function () {
          introForce = false; introPage = 'welcome';
          if (f.ready === 'yes') return leave('/');
          return api('GET', '/api/folders/intro' + qs({ path: p })).then(function (i) { return i && i.show === true; }, function () { return false; }).then(function (show) {
            if (show) { firstPickFolder = p; leave('/new'); } else leave('/');
          });
        });
      }, function (e) { busy = false; msg = '이 폴더를 기억하지 못했어: ' + e.message; draw(); });
    }
    function draw() {
      clear(wrap);
      var box = h('section', { class: 'light intro-box', 'data-pick': '1' },
        h('span', { class: 'eb', text: '1단계 · 프로젝트' }),
        h('h1', { text: '어느 고객사 프로젝트에서 일할까?' }),
        h('span', { class: 'lm', text: '최근에 쓴 폴더야. 처음이면 GitHub에서 받은 고객사 저장소 폴더를 골라.' }));
      (recent || []).forEach(function (f) {
        var nm = nameOf(f.path), c = readyChip(f);
        box.appendChild(h('button', { type: 'button', class: 'folder-opt proj', 'data-pick-folder': f.path, 'aria-pressed': String(f.path === sel), title: f.path, onClick: function () { sel = f.path; msg = ''; draw(); } },
          h('span', { class: 'pi', 'aria-hidden': 'true', text: nm.replace(/[^A-Za-z0-9가-힣]/g, '').slice(0, 2).toUpperCase() || '··' }),
          h('span', { class: 'pn' }, h('b', { text: nm }), h('small', { class: 'mono', text: shortPath(f.path) })),
          h('span', { class: ('chip2 ' + c.cls).trim(), 'data-ready': f.ready || 'unknown', text: c.text })));
      });
      box.appendChild(h('button', { type: 'button', class: 'folder-opt proj add', 'data-pick-browse': '1', disabled: browseBusy, onClick: browse },
        h('span', { class: 'pi', 'aria-hidden': 'true', text: '+' }), h('span', { class: 'pn' }, h('span', { text: browseBusy ? '창 여는 중' : '다른 폴더 찾아보기' }))));
      if (browseBusy) box.appendChild(h('p', { class: 'note-muted', role: 'status', text: '폴더 선택 창을 열었어. 창이 보이지 않으면 작업 표시줄을 확인해 줘.' }));
      // 시안 G-02 엔 경로 입력칸이 없다(폴더는 "다른 폴더 찾아보기" 의 OS 선택 창으로 고른다). 선택 창을 못 열었을 때만 대신 입력칸을 보인다.
      if (typing) {
        box.appendChild(h('label', { for: 'pick-custom', class: 'field-label', text: '폴더 경로를 직접 적기' }));
        box.appendChild(h('div', { class: 'inline-row' },
          h('input', { id: 'pick-custom', class: 'input', value: custom, placeholder: '예: C:\\Work\\public-cloud', autocomplete: 'off', onInput: function (e) { custom = e.target.value; }, onKeydown: function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); typed(); } } }),
          h('button', { type: 'button', class: 'pill line sm', 'data-pick-use': '1', disabled: customBusy, text: customBusy ? '확인 중' : '사용', onClick: typed })));
      }
      box.appendChild(h('p', { class: 'note-attn', role: 'alert', text: msg, hidden: !msg }));
      box.appendChild(h('div', { class: 'acts end' },
        h('button', { type: 'button', class: 'pill line', 'data-pick-back': '1', text: '뒤로', onClick: function () { clearTimeout(timer); introPage = 'welcome'; renderRoute(); } }),
        h('button', { type: 'button', class: 'pill dark', 'data-pick-ok': '1', disabled: !sel || busy, text: busy ? '기억하는 중' : '이 프로젝트로', onClick: confirmPick })));
      wrap.appendChild(box);
    }
    draw(); load();
    return wrap;
  }
  function introView() {
    var d = startData, blocking = d.blocking, names = { github: 'GitHub 연결', version: '하네스 판', claude: 'Claude Code 로그인' };
    if (introPage === 'project' && !blocking) return projectPickView();
    var rows = (d.checks && d.checks.length ? d.checks : ['github', 'version', 'claude'].map(function (id) { return { id: id, name: names[id], state: 'wait', detail: '확인하는 중이야' }; }));
    var CL = { ok: 'ok', fail: 'fail', old: 'wait', unknown: 'unk', wait: 'wait' };
    function done() { introPage = 'project'; renderRoute(); }
    var list = h('div', { class: 'checks' }, rows.map(function (c) {
      var kids = [h('i', { class: 'mk', 'aria-hidden': 'true' }), h('span', { class: 'cn', text: c.name }), h('span', { class: 'ct mono', text: c.detail || '' })];
      if (c.fix && (c.state === 'fail' || c.state === 'old')) kids.push(h('span', { class: 'fix', text: c.fix }));
      return h('div', { class: 'crow ' + CL[c.state], 'data-check': c.id }, kids);
    }));
    var steps = [['1', '프로젝트 고르기', '고객사 폴더 하나'], ['2', '할 일 말하기', '"요구사항 써 줘"처럼'], ['3', 'AI 질문에 답하기', '버튼으로 고르면 돼']];
    var acts = blocking
      ? [h('button', { type: 'button', class: 'pill line', text: '그냥 열기', onClick: function () { introSkip = true; renderRoute(); } }),
         h('button', { type: 'button', class: 'pill dark', disabled: !!d.loading, text: d.loading ? '점검하는 중이야' : '다시 점검', onClick: function () { startPolls = 0; loadStart(true); } })]
      : [h('button', { type: 'button', class: 'pill dark', 'data-intro-start': '1', text: '시작하기', onClick: done })];
    return h('div', { class: 'intro' }, h('section', { class: 'light intro-box' },
      h('span', { class: 'eb', text: blocking ? '점검 결과' : (d.firstRun ? '처음 열었어' : '처음 화면') }),
      h('h1', { text: blocking ? '먼저 고칠 게 있어' : 'Blueward Harness에 온 걸 환영해' }),
      h('span', { class: 'lm', text: blocking ? '아래 ✕ 줄을 고친 다음 "다시 점검"을 눌러 줘. 급하면 그냥 열어도 되지만, GitHub 일은 안 될 수 있어.'
        : 'AI와 함께 고객사 문서(SRS·Spec·매뉴얼·CTS·Role)를 만들고 개발하는 곳이야. 시작 전에 필요한 것을 자동으로 확인했어.' }),
      list,
      h('span', { class: 'eb', text: '이렇게 써' }),
      h('div', { class: 'num3' }, steps.map(function (s) {
        return h('div', { class: 'n3' }, h('span', { class: 'eb', text: s[0] }), h('b', { text: s[1] }), h('span', { class: 'lm sm', text: s[2] }));
      })),
      h('div', { class: 'acts end' }, acts)));
  }
  /* 헤더 오른쪽 프로젝트 이름: 지금 화면이 다루는 폴더만 보인다. 새 작업은 고른 작업 폴더, 세션·질문·승인은 그 세션.
     그 밖의 화면은 열린 세션들의 프로젝트가 하나뿐일 때만 보이고, 여럿이면 어느 것인지 알 수 없어 비워 둔다(예전에는 가장 위 세션 것을 보여 줘서 틀렸다). */
  function folderLabel(p) {
    var segs = String(p || '').replace(/[\\/]+$/, '').split(/[\\/]+/).filter(Boolean);
    return segs.slice(-2).join('/');
  }
  function projectName(s) { return baseName(s.repo) || folderLabel(s.cwd); }
  function projectOf() {
    if (route.name === 'new') return draft.cwd ? folderLabel(draft.cwd) : '';
    var s = null;
    if (route.name === 'session') s = sessions.get(route.id);
    else if (route.name === 'request') { var r = requests.get(route.id); s = r && sessions.get(r.sessionId || r.session_id); }
    if (s) return projectName(s);
    var names = {};
    sortedSessions().filter(function (x) { return x.status !== 'ended'; }).forEach(function (x) { var n = projectName(x); if (n) names[n] = 1; });
    var all = Object.keys(names);
    return all.length === 1 ? all[0] : '';
  }
  /* 새 작업으로 가는 길. 세션·질문 화면에서 누르면 그 세션의 폴더를 기본값으로 쓰도록 출처 세션을 넘긴다(/new?from=세션id). */  function newHref() {
    var sid = null;
    if (route.name === 'session') sid = route.id;
    else if (route.name === 'request') { var r = requests.get(route.id); sid = r && (r.sessionId || r.session_id); }
    return sid ? '/new?from=' + encodeURIComponent(sid) : '/new';
  }

  /* 상단 헤더. 내 일 = 처음 화면, 작업 = 가장 위 세션(내 차례가 먼저), 산출물 = /docs, 새 작업 = /new. */
  function renderHead(cur) {
    clear(headEl);
    var rows = sortedSessions(), work = rows[0] ? '/s/' + encodeURIComponent(rows[0].id) : null;
    var inWork = route.name === 'session' || route.name === 'request';
    var nav = h('nav', { class: 'topnav', 'aria-label': '메뉴' });
    nav.appendChild(link('/', { text: '내 일', 'aria-current': route.name === 'home' ? 'page' : null }));
    if (work) nav.appendChild(link(work, { text: '작업', 'aria-current': inWork ? 'page' : null }));
    nav.appendChild(link('/docs', { text: '산출물', 'aria-current': route.name === 'docs' ? 'page' : null }));
    nav.appendChild(link(newHref(), { text: '새 작업', 'aria-current': route.name === 'new' ? 'page' : null }));
    headEl.appendChild(link('/', { class: 'brand', 'aria-label': 'Blueward Harness' }, h('img', { class: 'brand-logo', src: '/static/logo-sauce.png', alt: 'Blueward' })));
    headEl.appendChild(nav);
    headEl.appendChild(h('span', { class: 'sp' }));
    var proj = projectOf();
    if (proj) headEl.appendChild(h('span', { class: 'eb proj', title: '프로젝트', text: proj }));
    headEl.appendChild(link('/settings', { class: 'pill ghost', 'aria-current': cur === '/settings' ? 'page' : null, text: '설정' }));  // 시안 헤더: 아이콘 없는 글자 단추(.bs)
  }
  // 접기·펼치기 단추 하나: 접힌 칸과 펼친 칸 모두 목록 맨 위, 같은 자리·같은 크기. 화살표 방향만 반대다(SVG).
  function foldBtn(collapsed) {
    return h('button', { type: 'button', class: 'fold-btn', 'aria-label': collapsed ? '목록 펼치기' : '목록 접기', title: (collapsed ? '목록 펼치기' : '목록 접기') + ' ( [ )',
      'aria-expanded': String(!collapsed), 'aria-keyshortcuts': '[', onClick: function () { setCollapsed(!collapsed); } }, icon(collapsed ? 'chev' : 'back', 16));
  }
  // 세션 기억 링(#648): % 를 알면 채워진 링(80% 초과 노랑, 90% 이상 빨강), 토큰 수만 알면 점선 링에 만 단위, 모르면 "?".
  function memRing(s) {
    var m = window.BHLogic.memoryOf(s);
    if (m.kind === 'pct') return h('span', { class: 'ring pct' + (m.level ? ' ' + m.level : ''), style: '--p:' + m.pct, title: '기억 ' + m.pct + '% · ' + m.title }, h('b', { text: m.pct + '%' }));
    if (m.kind === 'tokens') return h('span', { class: 'ring unk', title: m.title }, h('b', { text: m.tokens >= 10000 ? Math.round(m.tokens / 10000) + '만' : '<1만' }));
    return h('span', { class: 'ring unk', title: m.title }, h('b', { text: '?' }));
  }
  function renderSide() {
    if (!sideEl) return;
    var d = sideData(), col = isCollapsed(), cur = location.pathname;
    appEl.dataset.collapsed = col ? 'true' : 'false';
    renderAnn(d); renderHead(cur);
    clear(sideEl);
    if (col) { sideEl.appendChild(renderRail(d, cur)); return; }

    var rows = sortedSessions(), L = window.BHLogic;
    var nav = h('nav', { class: 'nav', 'aria-label': '세션 목록' });
    nav.appendChild(h('div', { class: 'sh' }, h('span', { class: 'eb', text: '세션 ' + rows.length }), h('span', { class: 'eb', text: '단계 · 기억' }), foldBtn(false)));
    var list = h('div', { class: 'nav-list' });
    if (!rows.length && loadedOnce) list.appendChild(h('p', { class: 's-empty', text: '아직 세션이 없어. 새 작업을 시작하면 여기에 생겨.' }));
    rows.forEach(function (s) {
      var st = sideStatus(s), p = firstPending(s);
      var onThis = cur === '/s/' + encodeURIComponent(s.id) || (p && cur === '/r/' + encodeURIComponent(p.rid));
      var steps = s.flowId && L ? L.barSteps(s) : [];
      var bar = null;
      if (steps.length) {
        var now = steps.filter(function (x) { return x.state === 'now'; })[0];
        bar = h('span', { class: 'bar', role: 'img', 'aria-label': '진행 순서 ' + steps.length + '단계' + (now ? ', 지금 ' + now.name : '') },
          steps.map(function (x) { return h('i', { class: x.state === 'now' ? 'n' : x.state === 'done' || x.state === 'skipped' ? 'd' : '', title: x.name + ' · ' + x.label }); }));
      }
      list.appendChild(link('/s/' + encodeURIComponent(s.id), { class: 'srow' + (s.status === 'ended' ? ' ended' : ''), 'aria-current': onThis ? 'page' : null },
        memRing(s),
        h('span', { class: 'sinfo' },
          h('span', { class: 'n', text: sessionTitle(s) }),
          bar,
          h('small', { class: st.tone === 'attn' ? 'w' : '', title: st.text, text: st.text }))));
    });
    nav.appendChild(list);
    var foot = h('div', { class: 'nav-foot' });
    foot.appendChild(link(newHref(), { class: 'snew', text: '+ 새 세션' }));
    nav.appendChild(foot);
    sideEl.appendChild(nav);
  }
  function renderRail(d, cur) {
    var n = d.todo.length, rows = sortedSessions();
    return h('nav', { class: 'rail', 'aria-label': '세션 목록 (접힘)' },
      foldBtn(true),
      link(d.todo.length ? d.todo[0].href : '/', { class: 'rail-count' + (n ? ' has' : ''), 'aria-label': '내가 할 일 ' + n + '건', title: '내가 할 일 ' + n + '건' },
        h('span', { class: 'n', text: String(n) }), h('span', { class: 'l', text: '내가 할 일' })),
      rows.map(function (s) {
        var st = sideStatus(s), p = firstPending(s), name = sessionTitle(s);
        var onThis = cur === '/s/' + encodeURIComponent(s.id) || (p && cur === '/r/' + encodeURIComponent(p.rid));
        return link('/s/' + encodeURIComponent(s.id), { class: 'rail-ring' + (st.tone === 'attn' ? ' turn' : '') + (s.status === 'ended' ? ' ended' : ''), 'aria-label': name + ' · ' + st.text, title: name + ' · ' + st.text, 'aria-current': onThis ? 'page' : null },
          h('span', { class: 'ring unk' }, h('b', { text: '?' })));
      }),
      h('span', { class: 'rail-sp' }),
      link(newHref(), { class: 'rail-add', 'aria-label': '새 세션', title: '새 세션' }, icon('plus', 14)));
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== '[' || e.isComposing || e.keyCode === 229 || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target, tag = t && t.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
    e.preventDefault();
    setCollapsed(!isCollapsed());
  });

  /* ---------- 공통 조각 ---------- */
  function topline(left) {
    return h('div', { class: 'topline' }, left ? h('span', { class: 'wrap-any', text: left }) : null);
  }
  function backToSession(sid, label) {
    return sid ? link('/s/' + encodeURIComponent(sid), { class: 'linkbtn', text: label || '세션으로 돌아가기' }) : link('/', { class: 'linkbtn', text: '처음 화면으로' });
  }
  function missingView(root) {
    root.appendChild(stateBox('warn', '이 주소의 화면이 없습니다', '주소를 다시 확인하거나 처음 화면으로 이동하세요.', link('/', { class: 'btn', text: '처음 화면으로' })));
  }

  /* ---------- 홈과 갈래 화면 조각(flow-ui.js) ---------- */
  var ui = window.BHFlowUI.create({
    h: h, clear: clear, api: api, qs: qs, listOf: listOf, icon: icon, link: link, go: go, sessions: sessions, requests: requests,
    baseName: baseName, fmtSize: fmtSize, clock: clock, safeHttp: safeHttp, mergeSession: mergeSession, refreshSession: refreshSession,
    kindOf: kindOf, skillLabel: skillLabel, requestTitle: requestTitle, topline: topline,
    startNew: function (text) { if (text && text.trim()) draft.text = text.trim(); go('/new'); }, stateBox: stateBox, loadingBox: loadingBox,
    loaded: function () { return loadedOnce; }, conn: function () { return conn.state; }
  });
  /* 판이 바뀐 뒤 처음 여는 홈에 "이번에 바뀐 것" 카드 하나(#647). 서버가 지난번 본 판과 비교해 줄 것만 주고, [알겠어]로 본 판을 남긴다.
     첫 실행 화면이 뜨는 동안에는 부르지도 않는다(boot). 카드를 못 읽으면 홈은 그대로다. */
  var whatsNew = null, whatsSlot = null, whatsMore = false, whatsNote = '', whatsStarted = false;
  function loadWhatsNew() {
    if (whatsStarted) return; whatsStarted = true;
    api('GET', '/api/whats-new').then(function (d) {
      whatsNew = d && d.items && d.items.length ? d : null;
      if (whatsSlot) drawWhatsNew();  // 홈을 떠나면 destroy 가 whatsSlot 을 비운다
    }, function () { /* 못 읽으면 카드를 안 띄운다 */ });
  }
  function drawWhatsNew() {
    var slot = whatsSlot; if (!slot) return;
    clear(slot);
    if (!whatsNew || introWanted()) return;
    var items = whatsNew.items, shown = items, total = 0, cut = items.length;
    items.forEach(function (it, i) { total += it.lines.length; if (total > 8 && cut === items.length && i > 0) cut = i; });
    if (!whatsMore && cut < items.length) shown = items.slice(0, cut);
    var body = h('div', { class: 'wn-list' }, shown.map(function (it) {
      return h('div', { class: 'wn-ver', 'data-wn-ver': it.version },
        h('span', { class: 'wn-v mono', text: it.version }),
        h('ul', null, it.lines.map(function (t) { return h('li', { text: t }); })));
    }));
    var acts = [h('button', { type: 'button', class: 'pill dark', 'data-wn-ok': '1', text: '알겠어', onClick: function () {
      api('POST', '/api/whats-new/seen', {}).then(function () { whatsNew = null; whatsNote = ''; drawWhatsNew(); },
        function (e) { whatsNote = '본 판을 남기지 못했어 · ' + (e && e.message || ''); drawWhatsNew(); });
    } })];
    if (!whatsMore && cut < items.length) acts.unshift(h('button', { type: 'button', class: 'pill ghost', 'data-wn-more': '1', text: '더 보기', onClick: function () { whatsMore = true; drawWhatsNew(); } }));
    slot.appendChild(h('section', { class: 'wn', 'data-whats-new': '1' },
      h('span', { class: 'eb accent', text: '이번에 바뀐 것' }),
      h('h2', { text: '하네스가 새 판(' + whatsNew.current + ')으로 바뀌었어 · 이번에 바뀐 것' }),
      body,
      whatsNote ? h('p', { class: 'wn-note', text: whatsNote }) : null,
      h('div', { class: 'wn-acts' }, acts)));
  }
  function homeView(root) {
    whatsSlot = h('div', { class: 'wn-slot' });
    var rest = h('div');
    root.appendChild(whatsSlot); root.appendChild(rest);
    drawWhatsNew();
    var v = ui.homeView(rest);
    if (v && v.destroy) { var d0 = v.destroy; v.destroy = function () { whatsSlot = null; d0(); }; }
    else v = Object.assign({}, v, { destroy: function () { whatsSlot = null; } });
    return v;
  }
  function docsView(root) { return ui.docsPage(root); }

  /* ---------- 세션 (/s/:id) ---------- */
  function sessionView(root) {
    var id = route.id, detail = null, errored = null, fetching = false, timer = null;
    var memDismissed = {}, regions = {}, parts = {}, syncLegend = function () {}, followVal = '', followNote = '', reportOpen = false, logAll = false, built = false, interruptAsk = false, permBusy = false, permNote = '', sent = [];
    var chatAll = false, chatOpen = {}, chatKey = null;  // 앞 대화를 펼쳤는지 · 긴 AI 말을 펼친 것(시각별) · 마지막으로 그린 대화 모양(새 항목 감지)

    function cur() { return sessions.get(id) || {}; }
    function fetchDetail() {
      if (fetching) return; fetching = true;
      api('GET', '/api/sessions/' + encodeURIComponent(id)).then(function (d) {
        d = d && d.session ? d.session : d;
        detail = d; errored = null; mergeSession(Object.assign({}, d, { id: id })); scheduleSide(); draw();
      }, function (e) { errored = e; draw(); }).then(function () { fetching = false; });
    }
    function refetchSoon() { clearTimeout(timer); timer = setTimeout(fetchDetail, 250); }

    function draw() {
      var s = cur();
      if (!built) {
        if (errored && errored.status === 404) { clear(root); root.appendChild(stateBox('warn', '세션을 찾을 수 없습니다', '이미 끝났거나 목록에서 지워진 세션입니다.', link('/', { class: 'btn', text: '처음 화면으로' }))); return; }
        if (errored && !s.id) { clear(root); root.appendChild(stateBox('warn', '세션을 불러오지 못했습니다', errored.message, h('button', { type: 'button', class: 'btn', text: '다시 시도', onClick: function () { errored = null; fetchDetail(); } }))); return; }
        if (!s.id) { clear(root); root.appendChild(loadingBox('세션을 불러오는 중입니다.')); return; }
        build();
      }
      paint(s);
    }

    /* 위에서부터: 제목 블록 · 순서 알약 · 숫자 띠 · 알림 · 새 세션 점검 · (대화 판 + 만든 산출물) · 도구 줄 · 폴더 알림 · 서브에이전트 · 권한 · 파일 · 기록 · 기술 정보 */
    function build() {
      built = true; clear(root);
      var page = h('div', { class: 'page sess' });
      function region(k, parent) { regions[k] = h('div', { 'data-r': k }); (parent || page).appendChild(regions[k]); return regions[k]; }
      region('memtop');  // 시안 G-18: 기억 배너는 제목 위 맨 꼭대기
      // 시안 G-09·12: 제목 블록(눈썹·제목·상태 줄·순서 알약) 오른쪽에 층 그림. 순서(갈래)가 있을 때만 그림이 보인다.
      var titleCol = h('div', { class: 'titlecol' });
      regions.head = h('div', { 'data-r': 'head' }); regions.stages = h('div', { 'data-r': 'stages' });
      titleCol.appendChild(regions.head); titleCol.appendChild(regions.stages);
      regions.iso = h('div', { class: 'iso', 'aria-hidden': 'true', hidden: true }, ['l1', 'l2', 'l3', 'l4'].map(function (c) { return h('i', { class: 'ly ' + c }); }));
      page.appendChild(h('div', { class: 'titlerow' }, titleCol, regions.iso));
      ['strip', 'notices'].forEach(function (k) { region(k); });
      // 갈래·도구·점검·문서 칸은 한 번 만들어 두고 세션이 바뀔 때 update 만 부른다. 새 세션 점검은 대화 판 맨 위 카드다(시안 13).
      parts.checks = ui.startChecksPanel();
      parts.flow = ui.flowPanel({ compact: true });
      parts.docs = ui.docsPanel();
      // 이어서 요청 입력칸은 다시 그리지 않는다.
      var followAssist = null;
      var input = h('input', { id: 'follow', class: 'comp-in', placeholder: '예: 표의 항목 순서를 바꿔 줘  (/ 로 스킬, @ 로 파일)', autocomplete: 'off',
        onInput: function (e) { followVal = e.target.value; followNote = ''; paintFollowNote(); },
        onKeydown: function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229 && !(followAssist && followAssist.isOpen())) { e.preventDefault(); sendFollow(); } } });
      followAssist = withAssist(input, function () { return cur().cwd; });
      var btn = h('button', { type: 'button', class: 'pill dark', text: '보내기', onClick: sendFollow });
      regions.msgs = h('div', { class: 'msgs', 'data-r': 'msgs' });
      regions.follow = h('div', { class: 'followbox', 'data-r': 'follow' },
        h('label', { for: 'follow', class: 'sr-only', text: '이 작업에 이어서 요청' }),
        h('div', { class: 'comp' }, followAssist.wrap, btn),
        h('p', { class: 'note-accent', 'data-note': '1', role: 'status' }),
        h('p', { class: 'note-muted', 'data-why': '1' }));
      regions.followInput = input; regions.followBtn = btn;
      var talk = h('section', { class: 'light talk', 'aria-label': 'AI와 대화' }, parts.checks.el, regions.msgs, parts.flow.el, regions.follow);
      var side = h('aside', { class: 'sess-side', 'aria-label': '만든 산출물' }, parts.docs.el);
      page.appendChild(h('div', { class: 'sess-grid' }, talk, side));
      // 시안 G-16: 대화 판에 막힘(✕)·확인 못 함(?) 카드가 있으면 그 아래 전체 폭으로 "표시 약속" 칸. PR 카드는 따로 늦게 그려지기도 해서 바뀔 때마다 본다.
      regions.legend = h('div', { 'data-r': 'legend' }); page.appendChild(regions.legend);
      syncLegend = function () {
        var has = !!talk.querySelector('.q.blocked, .q.unsure');
        if (has !== !!regions.legend.firstChild) regions.legend.replaceChildren.apply(regions.legend, has ? [ui.legend()] : []);
      };
      if (typeof window.MutationObserver === 'function') new window.MutationObserver(function () { syncLegend(); }).observe(talk, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
      region('folder'); region('subs');
      // 시안에 없는 옛 칸(도구 버튼 줄 · 권한 모드 · 검토 요청 주소와 바뀐 파일 · 일어난 일 기록 · 기술 정보)은 "자세히" 로 접는다. 기능은 그대로다.
      var fold = h('details', { class: 'more fold', 'data-fold': '1' }, h('summary', { text: '자세히 (도구 · 권한 · 검토 요청 주소 · 기록 · 기술 정보)' }));
      page.appendChild(fold);
      ['tools', 'perm', 'files', 'log', 'tech'].forEach(function (k) { region(k, fold); });
      parts.tools = ui.toolsRow(function () { var s = cur(); return { session: s.id ? s : null, cwd: s.cwd }; }); regions.tools.appendChild(parts.tools.el);
      parts.folder = ui.folderNotice(); regions.folder.appendChild(parts.folder.el);
      root.appendChild(page);
      // 권한 모드 고르개도 다시 그리지 않는다(열린 목록이 닫히지 않게).
      var sel = h('select', { id: 'perm-mode', class: 'input', 'aria-describedby': 'perm-note', onChange: changePermission },
        permissionOptions().map(function (o) { return h('option', { value: o.value, text: o.label }); }));
      regions.permSelect = sel;
      regions.perm.appendChild(h('section', { class: 'mt-32', 'data-perm': '1' },
        h('label', { for: 'perm-mode', class: 'label', text: '권한 모드' }), sel,
        h('p', { class: 'note-muted', id: 'perm-note', role: 'status', 'data-perm-note': '1' })));
    }

    function paintPerm(s) {
      var box = regions.perm.querySelector('[data-perm]');
      if (!box) return;
      box.hidden = !s.managed;
      if (!s.managed) return;
      if (!permBusy) regions.permSelect.value = s.permissionChoice || '';
      regions.permSelect.disabled = permBusy;
      var live = s.permissionMode ? '지금 적용된 모드: ' + permissionLabel(s.permissionMode === 'default' ? '' : s.permissionMode) : '';
      var note = regions.perm.querySelector('[data-perm-note]');
      note.textContent = [permNote, live, s.permissionNote].filter(Boolean).join(' · ');  // permissionNote: auto 를 못 쓴 사정(서버가 쉬운 말과 원문으로 준다)
    }

    function changePermission(e) {
      var mode = e.target.value;
      permBusy = true; permNote = '권한 모드를 바꾸는 중입니다.'; paintPerm(cur());
      api('PUT', '/api/sessions/' + encodeURIComponent(id) + '/permission', { mode: mode }).then(function (d) {
        permNote = d && d.live === false ? '다음에 이어서 띄울 때 적용됩니다.' : '권한 모드를 바꿨습니다.';
      }, function (err) { permNote = '바꾸지 못했습니다: ' + err.message; }).then(function () {
        permBusy = false; paintPerm(cur()); refetchSoon();
      });
    }

    function elapsedText(sec) {
      if (typeof sec !== 'number' || sec < 0) return '';
      if (sec < 60) return Math.floor(sec) + '초';
      var m = Math.floor(sec / 60);
      return m < 60 ? m + '분 ' + Math.floor(sec % 60) + '초' : Math.floor(m / 60) + '시간 ' + (m % 60) + '분';
    }

    function subRow(a, running) {
      var span = running ? (Date.now() / 1000 - a.startedAt) : a.durationSec;
      var meta = [a.state === 'done' ? '끝남' : '실행 중', elapsedText(span), a.background ? '백그라운드' : '', a.tools ? '도구 ' + a.tools + '회' : ''].filter(Boolean).join(' · ');
      return h('li', { class: running ? 'sub-run' : 'sub-done', 'data-sub': a.id },
        h('div', { class: 'sub-top' }, h('b', { text: a.type || '서브에이전트' }), h('span', { class: 'd', text: meta, 'data-sub-meta': running ? '1' : null })),
        a.description ? h('div', { class: 'sub-desc', text: a.description }) : null,
        running && a.currentAction ? h('div', { class: 'sub-act mono wrap-any', text: a.currentAction }) : null);
    }

    function paintSubs(s) {
      var all = (s.subagents || []).filter(function (a) { return a && typeof a === 'object'; });
      var runningList = all.filter(function (a) { return a.state === 'running'; });
      var doneList = all.filter(function (a) { return a.state === 'done'; }).reverse();
      var open = regions.subs.querySelector('details') ? regions.subs.querySelector('details').open : false;
      var out = [];
      if (runningList.length) out.push(h('section', { class: 'mt-32 subs-run' }, h('h2', { class: 'label', text: '서브에이전트 ' + runningList.length + '개 실행 중' }),
        h('ul', { class: 'plain-list sub-list' }, runningList.map(function (a) { return subRow(a, true); }))));
      if (doneList.length) out.push(h('details', { class: 'tech mt-16', open: open }, h('summary', { text: '끝난 서브에이전트 ' + doneList.length + '개' }),
        h('ul', { class: 'plain-list sub-list' }, doneList.map(function (a) { return subRow(a, false); }))));
      regions.subs.replaceChildren.apply(regions.subs, out);
    }

    function paintFollowNote() {
      var n = regions.follow && regions.follow.querySelector('[data-note]');
      if (n) { n.textContent = followNote; n.hidden = !followNote; }
    }

    // over 가 글이면 입력칸 대신 그 글을 보낸다(막힘 카드의 "그렇게 고쳐 줘" 버튼)
    function sendFollow(over) {
      var s = cur(), typed = typeof over !== 'string', text = (typed ? followVal : over).trim();
      if (!text || s.canSend === false) return;
      regions.followBtn.disabled = true;
      api('POST', '/api/sessions/' + encodeURIComponent(id) + '/messages', { text: text }).then(function () {
        if (typed) { followVal = ''; regions.followInput.value = ''; }
        sent.push({ text: text, at: Date.now() / 1000 });
        followNote = (s.status === 'running') ? '지금 단계가 끝나면 이어서 처리합니다.' : '이 작업에 전달했습니다.';
      }, function (e) { followNote = '보내지 못했습니다: ' + e.message; }).then(function () {
        regions.followBtn.disabled = cur().canSend === false; paintFollowNote(); paintMsgs(cur());
      });
    }

    function interrupt() {
      interruptAsk = false;
      api('POST', '/api/sessions/' + encodeURIComponent(id) + '/interrupt', {}).then(function () { followNote = '중단을 요청했습니다.'; paintFollowNote(); refetchSoon(); },
        function (e) { followNote = '중단하지 못했습니다: ' + e.message; paintFollowNote(); });
      draw();
    }

    function eyebrowFor(s) {
      var pend = (s.pendingRequestIds || []).length;
      if (pend) return ['attn', '내 응답을 기다리는 중'];
      if (s.status === 'running') return ['accent', '지금 하는 일'];
      if (s.status === 'starting') return ['accent', '시작하는 중'];
      if (s.status === 'ended') return ['sec', '끝난 세션'];
      if (s.askedInText) return ['attn', '내 답을 기다리는 중(추정)'];
      if (s.turnSkill) return ['attn', '작업을 마치고 기다리는 중'];
      return ['sec', '쉬는 중'];
    }
    // 큰 제목에는 도구 이름 + 앞부분만, 전체는 아래 작은 한 줄(actionLine)에 둔다
    var HEADLINE_MAX = 40;
    function shortAction(a) {
      var t = String(a).replace(/\s+/g, ' ').trim();
      return t.length > HEADLINE_MAX ? t.slice(0, HEADLINE_MAX).replace(/\s+$/, '') + '…' : t;
    }
    function actionLine(s) {
      if (s.status !== 'running' || !s.currentAction || (s.pendingRequestIds || []).length) return null;
      var full = String(s.currentAction);
      if (shortAction(full) === full.trim()) return null;
      return h('p', { class: 'action-line mono', title: full, text: full.replace(/\s+/g, ' ') });
    }
    function headlineFor(s) {
      var pend = (s.pendingRequestIds || []).length;
      if (pend) return 'Claude Code가 내 확인을 기다리고 있어';
      if (s.status === 'running') return s.currentAction ? shortAction(s.currentAction) : (s.currentSkill ? skillLabel(s.currentSkill) + ' 진행 중' : '작업하는 중이야');
      if (s.status === 'starting') return '세션을 시작하고 있어';
      if (s.status === 'ended') return '세션이 끝났어';
      if (s.askedInText) return '내 답을 기다리는 듯해(추정).';
      if (s.turnSkill) return '이제 ' + skillLabel(s.turnSkill, flowItem(s, s.turnSkill)) + ' 차례야.';
      return '다음 요청을 기다리고 있어';
    }
    // 글로 물은 것으로 추정할 때, git 상태로 짐작한 차례는 제목에서 내려 참고 한 줄로만 보인다
    function askedNote(s) {
      if (!s.askedInText || (s.pendingRequestIds || []).length || s.status === 'running' || s.status === 'ended') return null;
      var tail = s.turnSkill ? ' 참고로 git 상태로는 ' + skillLabel(s.turnSkill, flowItem(s, s.turnSkill)) + ' 차례로 보여.' : '';
      return h('div', { class: 'ai', 'data-asked': '1' }, h('span', { class: 'eb', text: '참고' }), '마지막 보고가 물음표로 끝나서 질문으로 추정했어(틀릴 수 있어).' + tail);
    }
    function flowItem(s, skill) { return (s.flow || []).filter(function (f) { return f.skill === skill; })[0]; }

    function modelLine(s) {
      var m = '';
      if (s.model) m = '모델: ' + s.model;
      else if (s.managed) m = '모델: ' + (s.modelChoice ? s.modelChoice + '(고른 값)' : '기본값');
      if (!m) return '';
      // 에포트는 init 에 실제 값이 없어 고른 값만 보인다(콘솔이 띄운 세션에서만)
      return s.managed ? m + ' · 에포트: ' + (s.effortChoice ? s.effortChoice + '(고른 값)' : '기본값')
        + ' · 권한: ' + (s.permissionChoice ? permissionLabel(s.permissionChoice) + '(고른 값)' : '기본') : m;
    }
    function elapsedStr(v) {
      var p = elapsedParts(v);
      return p ? p.map(function (x) { return x[0] + x[1]; }).join(' ') : '';
    }

    function paintHead(s) {
      var tt = s.title || baseName(s.cwd) || '세션';
      var eb = eyebrowFor(s), el = elapsedStr(s.startedAt), pend = (s.pendingRequestIds || []).length;
      var live = s.status === 'running' && !pend, headline = headlineFor(s);
      regions.head.replaceChildren(h('div', { class: 'ptitle' },
        h('span', { class: 'eb ' + (eb[0] === 'attn' ? 'attn' : eb[0] === 'accent' ? 'accent' : ''), text: (s.flowName ? s.flowName + ' · ' : '') + eb[1] }),
        h('h1', { text: tt }),
        h('p', { class: 'line' }, live ? h('span', { class: 'live' }, h('i'), headline) : headline,
          el ? h('span', { class: 'elapsed', 'data-elapsed': '1', text: ' · 경과 ' + el }) : null),
        actionLine(s)));  // 모델·권한 줄은 시안에 없어 "자세히" 의 기술 정보(kv)에만 둔다
    }

    // 순서 알약: ✓ 끝난 단계 / 지금 단계 / 남은 단계. 끝났으면 다음 갈래 이름을 마지막 알약으로 보인다.
    // 시안: 순서 알약과 층 그림은 "올릴 차례"(G-09, turnSkill deliver)와 "갈래가 끝남"(G-12)에서만 보인다.
    // 질문(G-07)·일하는 중(G-08)·막힘(G-16)·확인(G-17)·기억(G-18) 화면에는 없다.
    function stagesShown(s) {
      if (s.flowFinished) return true;
      // G-09 는 AI 가 일을 끝내고(일하는 중 아님) 질문·확인 없이 "올릴 차례" 일 때
      return s.turnSkill === 'deliver' && s.status !== 'running' && !(s.pendingRequestIds || []).length;
    }
    function paintStages(s) {
      var bar = s.flowId && (s.flowSteps || []).length && stagesShown(s) ? ui.stepBar(s, true) : null;
      if (bar && s.flowFinished) {
        var nx = window.BHLogic.nextOptions(s).options.filter(function (o) { return !o.disabled; })[0];
        if (nx) bar.appendChild(h('li', { class: 'step next' }, h('span', { class: 'snm', text: '→ 다음: ' + nx.label })));
      }
      regions.stages.replaceChildren.apply(regions.stages, bar ? [bar] : []);
      regions.iso.hidden = !bar;
    }

    function paintStrip(s) {
      var cells = window.BHLogic.sessionStrip(s);
      regions.strip.replaceChildren(h('div', { class: 'strip', role: 'list', 'aria-label': '진행 숫자' }, cells.map(function (c) {
        return h('div', { role: 'listitem', 'data-cell': c.id, title: c.title || null }, h('span', { class: 'eb', text: c.label }), h('span', { class: 'x ' + (c.tone || ''), text: c.value }));
      })));
    }

    function paintNotices(s) {
      var notices = [], top = [];
      // 시안 G-18: 기억이 90% 이상 찼으면 제목 위 맨 꼭대기에 노란 배너, [새 세션으로 넘기기](진한) [계속하기](테두리).
      // [계속하기] 는 이 화면을 다시 열 때까지만 닫는다.
      var mem = window.BHLogic.memoryOf(s);
      if (mem.kind === 'pct' && mem.level === 'hot' && s.status !== 'ended' && !memDismissed[s.id]) {
        var canHand = s.managed && s.flowId && !s.handedOffTo;
        top.push(h('div', { class: 'banner mem', role: 'status', 'data-memory-banner': '1' },
          h('b', { class: 'mem-t', text: '이 세션 기억이 거의 찼어 (' + mem.pct + '%)' }),
          h('span', { class: 'mem-d', text: canHand ? '더 길어지면 앞 내용을 잊고 실수할 수 있어. 지금까지 한 일을 정리해서 새 세션으로 넘기길 권해.'
            : '더 길어지면 앞 내용을 잊고 실수할 수 있어. ' + (s.managed ? '정해진 갈래가 없어서 여기서는 넘길 수 없어. 새 작업으로 시작해 줘.' : '터미널 세션이라 여기서는 넘길 수 없어. 터미널에서 /harness:handoff 를 불러 줘.') }),
          h('span', { class: 'acts mem-acts' },
            canHand ? h('button', { type: 'button', class: 'pill dark sm mem-go', text: '새 세션으로 넘기기', onClick: function () { parts.flow.handoffSame(cur()); } }) : null,
            h('button', { type: 'button', class: 'pill line sm mem-stay', text: '계속하기', onClick: function () { memDismissed[s.id] = true; paintNotices(cur()); } }))));
      }
      if (s.bypassPermissions || /bypass/i.test(String(s.permissionMode || ''))) {
        notices.push(h('div', { class: 'banner info' }, h('span', { text: '권한 우회 모드로 실행 중인 세션이야. 이 세션은 승인 요청이 발생하지 않아 콘솔에 승인 화면이 뜨지 않아.' })));
      }
      if (s.permissionNote) {
        notices.push(h('div', { class: 'banner info', 'data-perm-warn': '1', role: 'status' }, h('span', { text: s.permissionNote })));
      }
      if (s.handedOffTo) {
        notices.push(h('div', { class: 'banner info' }, h('span', { text: '다음 세션으로 넘어감 → ' }),
          link('/s/' + encodeURIComponent(s.handedOffTo), { text: '새 세션 보기' })));
      }
      regions.notices.replaceChildren.apply(regions.notices, notices);
      regions.memtop.replaceChildren.apply(regions.memtop, top);
    }

    // 이 일의 순서를 체크리스트로(AI 가 따로 알려 주는 할 일 목록은 데이터에 없다)
    function todoCard(s) {
      var steps = window.BHLogic.barSteps(s);
      if (!s.flowId || !steps.length) return null;
      return h('div', { class: 'q' }, h('span', { class: 'eb', text: '이 일의 순서' }),
        h('div', { class: 'todolist' }, steps.map(function (st) {
          return h('span', { class: st.state === 'done' || st.state === 'skipped' ? 'd' : st.state === 'now' ? 'n' : 'w', title: st.reason || null },
            h('i', { class: 'dot', 'aria-hidden': 'true' }), st.name + (st.state === 'now' ? ' — 지금' : st.state === 'skipped' ? ' (건너뜀)' : ''));
        })));
    }

    function reportMsg(s) {
      var rep = s.report, text = rep && typeof rep === 'object' ? (rep.text || rep.markdown || rep.body || '') : (rep || '');
      var when = rep && typeof rep === 'object' ? (rep.updatedAt || rep.at || rep.time) : null;
      var box = h('div', { class: 'ai', 'data-r': 'report' }, h('span', { class: 'eb', text: 'AI' + (when ? ' · ' + clock(when) + ' 기준' : '') }));
      if (!String(text).trim()) {
        box.appendChild(h('span', { class: 'quiet', text: s.status === 'running' ? '이번 차례가 끝나면 Claude Code의 결과 보고가 여기에 나타나.' : '아직 결과 보고가 없어.' }));
        return box;
      }
      var long = String(text).split('\n').length > 28 || String(text).length > 2200;
      var body = h('div', { class: 'report-body' + (long && !reportOpen ? ' clip' : ''), tabindex: long ? '0' : null });
      body.appendChild(window.BHMarkdown.render(String(text)));
      box.appendChild(body);
      if (long) box.appendChild(h('button', { type: 'button', class: 'disclose', 'aria-expanded': String(reportOpen), onClick: function () { reportOpen = !reportOpen; paintMsgs(cur()); } }, icon('chev', 14), reportOpen ? '접기' : '전체 보기'));
      return box;
    }

    // 대화 한 칸: 내 말은 말풍선(줄바꿈 그대로), AI 말은 마크다운(긴 글은 접기)
    function chatMe(c) { return h('div', { class: 'me', 'data-chat': 'me', text: String(c.text || '') }); }
    function chatAi(c) {
      var text = String(c.text || ''), key = String(c.t), open = !!chatOpen[key];
      var long = text.split('\n').length > 28 || text.length > 2200;
      var box = h('div', { class: 'ai', 'data-chat': 'ai' }, h('span', { class: 'eb', text: 'AI' + (c.t ? ' · ' + clock(c.t) : '') }));
      var body = h('div', { class: 'report-body' + (long && !open ? ' clip' : ''), tabindex: long ? '0' : null });
      body.appendChild(window.BHMarkdown.render(text));
      box.appendChild(body);
      if (long) box.appendChild(h('button', { type: 'button', class: 'disclose', 'aria-expanded': String(open), onClick: function () { chatOpen[key] = !open; paintMsgs(cur()); } }, icon('chev', 14), open ? '접기' : '전체 보기'));
      return box;
    }
    function askCard(rid) {
      var r = requests.get(rid);
      if (r && r.status && r.status !== 'pending') return null;
      var q = r && kindOf(r) === 'question';
      return h('div', { class: 'ask', 'data-ask': rid },
        h('span', { class: 'eb', text: '네 차례' + waitedText(r && (r.createdAt || r.createdAtMs)) }),
        h('b', { text: r ? requestTitle(r) : '확인해야 할 요청이 있어' }),
        h('span', { class: 'sub', text: r ? (q ? 'AI가 물어본 게 있어. 답하면 이어서 일해.' : 'AI가 허락을 기다려. 확인하고 정해 줘.') : '요청 내용을 불러오는 중이거나 읽지 못했어.' }),
        h('div', { class: 'acts' }, link('/r/' + encodeURIComponent(rid), { class: 'pill acc', text: r ? (q ? '답하기' : '승인하기') : '열기' })));
    }
    // 질문·승인 요청: 기다리는 중이면 '네 차례' 카드(여기서 한 번만), 끝났으면 답을 한 줄로
    function chatReq(c, s, drawn) {
      var pend = (s.pendingRequestIds || []).indexOf(c.id) >= 0;
      if (pend && !c.answer) { drawn[c.id] = true; return askCard(c.id); }
      var label = c.kind === 'question' ? '질문' : '승인 요청';
      return h('div', { class: 'reqnote', 'data-chat': 'req', 'data-chat-req': c.id },
        label + ': ' + String(c.title || '') + ' → ' + (c.answer ? String(c.answer) : '처리 결과를 알 수 없어'));
    }
    // 하네스 훅이 막은 이유(#650): 막힘은 빨간 ✕ 카드, 검사를 못 해 멈춘 건 보라 점선 ? 카드
    var HOOK_NAMES = {
      'pre-bash-git-guard': 'git 명령 검사', 'stop-deliver': '마무리 확인', 'pre_write_guard': '파일 쓰기 검사',
      'agent_delegation_guard': '서브에이전트 호출 검사', 'mcp_source_guard': 'SAP 소스 쓰기 검사'
    };
    function chatBlock(c, s) {
      var cannot = c.kind === 'cannot_check', name = HOOK_NAMES[c.hook] || String(c.hook || '하네스 훅');
      var text = String(c.text || ''), lines = text.split('\n'), first = lines[0].trim(), rest = lines.slice(1).join('\n').trim();
      var fix = String(c.fix || '').trim(), key = 'b' + String(c.t), open = !!chatOpen[key];
      var m = first.match(/^(.+?[.!?。](?=\s|$))\s*(.*)$/);  // 첫 문장은 크게, 나머지는 접기
      var head = m ? m[1] : first, more = ((m ? m[2] : '') + (rest ? '\n' + rest : '')).trim();
      var card = h('div', { class: 'q ' + (cannot ? 'unsure' : 'blocked'), 'data-chat': 'block', 'data-block-kind': cannot ? 'cannot_check' : 'blocked' });
      card.appendChild(h('span', { class: 'tagx ' + (cannot ? 'unk' : 'fail'), text: cannot ? '? 확인 못 함' : '✕ 막힘' }));
      card.appendChild(h('b', { class: 'bt', text: (cannot ? '검사를 못 해서 멈췄어 · ' : '하네스 검사가 막았어 · ') + name }));
      card.appendChild(h('span', { class: 'sm', 'data-block-head': '1', text: head }));
      if (more && open) card.appendChild(h('span', { class: 'sub', 'data-block-more': '1', text: more }));
      if (fix) card.appendChild(h('span', { class: 'sub', 'data-block-fix': '1' }, h('b', { text: '고치는 법 ' }), fix));
      // 시안 G-16: 막힘 [그렇게 고쳐 줘](진한) [내가 직접 볼게](테두리) [검사 원문](글자) /
      //            확인 못 함 [검사 다시 돌리기](진한) [관리자에게 알리기](테두리). 보낼 수 없는 세션이면 보내는 단추는 빼고 나머지만.
      var hkey = 'h' + String(c.t), mine = !!chatOpen[hkey], note = chatOpen['n' + String(c.t)] || '';
      var raw = more ? h('button', { type: 'button', class: 'linkbtn sm', 'data-block-raw': '1', 'aria-expanded': String(open),
        onClick: function () { chatOpen[key] = !open; paintMsgs(cur()); } }, open ? '원문 접기' : '검사 원문') : null;
      if (mine) {
        card.appendChild(h('div', { class: 'acts' }, h('span', { class: 'note-muted', 'data-block-mine': '1', text: '직접 보기로 했어.' }), raw));
        return card;
      }
      var send = s.canSend === true;
      var acts = cannot
        ? [send ? h('button', { type: 'button', class: 'pill dark sm', 'data-block-send': '1', text: '검사 다시 돌리기',
              onClick: function () { sendFollow('검사를 못 해서 멈춘 일을 다시 시도해 줘: ' + head + (fix ? '\n고치는 법: ' + fix : '')); } }) : null,
           h('button', { type: 'button', class: 'pill line sm', 'data-block-admin': '1', text: '관리자에게 알리기',
              onClick: function () {
                var msg = '[하네스 검사 못 함] ' + name + '\n' + text + (s.cwd ? '\n폴더: ' + s.cwd : '');
                var done = function (ok) { chatOpen['n' + String(c.t)] = ok ? '보낼 내용을 복사했어. 팀 메신저에 붙여 넣어 관리자에게 알려 줘.' : '복사하지 못했어. 위 문구를 직접 골라 복사해 줘.'; paintMsgs(cur()); };
                try { navigator.clipboard.writeText(msg).then(function () { done(true); }, function () { done(false); }); } catch (e) { done(false); }
              } })]
        : [send ? h('button', { type: 'button', class: 'pill dark sm', 'data-block-send': '1', text: '그렇게 고쳐 줘',
              onClick: function () { sendFollow('하네스 훅이 막은 이유대로 고쳐 줘: ' + head + (fix ? '\n고치는 법: ' + fix : '')); } }) : null,
           h('button', { type: 'button', class: 'pill line sm', 'data-block-self': '1', text: '내가 직접 볼게',
              onClick: function () { chatOpen[hkey] = true; paintMsgs(cur()); } }),
           raw];
      card.appendChild(h('div', { class: 'acts' }, acts));
      if (note) card.appendChild(h('p', { class: 'note-accent', role: 'status', text: note }));
      return card;
    }
    // 새 항목이 왔을 때 보던 자리가 대화 끝 근처일 때만 아래로 따라간다(위로 올려 읽는 중이면 그대로 둔다)
    function chatEndNear() {
      var el = regions.msgs;
      if (!el || !el.getBoundingClientRect || typeof window.innerHeight !== 'number') return false;
      return el.getBoundingClientRect().bottom <= window.innerHeight + 160;
    }
    var CHAT_FOLD = 12;
    function chatList(s, items, drawn) {
      var out = [], hidden = chatAll ? 0 : Math.max(0, items.length - CHAT_FOLD);
      if (s.chatPartial) out.push(h('p', { class: 'quiet', 'data-chat-partial': '1', text: '터미널에서 한 대화는 내 말과 AI 마지막 답만 보여.' }));
      if (items.length > CHAT_FOLD) {
        out.push(h('button', { type: 'button', class: 'disclose', 'data-chat-fold': '1', 'aria-expanded': String(chatAll), onClick: function () { chatAll = !chatAll; paintMsgs(cur()); } },
          icon('chev', 14), chatAll ? '앞 대화 접기' : '… 앞 대화 ' + hidden + '개 접힘'));
      }
      items.slice(hidden).forEach(function (c) {
        var el = c.role === 'me' ? chatMe(c) : c.role === 'ai' ? chatAi(c) : c.role === 'req' ? chatReq(c, s, drawn) : c.role === 'block' ? chatBlock(c, s) : null;
        if (el) out.push(el);
      });
      return out;
    }

    // 대화: 서버가 쌓은 대화(없으면 AI 마지막 보고) → 방금 보낸 말 → 순서·검토 요청 카드 → 네 차례(질문·승인) → 멈추기
    function paintMsgs(s) {
      var items = (Array.isArray(s.chat) ? s.chat : []).filter(function (c) { return c && typeof c === 'object'; });
      var drawn = {}, out = [];
      if (items.length) {
        out = chatList(s, items, drawn);
        // 서버 대화에 같은 글이 들어왔으면 이 탭에서 방금 보낸 말은 지운다
        sent = sent.filter(function (m) {
          return !items.some(function (c) { return c.role === 'me' && String(c.text || '').trim() === m.text.trim() && (Number(c.t) || 0) >= m.at - 30; });
        });
      } else {
        out = [reportMsg(s)];
      }
      sent.forEach(function (m) { out.push(h('div', { class: 'me', text: m.text })); });
      var note = askedNote(s);
      if (note) out.push(note);
      if (s.status === 'running') { var td = todoCard(s); if (td) out.push(td); }
      var prc = ui.prCard(s);
      if (prc) out.push(prc);
      (s.pendingRequestIds || []).forEach(function (rid) {
        if (drawn[rid]) return;
        var card = askCard(rid);
        if (card) out.push(card);
      });
      var last = items[items.length - 1];
      var key = items.length + ':' + (last ? String(last.t) + String(last.answer || '') : '');
      var follow = chatKey !== null && key !== chatKey && chatEndNear();
      chatKey = key;
      if (s.managed && s.status === 'running') {
        out.push(interruptAsk
          ? h('div', { class: 'acts' }, h('span', { class: 'quiet', text: '진행 중인 작업을 멈출까?' }), h('button', { type: 'button', class: 'pill dark sm', text: '중단', onClick: interrupt }), h('button', { type: 'button', class: 'pill line sm', text: '취소', onClick: function () { interruptAsk = false; draw(); } }))
          : h('div', { class: 'acts' }, h('button', { type: 'button', class: 'pill line sm', text: '작업 멈추기', onClick: function () { interruptAsk = true; draw(); } })));
      }
      regions.msgs.replaceChildren.apply(regions.msgs, out);
      var tail = regions.msgs.lastChild;
      if (follow && tail && tail.scrollIntoView) tail.scrollIntoView({ block: 'nearest' });
    }

    function paint(s) {
      var tt = s.title || baseName(s.cwd) || '세션';
      setTitle(tt);
      paintHead(s); paintStages(s); paintStrip(s); paintNotices(s);
      paintMsgs(s);
      paintSubs(s);
      paintPerm(s);
      parts.checks.update(s); parts.flow.update(s); parts.tools.update();
      parts.folder.update(s.cwd, window.BHLogic.sameFolderBusy(s, Array.from(sessions.values())), function (path) { draft.cwd = path; draft.picked = null; });
      parts.docs.update(s);
      paintFollow(s);
      paintFiles(s);
      paintLog(s);
      paintTech(s);
      syncLegend();
    }

    function paintFollow(s) {
      var can = s.canSend !== false;
      regions.followInput.disabled = !can; regions.followBtn.disabled = !can;
      var why = regions.follow.querySelector('[data-why]');
      why.textContent = can ? '' : (s.cannotSendReason || '이 세션에는 지금 요청을 보낼 수 없어.');
      why.hidden = can;
      paintFollowNote();
    }

    function paintFiles(s) {
      var out = [];
      var prs = (s.prLinks || []).map(function (p) { return typeof p === 'string' ? { url: p } : p; }).filter(function (p) { return p && p.url; });
      if (prs.length) out.push(h('section', { class: 'mt-40' }, h('h2', { class: 'label', text: '검토 요청(PR)' }),
        h('ul', { class: 'plain-list' }, prs.map(function (p) {
          var u = safeHttp(p.url);
          return h('li', null, u ? h('a', { href: u, target: '_blank', rel: 'noopener noreferrer', text: p.title || p.url }) : h('span', { text: p.title || p.url }), p.number ? h('span', { class: 'd', text: '#' + p.number }) : null);
        }))));
      var files = (s.changedFiles || []).map(function (f) { return typeof f === 'string' ? { path: f } : f; }).filter(function (f) { return f && f.path; });
      if (files.length) out.push(h('section', { class: 'mt-40' }, h('h2', { class: 'label', text: '바뀐 파일 ' + files.length + '개' }),
        h('ul', { class: 'plain-list' }, files.map(function (f) {
          var delta = f.added != null || f.deleted != null ? '+' + (f.added || 0) + ' −' + (f.deleted || 0) : (f.delta || f.status || '');
          return h('li', null, h('span', { class: 'mono wrap-any', text: f.path }), delta ? h('span', { class: 'd', text: delta }) : null);
        }))));
      regions.files.replaceChildren.apply(regions.files, out);
    }

    function paintLog(s) {
      var log = (s.log || []).slice().reverse(), shown = logAll ? log : log.slice(0, 30);
      var sec = h('section', { class: 'mt-64' }, h('h2', { class: 'label', text: '이 세션에서 일어난 일' }));
      if (!log.length) sec.appendChild(h('p', { class: 'note-muted', text: '아직 기록이 없어.' }));
      else {
        sec.appendChild(h('ul', { class: 'logs' }, shown.map(function (l) { return h('li', null, h('time', { text: clock(l.time) }), h('span', { text: l.text })); })));
        if (log.length > shown.length) sec.appendChild(h('button', { type: 'button', class: 'disclose', onClick: function () { logAll = true; paintLog(cur()); } }, icon('chev', 14), '이전 기록 ' + (log.length - shown.length) + '개 더 보기'));
      }
      regions.log.replaceChildren(sec);
    }

    function paintTech(s) {
      var open = regions.tech.querySelector('details') ? regions.tech.querySelector('details').open : false;
      var subs = (s.subagents || []).map(function (a) { return typeof a === 'string' ? a : [a.model || a.name || a.type, a.task || a.description || a.state || a.status].filter(Boolean).join(' · '); });
      var rows = [
        ['저장소', [s.repo, s.branch].filter(Boolean).join(' / ')],
        ['작업 폴더', s.cwd], ['현재 동작', s.currentAction], ['현재 스킬', s.currentSkill], ['상태', s.status],
        ['권한 모드', s.permissionMode], ['모델', modelLine(s).replace(/^모델: /, '').replace(/ · 에포트: /, ' · 에포트 ')], ['세션 ID', s.id], ['실행 방식', s.managed ? '콘솔이 띄운 세션' : '터미널 세션'],
        ['서브에이전트', subs.length ? subs.join('\n') : '돌고 있는 서브에이전트 없음']
      ].filter(function (r) { return r[1]; });
      var dl = h('dl', { class: 'kv' });
      rows.forEach(function (r) { dl.appendChild(h('dt', { text: r[0] })); dl.appendChild(h('dd', { class: r[0] === '서브에이전트' ? '' : 'mono', text: r[1] })); });
      var d = h('details', { class: 'tech', open: open }, h('summary', { text: '기술 정보 보기' }), dl);
      regions.tech.replaceChildren(d);
    }

    fetchDetail();
    draw();
    return {
      title: function () { return cur().title || ''; },
      onSession: function (sid) { if (sid === id) draw(); },
      onRequest: function () { draw(); },
      onData: function () { draw(); },
      onRemoved: function (rid) { if (rid === id) { errored = new ApiError(404, ''); built = false; draw(); } },
      tick: function () {
        var el = regions.head && regions.head.querySelector('[data-elapsed]');
        var t = elapsedStr(cur().startedAt);
        if (el && t) el.textContent = ' · 경과 ' + t;
        if (regions.subs && runningSubagents(cur()).length) paintSubs(cur());  // 서브에이전트 경과 시간
      },
      destroy: function () { clearTimeout(timer); Object.keys(parts).forEach(function (k) { parts[k].destroy(); }); }
    };
  }

  /* ---------- 승인·질문 (/r/:rid) ---------- */
  function requestView(root) {
    var rid = route.id, req = requests.get(rid) || null, errored = null, outcome = null, busy = false;
    var why = '', answers = null, picked = null, otherTexts = null, sendErr = '', hadSession = false;

    function fetchReq() {
      api('GET', '/api/requests/' + encodeURIComponent(rid)).then(function (r) {
        r = r && r.request ? r.request : r; if (!r.id) r.id = rid;
        requests.set(rid, Object.assign({}, requests.get(rid) || {}, r)); req = requests.get(rid); errored = null; draw();
      }, function (e) { errored = e; draw(); });
    }
    function isPending() { return req && (!req.status || req.status === 'pending' || req.status === 'waiting') && !outcome; }
    function sessionOf() { return req && (sessions.get(req.sessionId || req.session_id) || {}); }

    function draw() {
      clear(root);
      if (!req) {
        if (errored && errored.status === 404) return root.appendChild(stateBox('warn', '요청을 찾을 수 없습니다', '이미 지나간 요청이거나 콘솔이 다시 시작되어 기록이 없습니다.', link('/', { class: 'btn', text: '처음 화면으로' })));
        if (errored) return root.appendChild(stateBox('warn', '요청을 불러오지 못했습니다', errored.message, h('button', { type: 'button', class: 'btn', text: '다시 시도', onClick: function () { errored = null; draw(); fetchReq(); } })));
        return root.appendChild(loadingBox('요청을 불러오는 중입니다.'));
      }
      var isQ = kindOf(req) === 'question';
      hadSession = !!(sessionOf() || {}).id;
      setTitle(isQ ? '질문' : '승인');
      (isQ ? drawQuestion : drawPermission)();
      fetchDetail();
    }

    function sid() { return req.sessionId || req.session_id; }
    /* 시안 G-07·17: 그 세션의 최근 대화(내 말 · AI 말)와 카드 아래 "AI에게 말하기" 입력창. 세션 화면의 대화 모양과 이어 요청을 그대로 따른다.
       대화는 세션 상세에만 있어 한 번 따로 읽는다. 못 읽으면 대화 없이 카드만 보인다. */
    var detail = null, detailTried = false, sayVal = '', sayNote = '', sayBusy = false, CHAT_SHOWN = 3;
    function fetchDetail() {
      if (detailTried || !req || !sid()) return;
      detailTried = true;
      api('GET', '/api/sessions/' + encodeURIComponent(sid())).then(function (d) { detail = d && d.session ? d.session : d; if (detail) draw(); }, function () {});
    }
    function sessData() { return Object.assign({}, sessionOf() || {}, detail || {}); }
    function recentChat() {
      var items = (Array.isArray(sessData().chat) ? sessData().chat : []).filter(function (c) { return c && (c.role === 'me' || c.role === 'ai') && String(c.text || '').trim(); });
      return items.slice(-CHAT_SHOWN).map(function (c) {
        if (c.role === 'me') return h('div', { class: 'me', 'data-chat': 'me', text: String(c.text) });
        var text = String(c.text), long = text.split('\n').length > 28 || text.length > 2200;
        var body = h('div', { class: 'report-body' + (long ? ' clip' : '') });
        body.appendChild(window.BHMarkdown.render(text));
        return h('div', { class: 'ai', 'data-chat': 'ai' }, h('span', { class: 'eb', text: 'AI' + (c.t ? ' · ' + clock(c.t) : '') }), body);
      });
    }
    function sayBox() {
      var s = sessData(), can = !!sid() && s.canSend !== false && s.status !== 'ended', box = h('div', { class: 'followbox', 'data-say': '1' });
      var note = h('p', { class: 'note-accent', role: 'status', text: sayNote, hidden: !sayNote });
      var input = h('input', { id: 'say', class: 'comp-in', value: sayVal, placeholder: 'AI에게 말하기 — 예: 잠깐, 이 파일은 지우지 말고 이름만 바꿔 줘  (/ 로 스킬, @ 로 파일)', autocomplete: 'off', disabled: !can,
        onInput: function (e) { sayVal = e.target.value; sayNote = ''; note.textContent = ''; note.hidden = true; },
        onKeydown: function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229 && !(assist && assist.isOpen())) { e.preventDefault(); send(); } } });
      var assist = withAssist(input, function () { return s.cwd || req.cwd; });
      var btn = h('button', { type: 'button', class: 'pill dark', disabled: !can || sayBusy, text: '보내기', onClick: send });
      function send() {
        var text = sayVal.trim(); if (!text || !can || sayBusy) return;
        sayBusy = true; btn.disabled = true;
        api('POST', '/api/sessions/' + encodeURIComponent(sid()) + '/messages', { text: text }).then(function () {
          sayVal = ''; input.value = ''; sayNote = s.status === 'running' ? '지금 단계가 끝나면 이어서 처리합니다.' : '이 작업에 전달했습니다.';
        }, function (e) { sayNote = '보내지 못했습니다: ' + e.message; }).then(function () { sayBusy = false; btn.disabled = false; note.textContent = sayNote; note.hidden = !sayNote; });
      }
      box.appendChild(h('label', { for: 'say', class: 'sr-only', text: 'AI에게 말하기' }));
      box.appendChild(h('div', { class: 'comp' }, assist.wrap, btn));
      box.appendChild(note);
      if (!can) box.appendChild(h('p', { class: 'note-muted', 'data-say-why': '1', text: s.cannotSendReason || (sid() ? '이 세션에는 지금 말을 보낼 수 없어.' : '세션을 알 수 없어 말을 보낼 수 없어.') }));
      return box;
    }
    function ebText(isQ) {
      var s = sessionOf() || {}, open = isPending();
      return (s.flowName ? s.flowName + ' · ' : '') + (open ? (isQ ? '내 답을 기다리는 중' : '내 승인을 기다리는 중') + waitedText(req.createdAt || req.createdAtMs) : (isQ ? '처리된 질문' : '처리된 승인 요청'));
    }
    /* 위 제목 블록(갈래 · 지금 하는 일, 세션 이름, 한 줄 상태) + 순서 알약 + 숫자 띠. 세션 화면과 같은 모양이다. */
    function head(page, isQ, line) {
      var s = sessionOf() || {}, open = isPending();
      page.appendChild(h('div', { class: 'ptitle' },
        h('span', { class: 'eb ' + (open ? 'attn' : ''), 'data-eb': '1', text: ebText(isQ) }),
        h('h1', { text: s.title || baseName(s.cwd) || (isQ ? '질문' : '승인') }),
        h('p', { class: 'line', text: line })));
      // 질문(G-07)·확인(G-17) 화면에는 순서 알약이 없다(시안)
      if (s.id) {
        var cells = window.BHLogic.sessionStrip(s);
        page.appendChild(h('div', { class: 'strip', role: 'list', 'aria-label': '진행 숫자' }, cells.map(function (c) {
          return h('div', { role: 'listitem', 'data-cell': c.id, title: c.title || null }, h('span', { class: 'eb', text: c.label }), h('span', { class: 'x ' + (c.tone || ''), text: c.value }));
        })));
      }
    }

    /* 결과 */
    var RES = {
      allow: ['허락했어.', '세션이 작업을 이어 가.'], allow_session: ['허락했어.', '이 세션에서는 같은 작업을 다시 묻지 않아.'],
      always: ['허락했어.', '이 세션에서는 같은 작업을 다시 묻지 않아.'],
      deny: ['하지 말라고 했어.', '세션이 다른 방법을 찾아.'], answered: ['세션에 답을 전달했어.', ''],
      terminal: ['터미널에서 처리됨', '터미널에서 이미 답해서 콘솔에서는 할 일이 없어.'],
      handoff: ['터미널로 넘어감', '기다리는 시간이 지나 터미널의 질문창이 대신 처리해.'],
      expired: ['닫힌 요청', '시간이 지났거나 세션이 끝나 더 이상 답할 수 없어.'], closed: ['닫힌 요청', '세션이 끝났거나 다른 곳에서 처리되어 더 이상 답할 수 없어.']
    };
    function resultOf() {
      if (outcome) return outcome;
      var code = String(req.outcome || req.closedReason || req.resolution && req.resolution.code || req.status || 'closed').toLowerCase();
      var key = /terminal|처리/.test(code) ? (/hand|넘/.test(code) ? 'handoff' : 'terminal') : /hand/.test(code) ? 'handoff' : /allowed_session|allow_session/.test(code) ? 'allow_session' : /allow/.test(code) ? 'allow' : /den/.test(code) ? 'deny' : /answer/.test(code) ? 'answered' : /expire|timeout/.test(code) ? 'expired' : 'closed';
      var r = RES[key].slice();
      var custom = req.resultText || (req.resolution && (req.resolution.text || req.resolution.message)) || (typeof req.resolution === 'string' ? req.resolution : '');
      if (custom) r[1] = custom;
      return { title: r[0], note: r[1], extra: req.reason ? '전달한 이유: ' + req.reason : '' };
    }
    function resultBlock() {
      var r = resultOf();
      return h('div', { class: 'result ai', role: 'status' }, h('span', { class: 'eb', text: '결과' }), h('p', { class: 'big', text: r.title }), r.note ? h('p', { class: 'sub', text: r.note }) : null, r.extra ? h('p', { class: 'sub', text: r.extra }) : null,
        (r.lines || []).map(function (l) { return h('p', { class: 'sub', text: l }); }), backToSession(sid()));
    }

    /* 승인: 시안의 "확인 필요" 카드. 한 줄 요약은 바로 보이고, 명령 원문·입력 전체는 "자세히" 에 있다.
       쉬운 설명이 없는 명령, 샌드박스를 끄거나 백그라운드로 도는 명령, 파일을 쓰고 고치는 일은 접지 않고 열어 둔다(무엇을 허락하는지 가려지면 안 된다). */
    var TOOL_FIELDS = { Bash: ['명령', 'command'], Write: ['파일', 'file_path'], Edit: ['파일', 'file_path'], MultiEdit: ['파일', 'file_path'], Read: ['파일', 'file_path'], NotebookEdit: ['노트북', 'notebook_path'], WebFetch: ['주소', 'url'], Glob: ['패턴', 'pattern'], Grep: ['검색어', 'pattern'], WebSearch: ['검색어', 'query'] };
    function drawPermission() {
      var page = h('div', { class: 'page sess req' });
      var tool = req.toolName || req.tool_name || '도구', input = req.toolInput || req.tool_input || req.input || {};
      head(page, false, isPending() ? 'AI가 네 허락을 기다리고 있어' : '이미 처리된 요청이야');
      var panel = h('section', { class: 'light talk' }), msgs = h('div', { class: 'msgs' });
      /* 시안 17: 되돌릴 수 없는 일(서버가 req.risk = 'irreversible' 과 쉬운 말 사유 riskNote 를 준다)은 같은 카드에 꼬리표와 한 줄 설명을 더한다. */
      var irrev = req.risk === 'irreversible';
      var f = TOOL_FIELDS[tool], risk = irrev ? '하네스는 되돌릴 수 없는 일은 항상 사람에게 물어.' : (req.risk || req.riskNote || req.warning);
      /* 시안 17: 단추는 행동을 그대로 말한다. 되돌릴 수 없는 일만 지우기 · 올리기를 가려내고, 나머지는 이번만 허락 / 하지 마. */
      var cmdText = String(input && (input.command || input.file_path) || ''), noteText = String(req.riskNote || req.title || '');
      var verbs = ['이번만 허락', '하지 마'];
      if (irrev) {
        if (/(^|[\s;&|])(rm|rmdir|del|erase|unlink)\s|Remove-Item|지우|삭제/i.test(cmdText + ' ' + noteText)) verbs = ['이번만 지워', '지우지 마'];
        else if (/git\s+push|gh\s+pr\s+(create|merge)|올리|푸시/i.test(cmdText + ' ' + noteText)) verbs = ['이번만 올려', '올리지 마'];
      }
      msgs.appendChild(h('div', { class: 'ai' }, h('span', { class: 'eb', text: 'AI' }), req.description || (irrev ? tool + ' 도구를 쓰려는데 되돌릴 수 없는 일이라 네 확인이 필요해.' : tool + ' 도구를 쓰려는데 네 확인이 필요해.')));

      var card = h('div', { class: 'bad' + (irrev ? ' irrev' : ''), 'data-risk': irrev ? 'irreversible' : null });
      card.appendChild(h('span', { class: 'tagx', text: irrev ? '확인 필요 · 되돌릴 수 없어' : '확인 필요' }));
      card.appendChild(h('b', { class: 'bt', text: req.title || (irrev && req.riskNote ? req.riskNote : 'Claude Code가 ' + tool + ' 도구를 쓰려고 해. 허락할까?') }));
      // 시안 17: 하네스 안내 줄은 강조 없이 연한 보통 글. 그 밖의 경고(req.risk 글)는 예전처럼 강조한다.
      if (risk) card.appendChild(h('span', { class: irrev ? 'muted-line' : 'warn-line', text: typeof risk === 'string' ? risk : (risk.text || risk.message || '') }));
      if (input && input.description) card.appendChild(h('span', { class: 'sm', text: str(input.description) }));
      if (f && input && input[f[1]] != null && tool !== 'Bash') card.appendChild(h('span', { class: 'sm' }, f[0] + ': ', h('b', { text: str(input[f[1]]) })));
      if (input && input.dangerouslyDisableSandbox) card.appendChild(h('span', { class: 'warn-line', text: '샌드박스를 끄고 실행해(dangerouslyDisableSandbox)' }));
      if (input && input.run_in_background) card.appendChild(h('span', { class: 'sm', text: '백그라운드로 실행해(run_in_background)' }));

      var rows = h('dl', { class: 'rows' });
      function row(k, v, mono, scroll) { if (v == null || v === '') return; rows.appendChild(h('dt', { text: k })); rows.appendChild(h('dd', { class: (mono ? 'mono' : '') + (scroll ? ' scroll' : ''), tabindex: scroll ? '0' : null, text: v })); }
      row('도구', tool, true);
      if (f && input && input[f[1]] != null) row(f[0], str(input[f[1]]), true, tool === 'Bash');  // 여러 줄 명령(heredoc)의 줄바꿈을 그대로 보인다
      if (input && input.description) row('설명', str(input.description));
      if (input && typeof input.content === 'string') row('쓸 내용', input.content, true, true);
      if (input && typeof input.old_string === 'string') row('원래 글', input.old_string, true, true);
      if (input && typeof input.new_string === 'string') row('바꾼 글', input.new_string, true, true);
      var s = sessionOf() || {};
      row('작업 폴더', req.cwd || s.cwd, true);
      var friendly = tool === 'Bash' && input && input.description && !input.dangerouslyDisableSandbox && !input.run_in_background;
      var det = h('details', { class: 'more', open: !friendly }, h('summary', { text: tool === 'Bash' ? '자세히 (명령 원문)' : '자세히 (바뀌는 내용)' }), rows);
      var kv = h('dl', { class: 'kv' });
      [['세션', s.title || sid()], ['브랜치', s.branch], ['도구 이름', tool], ['요청 ID', rid]].forEach(function (r) { if (r[1]) { kv.appendChild(h('dt', { text: r[0] })); kv.appendChild(h('dd', { class: 'mono', text: String(r[1]) })); } });
      det.appendChild(kv);
      /* 입력 전체는 항상 이 안에 있다. 사용자가 무엇을 허락하는지 가려지면 안 된다(MCP, Agent, Skill 등 목록에 없는 도구 포함). */
      det.appendChild(h('h2', { class: 'label', text: '도구에 넘기는 입력 전체' }));
      det.appendChild(h('pre', { class: 'box scroll', tabindex: '0', 'aria-label': '도구 입력 전체', text: JSON.stringify(input, null, 2) }));
      card.appendChild(det);

      if (isPending()) {
        var canSess = !(irrev || req.canAllowSession === false || req.hasSuggestions === false || (Array.isArray(req.permissionSuggestions) && !req.permissionSuggestions.length) || (Array.isArray(req.permission_suggestions) && !req.permission_suggestions.length));
        var sugg = Array.isArray(req.suggestionText) ? req.suggestionText : [];
        if (canSess) card.appendChild(h('div', { class: 'sugg', role: 'group', 'aria-label': '다시 묻지 않기로 추가되는 규칙' },
          h('p', { class: 'sugg-h', text: '"허용하고 이 세션에서 다시 묻지 않기"를 누르면 다음 규칙이 추가됩니다' }),
          sugg.length ? h('ul', { class: 'sugg-l' }, sugg.map(function (x) { return h('li', { class: 'mono', text: x }); }))
            : h('p', { class: 'sub', text: '규칙 내용을 읽지 못했어. 위 입력 전체를 확인해.' }),
          req.suggestions ? h('pre', { class: 'box scroll', tabindex: '0', text: JSON.stringify(req.suggestions, null, 2) }) : null));
        // 시안엔 이유 입력칸이 없어 접어 둔다(기능은 남김). 적은 이유가 있으면 펼친 채로 둔다.
        card.appendChild(h('details', { class: 'more', 'data-why-fold': '1', open: !!why },
          h('summary', { text: '이유 적기(선택)' }),
          h('label', { for: 'why', class: 'field-label', text: verbs[1] + ' 를 누를 때 AI에게 전달할 이유' }),
          h('input', { id: 'why', class: 'input', value: why, placeholder: '예: 리뷰가 끝난 뒤에 해 줘', autocomplete: 'off', onInput: function (e) { why = e.target.value; } })));
        if (sendErr) card.appendChild(h('p', { class: 'note-attn', role: 'alert', text: sendErr }));
        card.appendChild(h('div', { class: 'acts' },
          h('button', { type: 'button', class: 'pill dark', 'data-decide': 'allow', disabled: busy, text: verbs[0], onClick: function () { decide('allow'); } }),
          h('button', { type: 'button', class: 'pill line', 'data-decide': 'deny', disabled: busy, text: verbs[1], onClick: function () { decide('deny'); } }),
          canSess ? h('button', { type: 'button', class: 'pill line', disabled: busy, text: '허용하고 이 세션에서 다시 묻지 않기', onClick: function () { decide('allow_session'); } }) : null));
        msgs.appendChild(card);
      } else { msgs.appendChild(card); msgs.appendChild(resultBlock()); }
      panel.appendChild(msgs);
      if (isPending()) panel.appendChild(sayBox());
      page.appendChild(panel);
      root.appendChild(page);
    }
    function decide(d) {
      busy = true; sendErr = ''; var reason = why.trim(); draw();
      var body = { decision: d }; if (d === 'deny' && reason) body.reason = reason;
      api('POST', '/api/requests/' + encodeURIComponent(rid) + '/answer', body).then(function () {
        var r = RES[d].slice(); if (d === 'deny' && reason) r[1] = '전달한 이유: ' + reason;
        outcome = { title: r[0], note: r[1] };
      }, function (e) { afterFail(e); }).then(function () { busy = false; draw(); });
    }
    function afterFail(e) {
      if (e.status === 404 || e.status === 409 || e.status === 410) { sendErr = ''; fetchReq(); req = Object.assign({}, req, { status: req.status === 'pending' ? 'closed' : req.status }); requests.set(rid, req); }
      else sendErr = '전달하지 못했습니다: ' + e.message;
    }

    /* 질문: 보기 하나가 알약 버튼. 질문 글은 카드 안에 한 번만 나온다(위 제목은 세션 이름이라 겹치지 않는다, #635). */
    function qKey(q) { return q.question; }
    function initAnswers() {
      if (picked) return;
      picked = {}; otherTexts = {};
      questionsOf(req).forEach(function (q, i) { picked[i] = []; otherTexts[i] = ''; });
    }
    function answerOf(i, q) {
      var other = (otherTexts[i] || '').trim();
      if (q.multiSelect) {
        var parts = (picked[i] || []).slice(); if (other) parts.push(other);
        return parts.length ? parts.join(', ') : '';
      }
      return other || (picked[i] && picked[i][0]) || '';
    }
    function drawQuestion() {
      initAnswers();
      var qsList = questionsOf(req), page = h('div', { class: 'page sess req' });
      var multi = qsList.length > 1, open = isPending();
      head(page, true, open ? (multi ? 'AI가 ' + qsList.length + '가지를 물어봤어 · 답하면 이어서 일해' : 'AI가 물어본 게 있어 · 답하면 이어서 일해') : '이미 처리된 질문이야');
      var panel = h('section', { class: 'light talk' }), msgs = h('div', { class: 'msgs' });
      recentChat().forEach(function (el) { msgs.appendChild(el); });  // 시안 G-07: 질문 카드 위에 그 세션의 최근 대화
      qsList.forEach(function (q, i) {
        var opts = q.options || [], hasPrev = opts.some(function (o) { return o && o.preview; });
        var card = h('div', { class: 'q', role: 'group', 'aria-labelledby': 'qh-' + i });
        card.appendChild(h('span', { class: 'eb', text: (multi ? '질문 ' + (i + 1) + ' / ' + qsList.length : '질문') + (q.header ? ' · ' + q.header : '') + (q.multiSelect ? ' · 여러 개 선택' : '') }));
        card.appendChild(h('b', { id: 'qh-' + i, text: q.question || '질문이 있어' }));
        var list = h('div', { class: 'qo' + (hasPrev ? ' col' : '') });
        opts.forEach(function (o) {
          var label = typeof o === 'string' ? o : o.label, on = picked[i].indexOf(label) >= 0;
          list.appendChild(h('button', { type: 'button', class: 'qopt', 'aria-pressed': String(on), disabled: !open || busy, onClick: function () {
            if (q.multiSelect) { picked[i] = on ? picked[i].filter(function (x) { return x !== label; }) : picked[i].concat(label); }
            else { picked[i] = on ? [] : [label]; otherTexts[i] = ''; }
            draw();
          } }, h('span', { class: 't', text: label }), o && o.description ? h('small', { text: o.description }) : null));
        });
        if (hasPrev) {
          var sel = opts.filter(function (o) { return o && o.label === picked[i][picked[i].length - 1]; })[0];
          card.appendChild(h('div', { class: 'q-body' }, list, h('pre', { class: 'box lg q-preview' + (sel && sel.preview ? '' : ' empty'), 'aria-label': '선택한 항목 미리보기', text: sel && sel.preview ? sel.preview : '항목을 고르면 미리보기가 여기에 보여.' })));
        } else card.appendChild(list);
        card.appendChild(h('label', { for: 'other-' + i, class: 'sr-only', text: '다른 답이 있으면 직접 적어 줘' }));  // 시안엔 보이는 글 없이 입력칸만
        card.appendChild(h('input', { id: 'other-' + i, class: 'input q-other', value: otherTexts[i], placeholder: '다른 답이 있으면 직접 적어 줘 — 예: 구매팀 김OO, 10/28 회의', autocomplete: 'off', disabled: !open || busy,
          onInput: function (e) {
            otherTexts[i] = e.target.value;
            if (!q.multiSelect && e.target.value.trim() && picked[i].length) { picked[i] = []; card.querySelectorAll('.qopt').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); }); }
            syncSend();
          } }));
        msgs.appendChild(card);
      });

      if (open) {
        var sendBtn = h('button', { type: 'button', id: 'qsend', class: 'pill dark', text: '답 보내기', disabled: busy, onClick: sendAnswers });
        msgs.appendChild(h('div', { class: 'acts end' }, sendBtn));
        msgs.appendChild(h('p', { class: 'q-status', id: 'qstat', role: 'status' }));
        if (sendErr) msgs.appendChild(h('p', { class: 'note-attn', role: 'alert', text: sendErr }));
      } else msgs.appendChild(resultBlock());
      panel.appendChild(msgs);
      if (open) panel.appendChild(sayBox());
      page.appendChild(panel);
      root.appendChild(page);
      syncSend();
    }
    function allAnswered() { return questionsOf(req).every(function (q, i) { return !!answerOf(i, q); }); }
    function syncSend() {
      var b = root.querySelector('#qsend'), st = root.querySelector('#qstat'); if (!b) return;
      var left = questionsOf(req).filter(function (q, i) { return !answerOf(i, q); }).length;
      b.disabled = busy || left > 0;
      if (st) st.textContent = left ? '아직 답하지 않은 질문이 ' + left + '개 있어.' : '';
    }
    function sendAnswers() {
      var qsList = questionsOf(req), ans = {}, lines = [];
      qsList.forEach(function (q, i) { ans[qKey(q)] = answerOf(i, q); lines.push(q.question + ' → ' + answerOf(i, q)); });
      busy = true; sendErr = ''; draw();
      api('POST', '/api/requests/' + encodeURIComponent(rid) + '/answer', { answers: ans }).then(function () {
        outcome = { title: '세션에 답을 전달했어.', note: '', lines: lines };
      }, afterFail).then(function () { busy = false; draw(); });
    }

    if (!req) fetchReq(); else { fetchReq(); }
    draw();
    return {
      title: function () { return ''; },
      onRequest: function (id) { if (id === rid) { req = requests.get(rid); draw(); } },
      /* 세션 정보가 뒤늦게 오면 제목 블록만 채우려고 다시 그린다. 이미 있을 때는 입력 중인 칸을 지우지 않게 그대로 둔다. */
      onSession: function () { if (req && !hadSession && (sessionOf() || {}).id) draw(); },
      onData: function () { if (req && !hadSession && (sessionOf() || {}).id) draw(); },
      onRemoved: function (id) { if (id === rid) { req = requests.get(rid) || req; draw(); } },
      tick: function () { var e = root.querySelector('[data-eb]'); if (e && isPending()) e.textContent = ebText(kindOf(req) === 'question'); }
    };
  }

  /* ---------- 입력창 보조: 스킬 버튼, / 자동완성, @ 파일 멘션 ---------- */
  var ASSIST_MAX_ITEMS = 8;
  var ASSIST_FILE_DELAY = 150;
  var ASSIST_HINT_LENGTH = 60;
  var MENTION_QUOTE = '"';  /* 공백 든 경로는 @"경로" 로 감싼다(Claude Code 의 @ 멘션 형식) */
  var QUOTED_MENTION = /(^|\s)@"([^"]*)$/;
  var DEFAULT_PLUGIN = 'harness';
  var CARET_KEYS = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
  var skillInfo = null, skillWaiters = [], skillLoading = false;
  function withSkills(cb) {
    if (skillInfo) { cb(skillInfo); return; }
    skillWaiters.push(cb);
    if (skillLoading) return;
    skillLoading = true;
    api('GET', '/api/skills').then(function (d) {
      skillInfo = { plugin: (d && d.plugin) || DEFAULT_PLUGIN, skills: listOf(d, 'skills') };
    }, function (e) { console.warn('스킬 목록을 불러오지 못했습니다', e); }).then(function () {
      skillLoading = false;
      var info = skillInfo || { plugin: DEFAULT_PLUGIN, skills: [] }; // 못 불러왔으면 비워 두고 다음에 다시 시도한다
      var w = skillWaiters; skillWaiters = [];
      w.forEach(function (f) { f(info); });
    });
  }
  function setFieldValue(field, value, caret) {
    field.value = value;
    field.focus();
    if (field.setSelectionRange) field.setSelectionRange(caret, caret);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function skillCommand(info, name) { return '/' + info.plugin + ':' + name + ' '; }
  /* 입력칸을 감싸 / 와 @ 자동완성 목록을 붙인다. getRoot 는 @ 로 찾을 작업 폴더를 돌려준다. */
  function withAssist(field, getRoot) {
    var box = h('ul', { class: 'assist', role: 'listbox', hidden: true });
    var state = { items: [], index: 0, token: null, seq: 0 }, timer = null;
    function isOpen() { return !box.hidden; }
    function close() { clearTimeout(timer); state.seq++; state.items = []; state.token = null; box.hidden = true; }
    function render() {
      clear(box);
      state.items.forEach(function (it, i) {
        box.appendChild(h('li', { role: 'option', class: 'assist-item', 'aria-selected': String(i === state.index), onMousedown: function (e) { e.preventDefault(); pick(i); } },
          h('span', { class: 'nm', text: it.label }), it.hint ? h('span', { class: 'hint', text: it.hint }) : null));
      });
      box.hidden = !state.items.length;
    }
    function show(items) { state.items = items; state.index = 0; render(); }
    function pick(i) {
      var it = state.items[i], t = state.token;
      if (!it || !t) return;
      var next = field.value.slice(0, t.start) + it.insert + field.value.slice(t.end);
      close();
      setFieldValue(field, next, t.start + it.insert.length);
    }
    function tokenAt() {
      var pos = field.selectionStart;
      if (pos == null) return null;
      var before = field.value.slice(0, pos);
      var quoted = QUOTED_MENTION.exec(before);  /* @" 로 시작하면 닫는 따옴표 전까지(공백 포함)가 검색어 */
      if (quoted) return { kind: '@', query: quoted[2], start: pos - quoted[2].length - 2, end: pos };
      var m = /(^|\s)([\/@])([^\s]*)$/.exec(before);
      return m ? { kind: m[2], query: m[3], start: pos - m[3].length - 1, end: pos } : null;
    }
    function fileInsert(path) {
      return /\s/.test(path) ? '@' + MENTION_QUOTE + path + MENTION_QUOTE + ' ' : '@' + path + ' ';
    }
    function skillItems(info, query) {
      /* 이름(start) 과 접두를 붙인 이름(harness:start) 둘 다 받는다. /h, /ha 는 이름에 든 글자로만 거른다. */
      var q = query.toLowerCase(), pre = info.plugin.toLowerCase() + ':';
      if (q.indexOf(pre) === 0) q = q.slice(pre.length);
      else if (q === info.plugin.toLowerCase()) q = '';
      var hits = info.skills.filter(function (sk) { return sk.name.toLowerCase().indexOf(q) >= 0; });
      hits.sort(function (a, b) { return (a.name.toLowerCase().indexOf(q) === 0 ? 0 : 1) - (b.name.toLowerCase().indexOf(q) === 0 ? 0 : 1); });
      return hits.slice(0, ASSIST_MAX_ITEMS).map(function (sk) {
        var d = sk.description || '';
        return { label: '/' + sk.name, hint: d.length > ASSIST_HINT_LENGTH ? d.slice(0, ASSIST_HINT_LENGTH) + '…' : d, insert: skillCommand(info, sk.name) };
      });
    }
    function update() {
      var t = tokenAt();
      if (!t) { close(); return; }
      clearTimeout(timer);
      var mine = ++state.seq;
      state.token = t;
      if (t.kind === '/') {
        withSkills(function (info) { if (mine === state.seq) show(skillItems(info, t.query)); });
        return;
      }
      var root = getRoot();
      if (!root) { show([]); return; }
      timer = setTimeout(function () {
        api('GET', '/api/files' + qs({ root: root, q: t.query })).then(function (d) {
          if (mine !== state.seq || !document.body.contains(field)) return;
          show(listOf(d, 'files').slice(0, ASSIST_MAX_ITEMS * 2).map(function (p) { return { label: p, hint: '', insert: fileInsert(p) }; }));
        }, function (e) { console.warn('파일을 찾지 못했습니다', e); if (mine === state.seq) show([]); });
      }, ASSIST_FILE_DELAY);
    }
    field.addEventListener('input', update);
    field.addEventListener('click', update);
    field.addEventListener('blur', close);
    field.addEventListener('keyup', function (e) { if (CARET_KEYS.indexOf(e.key) >= 0) update(); });
    field.addEventListener('keydown', function (e) {
      if (!isOpen() || e.isComposing || e.keyCode === 229) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        state.index = (state.index + (e.key === 'ArrowDown' ? 1 : state.items.length - 1)) % state.items.length;
        render();
      } else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(state.index); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    });
    return { wrap: h('div', { class: 'assist-wrap' }, field, box), isOpen: isOpen };
  }

  /* ---------- 새 작업 ---------- */
  var PERMISSION_FALLBACK = [{ value: '', label: '기본(그때그때 확인)' }, { value: 'acceptEdits', label: '파일 고치기는 자동 허용' }, { value: 'plan', label: '계획만 세우기' }, { value: 'auto', label: '알아서 하되 위험한 건 AI가 막기' }];
  /* 설정 "AI가 묻는 범위"(서버 ask.json). 시안 19 글. */
  var ASK_OPTIONS = [{ value: 'needed', label: '꼭 필요할 때만 (권장)', desc: 'GitHub에 올리기 · 파일 지우기 · 작업 폴더 밖 파일 · SAP에 저장하기' },
    { value: 'edits', label: '문서를 바꿀 때마다', desc: 'AI가 고친 내용을 하나씩 직접 볼 때' }, { value: 'all', label: '모든 명령마다', desc: '관리자 점검용 · 확인이 아주 많아져' }];
  var draft = { text: '', cwd: '', note: '', answers: {}, picked: null, extraPaths: [], model: null, modelCustom: false, customName: '', effort: null, permission: null, flowId: null, flowUser: false, kindFlowId: '', insist: false, kind: -1 };
  /* 새 작업의 종류 버튼: [이름, 한 줄 설명, 갈래 id(없으면 도구만 쓰는 일), 입력칸에 미리 넣는 문장]. 갈래 id 는 workflow.json flows 와 같다. */
  var KINDS = [
    ['요구사항정의서', '고객 요구를 SRS로', 'srs', '요구사항정의서(SRS)를 만들고 싶어. '],
    ['개발 Spec', '요구사항으로 설계서', 'spec', '개발 Spec 을 만들고 싶어. '],
    ['사용자 매뉴얼', '화면 캡처 · pptx', '', '사용자 매뉴얼을 만들고 싶어. '],
    ['CTS 관리대장', '요청 건 · xlsx', '', 'CTS 관리대장에 요청 건을 더하고 싶어. '],
    ['Role 정리', '메뉴 배정 · xlsx', '', 'Role(사용자 권한) 메뉴 배정을 정리하고 싶어. '],
    ['개발하기', 'Spec 승인된 건', 'dev', '새 기능을 개발하고 싶어. '],
    ['설정하기', '설정으로 처리할 건', 'config', '설정 건을 처리하고 싶어. '],
    ['ATC 지적 고치기', 'SAP 검사 결과', '', 'ATC 지적을 돌려서 고치고 싶어. '],
    ['작은 수정', '오타 · 설정 한 줄', 'fix', '작은 수정을 하고 싶어. '],
    ['잘 모르겠어', 'AI가 골라 줘', '', '']
  ];
  var CUSTOM_MODEL = '__custom__';
  var MODEL_NAME = /^claude-[a-z0-9][a-z0-9.\-]{0,62}(\[1m\])?$/;
  var MODEL_FALLBACK = [{ value: '', label: '기본값(Claude Code 설정을 따름)' }, { value: 'fable', label: 'Fable' }, { value: 'opus', label: 'Opus' }, { value: 'sonnet', label: 'Sonnet' }, { value: 'haiku', label: 'Haiku' }];
  var EFFORT_FALLBACK = [{ value: '', label: '기본값' }, { value: 'low', label: '낮음' }, { value: 'medium', label: '보통' }, { value: 'high', label: '높음' }, { value: 'xhigh', label: '아주 높음' }, { value: 'max', label: '최대' }];
  var modelInfo = null;
  function modelOptions() { return (modelInfo && modelInfo.options) || MODEL_FALLBACK; }
  function effortOptions() { return (modelInfo && modelInfo.effortOptions) || EFFORT_FALLBACK; }
  function permissionOptions() { return (modelInfo && modelInfo.permissionOptions) || PERMISSION_FALLBACK; }
  function permissionLabel(v) {
    var hit = permissionOptions().filter(function (o) { return o.value === v; })[0];
    return hit ? hit.label : v;
  }
  function permissionChoice() {
    if (draft.permission == null) {
      var saved = window.BH.read('bh-permission');
      draft.permission = saved != null && permissionOptions().some(function (o) { return o.value === saved; }) ? saved : '';
    }
    return draft.permission;
  }
  function effortLabel(o) { return o.value ? o.label + ' (' + o.value + ')' : o.label; }
  function customOk() { return MODEL_NAME.test(draft.customName.trim()); }
  function modelChoice() {
    if (draft.model == null) {
      var saved = window.BH.read('bh-model');
      var known = function (v) { return modelOptions().some(function (o) { return o.value === v; }); };
      if (saved != null && known(saved)) draft.model = saved;
      else if (saved != null && MODEL_NAME.test(saved)) { draft.model = ''; draft.modelCustom = true; draft.customName = saved; }
      else draft.model = (modelInfo && modelInfo.default) || '';
    }
    return draft.modelCustom ? draft.customName.trim() : draft.model;
  }
  function effortChoice() {
    if (draft.effort == null) {
      var saved = window.BH.read('bh-effort');
      var known = function (v) { return effortOptions().some(function (o) { return o.value === v; }); };
      draft.effort = saved != null && known(saved) ? saved : ((modelInfo && modelInfo.defaultEffort) || '');
    }
    return draft.effort;
  }
  function newView(root) {
    var step = 'write', aid = null, data = null, err = '', textErr = false;
    var recent = null, picking = false, custom = '', customMsg = '', customBusy = false;
    var browsing = false, dir = '', fsRows = null, fsErr = '', pollTimer = null, previewText = '', previewOpen = false, previewTimer = null;
    var starting = false, startedId = null, startErr = '', alive = true, browseBusy = false, modelErr = false, advOpen = false;
    var BL = window.BHLogic, ready = null, readyCwd = null, readySig = 'null';
    var recentTimer = null, recentTries = 0, intro = null;  // intro: 준비 안 된 폴더를 처음 골랐을 때 보이는 "프로젝트 준비" 안내가 가리키는 폴더
    if (firstPickFolder) {  // 첫 실행 02 에서 준비 안 된 폴더를 골라 왔다: 그 폴더로 바로 03(프로젝트 준비) 안내를 확인한다
      draft.cwd = firstPickFolder; draft.picked = null;
      var firstP = firstPickFolder; firstPickFolder = null;
      setTimeout(function () { if (alive) checkIntro(firstP); }, 0);
    }
    var tools = ui.toolsRow(function () { return { session: null, cwd: draft.cwd, onInsert: insertTool }; });
    var folderWarn = ui.folderNotice(), chooser = ui.flowChooser(), preview = ui.flowPreview();
    function insertTool(skill) {
      var field = document.getElementById('brief');
      if (!field) { tools.say('요청을 적는 화면에서 누르면 입력칸에 넣어 드려요.'); return; }
      var cmd = skillCommand(skillInfo || { plugin: DEFAULT_PLUGIN }, skill), rest = field.value.replace(/^\/\S*\s*/, '');
      setFieldValue(field, cmd + rest, cmd.length);
    }
    // 종류 버튼으로 고른 갈래를 AI 가 다르게 보면 사용자가 답할 때까지 갈래를 정하지 않는다(#668).
    function kindConflict() { return draft.flowUser ? null : BL.kindConflict(res().flow, draft.kindFlowId); }
    function effectiveFlow() {
      if (draft.flowUser) return draft.flowId;
      if (draft.kindFlowId) return kindConflict() ? null : draft.kindFlowId;
      var f = res().flow;
      return f && f.confident ? f.id : null;
    }
    // 시작할 수 없는 사유. 묻는 카드에 답하지 않았거나, 종류 버튼으로 개발을 골랐는데 Spec 이 없다고 확실할 때.
    function startBlock() {
      if (kindConflict()) return '위에서 AI 추천을 어떻게 할지 먼저 골라 줘.';
      if (draft.kindFlowId === 'dev' && effectiveFlow() === 'dev') return BL.devBlock('dev', ready) || '';
      return '';
    }
    function keepKind() {
      if (BL.devBlock(draft.kindFlowId, ready)) { draft.insist = true; draw(); return; }
      draft.flowId = draft.kindFlowId; draft.flowUser = true; draw(); schedulePreview();
    }

    function res() { return (data && data.result) || data || {}; }
    function candidates() { return listOf(res(), 'candidates').map(function (c) { return typeof c === 'string' ? { path: c } : c; }).filter(function (c) { return c && c.path; }); }
    function extraQs() { return listOf(res(), 'extraQuestions').map(function (q) { return typeof q === 'string' ? { question: q, options: [] } : q; }).filter(function (q) { return q && q.question && !q.flowChoice; }); }

    function loadModels() {
      if (modelInfo) return;
      api('GET', '/api/models').then(function (d) { modelInfo = d && Array.isArray(d.options) ? d : null; }, function () { modelInfo = null; }).then(function () { if (alive) draw(); });
    }
    function loadRecent() {
      api('GET', '/api/folders/recent').then(function (d) {
        recent = parseRecent(d);
        watchReady();
        return defaultFolder();
      }, function () { recent = []; return defaultFolder(); });
    }
    function parseRecent(d) { return listOf(d, 'folders').map(function (f) { return typeof f === 'string' ? { path: f } : f; }).filter(function (f) { return f && f.path; }); }
    // 서버가 폴더의 준비 여부를 아직 읽는 중(checking)이면 잠시 뒤 다시 묻는다. 값이 바뀐 때만 다시 그린다.
    function watchReady() {
      clearTimeout(recentTimer);
      if (!alive || recentTries >= 6 || !(recent || []).some(function (f) { return f.checking; })) return;
      recentTries++;
      recentTimer = setTimeout(function () {
        api('GET', '/api/folders/recent').then(function (d) {
          if (!alive) return;
          var next = parseRecent(d), sig = JSON.stringify(next);
          if (sig !== JSON.stringify(recent)) { recent = next; draw(); }
          watchReady();
        }, function () {});
      }, 1500);
    }
    /* 기본 폴더 순서: 세션 화면에서 왔으면 그 세션 폴더 → 콘솔에서 마지막으로 작업을 시작한 폴더(서버가 기억) → 없으면 기본값 없이 목록을 펼친다.
       다른 세션이 움직인 흔적으로는 정하지 않는다. */
    function defaultFolder() {
      var from = new URLSearchParams(location.search).get('from'), src = from ? sessions.get(from) : null;
      if (src && src.cwd) { draft.cwd = src.cwd; draft.picked = null; }
      if (from && !src) {  // 목록이 아직 안 왔으면 그 세션만 따로 읽는다
        return api('GET', '/api/sessions/' + encodeURIComponent(from)).then(function (s) { if (s && s.cwd) { draft.cwd = s.cwd; draft.picked = null; } }, function () {}).then(function () { return lastFolder(); });
      }
      if (draft.cwd) { draw(); return null; }
      return lastFolder();
    }
    function lastFolder() {
      if (draft.cwd) { if (alive) draw(); return null; }
      return api('GET', '/api/folders/last').then(function (d) { if (!draft.cwd && d && d.path) draft.cwd = d.path; }, function () {}).then(function () {
        // 기본 폴더가 없어도 목록을 처음부터 펼치지 않는다(시안 G-05 는 한 줄). "폴더를 골라 줘 [고르기]" 를 보이고,
        // 고르지 않고 작업 시작을 누르면 begin() 이 목록을 연다(#721). 다른 세션 흔적으로 정하지 않는 #669 기준은 그대로.
        if (alive) draw();
      });
    }

    /* 분석 상태 */
    function begin() {
      if (!draft.text.trim()) { textErr = true; draw(); return; }
      if (draft.modelCustom && !customOk()) { modelErr = true; draw(); return; }
      if (!draft.cwd) { picking = true; err = ''; draw(); return; }
      // 종류 버튼의 갈래는 AI 추천과 겹쳐 보기 전까지 사용자가 확정한 선택이 아니다(#668).
      step = 'analyzing'; err = ''; draft.kindFlowId = kindFlow() || ''; draft.flowId = null; draft.flowUser = false; draft.insist = false; draw();
      api('POST', '/api/new', { text: draft.text.trim(), cwd: draft.cwd, model: modelChoice(), effort: effortChoice() }).then(function (d) {
        aid = d && (d.id || d.analysisId); if (!aid) throw new ApiError(0, '분석을 시작하지 못했습니다.');
        history.replaceState(null, '', '/new?id=' + encodeURIComponent(aid));
        data = d; poll();
      }, function (e) { if (!alive) return; step = 'failed'; err = e.message; draw(); });
    }
    function norm(st) {
      st = String(st || '').toLowerCase();
      if (/^(ready|done|complete|completed|ok|success)$/.test(st)) return 'ready';
      if (/fail|error|cancel/.test(st)) return 'failed';
      return 'analyzing';
    }
    function poll() {
      clearTimeout(pollTimer);
      api('GET', '/api/new/' + encodeURIComponent(aid)).then(function (d) {
        if (!alive) return; data = d;
        var st = norm(d.status);
        if (st === 'ready') { enterReview(); }
        else if (st === 'failed') { step = 'failed'; err = d.error || d.message || '분석에 실패했습니다.'; draw(); }
        else pollTimer = setTimeout(poll, 1200);
      }, function (e) {
        if (!alive) return;
        if (e.status === 404) { step = 'failed'; err = '분석 기록을 찾을 수 없습니다. 콘솔이 다시 시작되었을 수 있습니다.'; draw(); }
        else if (e.status === 401) return;
        else pollTimer = setTimeout(poll, 2500);
      });
    }
    function enterReview() {
      if (!draft.picked) draft.picked = candidates().map(function (c) { return c.path; });
      step = 'review'; draw(); schedulePreview();
    }

    /* 미리보기 */
    function pickedAll() { return (draft.picked || []); }
    function answerMap() { var m = {}; Object.keys(draft.answers).forEach(function (k) { if ((draft.answers[k] || '').trim()) m[k] = draft.answers[k].trim(); }); return m; }
    function schedulePreview() {
      if (!previewOpen || !aid) return;
      clearTimeout(previewTimer);
      previewTimer = setTimeout(function () {
        var am = answerMap();
        api('GET', '/api/new/' + encodeURIComponent(aid) + '/preview' + qs({ picked: pickedAll(), note: draft.note.trim(), flow: effectiveFlow(), extraAnswers: Object.keys(am).length ? JSON.stringify(am) : '' })).then(function (d) {
          previewText = typeof d === 'string' ? d : (d && (d.text || d.message || d.preview)) || '';
          var pre = root.querySelector('[data-preview]'); if (pre) pre.textContent = previewText || '(내용이 없습니다)';
        }, function (e) { var pre = root.querySelector('[data-preview]'); if (pre) pre.textContent = '미리보기를 불러오지 못했습니다: ' + e.message; });
      }, 300);
    }

    function start() {
      starting = true; startErr = ''; draw();
      api('POST', '/api/new/' + encodeURIComponent(aid) + '/start', { picked: pickedAll(), extraAnswers: answerMap(), note: draft.note.trim(), model: modelChoice(), effort: effortChoice(), permission: permissionChoice(), flow: draft.flowUser || draft.kindFlowId ? effectiveFlow() : undefined }).then(function (d) {
        startedId = (d && (d.id || d.sessionId || (d.session && d.session.id))) || '';
        if (startedId) { mergeSession({ id: startedId }); }
        history.replaceState(null, '', '/new');
      }, function (e) { startErr = '시작하지 못했습니다: ' + e.message; }).then(function () { starting = false; draw(); });
    }

    /* 폴더 */
    function useFolder(p) { draft.cwd = p; draft.picked = null; picking = false; browsing = false; fsRows = null; dir = ''; customMsg = ''; intro = null; draw(); checkIntro(p); }
    // 고른 폴더가 준비 안 됨(no)이고 이 폴더로 안내를 본 적이 없으면 서버가 show 를 true 로 준다. 확인 못 함이면 안내하지 않는다.
    function checkIntro(p) {
      if (step !== 'write') return;
      api('GET', '/api/folders/intro' + qs({ path: p })).then(function (d) {
        if (!alive || draft.cwd !== p || step !== 'write' || !d || d.show !== true) return;
        intro = p; draw();
        if (mainEl) mainEl.scrollTop = 0;  // 목록을 내려서 골랐어도 안내 제목과 [만들기] 가 먼저 보이게
        window.scrollTo(0, 0);
        api('POST', '/api/folders/intro/seen', { path: p }).then(null, function (e) { console.debug('안내 표시를 남기지 못했습니다', e); });  // 보여 줬다고 서버에 남긴다(브라우저 저장소가 아니다)
      }, function () {});
    }
    function introDone(create) {
      intro = null;
      if (create) { draft.text = skillCommand(skillInfo || { plugin: DEFAULT_PLUGIN }, 'scaffold'); draft.kind = -1; begin(); }
      else draw();
    }
    function drawIntro(page) {
      var nm = baseName(draft.cwd) || draft.cwd;
      page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb accent', text: '1단계 · 프로젝트 준비' }), h('h1', { title: draft.cwd, text: nm + ' 준비하기' }), h('p', { class: 'line', text: '이 폴더엔 아직 하네스 구조가 없어' })));  // 전체 경로는 제목 title 로(시안 G-03 엔 경로 줄이 없다)
      var panel = h('section', { class: 'light newbox', 'data-folder-intro': '1' });
      panel.appendChild(h('div', { class: 'ask' },
        h('span', { class: 'eb', text: '네 차례' }),
        h('b', { text: '표준 구조를 만들까? 한 번만 하면 돼' }),
        h('span', { class: 'sub', text: '만들고 나면 GitHub에 올려서 팀 승인을 받아. 그다음부터 문서를 쓸 수 있어.' }),
        h('div', { class: 'acts' },
          h('button', { type: 'button', class: 'pill acc', 'data-intro-make': '1', text: '만들기', onClick: function () { introDone(true); } }),
          h('button', { type: 'button', class: 'pill line', 'data-intro-later': '1', text: '나중에', onClick: function () { introDone(false); } }))));
      // 시안 G-03: 두 칸(.grid3 > .lt) 안에 줄(이름 | 설명)
      panel.appendChild(h('div', { class: 'grid3' },
        h('div', { class: 'lt' }, h('span', { class: 'eb', text: '만들어지는 것' }), [['templates/', '고객 양식을 넣는 곳'], ['rules/', '문서 검사 기준'], ['docs/ssot/', '요구사항정의서 자리'], ['audit/', '변경 기록']].map(function (r) {
          return h('div', { class: 'srow2' }, h('span', { class: 'lm mono', text: r[0] }), h('span', { text: r[1] }));
        })),
        h('div', { class: 'lt' }, h('span', { class: 'eb', text: '만든 뒤 할 일' }), ['고객 양식 파일을 templates/ 에 넣기', 'GitHub에 올려서 승인받기', '첫 작업 시작'].map(function (t, i) {
          return h('div', { class: 'srow2' }, h('span', { class: 'lm', text: String(i + 1) }), h('span', { text: t }));
        }))));
      page.appendChild(panel);
    }
    function validateCustom() {
      var p = custom.trim(); if (!p) return;
      customBusy = true; customMsg = ''; draw();
      api('POST', '/api/folders/validate', { path: p }).then(function (d) {
        var ok = d && (d.ok === true || d.valid === true);
        if (ok) { custom = ''; useFolder(d.path || d.realpath || p); }
        else customMsg = (d && (d.error || d.reason || d.message)) || '이 폴더를 사용할 수 없습니다.';
      }, function (e) { customMsg = e.message; }).then(function () { customBusy = false; if (alive) draw(); });
    }
    function browseFolder() {
      if (browseBusy) return;
      browseBusy = true; customMsg = ''; draw();
      api('POST', '/api/folders/pick', { path: draft.cwd || '' }).then(function (d) {
        if (d && d.cancelled) return null;
        var p = d && d.path;
        if (!p) { customMsg = '고른 폴더를 받지 못했습니다. 경로를 직접 적어 주세요.'; return null; }
        return api('POST', '/api/folders/validate', { path: p }).then(function (v) {
          if (v && (v.ok === true || v.valid === true)) useFolder(v.path || v.realpath || p);
          else customMsg = (v && (v.error || v.reason || v.message)) || '이 폴더를 사용할 수 없습니다.';
        });
      }).then(null, function (e) { customMsg = e.message; }).then(function () { browseBusy = false; if (alive) draw(); });
    }
    function loadFs() {
      fsRows = null; fsErr = ''; draw();
      api('GET', '/api/fs' + qs({ root: draft.cwd, dir: dir })).then(function (d) {
        fsRows = listOf(d, 'entries').concat(!Array.isArray(d) && !(d && d.entries) ? listOf(d, 'items') : []);
        draw();
      }, function (e) { fsErr = e.message; fsRows = []; draw(); });
    }
    function togglePath(p) {
      var i = draft.picked.indexOf(p);
      if (i >= 0) draft.picked.splice(i, 1); else draft.picked.push(p);
      draw(); schedulePreview();
    }

    /* 그리기 */
    var TITLES = {
      write: ['새 작업', '무엇을 할까?', ''],  // 시안 G-05 는 제목 아래 설명 줄이 없다
      analyzing: ['새 작업 · 살펴보는 중', '요청과 폴더의 자료를 살펴보고 있어', '파일은 아직 고치지 않아.'],
      failed: ['새 작업 · 확인 못 함', '요청을 살펴보지 못했어', '아래 이유를 보고 요청을 고쳐서 다시 해 봐.'],
      review: ['새 작업 · 확인', '이렇게 진행할게', '시작 전에 한 번만 봐 줘']
    };
    // 개발 준비 상태(#668): 작업 폴더가 바뀔 때마다 한 번 읽는다. 읽지 못함·해당 없음이면 ready 는 null 이고 화면은 예전과 같다.
    function checkReady() {
      var cwd = draft.cwd;
      if (readyCwd === cwd) return;
      readyCwd = cwd; ready = null; readySig = 'null';
      if (!cwd) return;
      ui.devReadyFor(cwd).then(function (r) {
        if (!alive || cwd !== draft.cwd) return;
        var v = BL.devReadyView(r && r.ok ? r.data : null), sig = JSON.stringify(v);
        if (sig !== readySig) { readySig = sig; ready = v; draw(); }
      });
    }
    function draw() {
      if (!alive) return;
      checkReady();
      var keepFocus = document.activeElement && document.activeElement.id, selStart = document.activeElement && document.activeElement.selectionStart;
      clear(root);
      var page = h('div', { class: 'page sess newp' });
      if (intro && intro === draft.cwd && step === 'write') {
        drawIntro(page);
        root.appendChild(page);
        renderHead(location.pathname);
        return;
      }
      var t = TITLES[step] || TITLES.review;
      page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: step === 'write' ? 'eb' : 'eb accent', text: t[0] }), h('h1', { text: t[1] }), t[2] ? h('p', { class: 'line', text: t[2] }) : null));
      var panel = h('section', { class: 'light newbox' });
      if (step === 'write') drawWrite(panel);
      else if (step === 'analyzing') drawAnalyzing(panel);
      else if (step === 'failed') drawFailed(panel);
      else drawReview(panel);
      page.appendChild(panel);
      if (step === 'write' || step === 'review') { page.appendChild(tools.el); tools.update(); }
      root.appendChild(page);
      renderHead(location.pathname);  // 헤더의 프로젝트 이름이 지금 고른 작업 폴더를 따라가게
      if (keepFocus) { var f = document.getElementById(keepFocus); if (f && f !== document.activeElement) { f.focus(); try { if (selStart != null) f.setSelectionRange(selStart, selStart); } catch (e) { console.debug('커서 위치를 되돌리지 못했습니다', e); } } }
    }
    function folderBar(page) {
      // 시안 G-05: 작은 muted 한 줄 + 오른쪽 작업 시작 단추. 목록은 [바꾸기]·[고르기] 를 눌러야 펼친다(폴더 없이 작업 시작을 누를 때도 펼침).
      var bar = h('span', { class: 'folder-bar' },
        h('span', { class: 'k', text: '작업 폴더 · ' }), draft.cwd ? h('span', { class: 'v', title: draft.cwd, text: baseName(draft.cwd) || draft.cwd }) : h('span', { class: 'v none', text: recent === null ? '불러오는 중' : '폴더를 골라 줘' }),
        h('button', { type: 'button', class: 'pill line sm', 'data-folder-toggle': '', 'aria-expanded': String(picking), onClick: function () { picking = !picking; draw(); } }, picking ? '닫기' : (draft.cwd ? '바꾸기' : '고르기')));
      if (!picking) return bar;
      var box = h('div', { class: 'folder-pick' });
      (recent || []).forEach(function (f) {
        var nm = baseName(f.path) || f.path;
        box.appendChild(h('button', { type: 'button', class: 'folder-opt proj', 'aria-pressed': String(f.path === draft.cwd), onClick: function () { useFolder(f.path); } },
          h('span', { class: 'pi', 'aria-hidden': 'true', text: nm.replace(/[^A-Za-z0-9가-힣]/g, '').slice(0, 2).toUpperCase() || '··' }),
          h('span', { class: 'pn' }, h('b', { text: nm }), h('small', { class: 'mono', text: f.path }),
            f.ready === 'yes' && f.formsMissing === 'yes' ? h('small', { class: 'forms-hint', 'data-forms-missing': '1', title: BL.FORMS_MISSING_TEXT, text: BL.FORMS_MISSING_SHORT }) : null),
          (function () { var c = readyChip(f); return h('span', { class: ('chip2 ' + c.cls).trim(), 'data-ready': f.ready || 'unknown', text: c.text }); })()));
      });
      if (recent && !recent.length) box.appendChild(h('p', { class: 'note-muted', text: '최근에 쓴 폴더가 없어. 아래에 경로를 적어 줘.' }));
      box.appendChild(h('button', { type: 'button', class: 'folder-opt proj add', disabled: browseBusy, onClick: browseFolder },  // 시안 G-02: 점선 "다른 폴더 찾아보기" 줄
        h('span', { class: 'pi', 'aria-hidden': 'true', text: '+' }), h('span', { class: 'pn' }, h('span', { text: browseBusy ? '창 여는 중' : '다른 폴더 찾아보기' }))));
      box.appendChild(h('label', { for: 'custom', class: 'field-label', text: '다른 폴더 경로' }));
      box.appendChild(h('div', { class: 'inline-row' },
        h('input', { id: 'custom', class: 'input', value: custom, placeholder: 'C:\\Work\\project  또는  /Users/me/project', autocomplete: 'off', onInput: function (e) { custom = e.target.value; }, onKeydown: function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); validateCustom(); } } }),
        h('button', { type: 'button', class: 'pill line sm', disabled: customBusy, text: customBusy ? '확인 중' : '사용', onClick: validateCustom })));
      if (browseBusy) box.appendChild(h('p', { class: 'note-muted', role: 'status', text: '폴더 선택 창을 열었어. 창이 보이지 않으면 작업 표시줄을 확인해 줘. 고르면 이 화면에 자동으로 적용돼.' }));
      box.appendChild(h('p', { class: 'note-attn', role: 'alert', text: customMsg, hidden: !customMsg }));
      page.appendChild(box);
      return bar;
    }
    // 종류 버튼은 입력칸에 문장을 미리 넣고, 갈래가 있는 종류는 그 갈래로 시작하겠다고 정해 둔다(분석 결과보다 먼저 고른 사람의 선택).
    function pickKind(i) {
      var prev = KINDS[draft.kind], k = KINDS[i], same = draft.kind === i;
      var prefilled = !draft.text.trim() || (prev && draft.text.trim() === prev[3].trim());
      draft.kind = same ? -1 : i; draft.insist = false;
      if (prefilled) draft.text = same ? '' : k[3];
      draw();
      var f = document.getElementById('brief');
      if (f) { f.focus(); try { f.setSelectionRange(f.value.length, f.value.length); } catch (e) { console.debug('커서 위치를 되돌리지 못했습니다', e); } }
    }
    function kindFlow() { var k = KINDS[draft.kind]; return k ? k[2] : ''; }
    function drawWrite(panel) {
      panel.appendChild(h('div', { class: 'kinds', role: 'group', 'aria-label': '하고 싶은 일의 종류' }, KINDS.map(function (k, i) {
        var hint = BL.kindHint(k[2], ready);  // 판정 대상이 아니거나 확인 못 하면 null 이라 예전 그대로
        return h('button', { type: 'button', class: 'kind' + (hint ? ' ' + hint.tone : ''), 'data-kind': k[0], 'aria-pressed': String(draft.kind === i), onClick: function () { pickKind(i); } },
          h('b', { text: k[0] }), h('small', { text: k[1] }), hint ? h('small', { class: 'khint', 'data-hint': k[2], text: hint.text }) : null);
      })));
      // 개발하기를 눌렀는데 Spec 있는 건이 없다고 확실하면 분석 전에 바로 알린다.
      if (kindFlow() === 'dev' && BL.devBlock('dev', ready)) {
        var specIdx = KINDS.map(function (k) { return k[2]; }).indexOf('spec');
        panel.appendChild(ui.askCard({
          id: 'dev-nospec', label: '개발 시작 확인',
          lead: ['Spec 있는 개발 건이 아직 없어. 개발은 ', h('b', { text: '개발 Spec' }), ' 이 승인돼 있어야 시작할 수 있어.'],
          block: draft.insist ? BL.devBlock('dev', ready) : '',
          switchText: '개발 Spec 으로 바꾸기 (추천)', keepText: '그래도 개발하기',
          onSwitch: function () { pickKind(specIdx); }, onKeep: function () { draft.insist = true; draw(); }
        }));
      }
      panel.appendChild(h('label', { for: 'brief', class: 'field-label', text: '하고 싶은 일을 한두 줄로' }));
      var brief = h('textarea', { id: 'brief', class: 'textarea', rows: '3', value: draft.text, placeholder: '예: 구매요청을 올리면 팀장에게 승인 메일이 가면 좋겠어  (/ 로 스킬, @ 로 파일)',
        onInput: function (e) { draft.text = e.target.value; if (textErr) { textErr = false; var m = root.querySelector('[data-terr]'); if (m) m.hidden = true; } } });
      panel.appendChild(withAssist(brief, function () { return draft.cwd; }).wrap);
      panel.appendChild(h('p', { class: 'note-attn', 'data-terr': '1', role: 'alert', text: '어떤 일인지 한 줄이라도 적어 줘.', hidden: !textErr }));
      panel.appendChild(h('div', { class: 'refbox' },
        h('span', { text: '참고 파일(회의록 · 고객 메일 · 기존 양식)은 입력칸에 @ 를 치면 작업 폴더에서 골라 넣을 수 있어.' }),
        h('button', { type: 'button', class: 'pill line sm', text: '@ 로 파일 넣기', onClick: function () {
          var f = document.getElementById('brief'); if (!f) return;
          var v = f.value + (f.value && !/\s$/.test(f.value) ? ' ' : '') + '@';
          setFieldValue(f, v, v.length);
        } })));
      panel.appendChild(h('span', { class: 'eb', text: '이렇게 진행돼' }));
      panel.appendChild(preview.el);
      var k = KINDS[draft.kind];
      preview.update({ cwd: draft.cwd, flowId: kindFlow(), note: !k ? '어떤 순서로 할지는 AI가 요청을 읽은 다음 알려 줘. 위에서 종류를 고르면 그 순서를 미리 볼 수 있어.' : '이 종류는 정해진 순서 없이 그 도구 스킬로 바로 시작해.' });
      var folderLine = folderBar(panel);
      panel.appendChild(folderWarn.el);
      folderWarn.update(draft.cwd, window.BHLogic.otherSessions(draft.cwd, Array.from(sessions.values()), null).length > 0, useFolder);
      modelChoice(); effortChoice(); permissionChoice();
      var adv = h('details', { class: 'more', open: advOpen, onToggle: function (e) { advOpen = e.target.open; } }, h('summary', { text: '고급 설정 (모델 · 생각 깊이 · 권한)' }));
      adv.appendChild(h('div', { class: 'field-pair' },
        h('div', { class: 'field' },
          h('label', { for: 'model', class: 'field-label', text: '모델' }),
          h('select', { id: 'model', class: 'input', onChange: function (e) {
            if (e.target.value === CUSTOM_MODEL) { draft.modelCustom = true; modelErr = false; }
            else { draft.modelCustom = false; draft.model = e.target.value; window.BH.write('bh-model', draft.model); }
            draw();
          } },
          modelOptions().map(function (o) { return h('option', { value: o.value, selected: !draft.modelCustom && o.value === draft.model, text: o.label }); })
            .concat([h('option', { value: CUSTOM_MODEL, selected: draft.modelCustom, text: '정식 이름 직접 입력' })]))),
        h('div', { class: 'field' },
          h('label', { for: 'effort', class: 'field-label', text: '에포트' }),
          h('select', { id: 'effort', class: 'input', onChange: function (e) { draft.effort = e.target.value; window.BH.write('bh-effort', draft.effort); } },
            effortOptions().map(function (o) { return h('option', { value: o.value, selected: o.value === draft.effort, text: effortLabel(o) }); })))));
      if (draft.modelCustom) {
        adv.appendChild(h('label', { for: 'model-custom', class: 'field-label', text: '모델 정식 이름' }));
        adv.appendChild(h('input', { id: 'model-custom', class: 'input', type: 'text', value: draft.customName, placeholder: '예: claude-opus-4-1', autocomplete: 'off', spellcheck: 'false',
          onInput: function (e) { draft.customName = e.target.value; modelErr = false; var m = root.querySelector('[data-merr]'); if (m) m.hidden = true; if (customOk()) window.BH.write('bh-model', draft.customName.trim()); } }));
        adv.appendChild(h('p', { class: 'note-attn', 'data-merr': '1', role: 'alert', text: '이름은 claude- 로 시작하고 영문 소문자, 숫자, 점, 하이픈만 쓸 수 있어.', hidden: !modelErr }));
      }
      adv.appendChild(h('div', { class: 'field-pair' },
        h('div', { class: 'field' },
          h('label', { for: 'permission', class: 'field-label', text: '권한 모드' }),
          h('select', { id: 'permission', class: 'input', onChange: function (e) { draft.permission = e.target.value; window.BH.write('bh-permission', draft.permission); } },
            permissionOptions().map(function (o) { return h('option', { value: o.value, selected: o.value === draft.permission, text: o.label }); })))));
      adv.appendChild(h('p', { class: 'note-muted', text: '요청을 살펴볼 때와 작업을 진행할 때 같은 모델과 에포트(생각의 깊이)를 써. 권한 모드는 작업을 진행하는 Claude Code 세션에만 적용돼.' }));
      panel.appendChild(adv);
      panel.appendChild(h('div', { class: 'bottom' }, folderLine, h('span', { class: 'sp' }),
        h('button', { type: 'button', class: 'pill dark big', text: '작업 시작', onClick: begin })));
      if (startedId !== null) panel.appendChild(h('div', { class: 'started', role: 'status' }, h('span', { text: '이전 작업을 시작했어.' }), link(startedId ? '/s/' + encodeURIComponent(startedId) : '/', { text: '작업 화면으로 이동' })));
    }
    function drawAnalyzing(panel) {
      panel.appendChild(h('p', { class: 'quiet', text: '필요한 자료를 고르면 확인을 요청할게.' }));
      panel.appendChild(h('div', { class: 'progress', role: 'status', 'aria-label': '분석 중' }, h('i')));
      panel.appendChild(h('div', { class: 'acts' }, h('button', { type: 'button', class: 'pill line sm', text: '요청 고치기', onClick: function () { clearTimeout(pollTimer); aid = null; step = 'write'; history.replaceState(null, '', '/new'); draw(); } })));
    }
    function drawFailed(panel) {
      panel.appendChild(h('div', { class: 'bad' }, h('span', { class: 'tagx', text: '확인 못 함' }), h('b', { class: 'bt', text: 'Claude Code가 요청을 살펴보지 못했어' }), h('span', { class: 'sm', text: err || '알 수 없는 오류야.' })));
      panel.appendChild(h('div', { class: 'acts end' },
        h('button', { type: 'button', class: 'pill line', text: '요청 고치기', onClick: function () { step = 'write'; history.replaceState(null, '', '/new'); draw(); } }),
        h('button', { type: 'button', class: 'pill dark', text: '다시 시도', onClick: begin })));
    }
    function drawReview(panel) {
      var msgs = h('div', { class: 'msgs' });
      if (draft.text.trim()) msgs.appendChild(h('div', { class: 'me', text: draft.text.trim() }));
      if (res().understood) msgs.appendChild(h('div', { class: 'ai' }, h('span', { class: 'eb', text: 'AI' }), res().understood));
      panel.appendChild(msgs);
      panel.appendChild(chooser.el);
      var kd = KINDS[draft.kind];
      chooser.update({ cwd: draft.cwd, found: res().flow, selected: effectiveFlow(), userPicked: draft.flowUser || (!!draft.kindFlowId && !kindConflict()),
        kindFlowId: draft.kindFlowId, kindName: kd && kd[2] === draft.kindFlowId ? '그래도 ' + kd[0] : '', ready: ready, insist: draft.insist,
        onPick: function (fid) { draft.flowId = fid; draft.flowUser = true; draw(); schedulePreview(); }, onKeep: keepKind });

      var cands = candidates(), cp = cands.map(function (c) { return c.path; });
      var sec = h('div', { class: 'lt' });
      sec.appendChild(h('span', { class: 'eb', text: 'AI가 읽을 자료 · ' + draft.picked.length + '개 선택' }));
      var ul = h('ul', { class: 'cand' });
      cands.forEach(function (c) {
        var on = draft.picked.indexOf(c.path) >= 0;
        ul.appendChild(h('li', null, h('label', null,
          h('input', { type: 'checkbox', checked: on, onChange: function () { togglePath(c.path); } }),
          h('span', { style: null }, h('span', { class: 'nm', text: baseName(c.path) }), c.reason ? h('span', { class: 'rs', text: c.reason }) : null, h('span', { class: 'pt', text: c.path })))));
      });
      sec.appendChild(ul);
      (res().excluded || []).forEach(function (x) {
        sec.appendChild(h('div', { class: 'cand-extra' }, h('span', { class: 'wrap-any' }, h('b', { text: '제외됨' }), h('span', { class: 'mono', text: String(x.path) }), h('span', { class: 'sub', text: ' ' + String(x.reason) }))));
      });
      if (!cands.length) sec.appendChild(h('p', { class: 'empty-line', text: '이 폴더에서 관련 자료를 찾지 못했어. 직접 고르거나 그대로 진행할 수 있어.' }));
      draft.picked.filter(function (p) { return cp.indexOf(p) < 0; }).forEach(function (p) {
        sec.appendChild(h('div', { class: 'cand-extra' }, h('span', { class: 'wrap-any' }, h('b', { text: '직접 추가' }), h('span', { class: 'mono', text: p })),
          h('button', { type: 'button', class: 'iconbtn', 'aria-label': p + ' 빼기', onClick: function () { togglePath(p); } }, icon('close', 14))));
      });
      sec.appendChild(h('div', { class: 'cand-extra' }, h('button', { type: 'button', class: 'pill line sm', 'aria-expanded': String(browsing), text: browsing ? '폴더 닫기' : '다른 자료 직접 고르기', onClick: function () { browsing = !browsing; if (browsing) loadFs(); else draw(); } })));
      if (browsing) sec.appendChild(drawBrowser());

      var qsec = h('div', { class: 'lt' }, h('span', { class: 'eb', text: 'AI가 물어볼 것 (미리 알려 줘도 돼)' }));
      extraQs().forEach(function (q, i) {
        var id = 'xq' + i, opts = (q.options || []).map(function (o) { return typeof o === 'string' ? o : o.label; });
        qsec.appendChild(h('label', { for: id, class: 'sect-h' + (i ? ' mt-24' : ''), text: q.question }));
        if (opts.length) qsec.appendChild(h('div', { class: 'chips', role: 'group', 'aria-label': q.question }, opts.map(function (o) {
          return h('button', { type: 'button', class: 'chip', 'aria-pressed': String(draft.answers[q.question] === o), text: o, onClick: function () { draft.answers[q.question] = draft.answers[q.question] === o ? '' : o; draw(); schedulePreview(); } });
        })));
        qsec.appendChild(h('input', { id: id, class: 'input' + (opts.length ? ' mt-16' : ''), value: draft.answers[q.question] || '', placeholder: opts.length ? '직접 입력' : '몰라도 괜찮아. 비워 두면 Claude Code가 다시 물어.', autocomplete: 'off',
          onInput: function (e) { draft.answers[q.question] = e.target.value; schedulePreview(); }, onChange: function () { if (opts.length) draw(); } }));
      });
      qsec.appendChild(h('label', { for: 'note', class: 'field-label', text: '그 밖에 알아 두면 좋은 내용이 있어?' }));
      qsec.appendChild(h('textarea', { id: 'note', class: 'textarea', rows: '3', value: draft.note, placeholder: '선택 사항', onInput: function (e) { draft.note = e.target.value; schedulePreview(); } }));
      panel.appendChild(h('div', { class: 'grid3' }, sec, qsec));

      panel.appendChild(h('details', { class: 'more', open: previewOpen, onToggle: function (e) { previewOpen = e.target.open; if (previewOpen) schedulePreview(); } }, h('summary', { text: '세션에 보낼 내용 보기' }),
        h('pre', { class: 'box', 'data-preview': '1', text: previewText || '불러오는 중이야.' })));

      if (startedId === null) {
        if (startErr) panel.appendChild(h('p', { class: 'note-attn', role: 'alert', text: startErr }));
        panel.appendChild(h('div', { class: 'acts end' },
          h('button', { type: 'button', class: 'pill line', text: '다른 걸로 할래', onClick: function () { clearTimeout(pollTimer); step = 'write'; aid = null; history.replaceState(null, '', '/new'); draw(); } }),
          startBlock() ? h('span', { class: 'note-attn', role: 'status', text: startBlock() }) : null,
          h('button', { type: 'button', class: 'pill dark big', disabled: starting || !!startBlock(), text: starting ? '시작하는 중' : '이대로 시작', onClick: start })));
      } else {
        panel.appendChild(h('div', { class: 'started', role: 'status' }, h('span', { text: '작업을 시작했어.' }), link(startedId ? '/s/' + encodeURIComponent(startedId) : '/', { text: '작업 화면으로 이동' })));
      }
    }
    function drawBrowser() {
      var box = h('div', { class: 'browser' });
      var root0 = baseName(draft.cwd) || draft.cwd;
      box.appendChild(h('div', { class: 'browser-bar' },
        dir ? h('button', { type: 'button', class: 'iconbtn', 'aria-label': '상위 폴더', onClick: function () { dir = dir.indexOf('/') >= 0 ? dir.slice(0, dir.lastIndexOf('/')) : ''; loadFs(); } }, icon('back', 15)) : null,
        h('span', { text: root0 + (dir ? '/' + dir : '') })));
      if (fsRows === null) { box.appendChild(h('p', { class: 'msg', role: 'status', text: '불러오는 중입니다.' })); return box; }
      if (fsErr) box.appendChild(h('p', { class: 'msg', role: 'alert', text: '폴더를 열지 못했습니다: ' + fsErr }));
      var ul = h('ul');
      fsRows.forEach(function (r) {
        var name = r.name, isDir = /^(dir|directory|folder|d)$/i.test(String(r.kind || r.type || '')) || r.isDir === true, p = (dir ? dir + '/' : '') + name;
        if (isDir) ul.appendChild(h('li', null, h('button', { type: 'button', class: 'ent', onClick: function () { dir = p; loadFs(); } }, icon('folder', 16), h('span', { class: 'nm', text: name }))));
        else ul.appendChild(h('li', null, h('label', { class: 'ent' }, h('input', { type: 'checkbox', checked: draft.picked.indexOf(p) >= 0, onChange: function () { togglePath(p); } }), h('span', { class: 'nm', text: name }), h('span', { class: 'sz', text: fmtSize(r.size) }))));
      });
      box.appendChild(ul);
      if (!fsRows.length && !fsErr) box.appendChild(h('p', { class: 'msg', text: '이 폴더에는 파일이 없습니다.' }));
      return box;
    }

    // 주소에 분석 id 가 있으면 이어서 본다.
    var resume = new URLSearchParams(location.search).get('id');
    if (resume) {
      aid = resume; step = 'analyzing'; draw();
      api('GET', '/api/new/' + encodeURIComponent(aid)).then(function (d) {
        data = d; if (d.cwd) draft.cwd = d.cwd; if (d.text && !draft.text) draft.text = d.text;
        var st = norm(d.status);
        if (st === 'ready') enterReview(); else if (st === 'failed') { step = 'failed'; err = d.error || d.message || '분석에 실패했습니다.'; draw(); } else poll();
        loadRecent();
      }, function () { aid = null; step = 'write'; history.replaceState(null, '', '/new'); draw(); loadRecent(); loadModels(); });
    } else { draw(); loadRecent(); loadModels(); }
    return {
      title: function () { return '새 작업'; },
      destroy: function () { alive = false; clearTimeout(pollTimer); clearTimeout(recentTimer); clearTimeout(previewTimer); tools.destroy(); folderWarn.destroy(); chooser.destroy(); preview.destroy(); if (startedId !== null) draft = { text: '', cwd: draft.cwd, note: '', answers: {}, picked: null, extraPaths: [], kind: -1 }; }
    };
  }

  /* ---------- 설정 ---------- */
  /* 시안 19: 글자 크기 · AI가 묻는 범위 · 알림(스위치 셋, 서버 notify.json) · 연결 상태 · 고급. 화면 밝기(다크 한 벌뿐)는 넣지 않았다. */
  function settingsView(root) {
    var alive = true, conn = { gh: '불러오는 중이야', ver: '불러오는 중이야', proj: '불러오는 중이야' };
    function set(label, body) {
      return h('div', { class: 'set' }, h('span', { class: 'eb', text: label }), h('div', { class: 'sc' }, body));
    }
    function crow(k, v) { return h('div', { class: 'srow2' }, h('span', { class: 'lm', text: k }), h('span', { text: v })); }
    function cwdNow() { return (sortedSessions().filter(function (x) { return x.status !== 'ended'; })[0] || sortedSessions()[0] || {}).cwd; }
    var lastCwd;
    // 확인할 폴더는 세션 목록이 온 뒤에 정해진다. 목록이 오거나 첫 세션의 폴더가 바뀌면 다시 읽는다.
    function loadConn(first) {
      var cwd = cwdNow();
      if (first) api('GET', '/api/health').then(function (d) { conn.ver = d && d.version ? d.version + ' (이 콘솔이 실린 판)' : '확인 못 함'; },
        function (e) { conn.ver = '확인 못 함 · ' + e.message; }).then(paintConn);
      if (!cwd && !loadedOnce) return;
      lastCwd = cwd || '';
      if (!cwd) { conn.gh = '확인 못 함 · 확인할 작업 폴더(세션)가 없어'; conn.proj = '확인 못 함 · 확인할 작업 폴더(세션)가 없어'; paintConn(); return; }
      ui.approvalsFor(cwd).then(function (r) {
        var d = r.ok ? r.data : null;
        conn.gh = !r.ok ? '확인 못 함 · ' + (r.error && r.error.message || '읽지 못했어')
          : d && d.state === 'unknown' ? '확인 못 함 · ' + (d.reason || 'gh 로 읽지 못했어')
          : d && d.loading ? '확인하는 중이야' : '연결돼 있어 (gh 로 PR 정보를 읽었어)';
      }).then(paintConn);
      ui.flowsFor(cwd).then(function (r) {
        var c = r.ok && r.data && r.data.conditions && r.data.conditions['project-ready'], name = folderLabel(cwd);
        conn.proj = name + ' · ' + (!c ? '준비 여부 확인 못 함' : c.state === 'yes' ? '준비됨' : c.state === 'no' ? '준비 안 됨(templates/ · rules/ 없음)' : '준비 여부 확인 못 함');
      }).then(paintConn);
    }
    function paintConn() { if (alive) draw(); }
    var notifyErr = '';
    function saveNotify(key, val) {
      var body = {}; body[key] = val;
      api('PUT', '/api/settings/notify', body).then(function (d) { notifyCfg = d; notifyErr = ''; },
        function (e) { notifyErr = '알림 설정을 저장하지 못했어 · ' + (e && e.message || ''); }).then(function () { if (alive) draw(); });
    }
    var askErr = '';
    function saveAsk(level) {
      api('PUT', '/api/settings/ask', { level: level }).then(function (d) { askCfg = d; askErr = ''; },
        function (e) { askErr = '묻는 범위를 저장하지 못했어 · ' + (e && e.message || ''); }).then(function () { if (alive) draw(); });
    }
    // 처음 켤 때만 브라우저에 권한을 묻는다. 사용자 클릭 안에서 바로 불러야 브라우저가 물어 준다.
    function toggleNotify(key, want) {
      notifyErr = '';
      if (!want) return saveNotify(key, false);
      var p = notifyPerm();
      if (p === 'granted') return saveNotify(key, true);
      if (p !== 'default') return draw();  // 막힘·미지원은 안내 문구가 이미 보인다. 켠 채로 두지 않는다
      Promise.resolve(window.Notification.requestPermission()).then(function (r) {
        if (r === 'granted') saveNotify(key, true); else if (alive) draw();
      });
    }
    function loadModelsOnce() {
      if (modelInfo) return;
      api('GET', '/api/models').then(function (d) { modelInfo = d && Array.isArray(d.options) ? d : null; }, function () { modelInfo = null; }).then(function () { if (alive && modelInfo) draw(); });
    }
    function draw() {
      clear(root);
      var BH = window.BH, scale = BH.getScale();
      var page = h('div', { class: 'page' });
      page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '설정' }), h('h1', { text: '보기와 알림' })));
      var sec = h('section', { class: 'light setbox' });

      var seg = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': '글자 크기' }, BH.SCALES.map(function (z) {
        return h('button', { type: 'button', role: 'radio', class: 'scale', 'aria-checked': String(z[1] === scale), text: z[0], onClick: function () { BH.setScale(z[1]); draw(); } });
      }));
      sec.appendChild(set('글자 크기', seg));

      /* 시안 19 "AI가 묻는 범위": 서버 ask.json 과 이어진다. 읽기 전(askCfg 없음)에는 고르지 못한다. */
      var askNow = askCfg && askCfg.level;
      var askRadios = h('div', { class: 'radios', role: 'radiogroup', 'aria-label': 'AI가 묻는 범위' }, ASK_OPTIONS.map(function (o) {
        var on = o.value === askNow;
        return h('button', { type: 'button', role: 'radio', class: 'radio', 'aria-checked': String(on), 'data-ask-opt': o.value, disabled: !askCfg,
          onClick: function () { saveAsk(o.value); } },
          h('i', { class: 'rd' + (on ? ' on' : ''), 'aria-hidden': 'true' }), h('span', null, h('b', { text: o.label }), o.desc ? h('small', { text: o.desc }) : null));
      }));
      sec.appendChild(set('AI가 묻는 범위', h('div', null, askRadios,
        askErr ? h('p', { class: 'note-attn', role: 'alert', text: askErr }) : null,
        askCfg && askCfg.problem ? h('p', { class: 'note-attn', role: 'alert', 'data-ask-problem': '1', text: askCfg.problem }) : null,
        h('p', { class: 'note-muted', 'data-ask-note': '1', text: '어떤 걸 골라도 위험한 일(main에 바로 올리기 · 강제 덮어쓰기 · SAP 운영 쓰기)은 하네스가 막아. 지우기 · GitHub에 올리기 · 작업 폴더 밖 쓰기처럼 되돌릴 수 없는 일은 항상 물어.' }))));

      // 시안 G-19: 설정엔 "AI가 묻는 범위" 하나만 둔다. 권한 모드(계획만 세우기 · 알아서 하되 위험한 건 AI가 막기 포함)는
      // 일마다 고르는 것이라 새 작업 "고급 설정" 의 권한 모드에서 고르고, 고른 값은 다음 새 작업에도 기억한다(bh-permission).

      var perm = notifyPerm(), rows = [['turn', '내 차례가 오면'], ['blocked', '막히거나 확인 못 한 일이 생기면'], ['done', 'AI가 일을 끝낼 때마다']];
      var permText = perm === 'unsupported' ? '이 브라우저는 알림을 지원하지 않아'
        : perm === 'granted' ? '브라우저 알림 · 허용됨'
        : perm === 'denied' ? '브라우저 알림 · 막힘'
        : '브라우저 알림 · 아직 안 물음 (스위치를 처음 켤 때 브라우저가 물어)';
      sec.appendChild(set('알림', h('div', null,
        h('div', { class: 'stack', role: 'group', 'aria-label': '알림' }, rows.map(function (r) {
          var on = !!(notifyCfg && notifyCfg[r[0]]) && perm === 'granted';
          return h('button', { type: 'button', role: 'switch', class: 'swrow', 'aria-checked': String(on), 'data-notify-key': r[0], disabled: !notifyCfg || perm === 'unsupported',
            onClick: function () { toggleNotify(r[0], !on); } },
            h('i', { class: 'sw' + (on ? ' on' : ''), 'aria-hidden': 'true' }), h('b', { text: r[1] }));
        })),
        h('p', { class: 'note-muted', 'data-notify-perm': perm, role: 'status', text: permText }),
        perm === 'denied' ? h('p', { class: 'note-attn', role: 'alert', text: '브라우저가 알림을 막았어 · 주소창 왼쪽 자물쇠에서 알림을 허용해 줘' }) : null,
        notifyErr ? h('p', { class: 'note-attn', role: 'alert', text: notifyErr }) : null,
        h('p', { class: 'note-muted', text: '콘솔 탭이 열려 있을 때만 알려 줘. 지금 보고 있는 화면에서는 보내지 않아.' }))));

      sec.appendChild(set('연결 상태', h('div', null, crow('GitHub', conn.gh), crow('하네스 판', conn.ver), crow('프로젝트', conn.proj))));

      sec.appendChild(set('처음 화면', h('div', null,
        h('button', { type: 'button', class: 'pill line', 'data-intro-again': '1', text: '처음 화면 다시 보기', onClick: function () { introForce = true; introSkip = false; introPage = 'welcome'; if (!startData) startData = { firstRun: false, blocking: false, checks: [] }; renderRoute(); loadStart(false); } }),
        h('p', { class: 'note-muted', text: '시작할 때 한 번 보이는 환영 화면과 자동 점검을 다시 봐.' }))));

      var model = modelChoice(), effort = effortChoice();
      var ml = (modelOptions().filter(function (o) { return o.value === model; })[0] || {}).label || model || '기본값';
      var el = (effortOptions().filter(function (o) { return o.value === effort; })[0] || {}).label || effort || '기본값';
      sec.appendChild(set('고급', h('details', { class: 'more' }, h('summary', { text: 'AI 모델 · 생각 깊이 · 기술 정보' }),
        crow('AI 모델', ml), crow('생각 깊이', el),
        h('p', { class: 'note-muted', text: '모델과 생각 깊이는 새 작업 화면의 "고급 설정" 에서 바꿔.' }))));
      page.appendChild(sec);
      root.appendChild(page);
    }
    function again() { if (alive && loadedOnce && (cwdNow() || '') !== lastCwd) loadConn(false); }
    api('GET', '/api/settings/notify').then(function (d) { notifyCfg = d; }, function (e) { notifyErr = '알림 설정을 읽지 못했어 · ' + (e && e.message || ''); }).then(function () { if (alive) draw(); });
    api('GET', '/api/settings/ask').then(function (d) { askCfg = d; }, function (e) { askErr = '묻는 범위를 읽지 못했어 · ' + (e && e.message || ''); }).then(function () { if (alive) draw(); });
    setTitle('설정'); loadModelsOnce(); loadConn(true); draw();
    return { onData: again, onSession: again, destroy: function () { alive = false; } };
  }

  /* ---------- 시작 ---------- */
  function boot() {
    var root = document.getElementById('root');
    appEl = h('div', { id: 'app', 'data-collapsed': 'false' });
    sideEl = h('aside', { class: 'side' });
    mainEl = h('main', { class: 'main', id: 'main' });
    annEl = h('div', { class: 'ann-slot' });
    headEl = h('header', { class: 'top' });
    appEl.appendChild(annEl); appEl.appendChild(headEl);
    appEl.appendChild(h('div', { class: 'shell' }, sideEl, mainEl));
    root.appendChild(appEl);
    // 점검 결과(첫 실행인지)가 오면 그 화면으로 처음부터 그린다. 늦거나 못 읽으면 홈을 막지 않고 그대로 그린다.
    var first = function () { if (!renderedOnce) renderRoute(); };
    var wn = function () { if (!(startData && startData.firstRun)) loadWhatsNew(); };  // 첫 실행 화면이 뜨는 동안엔 바뀐 점을 띄우지 않는다
    loadStart(false).then(function () { first(); wn(); }, function () { first(); wn(); });
    setTimeout(first, 1200);
    loadSessions().then(function () { connectEvents(); }, function (e) { if (e.status !== 401) { connectEvents(); scheduleRetryIfDown(); } });
    if (window.ResizeObserver) new ResizeObserver(function () { if (collapsed === null) scheduleSide(); }).observe(root);
  }
  function scheduleRetryIfDown() { if (conn.state === 'down') scheduleRetry(); }
  boot();
})();
