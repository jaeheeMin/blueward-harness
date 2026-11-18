/* Post(우체국) 테마의 파이프라인 탭(시안 pipeline-mockup/pipeline.html). 요구사항마다 다섯 칸(요구사항 → 개발 Spec → 개발 → 검토 → 합쳐짐) 중 어디에 있는지 보인다.
   사실은 서버 /api/pipeline(pipeline.py: origin/main 의 SRS·원장·Spec, 열린 PR)이 주고, 여기서는 세션을 요구사항에 붙이고 칸을 정한다.
   세션 → 요구사항: 세션 이름·갈래 사유·브랜치의 REQ-/DEV- 번호, 다음 갈래 옵션의 번호(BHLogic.reqIds), 세션 PR 번호가 그 요구사항의 열린 PR 인 것.
   폴더는 세션들의 작업 폴더(+ 마지막 폴더)이고, 같은 저장소의 worktree 는 서버가 준 repo.key 로 한 판에 모은다. 없는 데이터는 지어내지 않는다.
   순수 함수(numsIn·laneOf·board·groups·summary)는 DOM 을 만지지 않는다(node 로 시험한다). app.js 가 create(kit) 로 한 번 만들고 view(root) 를 부른다. */
(function (root) {
  'use strict';

  var LANES = ['요구사항(SRS)', '개발 Spec', '개발', '검토(PR)', '합쳐짐'];
  var LABEL = { turn: '내 차례', blocked: '막힘', unk: '확인 못 함', run: '일하는 중', wait: '승인 기다림', done: '끝남', idle: '쉬는 중' };
  /* 한 요구사항에 세션이 여럿이면 이 순서로 앞선 세션을 카드에 단다(같으면 최근 것) */
  var PICK = ['blocked', 'turn', 'unk', 'run', 'wait', 'idle', 'done'];
  var MAX_FOLDERS = 12;
  var NARROW = '(max-width: 820px)';  // 이 폭 이하에서는 칸을 세로로 쌓고 칸 머리로 접는다(시안 media query)
  var NUM_RE = /(^|[^A-Za-z])(?:REQ|DEV)-?(\d{1,6})(?!\d)/gi;  // pipeline.py NUM_RE 와 같다(브랜치의 dev013 도 13)

  function arr(v) { return Array.isArray(v) ? v : []; }
  function pad3(n) { var s = String(n); return s.length >= 3 ? s : ('00' + s).slice(-3); }
  function numsIn(text) {
    var out = [], m;
    NUM_RE.lastIndex = 0;
    while ((m = NUM_RE.exec(String(text || '')))) { var n = parseInt(m[2], 10); if (out.indexOf(n) < 0) out.push(n); }
    return out;
  }
  /* 세션이 다루는 요구사항 번호 */
  function sessionNums(s, L) {
    var out = numsIn([s.title, s.flowReason, s.branch].join(' '));
    (L && L.reqIds ? L.reqIds(s) : []).forEach(function (id) { var n = parseInt(String(id).slice(4), 10); if (out.indexOf(n) < 0) out.push(n); });
    return out;
  }

  /* 칸(0~4): 원장 완료·SRS Done → 합쳐짐 / 작업 PR 열림 → 검토 / Spec 이 origin/main 에 있거나 설정·표준 건 → 개발(설정·표준은 Spec 칸을 건너뛴다)
     / 다음 단계 미정 → 요구사항 / Spec 쓰는 세션이나 Spec PR 이 있음 → 개발 Spec / 그 밖 → 요구사항 */
  function laneOf(it, sess) {
    var prs = arr(it.prs);
    if (it.done) return 4;
    if (prs.some(function (p) { return p.kind === 'work'; })) return 3;
    if (it.kind || it.spec) return 2;
    if (it.unsure) return 0;
    if (arr(sess).some(function (s) { return s.flowId === 'spec'; }) || prs.some(function (p) { return p.kind === 'spec'; })) return 1;
    return 0;
  }
  function rank(state) { return state === 'blocked' ? 0 : state === 'turn' ? 1 : 2; }

  /* 판 하나: items(서버) + 그 저장소의 세션들 → 칸 다섯 개. 칸마다 [{ item, session, state }], 막힘 > 내 차례 > 번호순. */
  function board(items, sessions, L, PL) {
    var byNum = {}, prOwner = {};
    arr(items).forEach(function (it) { arr(it.prs).forEach(function (p) { (prOwner[p.number] = prOwner[p.number] || []).push(it.number); }); });
    arr(sessions).forEach(function (s) {
      if (!s || s.handedOffTo) return;  // 다음 세션에 넘긴 세션은 그 세션이 대신한다
      var nums = sessionNums(s, L), pr = s.flowPr && s.flowPr.number;
      if (pr && prOwner[pr]) prOwner[pr].forEach(function (n) { if (nums.indexOf(n) < 0) nums.push(n); });
      nums.forEach(function (n) { (byNum[n] = byNum[n] || []).push(s); });
    });
    var lanes = LANES.map(function () { return []; });
    arr(items).forEach(function (it) {
      var ss = byNum[it.number] || [], best = null, bestState = 'idle';
      ss.forEach(function (s) {
        var st = PL.stateOf(s, L), a = PICK.indexOf(st), b = PICK.indexOf(bestState);
        if (!best || a < b || (a === b && (s.updatedAt || 0) > (best.updatedAt || 0))) { best = s; bestState = st; }
      });
      lanes[laneOf(it, ss)].push({ item: it, session: best, state: best ? bestState : 'idle' });
    });
    lanes.forEach(function (l) { l.sort(function (a, b) { return rank(a.state) - rank(b.state) || a.item.number - b.item.number; }); });
    return lanes;
  }

  /* 폴더별 응답 [{ cwd, data }] 을 저장소별로 모은다. [{ key, name, data, cwds }], 읽은 순서 그대로. */
  function groups(results) {
    var out = [], at = {};
    arr(results).forEach(function (r) {
      var d = r && r.data, key = d && d.repo && d.repo.key;
      if (!key) return;
      var g = at[key];
      if (!g) { g = at[key] = { key: key, name: d.repo.name || '', data: d, cwds: [] }; out.push(g); }
      else if (g.data.loading && !d.loading) g.data = d;
      g.cwds.push(r.cwd);
    });
    return out;
  }

  /* 판 머리 옆 한 줄: SRS n건(SRS 가 없으면 원장 건수) · Spec 있는 개발 건 · 설정 · 표준 · 보류·취소 */
  function summary(d) {
    var items = arr(d.items), srs = items.filter(function (i) { return i.req; }).length;
    var parts = [srs ? 'SRS ' + srs + '건' : '원장 ' + items.length + '건'];
    parts.push('Spec 있는 개발 건 ' + items.filter(function (i) { return i.spec && !i.kind; }).length);
    parts.push('설정 ' + items.filter(function (i) { return i.kind === '설정'; }).length);
    parts.push('표준 ' + items.filter(function (i) { return i.kind === '표준'; }).length);
    if (d.hidden) parts.push('보류·취소 ' + d.hidden + '건 뺌');
    return parts.join(' · ');
  }

  /* kit: { h, clear, link, api, qs, L(BHLogic), PL(BHPostLogic), sessions(), loaded(), loadingBox, home()(고른 프로젝트 폴더 — 있으면 마지막 폴더 대신 쓴다, #1070) } */
  function create(kit) {
    var h = kit.h, L = kit.L, PL = kit.PL;
    var shut = {};  // 좁은 폭에서 접은 칸: 저장소 열쇠 + 칸 번호. 다시 그려도 그대로 둔다

    function chev() {
      var ns = 'http://www.w3.org/2000/svg', s = document.createElementNS(ns, 'svg'), p = document.createElementNS(ns, 'path');
      s.setAttribute('class', 'po-pl-chev'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
      p.setAttribute('d', 'M6 9l6 6 6-6'); s.appendChild(p);
      return s;
    }
    function ring(s) {
      var m = L.memoryOf(s);
      if (m.kind !== 'pct') return null;  // 모르는 기억은 그리지 않는다(카드는 세션 상태가 주인공이다)
      return h('span', { class: 'ring pct po-pl-ring' + (m.level ? ' ' + m.level : ''), style: '--p:' + m.pct, role: 'img', 'aria-label': '기억 ' + m.pct + '%', title: m.title }, h('b'));
    }
    function card(c) {
      var it = c.item, s = c.session, st = c.state;
      var cls = 'po-pl-req' + (st === 'turn' ? ' turn' : st === 'blocked' ? ' blocked' : '');
      var kids = [
        h('i', { class: 'po-st po-st-' + st, 'aria-hidden': 'true', text: PL.GLYPH[st] || '' }),
        h('span', { class: 'po-pl-rid', text: (it.req ? it.req + ' · ' : '') + it.dev }),
        h('b', { class: 'po-pl-t', text: it.title }),
        it.kind ? h('span', { class: 'po-pl-kind', text: it.kind }) : null,
        s ? h('span', { class: 'po-pl-sess' }, ring(s), h('span', { text: LABEL[st] || '' })) : null
      ];
      var prs = arr(it.prs).map(function (p) { return '#' + p.number; }).join(', ');
      var tip = prs ? '열린 PR ' + prs : null;
      var node = s ? kit.link('/s/' + encodeURIComponent(s.id), { class: cls, title: tip }, kids) : h('div', { class: cls, title: tip }, kids);
      return h('li', { 'data-req': String(it.number) }, node);
    }
    function lanesEl(g, narrow) {
      var lanes = board(g.data.items, kit.sessions().filter(function (s) { return g.cwds.indexOf(s.cwd) >= 0; }), L, PL);
      return h('div', { class: 'po-pl-lanes' }, lanes.map(function (cards, i) {
        var key = g.key + '#' + i, closed = narrow && !!shut[key];
        var bits = [h('span', { class: 'po-pl-no', text: String(i + 1) }), h('span', { class: 'po-pl-nm', text: LANES[i] }), h('b', { text: String(cards.length) })];
        var head = narrow
          ? h('button', { type: 'button', class: 'po-pl-lh', 'aria-expanded': closed ? 'false' : 'true', onClick: function () { shut[key] = !shut[key]; draw(); } }, bits, chev())
          : h('div', { class: 'po-pl-lh' }, bits);
        return h('div', { class: 'po-pl-lane' + (closed ? ' shut' : ''), 'data-lane': String(i + 1) }, h('h3', null, head), h('ul', null, cards.map(card)));
      }));
    }
    function note(text, cls) { return h('p', { class: 'po-pl-note' + (cls ? ' ' + cls : ''), role: cls === 'unk' ? 'status' : null, text: text }); }
    function panel(g, narrow) {
      var d = g.data, hid = 'po-pl-h-' + g.key.replace(/[^A-Za-z0-9]/g, '').slice(-24), body = [];
      var sub = d.state === 'yes' ? (g.name ? g.name + ' · ' : '') + summary(d) : g.name;
      if (d.state === 'yes') {
        if (d.loading) body.push(note('최신 상태를 다시 읽는 중이야.'));
        if (d.prs && d.prs.state === 'unknown') body.push(note('열린 PR 을 읽지 못해 검토 칸이 비어 있을 수 있어. ' + (d.prs.reason || ''), 'unk'));
        if (!arr(d.items).length) body.push(note('origin/main 에 올라간 요구사항이 아직 없어.'));
        else body.push(lanesEl(g, narrow));
      } else if (d.loading) body.push(note('origin/main 과 열린 PR 을 읽는 중이야.'));
      else body.push(note('요구사항을 확인하지 못했어. ' + (d.reason || ''), 'unk'));  // 못 읽은 것을 빈 판이나 0건으로 뭉개지 않는다
      return h('section', { class: 'light po-panel po-pl', 'aria-labelledby': hid, 'data-repo': g.name },
        h('header', { class: 'po-ph' }, h('h2', { id: hid, text: '요구사항 파이프라인' }), sub ? h('span', { class: 'po-pl-sub', text: sub }) : null), body);
    }

    var st = null, rootEl = null, mq = null;
    function folders() {
      var seen = {}, out = [];
      kit.sessions().filter(function (s) { return s && s.cwd && !s.handedOffTo; })
        .sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); })
        .forEach(function (s) { if (!seen[s.cwd]) { seen[s.cwd] = 1; out.push(s.cwd); } });
      var last = (kit.home && kit.home()) || st.last;  // 고른 프로젝트가 있으면 그 저장소, 없으면(모든 저장소) 서버가 기억한 마지막 폴더
      if (last && !seen[last]) out.push(last);
      return out.slice(0, MAX_FOLDERS);
    }
    function load() {
      if (!st || st.busy) return;
      var list = folders(), my = st;
      st.busy = true; st.sig = list.join('|');
      Promise.all(list.map(function (cwd) {
        return kit.api('GET', '/api/pipeline' + kit.qs({ cwd: cwd })).then(function (d) { return { cwd: cwd, data: d }; }, function (e) { return { cwd: cwd, error: e }; });
      })).then(function (res) {
        if (my !== st) return;
        st.busy = false; st.results = res;
        clearTimeout(st.again);
        if (res.some(function (r) { return r.data && r.data.loading; })) st.again = setTimeout(load, 2000);  // 서버가 읽는 중이면 곧 다시 묻는다
        if (folders().join('|') !== st.sig) load();
        draw();
      });
    }
    function draw() {
      if (!st || !rootEl) return;
      var narrow = !!(mq && mq.matches), page = [];
      page.push(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '파이프라인' }), h('h1', { text: '요구사항이 지금 어디까지 왔나' }),
        h('p', { class: 'line po-pl-lead', text: 'SRS → 개발 Spec → 개발 → 검토 → 합쳐짐. 하네스는 이 순서를 지키게 해.' })));
      if (!st.results) {
        page.push(kit.loadingBox('요구사항을 읽는 중이야.'));
      } else {
        var gs = groups(st.results), shown = gs.filter(function (g) { return g.data.state !== 'no'; });
        var skipped = [], gone = [], failed = [];
        gs.forEach(function (g) { if (g.data.state === 'no' && skipped.indexOf(g.name) < 0) skipped.push(g.name); });
        st.results.forEach(function (r) {  // 403 = 서버가 아는 작업 폴더가 아니다(지운 worktree 따위). 그 밖은 읽지 못한 것
          if (r.error) (r.error.status === 403 ? gone : failed).push(r.cwd.replace(/[\\/]+$/, '').split(/[\\/]/).pop() + (r.error.status === 403 ? '' : '(' + (r.error.message || '오류') + ')'));
        });
        shown.forEach(function (g) { page.push(panel(g, narrow)); });
        if (!shown.length) {
          page.push(h('section', { class: 'light po-panel po-pl po-pl-empty', 'aria-labelledby': 'po-pl-empty-h' },
            h('header', { class: 'po-ph' }, h('h2', { id: 'po-pl-empty-h', text: st.results.length ? '보일 요구사항이 없어' : '아직 연 프로젝트 폴더가 없어' })),
            note(st.results.length ? 'origin/main 에 SRS(docs/ssot/SRS.md)나 진행 원장(audit/ledger/)이 있는 프로젝트 폴더에서 세션을 열면 요구사항이 여기 칸별로 보여.'
              : '프로젝트 폴더에서 새 작업을 시작하면 그 폴더의 요구사항이 여기 칸별로 보여.'),
            st.results.length ? null : h('div', { class: 'acts' }, kit.link('/new', { class: 'btn', text: '새 작업' }))));
        }
        if (skipped.length) page.push(note('SRS·진행 원장이 없는 폴더는 뺐어: ' + skipped.join(', '), 'skip'));
        if (gone.length) page.push(note('없어진 작업 폴더는 뺐어: ' + gone.join(', '), 'skip'));
        if (failed.length) page.push(note('요구사항을 읽지 못한 폴더: ' + failed.join(', '), 'skip unk'));
      }
      kit.clear(rootEl);
      rootEl.appendChild(h('div', { class: 'page po-pl-page' }, page));
    }
    function view(r) {
      if (st && st.again) clearTimeout(st.again);
      st = { results: null, busy: false, sig: '', last: '' }; rootEl = r;
      var my = st;
      mq = window.matchMedia ? window.matchMedia(NARROW) : null;
      if (mq && mq.addEventListener) mq.addEventListener('change', draw);
      draw();
      kit.api('GET', '/api/folders/last').then(function (d) { if (my === st && d && d.path) st.last = d.path; }, function () {}).then(function () { if (my === st && kit.loaded()) load(); });
      function onData() { if (!st || !kit.loaded()) return; if (!st.results || folders().join('|') !== st.sig) load(); else draw(); }
      return {
        title: function () { return '파이프라인'; },
        onData: onData, onSession: onData, onRemoved: onData,
        tick: load,
        destroy: function () { if (mq && mq.removeEventListener) mq.removeEventListener('change', draw); clearTimeout(my.again); st = null; rootEl = null; }
      };
    }
    return { view: view };
  }

  var api = { LANES: LANES, LABEL: LABEL, numsIn: numsIn, sessionNums: sessionNums, laneOf: laneOf, board: board, groups: groups, summary: summary, create: create };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.BHPostPipeline = api;
})(typeof window !== 'undefined' ? window : this);
