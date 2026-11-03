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

  function mergeSession(s) {
    if (!s || !s.id) return null;
    var old = sessions.get(s.id) || {};
    var m = Object.assign({}, old, s);
    sessions.set(s.id, m);
    (m.pendingRequestIds || []).forEach(ensureRequest);
    return m;
  }
  function ensureRequest(rid) {
    if (requests.has(rid) || reqFetching[rid]) return;
    reqFetching[rid] = true;
    api('GET', '/api/requests/' + encodeURIComponent(rid)).then(function (r) {
      if (r) { r = r.request || r; if (!r.id) r.id = rid; requests.set(rid, r); scheduleSide(); }
    }, function () {}).then(function () { delete reqFetching[rid]; });
  }
  var sessTimers = {};
  function refreshSession(id) {
    clearTimeout(sessTimers[id]);
    sessTimers[id] = setTimeout(function () {
      api('GET', '/api/sessions/' + encodeURIComponent(id)).then(function (d) {
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
    if (document.hidden) { eventsPaused = true; return; }  // 숨겨진 탭은 붙지 않는다(보이면 붙는다)
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
    clear(mainEl);
    mainEl.scrollTop = 0; window.scrollTo(0, 0);
    var root = h('div');
    mainEl.appendChild(connBanner());
    mainEl.appendChild(root);
    var v = ({ home: homeView, session: sessionView, request: requestView, 'new': newView, settings: settingsView, missing: missingView })[route.name](root);
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
            todo.push({ href: '/r/' + encodeURIComponent(rid), verb: !r ? '요청 확인하기' : kindOf(r) === 'question' ? '답하기' : '승인하기', title: requestTitle(r), sub: title, t: s.updatedAt });
          });
        } else {
          todo.push({ href: '/s/' + encodeURIComponent(s.id), verb: s.askedInText ? '답하기(추정)' : s.turnSkill ? skillLabel(s.turnSkill) : '확인하기', title: title, sub: sub, t: s.updatedAt });
        }
      } else if (g === 'running') {
        run.push({ href: '/s/' + encodeURIComponent(s.id), title: title, sub: (s.currentAction || (s.currentSkill ? skillLabel(s.currentSkill) : '작업 중')) + subagentSummary(s), t: s.updatedAt });
      } else {
        idle.push({ href: '/s/' + encodeURIComponent(s.id), title: title, sub: s.status === 'ended' ? '끝난 세션' : sub, t: s.updatedAt });
      }
    });
    return { todo: todo, run: run, idle: idle };
  }
  function renderSide() {
    if (!sideEl) return;
    var d = sideData(), col = isCollapsed(), cur = location.pathname;
    appEl.dataset.collapsed = col ? 'true' : 'false';
    clear(sideEl);
    if (col) { sideEl.appendChild(renderRail(d, cur)); return; }

    var nav = h('nav', { class: 'nav', 'aria-label': '작업 목록' });
    var navHead = h('div', { class: 'nav-head' }), navList = h('div', { class: 'nav-list' }), navFoot = h('div', { class: 'nav-foot' });
    nav.appendChild(navHead); nav.appendChild(navList); nav.appendChild(navFoot);
    navHead.appendChild(link('/', { class: 'brand', 'aria-label': 'Blueward Harness' }, h('img', { class: 'brand-logo', src: '/static/blueward-logo.png', alt: 'Blueward' }), h('b', null, h('span', { text: 'Harness' }))));
    navHead.appendChild(link('/new', { class: 'newbtn', text: '새 작업' }));
    function group(title, items, cls, first, emptyText, withVerb) {
      navList.appendChild(h('h2', { class: 'grp-h' + (cls ? ' ' + cls : '') + (first ? ' first' : '') }, title, h('span', { text: String(items.length) })));
      if (!items.length && loadedOnce) navList.appendChild(h('p', { class: 'grp-empty', text: emptyText }));
      items.forEach(function (it) {
        navList.appendChild(link(it.href, { class: 'item', 'aria-current': cur === it.href ? 'page' : null },
          withVerb ? h('span', { class: 'verb', text: it.verb }) : null,
          h('span', { class: 'ttl', text: it.title }),
          h('span', { class: 'sub', title: it.sub, text: it.sub })));
      });
    }
    group('내가 할 일', d.todo, 'attn', true, '지금 할 일이 없습니다.', true);
    group('Claude Code가 하는 일', d.run, '', false, '일하는 세션이 없습니다.', false);
    group('쉬는 중', d.idle, '', false, '쉬는 세션이 없습니다.', false);
    navFoot.appendChild(link('/settings', { class: 'side-link', 'aria-current': cur === '/settings' ? 'page' : null }, icon('settings', 16), '설정'));
    navFoot.appendChild(h('button', { type: 'button', class: 'fold', 'aria-keyshortcuts': '[', 'aria-label': '목록 접기', onClick: function () { setCollapsed(true); } },
      h('span', { text: '목록 접기' }), h('kbd', { text: '[' })));
    sideEl.appendChild(nav);
  }
  function renderRail(d, cur) {
    var n = d.todo.length;
    return h('nav', { class: 'rail', 'aria-label': '작업 목록 (접힘)' },
      h('button', { type: 'button', class: 'rail-btn', 'aria-label': '목록 펼치기 ([ 키)', title: '목록 펼치기 ( [ )', 'aria-keyshortcuts': '[', onClick: function () { setCollapsed(false); } }, icon('panel', 18)),
      link('/new', { class: 'rail-btn solid', 'aria-label': '새 작업', title: '새 작업' }, icon('plus', 18)),
      link(d.todo.length ? d.todo[0].href : '/', { class: 'rail-count' + (n ? ' has' : ''), 'aria-label': '내가 할 일 ' + n + '건', title: '내가 할 일 ' + n + '건' },
        h('span', { class: 'n', text: String(n) }), h('span', { class: 'l', text: '내가 할 일' })),
      h('span', { class: 'rail-sp' }),
      link('/settings', { class: 'rail-btn', 'aria-label': '설정', title: '설정', 'aria-current': cur === '/settings' ? 'page' : null }, icon('settings', 18)));
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
    return h('div', { class: 'topline' }, left ? h('span', { class: 'wrap-any', text: left }) : null, designQuick());
  }
  /* 디자인 빠른 전환: 위쪽 줄의 작은 버튼 4개. 고른 값은 theme.js 가 이 PC 에 저장한다. */
  function syncDesignButtons() {
    var cur = window.BH.getDesign(), list = document.querySelectorAll('[data-design-id]');
    for (var i = 0; i < list.length; i++) list[i].setAttribute('aria-pressed', String(list[i].getAttribute('data-design-id') === cur));
  }
  function setDesign(id) { window.BH.setDesign(id); syncDesignButtons(); }
  function designQuick() {
    var cur = window.BH.getDesign();
    return h('div', { class: 'design-quick', role: 'group', 'aria-label': '디자인 바꾸기' }, window.BH.DESIGNS.map(function (d) {
      return h('button', { type: 'button', class: 'dq', 'data-design-id': d[0], 'aria-pressed': String(d[0] === cur), 'aria-label': '디자인 ' + d[1], title: d[1], text: d[2], onClick: function () { setDesign(d[0]); } });
    }));
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
    kindOf: kindOf, skillLabel: skillLabel, topline: topline, stateBox: stateBox, loadingBox: loadingBox,
    loaded: function () { return loadedOnce; }, conn: function () { return conn.state; }
  });
  function homeView(root) { return ui.homeView(root); }

  /* ---------- 세션 ---------- */
  function sessionView(root) {
    var id = route.id, detail = null, errored = null, fetching = false, timer = null;
    var regions = {}, parts = {}, followVal = '', followNote = '', reportOpen = false, logAll = false, built = false, interruptAsk = false, permBusy = false, permNote = '';

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

    function build() {
      built = true; clear(root);
      var page = h('div', { class: 'page' });
      var tl = topline(' ');
      regions.title = tl.firstChild;
      page.appendChild(tl);
      ['checks', 'flow', 'tools', 'head', 'notices', 'folder', 'subs', 'perm', 'report', 'docs', 'follow', 'files', 'log', 'tech'].forEach(function (k) {
        regions[k] = h('div', { 'data-r': k });
        page.appendChild(regions[k]);
      });
      root.appendChild(page);
      // 갈래·도구·점검·문서 칸은 한 번 만들어 두고 세션이 바뀔 때 update 만 부른다.
      parts.checks = ui.startChecksPanel(); regions.checks.appendChild(parts.checks.el);
      parts.flow = ui.flowPanel(); regions.flow.appendChild(parts.flow.el);
      parts.tools = ui.toolsRow(function () { var s = cur(); return { session: s.id ? s : null, cwd: s.cwd }; }); regions.tools.appendChild(parts.tools.el);
      parts.folder = ui.folderNotice(); regions.folder.appendChild(parts.folder.el);
      parts.docs = ui.docsPanel(); regions.docs.appendChild(parts.docs.el);
      // 이어서 요청 입력칸은 다시 그리지 않는다.
      var followAssist = null;
      var input = h('input', { id: 'follow', class: 'input lg', placeholder: '예: 표의 항목 순서를 바꿔 주세요  (/ 로 스킬, @ 로 파일)', autocomplete: 'off',
        onInput: function (e) { followVal = e.target.value; followNote = ''; paintFollowNote(); },
        onKeydown: function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229 && !(followAssist && followAssist.isOpen())) { e.preventDefault(); sendFollow(); } } });
      followAssist = withAssist(input, function () { return cur().cwd; });
      var btn = h('button', { type: 'button', class: 'btn', text: '보내기', onClick: sendFollow });
      regions.follow.appendChild(h('section', { class: 'mt-44' },
        h('label', { for: 'follow', class: 'label', text: '이 작업에 이어서 요청' }),
        h('div', { class: 'row' }, h('div', { class: 'grow' }, followAssist.wrap), h('div', { class: 'fixed' }, btn)),
        h('p', { class: 'note-accent', 'data-note': '1', role: 'status' }),
        h('p', { class: 'note-muted', 'data-why': '1' })));
      regions.followInput = input; regions.followBtn = btn;
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
      note.textContent = [permNote, live].filter(Boolean).join(' · ');
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

    function sendFollow() {
      var s = cur(), text = followVal.trim();
      if (!text || s.canSend === false) return;
      regions.followBtn.disabled = true;
      api('POST', '/api/sessions/' + encodeURIComponent(id) + '/messages', { text: text }).then(function () {
        followVal = ''; regions.followInput.value = '';
        followNote = (s.status === 'running') ? '지금 단계가 끝나면 이어서 처리합니다.' : '이 작업에 전달했습니다.';
      }, function (e) { followNote = '보내지 못했습니다: ' + e.message; }).then(function () {
        regions.followBtn.disabled = cur().canSend === false; paintFollowNote();
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
      if (pend) return 'Claude Code가 내 확인을 기다리고 있습니다';
      if (s.status === 'running') return s.currentAction ? shortAction(s.currentAction) : (s.currentSkill ? skillLabel(s.currentSkill) + ' 진행 중' : '작업하는 중입니다');
      if (s.status === 'starting') return '세션을 시작하고 있습니다';
      if (s.status === 'ended') return '세션이 끝났습니다';
      if (s.askedInText) return '내 답을 기다리는 듯해요(추정).';
      if (s.turnSkill) return '이제 ' + skillLabel(s.turnSkill, flowItem(s, s.turnSkill)) + ' 차례예요.';
      return '다음 요청을 기다리고 있습니다';
    }
    // 글로 물은 것으로 추정할 때, git 상태로 짐작한 차례는 제목에서 내려 참고 한 줄로만 보인다
    function askedNote(s) {
      if (!s.askedInText || (s.pendingRequestIds || []).length || s.status === 'running' || s.status === 'ended') return null;
      var tail = s.turnSkill ? ' 참고로 git 상태로는 ' + skillLabel(s.turnSkill, flowItem(s, s.turnSkill)) + ' 차례로 보여요.' : '';
      return h('p', { class: 'note-muted', 'data-asked': '1', text: '마지막 보고가 물음표로 끝나서 질문으로 추정했어요(틀릴 수 있어요).' + tail });
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

    function paint(s) {
      var tt = s.title || baseName(s.cwd) || '세션';
      setTitle(tt);
      regions.title.textContent = tt;
      var eb = eyebrowFor(s);
      var el = elapsedParts(s.startedAt);
      regions.head.replaceChildren(h('div', { class: 'head' },
        h('div', { class: 'l' },
          h('div', { class: 'eyebrow tone-' + eb[0] }, h('i'), eb[1]),
          h('h1', { class: 'big', text: headlineFor(s) }),
          actionLine(s),
          askedNote(s),
          modelLine(s) ? h('p', { class: 'note-muted', 'data-model': '1', text: modelLine(s) }) : null,
          (s.managed && (s.status === 'running') ? (interruptAsk
            ? h('div', { class: 'confirm' }, h('span', { text: '진행 중인 작업을 멈출까요?' }), h('button', { type: 'button', class: 'btn sm', text: '중단', onClick: interrupt }), h('button', { type: 'button', class: 'btn sm', text: '취소', onClick: function () { interruptAsk = false; draw(); } }))
            : h('div', { class: 'mt-16' }, h('button', { type: 'button', class: 'btn sm', text: '작업 중단', onClick: function () { interruptAsk = true; draw(); } }))) : null)),
        el ? h('div', { class: 'r' },
          h('div', { class: 'big-num', 'data-elapsed': '1' }, el.map(function (p) { return [p[0], p[1] ? h('span', { text: p[1] }) : null]; })),
          h('div', { class: 'big-cap', text: '세션 시작 후 경과' })) : null));

      var notices = [];
      var pend = s.pendingRequestIds || [];
      pend.forEach(function (rid) {
        var r = requests.get(rid);
        if (r && r.status && r.status !== 'pending') return;
        notices.push(h('div', { class: 'banner', role: 'status' }, h('span', { text: (r ? (kindOf(r) === 'question' ? '답해야 할 질문이 있습니다' : '승인해야 할 요청이 있습니다') : '확인해야 할 요청이 있습니다') + (r ? ' · ' + requestTitle(r) : '') }),
          link('/r/' + encodeURIComponent(rid), { text: r ? (kindOf(r) === 'question' ? '답하기' : '승인하기') : '열기' })));
      });
      if (s.bypassPermissions || /bypass/i.test(String(s.permissionMode || ''))) {
        notices.push(h('div', { class: 'banner info' }, h('span', { text: '권한 우회 모드로 실행 중인 세션입니다. 이 세션은 승인 요청이 발생하지 않아 콘솔에 승인 화면이 뜨지 않습니다.' })));
      }
      if (s.handedOffTo) {
        notices.push(h('div', { class: 'banner info' }, h('span', { text: '다음 세션으로 넘어감 → ' }),
          link('/s/' + encodeURIComponent(s.handedOffTo), { text: '새 세션 보기' })));
      }
      regions.notices.replaceChildren.apply(regions.notices, notices);

      paintSubs(s);
      paintPerm(s);
      paintReport(s);
      parts.checks.update(s); parts.flow.update(s); parts.tools.update();
      parts.folder.update(s.cwd, window.BHLogic.sameFolderBusy(s, Array.from(sessions.values())), function (path) { draft.cwd = path; draft.picked = null; });
      parts.docs.update(s);
      paintFollow(s);
      paintFiles(s);
      paintLog(s);
      paintTech(s);
    }

    function paintReport(s) {
      var rep = s.report, text = rep && typeof rep === 'object' ? (rep.text || rep.markdown || rep.body || '') : (rep || '');
      var when = rep && typeof rep === 'object' ? (rep.updatedAt || rep.at || rep.time) : null;
      var sec = h('section', { class: 'report', 'aria-labelledby': 'rep-h' });
      sec.appendChild(h('div', { class: 'report-h' }, h('h2', { id: 'rep-h', text: '결과 보고' }), when ? h('span', { text: clock(when) + ' 기준' }) : null));
      if (!String(text).trim()) {
        sec.appendChild(h('p', { class: 'report-empty', text: s.status === 'running' ? '이번 차례가 끝나면 Claude Code의 결과 보고가 여기에 나타납니다.' : '아직 결과 보고가 없습니다.' }));
      } else {
        var long = String(text).split('\n').length > 28 || String(text).length > 2200;
        var body = h('div', { class: 'report-body' + (long && !reportOpen ? ' clip' : ''), tabindex: long ? '0' : null });
        body.appendChild(window.BHMarkdown.render(String(text)));
        sec.appendChild(body);
        if (long) sec.appendChild(h('div', { class: 'report-foot' }, h('button', { type: 'button', class: 'disclose', 'aria-expanded': String(reportOpen), onClick: function () { reportOpen = !reportOpen; paintReport(cur()); } }, icon('chev', 14), reportOpen ? '접기' : '전체 보기')));
      }
      regions.report.replaceChildren(sec);
    }

    function paintFollow(s) {
      var can = s.canSend !== false;
      regions.followInput.disabled = !can; regions.followBtn.disabled = !can;
      var why = regions.follow.querySelector('[data-why]');
      why.textContent = can ? '' : (s.cannotSendReason || '이 세션에는 지금 요청을 보낼 수 없습니다.');
      why.hidden = can;
      paintFollowNote();
    }

    function paintFiles(s) {
      var out = [];
      var prs = (s.prLinks || []).map(function (p) { return typeof p === 'string' ? { url: p } : p; }).filter(function (p) { return p && p.url; });
      if (prs.length) out.push(h('section', { class: 'mt-40' }, h('h2', { class: 'label', text: 'PR' }),
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
      if (!log.length) sec.appendChild(h('p', { class: 'note-muted', text: '아직 기록이 없습니다.' }));
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
        var parts = elapsedParts(cur().startedAt);
        if (el && parts) { clear(el); parts.forEach(function (p) { add(el, p[0]); if (p[1]) el.appendChild(h('span', { text: p[1] })); }); }
        if (regions.subs && runningSubagents(cur()).length) paintSubs(cur());  // 서브에이전트 경과 시간
      },
      destroy: function () { clearTimeout(timer); Object.keys(parts).forEach(function (k) { parts[k].destroy(); }); }
    };
  }

  /* ---------- 승인·질문 (/r/:rid) ---------- */
  function requestView(root) {
    var rid = route.id, req = requests.get(rid) || null, errored = null, outcome = null, busy = false;
    var why = '', answers = null, picked = null, otherTexts = null, sendErr = '';

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
      setTitle(isQ ? '질문' : '승인');
      (isQ ? drawQuestion : drawPermission)();
    }

    function sid() { return req.sessionId || req.session_id; }
    function head(page, isQ) {
      var s = sessionOf() || {};
      page.appendChild(topline(s.title || baseName(s.cwd) || ''));
      var open = isPending();
      page.appendChild(h('div', { class: 'eyebrow ' + (open ? 'tone-attn' : 'tone-sec') }, h('i'),
        open ? (isQ ? '내 답을 기다리는 중' : '내 승인을 기다리는 중') + waitedText(req.createdAt || req.createdAtMs) : (isQ ? '처리된 질문' : '처리된 승인 요청')));
    }

    /* 결과 */
    var RES = {
      allow: ['허용했습니다.', '세션이 작업을 이어 갑니다.'], allow_session: ['허용했습니다.', '이 세션에서는 같은 작업을 다시 묻지 않습니다.'],
      always: ['허용했습니다.', '이 세션에서는 같은 작업을 다시 묻지 않습니다.'],
      deny: ['거부했습니다.', '세션이 다른 방법을 찾습니다.'], answered: ['세션에 답을 전달했습니다.', ''],
      terminal: ['터미널에서 처리됨', '터미널에서 이미 답해서 콘솔에서는 할 일이 없습니다.'],
      handoff: ['터미널로 넘어감', '기다리는 시간이 지나 터미널의 질문창이 대신 처리합니다.'],
      expired: ['닫힌 요청', '시간이 지났거나 세션이 끝나 더 이상 답할 수 없습니다.'], closed: ['닫힌 요청', '세션이 끝났거나 다른 곳에서 처리되어 더 이상 답할 수 없습니다.']
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
      return h('div', { class: 'result', role: 'status' }, h('p', { class: 'big', text: r.title }), r.note ? h('p', { class: 'sub', text: r.note }) : null, r.extra ? h('p', { class: 'sub', text: r.extra }) : null,
        (r.lines || []).map(function (l) { return h('p', { class: 'sub', text: l }); }), backToSession(sid()));
    }

    /* 승인 */
    var TOOL_FIELDS = { Bash: ['명령', 'command'], Write: ['파일', 'file_path'], Edit: ['파일', 'file_path'], MultiEdit: ['파일', 'file_path'], Read: ['파일', 'file_path'], NotebookEdit: ['노트북', 'notebook_path'], WebFetch: ['주소', 'url'], Glob: ['패턴', 'pattern'], Grep: ['검색어', 'pattern'], WebSearch: ['검색어', 'query'] };
    function drawPermission() {
      var page = h('div', { class: 'page w-820' });
      head(page, false);
      var tool = req.toolName || req.tool_name || '도구', input = req.toolInput || req.tool_input || req.input || {};
      page.appendChild(h('h1', { class: 'big', text: req.title || 'Claude Code가 ' + tool + ' 도구를 쓰려고 합니다. 허용할까요?' }));
      var risk = req.risk || req.riskNote || req.warning;
      if (risk) page.appendChild(h('p', { class: 'lede attn', text: typeof risk === 'string' ? risk : (risk.text || risk.message || '') }));
      if (req.description) page.appendChild(h('p', { class: 'lede', text: req.description }));

      var rows = h('dl', { class: 'rows' });
      function row(k, v, mono, scroll) { if (v == null || v === '') return; rows.appendChild(h('dt', { text: k })); rows.appendChild(h('dd', { class: (mono ? 'mono' : '') + (scroll ? ' scroll' : ''), tabindex: scroll ? '0' : null, text: v })); }
      row('도구', tool, true);
      var f = TOOL_FIELDS[tool];
      if (f && input && input[f[1]] != null) row(f[0], str(input[f[1]]), true, tool === 'Bash');  // 여러 줄 명령(heredoc)의 줄바꿈을 그대로 보인다
      if (input && input.description) row('설명', str(input.description));
      /* 위험을 바꾸는 값은 기본으로 보인다. 긴 값은 말줄임 없이 스크롤로 끝까지 볼 수 있다. */
      if (input && input.dangerouslyDisableSandbox) rows.appendChild(h('dt', { text: '샌드박스' })), rows.appendChild(h('dd', { class: 'attn-text', text: '샌드박스를 끄고 실행합니다(dangerouslyDisableSandbox)' }));
      if (input && input.run_in_background) row('실행 방식', '백그라운드로 실행합니다(run_in_background)');
      if (input && typeof input.content === 'string') row('쓸 내용', input.content, true, true);
      if (input && typeof input.new_string === 'string') row('바꿀 내용', input.new_string, true, true);
      if (input && typeof input.old_string === 'string') row('바뀌는 부분', input.old_string, true, true);
      var s = sessionOf() || {};
      row('작업 폴더', req.cwd || s.cwd, true);
      page.appendChild(rows);

      var det = h('details', { class: 'tech flat' }, h('summary', { text: '기술 정보 보기' }));
      var kv = h('dl', { class: 'kv' });
      [['세션', s.title || sid()], ['브랜치', s.branch], ['도구 이름', tool], ['요청 ID', rid]].forEach(function (r) { if (r[1]) { kv.appendChild(h('dt', { text: r[0] })); kv.appendChild(h('dd', { class: 'mono', text: String(r[1]) })); } });
      det.appendChild(kv);
      page.appendChild(det);
      /* 입력 전체는 접지 않고 항상 보인다. 사용자가 무엇을 허용하는지 가려지면 안 된다(MCP, Agent, Skill 등 목록에 없는 도구 포함). */
      page.appendChild(h('h2', { class: 'label mt-24', text: '도구에 넘기는 입력 전체' }));
      page.appendChild(h('pre', { class: 'box scroll', tabindex: '0', 'aria-label': '도구 입력 전체', text: JSON.stringify(input, null, 2) }));

      if (isPending()) {
        var canSess = !(req.canAllowSession === false || req.hasSuggestions === false || (Array.isArray(req.permissionSuggestions) && !req.permissionSuggestions.length) || (Array.isArray(req.permission_suggestions) && !req.permission_suggestions.length));
        var sugg = Array.isArray(req.suggestionText) ? req.suggestionText : [];
        if (canSess) page.appendChild(h('div', { class: 'sugg mt-24', role: 'group', 'aria-label': '다시 묻지 않기로 추가되는 규칙' },
          h('p', { class: 'sugg-h', text: '"허용하고 이 세션에서 다시 묻지 않기"를 누르면 다음 규칙이 추가됩니다' }),
          sugg.length ? h('ul', { class: 'sugg-l' }, sugg.map(function (x) { return h('li', { class: 'mono', text: x }); }))
            : h('p', { class: 'sub', text: '규칙 내용을 읽지 못했습니다. 아래 원문을 확인하십시오.' }),
          req.suggestions ? h('pre', { class: 'box scroll', tabindex: '0', text: JSON.stringify(req.suggestions, null, 2) }) : null));
        page.appendChild(h('label', { for: 'why', class: 'field-label mt-32', text: '거부 이유 (거부할 때만 Claude Code에게 전달됩니다)' }));
        page.appendChild(h('input', { id: 'why', class: 'input', value: why, placeholder: '예: 리뷰가 끝난 뒤에 해 주세요', autocomplete: 'off', onInput: function (e) { why = e.target.value; } }));
        if (sendErr) page.appendChild(h('p', { class: 'note-attn', role: 'alert', text: sendErr }));
        page.appendChild(h('div', { class: 'btn-row mt-24' },
          h('button', { type: 'button', class: 'btn', disabled: busy, text: '거부', onClick: function () { decide('deny'); } }),
          canSess ? h('button', { type: 'button', class: 'btn', disabled: busy, text: '허용하고 이 세션에서 다시 묻지 않기', onClick: function () { decide('allow_session'); } }) : null,
          h('button', { type: 'button', class: 'btn primary', disabled: busy, text: '허용', onClick: function () { decide('allow'); } })));
      } else page.appendChild(resultBlock());
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

    /* 질문 */
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
      var qsList = questionsOf(req), page = h('div', { class: 'page w-960' });
      head(page, true);
      var multi = qsList.length > 1;
      page.appendChild(h('h1', { class: 'big', text: req.title || (multi ? '질문 ' + qsList.length + '개에 답해 주세요' : (qsList[0] && qsList[0].question) || '질문이 있습니다') }));
      var s = sessionOf() || {};
      if (!multi && qsList[0] && qsList[0].header) page.appendChild(h('p', { class: 'lede', text: qsList[0].header }));
      else if (multi && s.title) page.appendChild(h('p', { class: 'lede', text: s.title }));
      var open = isPending();
      qsList.forEach(function (q, i) {
        var opts = q.options || [], hasPrev = opts.some(function (o) { return o && o.preview; });
        var fs = h('fieldset', { class: 'q-block', disabled: !open || busy });
        fs.appendChild(h('legend', { class: multi ? 'sect-h' : 'sr-only' }, q.question || '', q.header && multi ? [' ', h('small', { text: q.header })] : null, q.multiSelect ? [' ', h('small', { text: '여러 개 선택' })] : null));
        var list = h('div', { class: 'q-opts' + (hasPrev ? '' : ' grid') });
        opts.forEach(function (o) {
          var label = typeof o === 'string' ? o : o.label, on = picked[i].indexOf(label) >= 0;
          list.appendChild(h('button', { type: 'button', class: 'opt', 'aria-pressed': String(on), onClick: function () {
            if (q.multiSelect) { picked[i] = on ? picked[i].filter(function (x) { return x !== label; }) : picked[i].concat(label); }
            else { picked[i] = on ? [] : [label]; otherTexts[i] = ''; }
            draw();
          } }, h('span', { class: 'mark', text: on ? '선택됨' : '' }), h('span', { class: 't', text: label }), o.description ? h('span', { class: 'd', text: o.description }) : null));
        });
        if (hasPrev) {
          var sel = opts.filter(function (o) { return o && o.label === picked[i][picked[i].length - 1]; })[0];
          fs.appendChild(h('div', { class: 'q-body' }, list, h('pre', { class: 'box lg q-preview' + (sel && sel.preview ? '' : ' empty'), 'aria-label': '선택한 항목 미리보기', text: sel && sel.preview ? sel.preview : '항목을 고르면 미리보기가 여기에 보입니다.' })));
        } else fs.appendChild(list);
        fs.appendChild(h('label', { for: 'other-' + i, class: 'field-label', text: '다른 답이 있으면 직접 적어 주세요' }));
        fs.appendChild(h('input', { id: 'other-' + i, class: 'input', value: otherTexts[i], placeholder: '직접 입력', autocomplete: 'off',
          onInput: function (e) {
            otherTexts[i] = e.target.value;
            if (!q.multiSelect && e.target.value.trim() && picked[i].length) { picked[i] = []; fs.querySelectorAll('.opt').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); b.firstChild.textContent = ''; }); }
            syncSend();
          } }));
        page.appendChild(fs);
      });

      if (open) {
        var sendBtn = h('button', { type: 'button', id: 'qsend', class: 'btn primary', text: '답 보내기', disabled: busy, onClick: sendAnswers });
        page.appendChild(h('div', { class: 'btn-row mt-32' }, sendBtn));
        page.appendChild(h('p', { class: 'q-status', id: 'qstat', role: 'status' }));
        if (sendErr) page.appendChild(h('p', { class: 'note-attn', role: 'alert', text: sendErr }));
      } else page.appendChild(resultBlock());
      root.appendChild(page);
      syncSend();
    }
    function allAnswered() { return questionsOf(req).every(function (q, i) { return !!answerOf(i, q); }); }
    function syncSend() {
      var b = root.querySelector('#qsend'), st = root.querySelector('#qstat'); if (!b) return;
      var left = questionsOf(req).filter(function (q, i) { return !answerOf(i, q); }).length;
      b.disabled = busy || left > 0;
      if (st) st.textContent = left ? '아직 답하지 않은 질문이 ' + left + '개 있습니다.' : '';
    }
    function sendAnswers() {
      var qsList = questionsOf(req), ans = {}, lines = [];
      qsList.forEach(function (q, i) { ans[qKey(q)] = answerOf(i, q); lines.push(q.question + ' → ' + answerOf(i, q)); });
      busy = true; sendErr = ''; draw();
      api('POST', '/api/requests/' + encodeURIComponent(rid) + '/answer', { answers: ans }).then(function () {
        outcome = { title: '세션에 답을 전달했습니다.', note: '', lines: lines };
      }, afterFail).then(function () { busy = false; draw(); });
    }

    if (!req) fetchReq(); else { fetchReq(); }
    draw();
    return {
      title: function () { return ''; },
      onRequest: function (id) { if (id === rid) { req = requests.get(rid); draw(); } },
      onSession: function () { },
      onRemoved: function (id) { if (id === rid) { req = requests.get(rid) || req; draw(); } },
      tick: function () { var e = root.querySelector('.eyebrow'); if (e && isPending()) { var open = kindOf(req) === 'question'; e.lastChild.textContent = (open ? '내 답을 기다리는 중' : '내 승인을 기다리는 중') + waitedText(req.createdAt || req.createdAtMs); } }
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
  var PERMISSION_FALLBACK = [{ value: '', label: '기본(그때그때 확인)' }, { value: 'acceptEdits', label: '파일 고치기는 자동 허용' }, { value: 'plan', label: '계획만 세우기' }];
  var draft = { text: '', cwd: '', note: '', answers: {}, picked: null, extraPaths: [], model: null, modelCustom: false, customName: '', effort: null, permission: null, flowId: null, flowUser: false };
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
    var starting = false, startedId = null, startErr = '', alive = true, browseBusy = false, modelErr = false;
    var tools = ui.toolsRow(function () { return { session: null, cwd: draft.cwd, onInsert: insertTool }; });
    var folderWarn = ui.folderNotice(), chooser = ui.flowChooser();
    function insertTool(skill) {
      var field = document.getElementById('brief');
      if (!field) { tools.say('요청을 적는 화면에서 누르면 입력칸에 넣어 드려요.'); return; }
      var cmd = skillCommand(skillInfo || { plugin: DEFAULT_PLUGIN }, skill), rest = field.value.replace(/^\/\S*\s*/, '');
      setFieldValue(field, cmd + rest, cmd.length);
    }
    function effectiveFlow() {
      if (draft.flowUser) return draft.flowId;
      var f = res().flow;
      return f && f.confident ? f.id : null;
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
        recent = listOf(d, 'folders').map(function (f) { return typeof f === 'string' ? { path: f } : f; }).filter(function (f) { return f && f.path; });
        if (!draft.cwd && recent.length) draft.cwd = recent[0].path;
        if (!draft.cwd) picking = true;
        draw();
      }, function () { recent = []; if (!draft.cwd) picking = true; draw(); });
    }

    /* 분석 상태 */
    function begin() {
      if (!draft.text.trim()) { textErr = true; draw(); return; }
      if (draft.modelCustom && !customOk()) { modelErr = true; draw(); return; }
      if (!draft.cwd) { picking = true; err = ''; draw(); return; }
      step = 'analyzing'; err = ''; draft.flowId = null; draft.flowUser = false; draw();
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
      api('POST', '/api/new/' + encodeURIComponent(aid) + '/start', { picked: pickedAll(), extraAnswers: answerMap(), note: draft.note.trim(), model: modelChoice(), effort: effortChoice(), permission: permissionChoice(), flow: draft.flowUser ? draft.flowId : undefined }).then(function (d) {
        startedId = (d && (d.id || d.sessionId || (d.session && d.session.id))) || '';
        if (startedId) { mergeSession({ id: startedId }); }
        history.replaceState(null, '', '/new');
      }, function (e) { startErr = '시작하지 못했습니다: ' + e.message; }).then(function () { starting = false; draw(); });
    }

    /* 폴더 */
    function useFolder(p) { draft.cwd = p; draft.picked = null; picking = false; browsing = false; fsRows = null; dir = ''; customMsg = ''; draw(); }
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
    function draw() {
      if (!alive) return;
      var keepFocus = document.activeElement && document.activeElement.id, selStart = document.activeElement && document.activeElement.selectionStart;
      clear(root);
      var page = h('div', { class: 'page w-760' });
      page.appendChild(topline());
      if (step === 'write' || step === 'review') { page.appendChild(tools.el); tools.update(); }
      if (step === 'write') drawWrite(page);
      else if (step === 'analyzing') drawAnalyzing(page);
      else if (step === 'failed') drawFailed(page);
      else drawReview(page);
      root.appendChild(page);
      if (keepFocus) { var f = document.getElementById(keepFocus); if (f && f !== document.activeElement) { f.focus(); try { if (selStart != null) f.setSelectionRange(selStart, selStart); } catch (e) { console.debug('커서 위치를 되돌리지 못했습니다', e); } } }
    }
    function folderBar(page) {
      page.appendChild(h('div', { class: 'folder-bar' },
        h('div', null, h('div', { class: 'k', text: '작업 폴더' }), draft.cwd ? h('div', { class: 'v', text: draft.cwd }) : h('div', { class: 'v none', text: recent === null ? '불러오는 중' : '폴더를 골라 주세요' })),
        h('button', { type: 'button', class: 'btn sm', 'aria-expanded': String(picking), onClick: function () { picking = !picking; draw(); } }, picking ? '닫기' : (draft.cwd ? '폴더 바꾸기' : '폴더 고르기'))));
      if (!picking) return;
      var box = h('div', { class: 'folder-pick' });
      (recent || []).forEach(function (f) {
        box.appendChild(h('button', { type: 'button', class: 'folder-opt', 'aria-pressed': String(f.path === draft.cwd), onClick: function () { useFolder(f.path); }, text: f.path }));
      });
      if (recent && !recent.length) box.appendChild(h('p', { class: 'note-muted', text: '최근에 쓴 폴더가 없습니다. 아래에 경로를 적어 주세요.' }));
      box.appendChild(h('label', { for: 'custom', class: 'field-label', text: '다른 폴더 경로' }));
      box.appendChild(h('div', { class: 'inline-row' },
        h('input', { id: 'custom', class: 'input', value: custom, placeholder: 'C:\\Work\\project  또는  /Users/me/project', autocomplete: 'off', onInput: function (e) { custom = e.target.value; }, onKeydown: function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); validateCustom(); } } }),
        h('button', { type: 'button', class: 'btn sm', disabled: customBusy, text: customBusy ? '확인 중' : '사용', onClick: validateCustom }),
        h('button', { type: 'button', class: 'btn sm', disabled: browseBusy, text: browseBusy ? '창 여는 중' : '폴더 찾아보기', onClick: browseFolder })));
      if (browseBusy) box.appendChild(h('p', { class: 'note-muted', role: 'status', text: '폴더 선택 창을 열었어요. 창이 보이지 않으면 작업 표시줄을 확인해 주세요. 고르면 이 화면에 자동으로 적용됩니다.' }));
      box.appendChild(h('p', { class: 'note-attn', role: 'alert', text: customMsg, hidden: !customMsg }));
      page.appendChild(box);
    }
    function drawWrite(page) {
      page.appendChild(h('h1', { class: 'big mt-44', text: '어떤 일을 맡길까요?' }));
      page.appendChild(h('p', { class: 'lede', text: '평소 말하듯 적어 주세요. Claude Code가 살펴본 뒤 필요한 자료를 골라 확인을 요청합니다.' }));
      page.appendChild(h('label', { for: 'brief', class: 'label mt-32', text: '요청 내용' }));
      var brief = h('textarea', { id: 'brief', class: 'textarea xl', rows: '8', value: draft.text, placeholder: '예: 구매요청을 올리면 팀장에게 승인 메일이 가면 좋겠어요  (/ 로 스킬, @ 로 파일)',
        onInput: function (e) { draft.text = e.target.value; if (textErr) { textErr = false; var m = root.querySelector('[data-terr]'); if (m) m.hidden = true; } } });
      page.appendChild(withAssist(brief, function () { return draft.cwd; }).wrap);
      folderBar(page);
      page.appendChild(folderWarn.el);
      folderWarn.update(draft.cwd, window.BHLogic.otherSessions(draft.cwd, Array.from(sessions.values()), null).length > 0, useFolder);
      page.appendChild(h('p', { class: 'note-attn', 'data-terr': '1', role: 'alert', text: '어떤 일인지 한 줄이라도 적어 주세요.', hidden: !textErr }));
      modelChoice(); effortChoice(); permissionChoice();
      page.appendChild(h('div', { class: 'field-pair' },
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
        page.appendChild(h('label', { for: 'model-custom', class: 'field-label', text: '모델 정식 이름' }));
        page.appendChild(h('input', { id: 'model-custom', class: 'input', type: 'text', value: draft.customName, placeholder: '예: claude-opus-4-1', autocomplete: 'off', spellcheck: 'false',
          onInput: function (e) { draft.customName = e.target.value; modelErr = false; var m = root.querySelector('[data-merr]'); if (m) m.hidden = true; if (customOk()) window.BH.write('bh-model', draft.customName.trim()); } }));
        page.appendChild(h('p', { class: 'note-attn', 'data-merr': '1', role: 'alert', text: '이름은 claude- 로 시작하고 영문 소문자, 숫자, 점, 하이픈만 쓸 수 있어요.', hidden: !modelErr }));
      }
      page.appendChild(h('div', { class: 'field-pair' },
        h('div', { class: 'field' },
          h('label', { for: 'permission', class: 'field-label', text: '권한 모드' }),
          h('select', { id: 'permission', class: 'input', onChange: function (e) { draft.permission = e.target.value; window.BH.write('bh-permission', draft.permission); } },
            permissionOptions().map(function (o) { return h('option', { value: o.value, selected: o.value === draft.permission, text: o.label }); })))));
      page.appendChild(h('p', { class: 'note-muted', text: '요청을 살펴볼 때와 작업을 진행할 때 같은 모델과 에포트(생각의 깊이)를 씁니다. 권한 모드는 작업을 진행하는 Claude Code 세션에만 적용됩니다.' }));
      page.appendChild(h('div', { class: 'btn-row mt-24' }, h('button', { type: 'button', class: 'btn primary', text: '다음', onClick: begin })));
      if (startedId !== null) page.appendChild(h('div', { class: 'started', role: 'status' }, h('span', { text: '이전 작업을 시작했습니다.' }), link(startedId ? '/s/' + encodeURIComponent(startedId) : '/', { text: '작업 화면으로 이동' })));
    }
    function drawAnalyzing(page) {
      page.appendChild(h('div', { class: 'eyebrow tone-accent' }, h('i'), '살펴보는 중'));
      page.appendChild(h('h1', { class: 'big', text: '요청과 폴더의 자료를 살펴보고 있어요' }));
      page.appendChild(h('p', { class: 'lede', text: '파일은 아직 고치지 않습니다. 필요한 자료를 고르면 확인을 요청할게요.' }));
      page.appendChild(h('div', { class: 'progress', role: 'status', 'aria-label': '분석 중' }, h('i')));
      page.appendChild(h('div', { class: 'mt-24' }, h('button', { type: 'button', class: 'btn sm', text: '요청 고치기', onClick: function () { clearTimeout(pollTimer); aid = null; step = 'write'; history.replaceState(null, '', '/new'); draw(); } })));
    }
    function drawFailed(page) {
      page.appendChild(h('div', { class: 'eyebrow tone-attn' }, h('i'), '분석하지 못했습니다'));
      page.appendChild(h('h1', { class: 'big', text: 'Claude Code가 요청을 살펴보지 못했어요' }));
      page.appendChild(h('p', { class: 'lede', text: err || '알 수 없는 오류입니다.' }));
      page.appendChild(h('div', { class: 'btn-row mt-32' },
        h('button', { type: 'button', class: 'btn', text: '요청 고치기', onClick: function () { step = 'write'; history.replaceState(null, '', '/new'); draw(); } }),
        h('button', { type: 'button', class: 'btn primary', text: '다시 시도', onClick: begin })));
    }
    function drawReview(page) {
      page.appendChild(h('button', { type: 'button', class: 'backbtn', onClick: function () { clearTimeout(pollTimer); step = 'write'; aid = null; history.replaceState(null, '', '/new'); draw(); } }, icon('back', 14), '요청 고치기'));
      page.appendChild(h('h1', { class: 'big', text: '이 자료로 진행할까요?' }));
      if (res().understood) page.appendChild(h('p', { class: 'lede', text: res().understood }));
      page.appendChild(chooser.el);
      chooser.update({ cwd: draft.cwd, found: res().flow, selected: effectiveFlow(), userPicked: draft.flowUser,
        onPick: function (fid) { draft.flowId = fid; draft.flowUser = true; draw(); schedulePreview(); } });

      var cands = candidates(), cp = cands.map(function (c) { return c.path; });
      var sec = h('section', { class: 'mt-40' });
      sec.appendChild(h('h2', { class: 'grp-h' }, 'Claude Code가 고른 자료', h('span', { text: draft.picked.length + '개 선택' })));
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
      if (!cands.length) sec.appendChild(h('p', { class: 'empty-line', text: '이 폴더에서 관련 자료를 찾지 못했습니다. 직접 고르거나 그대로 진행할 수 있습니다.' }));
      draft.picked.filter(function (p) { return cp.indexOf(p) < 0; }).forEach(function (p) {
        sec.appendChild(h('div', { class: 'cand-extra' }, h('span', { class: 'wrap-any' }, h('b', { text: '직접 추가' }), h('span', { class: 'mono', text: p })),
          h('button', { type: 'button', class: 'iconbtn', 'aria-label': p + ' 빼기', onClick: function () { togglePath(p); } }, icon('close', 14))));
      });
      sec.appendChild(h('div', { class: 'cand-extra' }, h('button', { type: 'button', class: 'btn sm', 'aria-expanded': String(browsing), text: browsing ? '폴더 닫기' : '다른 자료 직접 고르기', onClick: function () { browsing = !browsing; if (browsing) loadFs(); else draw(); } })));
      if (browsing) sec.appendChild(drawBrowser());
      page.appendChild(sec);

      var qsec = h('section', { class: 'mt-40' }, h('h2', { class: 'label', text: '추가로 알려 주세요' }));
      extraQs().forEach(function (q, i) {
        var id = 'xq' + i, opts = (q.options || []).map(function (o) { return typeof o === 'string' ? o : o.label; });
        qsec.appendChild(h('label', { for: id, class: 'sect-h' + (i ? ' mt-24' : ''), text: q.question }));
        if (opts.length) qsec.appendChild(h('div', { class: 'chips', role: 'group', 'aria-label': q.question }, opts.map(function (o) {
          return h('button', { type: 'button', class: 'chip', 'aria-pressed': String(draft.answers[q.question] === o), text: o, onClick: function () { draft.answers[q.question] = draft.answers[q.question] === o ? '' : o; draw(); schedulePreview(); } });
        })));
        qsec.appendChild(h('input', { id: id, class: 'input lg' + (opts.length ? ' mt-16' : ''), value: draft.answers[q.question] || '', placeholder: opts.length ? '직접 입력' : '몰라도 괜찮습니다. 비워 두면 Claude Code가 다시 묻습니다.', autocomplete: 'off',
          onInput: function (e) { draft.answers[q.question] = e.target.value; schedulePreview(); }, onChange: function () { if (opts.length) draw(); } }));
      });
      qsec.appendChild(h('label', { for: 'note', class: 'sect-h mt-24', text: '그 밖에 알아 두면 좋은 내용이 있나요?' }));
      qsec.appendChild(h('textarea', { id: 'note', class: 'textarea', rows: '3', value: draft.note, placeholder: '선택 사항', onInput: function (e) { draft.note = e.target.value; schedulePreview(); } }));
      page.appendChild(qsec);

      var det = h('details', { class: 'tech', open: previewOpen, onToggle: function (e) { previewOpen = e.target.open; if (previewOpen) schedulePreview(); } }, h('summary', { text: '세션에 보낼 내용 보기' }),
        h('pre', { class: 'box', 'data-preview': '1', text: previewText || '불러오는 중입니다.' }));
      page.appendChild(det);

      if (startedId === null) {
        if (startErr) page.appendChild(h('p', { class: 'note-attn', role: 'alert', text: startErr }));
        page.appendChild(h('div', { class: 'btn-row mt-24' }, h('button', { type: 'button', class: 'btn primary', disabled: starting, text: starting ? '시작하는 중' : '이대로 시작', onClick: start })));
      } else {
        page.appendChild(h('div', { class: 'started', role: 'status' }, h('span', { text: '작업을 시작했습니다.' }), link(startedId ? '/s/' + encodeURIComponent(startedId) : '/', { text: '작업 화면으로 이동' })));
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
      destroy: function () { alive = false; clearTimeout(pollTimer); clearTimeout(previewTimer); tools.destroy(); folderWarn.destroy(); chooser.destroy(); if (startedId !== null) draft = { text: '', cwd: draft.cwd, note: '', answers: {}, picked: null, extraPaths: [] }; }
    };
  }

  /* ---------- 설정 ---------- */
  function settingsView(root) {
    function draw() {
      clear(root);
      var BH = window.BH, cur = BH.getTheme(), scale = BH.getScale();
      var page = h('div', { class: 'page' });
      page.appendChild(topline());
      page.appendChild(h('h1', { class: 'big mt-44', text: '설정' }));
      var sc = h('div', { class: 'row' });
      BH.SCALES.forEach(function (z) {
        sc.appendChild(h('button', { type: 'button', class: 'btn scale', 'aria-pressed': String(z[1] === scale), text: z[0], onClick: function () { BH.setScale(z[1]); draw(); } }));
      });
      page.appendChild(h('section', { class: 'mt-40' }, h('h2', { class: 'sect-h', text: '글자 크기' }), sc));
      var ds = h('div', { class: 'row' }), design = BH.getDesign();
      BH.DESIGNS.forEach(function (d) {
        ds.appendChild(h('button', { type: 'button', class: 'btn scale', 'data-design-id': d[0], 'aria-pressed': String(d[0] === design), text: d[1], onClick: function () { setDesign(d[0]); draw(); } }));
      });
      page.appendChild(h('section', { class: 'mt-40' }, h('h2', { class: 'sect-h', text: '디자인' }), ds,
        h('p', { class: 'note-muted mt-16', text: '기존이 아닌 디자인(A·B·C)을 고르면 색은 그 디자인이 정하고, 아래 테마는 기존 디자인일 때만 적용됩니다. 이 PC에 저장됩니다.' })));
      var grid = h('div', { class: 'themes' });
      Object.keys(BH.THEMES).forEach(function (id) {
        var t = BH.THEMES[id], sw = h('span', { class: 'sw', 'aria-hidden': 'true' });
        sw.style.background = t[0]; sw.style.borderColor = t[9] ? 'rgba(0,0,0,.14)' : 'rgba(255,255,255,.1)';
        function bar(w, hgt, col, mt) { var b = h('i'); b.style.width = w; b.style.height = hgt; b.style.background = col; if (mt) b.style.marginTop = mt; return b; }
        sw.appendChild(bar('62%', '8px', t[2])); sw.appendChild(bar('84%', '5px', t[4], '8px'));
        var dots = h('span', { class: 'dots' }), bt = h('i', { class: 'b' }); bt.style.background = t[7];
        var d1 = h('i'), d2 = h('i'); d1.style.background = t[5]; d2.style.background = t[6];
        dots.appendChild(bt); dots.appendChild(d1); dots.appendChild(d2); sw.appendChild(dots);
        grid.appendChild(h('button', { type: 'button', class: 'theme', 'aria-pressed': String(id === cur), onClick: function () { BH.setTheme(id); draw(); } },
          sw, h('span', { class: 'nmrow' }, h('b', { text: BH.NAMES[id] }), h('span', { text: t[9] ? '라이트' : '다크' }))));
      });
      page.appendChild(h('section', { class: 'mt-40' }, h('h2', { class: 'sect-h' }, '테마 ', h('small', { text: BH.NAMES[cur] })), grid,
        h('p', { class: 'note-muted mt-16', text: '고르는 즉시 모든 화면에 적용되고, 이 PC에 저장됩니다.' })));
      root.appendChild(page);
    }
    setTitle('설정'); draw();
    return {};
  }

  /* ---------- 시작 ---------- */
  function boot() {
    var root = document.getElementById('root');
    appEl = h('div', { id: 'app', 'data-collapsed': 'false' });
    sideEl = h('aside', { class: 'side' });
    mainEl = h('main', { class: 'main', id: 'main' });
    appEl.appendChild(sideEl); appEl.appendChild(mainEl);
    root.appendChild(appEl);
    renderRoute();
    loadSessions().then(function () { connectEvents(); }, function (e) { if (e.status !== 401) { connectEvents(); scheduleRetryIfDown(); } });
    if (window.ResizeObserver) new ResizeObserver(function () { if (collapsed === null) scheduleSide(); }).observe(root);
  }
  function scheduleRetryIfDown() { if (conn.state === 'down') scheduleRetry(); }
  boot();
})();
