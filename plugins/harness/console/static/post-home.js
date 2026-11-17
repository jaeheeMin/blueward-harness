/* Post(우체국) 테마의 오늘(홈) 화면. Sauce 홈(flow-ui.js homeView)과 같은 데이터·같은 칸(승인 기다리는 PR·최근 산출물·고쳐야 할 내 PR·프로젝트 준비)을 쓰고,
   모양만 시안대로 다시 짠다: 인사 → "지금 세션들"(장면 + 범례) → "내 차례 N건" 덱 → 숫자 칸 → 아래 칸들.
   장면 칸(#1056, 시안 C "현장 메모"): 사무실 장면이 테두리·둥근 모서리 틀 안에 폭 전체로 보이고, 그 위에 내 차례 메모가 뜬다(장면이 알려 준 좌표 옆).
   데이터가 없는 칸은 지어내지 않고 뺀다. 화면은 이벤트마다 통째로 다시 그리되(Sauce 홈과 같다) 장면 패널은 한 번만 만들어 둔다(장면은 매번 새로 만들지 않는다).
   app.js 가 create(kit) 로 한 번 만들고, 홈에 들어올 때마다 view(root, slots) 를 부른다. 덱의 질문 카드는 답이 성공하면 도장이 찍힌 채 잠깐 남는다(app.js stampStub). */
(function () {
  'use strict';

  var DAYS = ['일', '월', '화', '수', '목', '금', '토'];
  var LEGEND = ['turn', 'run', 'wait', 'blocked', 'unk', 'done'];
  /* 사무실 장면(office-post.js) 아래 팀 요약. 갈래(flowId) → 팀. 갈래가 없는 세션은 어느 팀에도 세지 않는다. */
  var TEAMS = [['요구분석팀', ['srs', 'srs-export']], ['설계팀', ['spec']], ['개발팀', ['dev']], ['기능컨설팅팀', ['config']], ['표준화팀', ['standard']], ['유지보수팀', ['fix']]];
  var NARROW = '(max-width: 760px)';  // 이 폭 이하에서는 메모가 장면 아래로 내려온다(시안 media query)

  function teamOf(flow) {
    for (var i = 0; i < TEAMS.length; i++) if (TEAMS[i][1].indexOf(flow) >= 0) return TEAMS[i][0];
    return '';
  }

  function dateLine(d) {
    var hr = d.getHours(), ap = hr < 12 ? '오전' : '오후', h12 = hr % 12 === 0 ? 12 : hr % 12, mm = d.getMinutes();
    return d.getFullYear() + '년 ' + (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + DAYS[d.getDay()] + '요일 · ' + ap + ' ' + h12 + ':' + (mm < 10 ? '0' + mm : mm);
  }

  /* kit: { h, clear, link, requests, L(BHLogic), home(ui.homeKit), questionCards, kindOf, isPlan, requestTitle, skillLabel, waited(v), projectOf(), loaded(), conn(), stateBox, loadingBox, sceneAttach(host) } */
  function create(kit) {
    var h = kit.h, clear = kit.clear, L = kit.L, HK = kit.home, PS = window.BHPostScene, PL = window.BHPostLogic;
    var redrawNow = function () {};
    var qc = kit.questionCards(function () { redrawNow(); }, function () {}, { noAvatar: true });  // 고른 값은 홈을 떠났다 와도 기억한다. 카드 머리에 손님이 이미 있다

    function stMark(kind) { return h('i', { class: 'po-st po-st-' + kind, 'aria-hidden': 'true', text: PS.GLYPH[kind] || '' }); }

    function tile(label, value, cls) {
      return h('div', { class: 'tile2' + (cls ? ' ' + cls : '') }, h('span', { class: 'eb', text: label }), h('span', { class: 'v', text: value }));
    }

    /* 덱에 올릴 카드. 내 차례(오래 기다린 순) 다음에 막힘·확인 못 함. PR 고치기 차례는 "고쳐야 할 내 PR" 칸이 따로 보이니 Sauce 홈처럼 뺀다. */
    function deckItems(list) {
      var turn = [], bad = [];
      list.forEach(function (s) {
        var bk = L.blockOf(s), pend = HK.pendingOf(s);
        if (bk) { bad.push({ id: s.id, kind: bk.kind === 'cannot_check' ? 'unk' : 'blocked', s: s, t: bk.t }); return; }
        // 내 차례는 Sauce 홈·띠와 같은 목록(BHLogic.turnItems)으로 정한다. 답할 요청이 있는 세션만(#1027 D5). PR 고치기는 따로 칸이 있어 뺀다
        if (L.turnItems([s], HK.openIds).some(function (t) { return t.kind === 'request' || t.kind === 'turn'; })) turn.push({ id: s.id, kind: 'turn', s: s, pend: pend });
      });
      turn.sort(function (a, b) { return (a.s.updatedAt || 0) - (b.s.updatedAt || 0); });
      // 방금 답해 도장이 찍힌 카드는 처리됨으로 바뀐 뒤에도 잠깐 남긴다(도장이 보이도록)
      qc.stamped().forEach(function (x) {
        if (turn.some(function (it) { return it.s.id === x.sid && it.pend && it.pend.rid === x.rid; })) { turn.forEach(function (it) { if (it.s.id === x.sid) { it.stampRid = x.rid; it.stampKind = x.kind; } }); return; }
        var s = list.filter(function (q) { return q.id === x.sid; })[0];
        if (s && !turn.concat(bad).some(function (it) { return it.s.id === s.id; })) turn.push({ id: s.id, kind: 'turn', s: s, pend: null, stampRid: x.rid, stampKind: x.kind });
      });
      return turn.concat(bad);
    }

    function kindLabel(it) {
      if (it.kind === 'blocked') return '막힘';
      if (it.kind === 'unk') return '확인 못 함';
      var r = it.pend && it.pend.r;
      if (it.stampRid) return it.stampKind === 'plan' ? '계획' : it.stampKind === 'permission' ? '승인' : '질문';  // 도장이 찍힌 카드는 그 요청의 종류(markStamp 의 kind)로
      if (!r) return '확인';
      var k = kit.kindOf(r);
      return kit.isPlan(r) ? '계획' : k === 'question' || k === 'elicitation' ? '질문' : '승인';
    }

    /* 덱 카드와 메모가 같은 문장·같은 동작을 쓴다: { q: 문장 } 또는 { node: 바로 답하는 질문 폼 }, 그리고 { href, verb }.
       inline 이 false(메모)면 질문 폼을 그리지 않고 문장 + 답하러 가는 링크만 준다(덱의 폼과 같은 칸이 두 번 생기지 않게). */
    function cardAct(it, inline) {
      var s = it.s;
      if (it.kind !== 'turn') {
        var cant = it.kind === 'unk';
        return { q: cant ? '검사를 못 해서 멈췄어 — 통과도 실패도 아니야' : '하네스 검사가 막았어 — 고친 뒤 이어서 하자', href: '/s/' + encodeURIComponent(s.id), verb: '가서 보기' };
      }
      var pend = it.pend, r = pend && pend.r, k = r && kit.kindOf(r);
      if (inline && it.stampRid) { var sq = qc.inlineQuestion(it.stampRid); if (sq) return { node: sq }; }
      if (inline && pend && r && k === 'question') {
        var q = qc.inlineQuestion(pend.rid);  // 보기를 바로 고른다(세션 화면과 같은 폼)
        if (q) return { node: q };
      }
      var plan = !!(r && kit.isPlan(r)), ask = k === 'question' || k === 'elicitation';
      var what = pend ? kit.requestTitle(r) : s.turnSkill === 'deliver' ? kit.skillLabel(s.turnSkill) + ' 끝남 — 다음을 정해 줘' : '내 차례야';
      var verb = ask ? '가서 답하기' : plan ? '가서 계획 보기' : pend ? '가서 승인하기' : '가서 확인하기';
      return { q: what, href: pend ? '/r/' + encodeURIComponent(pend.rid) : '/s/' + encodeURIComponent(s.id), verb: verb };
    }

    function cardBody(it) {
      var a = cardAct(it, true), b = h('div', { class: 'po-dc-b' });
      if (a.node) { b.appendChild(a.node); return b; }
      b.appendChild(h('p', { class: 'po-dc-q', text: a.q }));
      b.appendChild(h('div', { class: 'po-dc-act' }, kit.link(a.href, { class: 'pill acc', text: a.verb })));
      return b;
    }

    /* slots: { sceneHost, whatsSlot, scene() — 지금 붙은 장면 제어(focus(id) 를 줄 수 있으면 준다) } */
    function view(root, slots) {
      var gone = false, topId = null, items = [], officeOn = false, foc = null, focusId = null, memoId = null;
      var approvals = h('div', { class: 'approvals light po-panel po-mini' });
      var recent = h('div', { class: 'light po-panel po-mini', 'data-recent': '1' });
      var projects = h('div', { class: 'projects' });
      var fixBox = h('div', { class: 'fixbox' });
      var stats = HK.homeStats();
      stats.load();

      var helloSlot = h('div', { class: 'po-hello' });
      var sceneSub = h('span', { class: 'po-sub' });
      var calmList = h('ul', { class: 'po-maplist', 'aria-label': '지금 세션들' });  // 차분(fx=0)일 때 장면 대신 보이는 세션 목록(시안 mapFallback)
      var teamRow = h('ul', { class: 'po-teams', 'aria-label': '팀별 세션 수', hidden: true });  // 사무실 장면이 있을 때만(창구 요약 줄 자리)
      var memo = h('div', { class: 'po-memo', role: 'group', 'aria-label': '내 차례 메모', hidden: true });  // 장면 위에 띄우는 내 차례 메모(시안 .memo)
      var stageFrame = h('div', { class: 'po-stagew' }, slots.sceneHost, memo);  // 사무실 장면이 보이면 테두리·둥근 모서리 틀(시안 .stage), 메모는 이 틀 안에서 뜬다
      var scenePanel = h('section', { class: 'light po-panel po-scenep', 'aria-labelledby': 'po-scene-h' },
        h('header', { class: 'po-ph' }, h('h2', { id: 'po-scene-h', text: '지금 세션들' }), sceneSub),
        stageFrame, teamRow, calmList,
        h('ul', { class: 'po-legend', 'aria-label': '상태 표시' }, LEGEND.map(function (k) { return h('li', null, stMark(k), PS.LABEL[k]); })));
      var deckSlot = h('div');
      var restSlot = h('div', { class: 'po-rest' });
      var prSlot = h('div', { class: 'po-prslot' });  // 검토 요청(PR) 칸: Sauce 홈과 같은 줄들 + 그 안에 승인 기다리는 PR
      var foot = h('div', { class: 'po-foot' }, fixBox, recent, prSlot, slots.whatsSlot);
      var body = h('div', { class: 'page home po-home' }, helloSlot, scenePanel, deckSlot, restSlot);
      root.appendChild(body);

      function pickTop(id) { topId = id; paintDeck(); paintMemo(); var q = '"' + CSS.escape(id) + '"', c = deckSlot.querySelector('[data-call=' + q + '], [data-call-block=' + q + ']'); if (c) { var f = c.querySelector('a, button'); if (f) f.focus(); } }
      function step(d) {
        if (items.length < 2) return;
        var i = 0; items.forEach(function (it, n) { if (it.id === topId) i = n; });
        pickTop(items[(i + d + items.length) % items.length].id);
      }
      function onKey(e) {
        if ((e.key !== 'j' && e.key !== 'k') || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
        var t = e.target, tag = t && t.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
        e.preventDefault(); step(e.key === 'j' ? 1 : -1);
      }
      document.addEventListener('keydown', onKey);

      /* 덱을 통째로 다시 그리면 안에 있던 포커스가 body 로 빠진다. 카드(세션 id)와 카드 안 순서로 기억해 두었다가 다시 그린 뒤 그 자리로 돌려놓는다. */
      var FOCUSABLE = 'a, button, input, textarea, select';
      function cardOf(el) { return el.closest('[data-call], [data-call-block]'); }
      function cardId(c) { return c.getAttribute('data-call') || c.getAttribute('data-call-block'); }
      function focusMark() {
        var a = document.activeElement, c = a && a !== document.body && deckSlot.contains(a) ? cardOf(a) : null;
        return c ? { id: cardId(c), i: Array.prototype.indexOf.call(c.querySelectorAll(FOCUSABLE), a) } : null;
      }
      function focusBack(m) {
        if (!m || m.i < 0) return;
        var c = Array.prototype.filter.call(deckSlot.querySelectorAll('[data-call], [data-call-block]'), function (x) { return cardId(x) === m.id; })[0];
        var t = c && c.querySelectorAll(FOCUSABLE)[m.i];
        if (t) t.focus({ preventScroll: true });
      }

      /* 장면에 "이 사람을 보여 줘" 를 알린다. 번들이 옛 판이라 focus 가 없으면 아무것도 안 하고 메모는 기본 위치에 있다. */
      function syncFocus(id) {
        if (focusId === id) return;
        focusId = id;
        if (!id) foc = null;
        var sc = slots.scene && slots.scene();
        if (sc && typeof sc.focus === 'function') sc.focus(id);
      }

      /* 메모 자리: 장면이 알려 준 머리 위 좌표(host 기준 px) 오른쪽에 두고, 모자라면 왼쪽으로 뒤집는다. 좌표가 없으면 CSS 기본 자리(시안). 좁은 화면은 CSS 가 장면 아래에 둔다. */
      function placeMemo() {
        if (memo.hidden) return;
        var narrow = typeof matchMedia === 'function' && matchMedia(NARROW).matches;
        if (!foc || narrow || foc.id !== memoId) { memo.style.left = ''; memo.style.top = ''; memo.style.removeProperty('--tail'); memo.classList.remove('is-flip'); return; }
        var host = slots.sceneHost, W = stageFrame.clientWidth, H = stageFrame.clientHeight, mw = memo.offsetWidth, mh = memo.offsetHeight;
        var ox = host.offsetLeft, oy = host.offsetTop, hx = ox + foc.x, hy = oy + foc.y;
        var x = hx + 24, flip = false, y = hy - 44;
        if (x + mw > W - 8) { x = hx - 24 - mw; flip = true; }
        x = Math.max(8, Math.min(x, W - 8 - mw)); y = Math.max(8, Math.min(y, H - 8 - mh));
        memo.style.left = Math.round(x) + 'px'; memo.style.top = Math.round(y) + 'px';
        memo.style.setProperty('--tail', Math.round(Math.max(14, Math.min(hy - y - 6, mh - 26))) + 'px');
        memo.classList.toggle('is-flip', flip);
      }
      function onFocus(f) { foc = f && typeof f.x === 'number' && typeof f.y === 'number' ? f : null; placeMemo(); }

      /* 내 차례 메모(시안 .memo): 덱과 같은 순서의 topId 한 건. 사무실 장면이 보일 때만(차분이거나 번들이 없으면 없다). 여러 건이면 "다음" 으로 돌린다(J·K 도 된다).
         덱은 그대로 아래에 있다. 메모의 동작은 덱 카드와 같은 문장·같은 링크다. */
      function paintMemo() {
        var a0 = document.activeElement, fi = a0 && a0 !== document.body && memo.contains(a0) ? Array.prototype.indexOf.call(memo.querySelectorAll(FOCUSABLE), a0) : -1;
        var it = officeOn ? items.filter(function (x) { return x.id === topId; })[0] : null;
        clear(memo);
        memo.hidden = !it;
        memoId = it ? it.id : null;
        syncFocus(memoId);
        if (!it) return;
        var s = it.s, name = s.title || HK.folderName(s) || '이름 없는 세션', team = teamOf(s.flowId), a = cardAct(it, false);
        var from = it.pend && it.pend.r ? (it.pend.r.createdAt || it.pend.r.createdAtMs) : (it.t || s.updatedAt), w = kit.waited(from);
        var head = it.kind === 'turn' ? [team || '내 차례', w] : [kindLabel(it), team, w];
        var i = 0; items.forEach(function (x, n) { if (x.id === topId) i = n; });
        var sessionHref = '/s/' + encodeURIComponent(s.id), same = a.href === sessionHref;  // 가는 곳이 세션이면 "세션으로" 를 따로 두지 않는다
        memo.className = 'po-memo po-memo-' + it.kind;
        memo.appendChild(h('div', { class: 'po-memo-h' }, stMark(it.kind), h('span', { class: 'po-memo-kind', text: head.filter(Boolean).join(' · ') }),
          items.length > 1 ? h('button', { type: 'button', class: 'po-link po-memo-next', 'aria-label': '다음 일 보기', text: '다음 ' + (i + 1) + '/' + items.length, onClick: function () { step(1); } }) : null));
        memo.appendChild(h('p', { class: 'po-memo-q', text: a.q }));
        memo.appendChild(h('p', { class: 'po-memo-s', text: name }));
        memo.appendChild(h('div', { class: 'po-memo-acts' }, kit.link(a.href, { class: 'pill acc', text: a.verb }), same ? null : kit.link(sessionHref, { class: 'po-link', text: '세션으로' })));
        placeMemo();
        if (fi >= 0) { var t = memo.querySelectorAll(FOCUSABLE)[fi]; if (t) t.focus({ preventScroll: true }); }
      }

      function paintDeck() {
        var mark = focusMark();
        clear(deckSlot);
        var turnN = items.filter(function (it) { return it.kind === 'turn'; }).length, badN = items.length - turnN;
        if (!items.some(function (it) { return it.id === topId; })) topId = items[0] ? items[0].id : null;
        var nBlocked = items.filter(function (it) { return it.kind === 'blocked'; }).length, nUnk = items.filter(function (it) { return it.kind === 'unk'; }).length;
        var head = h('header', { class: 'po-ph' }, h('h2', null, '내 차례 ', h('b', { class: 'po-num', text: String(turnN) }), ' 건'),
          badN ? h('span', { class: 'po-sub', text: [nBlocked ? '막힌 일 ' + nBlocked + '건' : '', nUnk ? '확인 못 한 검사 ' + nUnk + '건' : ''].filter(Boolean).join(' · ') + ' · 따로 셈' }) : null,
          items.length > 1 ? h('span', { class: 'po-hint', text: 'J · K 다음 · 이전' }) : null);
        var stack = h('div', { class: 'po-stack' });
        if (!items.length) stack.appendChild(h('p', { class: 'quiet', text: '지금 네 답을 기다리는 일이 없어.' }));
        items.forEach(function (it) {
          var s = it.s, top = it.id === topId, name = s.title || HK.folderName(s) || '이름 없는 세션';
          var st = PS.stateOf(s, L), href = '/s/' + encodeURIComponent(s.id);
          var from = it.pend && it.pend.r ? (it.pend.r.createdAt || it.pend.r.createdAtMs) : (it.t || s.updatedAt);
          var w = kit.waited(from);
          var attrs = it.kind === 'turn' ? { 'data-call': s.id } : { 'data-call-block': s.id, 'data-block-kind': it.kind === 'unk' ? 'cannot_check' : 'blocked' };
          var hd = h('div', { class: 'po-dc-h' }, PS.avatar(s.id, st), stMark(it.kind),
            h('span', { class: 'po-dc-kind', text: kindLabel(it) }), kit.link(href, { class: 'po-dc-s', text: name }),
            w ? h('span', { class: 'po-dc-wait', text: w }) : null,
            top ? null : h('button', { type: 'button', class: 'pill line sm', 'aria-expanded': 'false', 'aria-label': name + ' 펼치기', text: '열기', onClick: function () { pickTop(it.id); } }));
          stack.appendChild(h('article', Object.assign({ class: 'po-dc po-dc-' + it.kind + (top ? ' is-top' : '') }, attrs), hd, top ? cardBody(it) : null));
        });
        deckSlot.appendChild(h('section', { class: 'light po-panel po-deck', 'aria-label': '내 차례' }, head, stack));
        focusBack(mark);
      }

      /* 차분: 장면이 없는 대신 같은 세션(장면에 올리는 것과 같은 줄)을 목록으로. 손님 아바타는 정지 그림, 둘째 줄은 상태 기호 + 상태 글 · 창구. */
      function paintCalm() {
        clear(calmList);
        calmList.hidden = !PS.calm();
        if (calmList.hidden) return;
        kit.sceneList().forEach(function (s) {
          var name = s.title || '이름 없는 세션', k = Math.max(0, Math.min(4, s.station | 0));
          calmList.appendChild(h('li', { class: 'po-ml po-ml-' + s.state },
            kit.link('/s/' + encodeURIComponent(s.id), { class: 'po-ml-a' }, PS.avatar(s.id, s.state, { size: 'sm' }),
              h('span', null, h('b', { text: name }), h('small', null, stMark(s.state), PS.LABEL[s.state] + ' · ' + (k + 1) + '번 창구 ' + PL.STATION[k].name)))));
        });
        if (!calmList.firstChild) calmList.appendChild(h('li', { class: 'quiet', text: '지금 일하는 세션이 없어.' }));
      }

      /* 사무실 장면 아래 팀 이름과 인원 수. 장면이 안 그려지는 차분(fx=0)이거나 사무실 장면이 없으면 숨긴다. */
      function paintTeams() {
        clear(teamRow);
        teamRow.hidden = !window.BHOfficeScene || PS.calm();
        if (teamRow.hidden) return;
        var list = kit.sceneList();
        TEAMS.forEach(function (t) {
          var n = list.filter(function (s) { return t[1].indexOf(s.flow) >= 0; }).length;
          teamRow.appendChild(h('li', { class: n ? 'has' : '' }, h('b', { text: t[0] }), h('span', { text: n + '명' })));
        });
      }

      function draw() {
        if (gone) return;
        if (!kit.loaded()) {
          scenePanel.hidden = true; memo.hidden = true; syncFocus(null); clear(helloSlot); clear(deckSlot); clear(restSlot);
          restSlot.appendChild(kit.conn() === 'down' ? kit.stateBox('warn', '서버에 연결할 수 없어', '서버가 꺼졌을 수 있어. 다시 연결을 시도하고 있어.') : kit.loadingBox('세션을 불러오는 중이야.'));
          return;
        }
        var list = HK.sessionList();
        clear(helloSlot); clear(restSlot);
        if (!list.length) {  // 세션이 없으면 Sauce 와 같은 첫 작업 안내(시안: C단계가 다듬는다)
          scenePanel.hidden = true; memo.hidden = true; syncFocus(null); clear(deckSlot); clear(prSlot); items = []; delete approvals.dataset.compact; approvals.className = 'approvals light po-panel po-mini';
          HK.emptyHome(restSlot, approvals, projects);
          HK.approvalCard(approvals, stats.showPr); HK.projectCard(projects);
          return;
        }
        scenePanel.hidden = false;
        officeOn = !!window.BHOfficeScene && !PS.calm();  // 사무실 장면이 보일 때만 틀·메모(차분이거나 번들이 없으면 지금 그대로)
        stageFrame.classList.toggle('is-office', officeOn);
        approvals.className = 'approvals'; approvals.dataset.compact = '1';  // 검토 요청 칸 안에서는 줄로 그린다(Sauce 홈과 같다)
        clear(prSlot); prSlot.appendChild(h('div', { class: 'light po-panel po-mini' }, HK.homePrBox(list, approvals)));
        var c = L.counts(list, HK.openIds), turnCount = L.turnItems(list, HK.openIds).length;  // 내 차례 숫자는 Sauce 홈·띠와 같은 목록 길이(#1027)
        sceneSub.textContent = c.total + '개';
        paintCalm();
        paintTeams();
        var proj = kit.projectOf() || HK.folderName(list[0]);
        helloSlot.appendChild(h('p', { class: 'po-date', text: dateLine(new Date()) + (proj ? ' · ' + proj : '') }));
        helloSlot.appendChild(h('h1', { text: '오늘 내 일' }));
        helloSlot.appendChild(h('p', { class: 'po-lede' }, '세션 ' + c.total + '개 중 ' + c.running + '개가 일하고 있어. ',
          turnCount ? h('b', { text: '네 답을 기다리는 일이 ' + turnCount + '건 있어.' }) : L.NO_TURN_TEXT + '.'));
        items = deckItems(list);
        paintDeck();
        paintMemo();
        restSlot.appendChild(h('div', { class: 'tiles2 po-tiles' }, tile('내 차례', String(turnCount), turnCount ? 'warn' : ''), tile('AI가 일하는 중', String(c.running), ''), stats.prTile, stats.weekTile, stats.tbTile));
        restSlot.appendChild(HK.homeTable(list));  // 내 세션 표(작업·단계·번호·기억·상태): Sauce 홈과 같은 칸
        restSlot.appendChild(foot);
        restSlot.appendChild(projects);
        HK.recentCard(recent, stats.showWeek);
        HK.approvalCard(approvals, stats.showPr);
        HK.projectCard(projects);
        HK.fixCard(fixBox);
      }
      redrawNow = function () { if (!gone) draw(); };
      function onPref(ev) { if (ev && ev.detail === 'fx') redrawNow(); }  // 효과 강도가 바뀌면 장면 ↔ 목록
      document.addEventListener('bh-pref', onPref);
      var ro = typeof ResizeObserver === 'function' ? new ResizeObserver(function () { placeMemo(); }) : null;  // 폭이 바뀌면(창 크기·760px 경계) 메모 자리를 다시 잡는다
      if (ro) ro.observe(stageFrame);
      draw();

      // 세션 이벤트가 초당 수십 번 와도 0.5초에 한 번, 프레임에 맞춰 다시 그린다. 덱의 입력칸에 쓰는 중이면 쓰기가 끝날 때까지 미룬다.
      var soonOn = false, soonLast = 0;
      function typing() { var a = document.activeElement; return !!(a && a.tagName === 'INPUT' && deckSlot.contains(a)); }
      function drawSoon() {
        if (soonOn || gone) return;
        soonOn = true;
        setTimeout(function () {
          requestAnimationFrame(function () {
            soonOn = false; soonLast = Date.now();
            if (gone) return;
            if (typing()) { drawSoon(); return; }
            draw();
          });
        }, Math.max(0, (typing() ? 1000 : 500) - (Date.now() - soonLast)));
      }
      return {
        onData: drawSoon, onSession: drawSoon, onRequest: drawSoon, onRemoved: draw, onFocus: onFocus,
        tick: function () { if (!typing()) draw(); },  // 날짜 줄·기다린 시간을 고친다
        title: function () { return ''; },
        destroy: function () { gone = true; redrawNow = function () {}; if (ro) ro.disconnect(); document.removeEventListener('keydown', onKey); document.removeEventListener('bh-pref', onPref); }
      };
    }

    return { view: view };
  }

  window.BHPostHome = { create: create, dateLine: dateLine };
})();
