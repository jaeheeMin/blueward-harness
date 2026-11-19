/* Post(Cozy Office) 테마의 오늘(홈) 화면. Sauce 홈(flow-ui.js homeView)과 같은 데이터·같은 칸(승인 기다리는 PR·최근 산출물·고쳐야 할 내 PR·프로젝트 준비)을 쓰고,
   모양만 시안대로 다시 짠다: 인사 → "지금 세션들"(장면 + 그 아래 정리) → "나를 찾는 사람" 덱 → 내 세션 → 아래 칸들.
   한 정보는 한 자리에만 둔다(요약 정리, 2026-11-19): 세션 수는 장면 머리, 상태별 수는 장면 아래 정리 줄(범례에 숫자를 붙였다), 몇 번째인지는 장면 버튼 —
   인사 문장·덱 머리·숫자 칸 줄·메모 머리에 같은 숫자를 되풀이하지 않는다. 덱 카드 순서는 장면이 사람을 돌아보는 순서와 같다(deckItems).
   장면 칸(#1056, 시안 C "현장 메모"): 사무실 장면이 테두리·둥근 모서리 틀 안에 폭 전체로 보이고, 그 위에 내 차례 메모가 뜬다(장면이 알려 준 좌표 옆).
   장면은 디오라마 번들(post/office/office-post.js, 계약 version 2)이고 메모는 여기서 그린다: 번들이 보는 사람 자리(onFocus)·누른 사람(onPick)·빈 바닥(onBackground)·전체 보기(onOverview)를 알려 준다.
   데이터가 없는 칸은 지어내지 않고 뺀다. 화면은 이벤트마다 통째로 다시 그리되(Sauce 홈과 같다) 장면 패널은 한 번만 만들어 둔다(장면은 매번 새로 만들지 않는다).
   app.js 가 create(kit) 로 한 번 만들고, 홈에 들어올 때마다 view(root, slots) 를 부른다. 덱의 질문 카드는 답이 성공하면 도장이 찍힌 채 잠깐 남는다(app.js stampStub). */
(function () {
  'use strict';

  var DAYS = ['일', '월', '화', '수', '목', '금', '토'];
  /* 장면 아래 정리 줄에 서는 상태 순서: 나를 찾는 사람(내 차례·막힘·확인 못 함 — 장면 버튼 「나를 찾는 사람」 이 세는 묶음) → 일하는 중·승인 기다림 → 끝·쉬는 중. 일곱 수를 더하면 장면 머리의 세션 수다 */
  var SUM = ['turn', 'blocked', 'unk', 'run', 'wait', 'done', 'idle'];
  /* 사무실 장면(office-post.js) 아래 팀 요약. 갈래(flowId) → 팀 표는 post-logic.js 에 있다(세션 화면 안내판과 같은 표). 갈래가 없거나 팀이 없는 갈래의 세션은 끝에 "팀 없음" 으로 따로 센다(paintTeams). */
  var TEAMS = window.BHPostLogic.TEAMS, teamOf = window.BHPostLogic.teamOf;
  var MY_PRS_POLL_MS = 20000;  // 열린 PR 상태를 확인하는 간격. 읽기는 flow-ui.js 가 60초 캐시로 막아 주고(고른 칸만 다시 그리고 네트워크는 안 부른다), 그 캐시를 여기서 비울 수 없어서 Sauce 홈의 61초 한 번 대신 짧게 자주 본다 — 캐시가 풀린 뒤 최대 20초 안에 새로 읽는다
  var NARROW = '(max-width: 760px)';  // 이 폭 이하에서는 메모가 장면 아래로 내려온다(시안 media query)
  var UNDER_W = 720;  // 장면 틀이 이 폭보다 좁아도 메모를 장면 아래에 둔다(번들이 버튼 글자를 빼는 폭과 같다). 틀 높이가 300px 아래라 떠 있는 메모가 아래 버튼 줄을 덮고, 사람 양옆 어디에도 자리가 없다
  var CALM_MAX = 12;  // 차분 목록에 처음 보이는 세션 수(나머지는 "더 보기")
  var SVGNS = 'http://www.w3.org/2000/svg';
  /* 장면 번들과 같은 규칙(ai-office-iso src/diorama/seating.ts isAsk·timeOf, office-post.ts lead): 손 든 사람은 내 차례·막힘·확인 못 함, 가장 오래 기다린 사람이 먼저 */
  var ASK = { turn: 1, blocked: 1, unk: 1 };
  function pickKindOf(state) { return ASK[state] ? 'ask' : state === 'done' ? 'done' : ''; }
  function timeOf(t) { return typeof t === 'number' ? t : t ? Date.parse(t) || Infinity : Infinity; }
  function leadOf(list) {
    var best = null, bt = Infinity;
    list.forEach(function (s) { if (!ASK[s.state]) return; var t = timeOf(s.t); if (best === null || t < bt) { best = s.id; bt = t; } });  // 같은 시각이면 목록에서 먼저 온 사람(번들의 정렬과 같다)
    return best;
  }
  function closeIcon() {
    var s = document.createElementNS(SVGNS, 'svg'), p = document.createElementNS(SVGNS, 'path');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('width', '16'); s.setAttribute('height', '16'); s.setAttribute('aria-hidden', 'true');
    s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '2.2'); s.setAttribute('stroke-linecap', 'round');
    p.setAttribute('d', 'M6 6l12 12M18 6L6 18'); s.appendChild(p);
    return s;
  }

  function dateLine(d) {
    var hr = d.getHours(), ap = hr < 12 ? '오전' : '오후', h12 = hr % 12 === 0 ? 12 : hr % 12, mm = d.getMinutes();
    return d.getFullYear() + '년 ' + (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + DAYS[d.getDay()] + '요일 · ' + ap + ' ' + h12 + ':' + (mm < 10 ? '0' + mm : mm);
  }

  /* kit: { h, clear, link, requests, L(BHLogic), home(ui.homeKit), questionCards, kindOf, isPlan, requestTitle, skillLabel, waited(v), projectOf(), projectTag(s), loaded(), conn(), stateBox, loadingBox, sceneAttach(host) } */
  function create(kit) {
    var h = kit.h, clear = kit.clear, L = kit.L, HK = kit.home, PS = window.BHPostScene, PL = window.BHPostLogic;
    var redrawNow = function () {};
    var qc = kit.questionCards(function () { redrawNow(); }, function () {}, { noAvatar: true });  // 고른 값은 홈을 떠났다 와도 기억한다. 카드 머리에 사람이 이미 있다

    function stMark(kind, tone) { return h('i', { class: 'po-st po-st-' + kind, 'data-color-role': tone || null, 'aria-hidden': 'true', text: PS.GLYPH[kind] || '' }); }

    /* 덱에 올릴 카드: 나를 찾는 사람 — 내 차례·막힘·확인 못 함. PR 검사가 실패한 세션(고쳐야 함)도 내 차례라 카드로 올린다("고쳐야 할 내 PR" 칸은 따로 그대로 있다).
       순서는 장면과 같다: 가장 오래 기다린 사람부터, 막힘·확인 못 함도 같이 섞어(번들 group(list, 'ask') — t 오름차순, 같으면 장면 목록 순서).
       그래서 덱 맨 위 카드 = 장면이 스스로 고른 사람 = 메모의 사람이고, J·K 와 장면 버튼 「나를 찾는 사람」 이 같은 차례로 돈다(전에는 내 차례 다음에 막힘이라 메모와 덱 맨 위가 달랐다). */
    function deckItems(list) {
      var turn = [], bad = [];
      list.forEach(function (s) {
        var bk = L.blockOf(s), pend = HK.pendingOf(s);
        if (bk) { bad.push({ id: s.id, kind: bk.kind === 'cannot_check' ? 'unk' : 'blocked', s: s, t: bk.t }); return; }
        // 내 차례는 Sauce 홈·띠와 같은 목록(BHLogic.turnItems)으로 정한다. 답할 요청이 있는 세션(#1027 D5)과 PR 검사가 실패한 세션
        var mine = L.turnItems([s], HK.openIds);
        var asks = mine.filter(function (t) { return t.kind === 'request'; }).length;  // 한 세션에 답할 요청이 여럿이면 카드는 하나, "요청 +N" 으로 알린다(머리 숫자는 요청마다 센다)
        // n = 이 카드가 맡은 내 차례 건수(turnItems 항목 수). 덱 머리 "내 차례 N건" 은 이 n 의 합이라 메모가 "내 차례 2–3/6" 처럼 같은 단위로 센다
        if (mine.some(function (t) { return t.kind === 'request' || t.kind === 'turn'; })) turn.push({ id: s.id, kind: 'turn', s: s, pend: pend, more: Math.max(0, asks - 1), n: mine.length });
        else if (mine.length && L.prNeedsFix(s)) turn.push({ id: s.id, kind: 'turn', s: s, pend: null, fix: true, n: mine.length });
      });
      // 방금 답해 도장이 찍힌 카드는 처리됨으로 바뀐 뒤에도 잠깐 남긴다(도장이 보이도록)
      qc.stamped().forEach(function (x) {
        if (turn.some(function (it) { return it.s.id === x.sid && it.pend && it.pend.rid === x.rid; })) { turn.forEach(function (it) { if (it.s.id === x.sid) { it.stampRid = x.rid; it.stampKind = x.kind; it.stampDecision = x.decision; } }); return; }
        var s = list.filter(function (q) { return q.id === x.sid; })[0];
        if (s && !turn.concat(bad).some(function (it) { return it.s.id === s.id; })) turn.push({ id: s.id, kind: 'turn', s: s, pend: null, stampRid: x.rid, stampKind: x.kind, stampDecision: x.decision, n: 0 });  // 이미 처리됨: 내 차례 건수에 안 든다
      });
      var at = {};
      kit.sceneList().forEach(function (x, i) { at[x.id] = i; });
      function seat(it) { return at[it.id] == null ? 1e9 : at[it.id]; }  // 장면에 없는 세션은 같은 시각이면 뒤로
      // 방금 답해 도장만 남은 카드(이미 처리됨 — 장면에서는 더는 손 든 사람이 아니다)는 순서에 넣지 않고 끝에 둔다: 맨 위 카드는 늘 장면이 스스로 고르는 사람이다
      var all = turn.concat(bad), left = all.filter(function (it) { return it.kind === 'turn' && !it.n; });
      var live = all.filter(function (it) { return left.indexOf(it) < 0; }).map(function (it) { return { t: it.s.updatedAt, seat: seat(it), it: it }; });
      return PL.byWait(live).map(function (r) { return r.it; }).concat(left);
    }

    /* 덱 카드·메모의 역할 색(theme-post.css [data-color-role]): 막힘·검사 실패는 오류, 확인 못 함은 보라, 승인·계획은 경고(승인 전 확인), 질문·확인은 알림.
       알림 말풍선(notice-logic.js kindMeta)과 같은 배정이다 — 같은 일이 자리마다 다른 색이면 안 된다. */
    function toneOf(it) {
      if (it.kind === 'blocked' || it.fix) return 'err';
      if (it.kind === 'unk') return 'unk';
      var lb = kindLabel(it);
      return lb === '승인' || lb === '계획' ? 'warn' : 'ask';
    }
    function kindLabel(it) {
      if (it.kind === 'blocked') return PL.LABEL.blocked;  // 막힘·확인 못 함은 요청 종류가 아니라 상태라 상태 이름(「막혔어요」·「확인하지 못했어요」)으로 부른다
      if (it.kind === 'unk') return PL.LABEL.unk;
      if (it.fix) return '고쳐야 함';
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
        return { q: cant ? '검사를 못 해서 멈췄어요 — 통과도 실패도 아니에요' : '하네스 검사가 막았어요 — 고친 뒤 이어서 해요', href: '/s/' + encodeURIComponent(s.id), verb: '가서 보기' };
      }
      var pend = it.pend, r = pend && pend.r, k = r && kit.kindOf(r);
      if (it.fix) return { q: 'PR #' + s.flowPr.number + ' 의 자동 검사가 실패했어요 — 고친 뒤 다시 올려요', href: '/s/' + encodeURIComponent(s.id), verb: '가서 고치기' };
      if (inline && it.stampRid) { var sq = qc.inlineQuestion(it.stampRid); if (sq) return { node: sq }; }
      if (it.stampRid && !pend) return { q: PL.stampedLine(it.stampDecision), href: '/s/' + encodeURIComponent(s.id), verb: '세션 보기' };  // 도장이 잠깐 남은 카드(메모에는 폼이 없다). 카드에 찍힌 도장 글자로 말한다
      if (inline && pend && r && k === 'question') {
        var q = qc.inlineQuestion(pend.rid);  // 보기를 바로 고른다(세션 화면과 같은 폼)
        if (q) return { node: q };
      }
      var plan = !!(r && kit.isPlan(r)), ask = k === 'question' || k === 'elicitation';
      // 올릴 차례(turnSkill deliver)는 올리기가 끝난 게 아니라 올릴지 정할 때다. 갈래 세션은 지금 단계(PL.turnLine), 올리기 단계면 세션 카드와 같은 질문
      var what = pend ? kit.requestTitle(r) : (PL && PL.turnLine(s, L)) || (s.turnSkill !== 'deliver' ? '확인할 일이 있어요' : s.flowId ? L.ASK_TEXT.deliver.q : '이제 ' + kit.skillLabel(s.turnSkill) + ' 차례예요.');
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

    /* 상태 칩(시안 .st): 색 + 모양. 답을 기다려요 세모 · 일하는 중 채운 동그라미 · 승인 기다림 네모 · 쉬는 중 빈 동그라미 · 막힘 마름모 · 확인 못 함 점선 동그라미 · 끝 체크.
       글은 장면·정리 줄·메모와 같은 상태 이름(PS.LABEL — 번들 LABEL 과 같은 해요체)이다. 칩만 따로 짧은 이름(「내 차례」·「끝남」)을 쓰던 것을 문구 6회차에 하나로 합쳤다. */
    function stChip(state, tone) { return h('span', { class: 'po-stc po-stc-' + state, 'data-color-role': tone || null, text: PS.LABEL[state] || '' }); }
    /* 세션 표의 상태 칩: Sauce 표(flow-ui.js homeTable)와 같은 판정이다. API 오류(#865)는 '끝남'·'쉬는 중' 이 아니라 오류로, PR 검사가 실패한 세션은 "내 차례" 가 아니라 "고쳐야 함" 으로 말한다.
       (막힘·확인 못 함은 stateOf 가 이미 가린다.) */
    function rowChip(s, st) {
      var bk = L.blockOf(s), an = !bk && window.BHApiNotice ? window.BHApiNotice.notice(s) : null;
      if (an && an.sideTone === 'err') return h('span', { class: 'po-stc po-stc-err', title: an.title, text: an.side });
      var g = L.groupOf(s, HK.openIds);
      if (!bk && s.status !== 'ended' && g !== 'running' && !HK.pendingOf(s) && L.prNeedsFix(s)) return h('span', { class: 'po-stc po-stc-turn', 'data-color-role': 'err', title: 'PR #' + s.flowPr.number + ' 의 자동 검사가 실패했어요', text: '고쳐야 함' });
      return stChip(st, st === 'turn' && kit.turnTone ? kit.turnTone(s) : '');
    }

    /* 번호·기억(Sauce 표의 '번호'·'기억' 칸): 이슈 번호는 브랜치 이름에서, PR 은 연결된 것만, 기억은 % 나 토큰 수를 알 때만. 모르는 값은 지어내지 않고 뺀다(점선 ? 는 소음, #1066).
       줄 전체가 세션 링크라 안에 링크를 둘 수 없다 — PR 은 글자만 보이고 주소는 PR 칸에서 간다. */
    function metaLine(s) {
      var issue = L.issueOf(s), pr = L.prBadge(s.flowPr), m = L.memoryOf(s), parts = [];
      if (issue) parts.push(h('span', { class: 'mono', text: '이슈 #' + issue }));
      // 칩 색·기호는 검사 결과(checks)로 정하지만 합쳐진·닫힌 PR 은 남은 검사 결과가 아니라 상태로(닫힌 PR 이 빨간 ✕ "닫힘" 으로 보이지 않게)
      var prSt = pr && String(s.flowPr.state || '').toUpperCase(), prCls = prSt === 'MERGED' ? 'pass' : prSt === 'CLOSED' ? 'none' : pr && pr.checks;
      if (pr) parts.push(h('span', { class: 'prchip ' + prCls, text: 'PR #' + pr.number + ' · ' + pr.text }));
      if (m.kind !== 'unknown') parts.push(h('span', { class: 'mono' + (m.level ? ' ' + m.level : ''), title: m.title, text: '기억 ' + m.text }));
      return parts.length ? h('div', { class: 't3' }, parts) : null;
    }

    /* 결재란(시안 .kyul): 칸은 그 세션 갈래의 실제 단계(BHLogic.barSteps — 홈 표의 단계 막대와 같은 값)이고 이름은 짧은 이름(stepShort).
       끝난 칸은 붉은 도장(결재 도장), 지금 칸은 남색 줄. 갈래가 없으면 칸이 없고 자리만 비운다(줄 정렬이 흔들리지 않게 자리 폭은 목록에서 가장 긴 결재란에 맞춘다). */
    var KYUL_CELL = 64;  // 칸 하나의 폭(px). 갈래 단계의 짧은 이름은 여섯 글자 이하(workflow.json)
    function kyul(steps) {
      if (!steps.length) return null;
      var now = steps.filter(function (x) { return x.state === 'now'; })[0], fin = steps.every(function (x) { return x.state === 'done' || x.state === 'skipped'; });
      return h('span', { class: 'po-kyul', role: 'img', 'aria-label': '결재란: ' + (fin ? '모든 단계 끝' : now ? L.stepShort(now) + ' 단계' : '단계 확인 못 함') },
        steps.map(function (st) {
          return h('span', { class: st.state === 'done' ? 'done' : st.state === 'now' ? 'now' : '', title: st.name }, h('small', { text: L.stepShort(st) }), h('em'));
        }));
    }

    /* 내 세션(시안 section.panel.cols + ul.ss): 두 단(1100px 이하 한 단). 줄 전체가 그 세션 링크. 줄 순서는 Sauce 홈 표와 같은 목록이다.
       둘째 줄은 팀 이름, 갈래는 있어도 팀이 없으면 갈래 이름, 갈래가 없으면 "정해진 갈래 없음"(Sauce 표의 둘째 줄과 같은 글). */
    function sessionsPanel(list) {
      var maxN = 0, rows, ended = list.filter(function (s) { return s.status === 'ended'; }).length;
      var all = list.map(function (s) { var steps = s.flowId ? L.barSteps(s) : []; if (steps.length > maxN) maxN = steps.length; return { s: s, steps: steps }; });
      rows = all.map(function (x) {
        var s = x.s, st = PS.stateOf(s, L), name = s.title || HK.folderName(s) || '이름 없는 세션';
        var sub = teamOf(PL.teamFlowOf(s)) || (s.flowId ? (s.flowName || s.flowId) : '정해진 갈래 없음');
        return h('li', { 'data-session': s.id }, kit.link('/s/' + encodeURIComponent(s.id), { class: 'po-ssa' },
          PS.avatar(s.id, st, { size: 'sm', name: name }),  // 사무실 장면의 그 사람(작은 칸은 안 움직인다). 번들이 없으면 제목 첫 글자
          h('div', { class: 'po-rt' }, h('div', { class: 't1', text: name, title: name }), h('div', { class: 't2' }, sub, kit.projectTag ? kit.projectTag(s) : null), metaLine(s)),  // 같은 저장소의 다른 폴더·저장소 확인 못 함 표(#1070)
          h('span', { class: 'po-kyulc', style: 'width:' + (maxN ? maxN * KYUL_CELL + 2 : 0) + 'px' }, kyul(x.steps)),
          rowChip(s, st)));
      });
      return h('section', { class: 'light po-panel po-cols', 'aria-labelledby': 'po-ss-h' },
        // 세션 수는 장면 머리 한 곳에만 있다("지금 세션들 N개" — 끝난 세션은 장면에 없다). 여기는 그 수와 달라지는 까닭(끝난 세션)만 말한다
        h('div', { class: 'po-ph' }, h('h2', { id: 'po-ss-h', text: '내 세션' }), ended ? h('span', { class: 'po-sub', 'data-ended': String(ended), text: '끝난 세션 ' + ended + '개도 같이 보여요' }) : null),
        h('ul', { class: 'po-mine' }, rows));
    }

    /* slots: { sceneHost, whatsSlot, scene() — 지금 붙은 장면 제어(focus(id) 를 줄 수 있으면 준다) } */
    function view(root, slots) {
      var calmAll = false, gone = false, topId = null, items = [], officeOn = false, foc = null, memoId = null;
      /* 메모가 누구 것인가(승인된 동작 시안): 고른 사람이 없으면 장면이 스스로 고른 사람(가장 오래 기다린 사람 — 번들의 auto 와 같은 사람)의 메모다.
         pickId: 사용자가 고른 세션(장면의 사람·버튼, 메모의 「다음」, J·K, 덱의 「열기」). pickKind: 고를 때 그 사람이 손을 들고 있었는지('ask')·끝냈는지('done') —
                 그 상태가 풀리면 번들이 스스로 놓고 다음 사람으로 가니(letGo) 여기도 같이 놓는다.
         shutId: 사용자가 메모를 닫은 세션(Esc · 빈 바닥 · ×). 장면의 줌·조명은 그대로다. 메모가 다른 사람 것으로 바뀌거나 사람·버튼을 누르면 다시 열린다
                 (불러오는 중·세션 0개로 메모가 잠깐 없어졌다 돌아와도 같은 사람이면 닫힌 채다).
         over: 「전체 보기」 중. 아무도 보지 않으니 메모가 없고, 사용자가 누군가를 고를 때까지 장면을 돌리지 않는다.
         told: 장면에 마지막으로 알린 것(세션 id | null = 스스로 고르기). undefined 면 다음에 꼭 다시 알린다. */
      var pickId = null, pickKind = '', shutId = null, over = false, told = null, saidOpen = false;
      var approvals = h('div', { class: 'approvals light po-panel po-mini' });
      var recent = h('div', { class: 'light po-panel po-mini', 'data-recent': '1' });
      /* 이번 주에 뽑은 산출물 수: 숫자 칸 줄에 따로 있던 것을 최근 산출물 칸 머리 바로 아래로 옮겼다(recentCard 가 머리를 그린 직후 부른다). 0 개와 확인 못 함은 그 칸의 문장이 이미 말한다 */
      function showWeek(n) { if (n > 0) recent.appendChild(h('span', { class: 'po-week', 'data-week': String(n), text: '이번 주에 ' + n + '개 뽑았어요' })); }
      var projects = h('div', { class: 'projects' });
      var fixBox = h('div', { class: 'fixbox' });
      var stats = HK.homeStats();
      stats.load();

      var helloSlot = h('div', { class: 'po-hello' });
      var sceneSub = h('span', { class: 'po-sub' });
      var calmList = h('ul', { class: 'po-maplist', 'aria-label': '지금 세션들' });  // 차분(fx=0)일 때 장면 대신 보이는 세션 목록(시안 mapFallback)
      var teamRow = h('ul', { class: 'po-teams', 'aria-label': '팀별 세션 수', hidden: true });  // 사무실 장면이 있을 때만(옛 요약 줄 자리)
      var sumRow = h('ul', { class: 'po-sum', 'aria-label': '상태별 세션 수' });  // 장면 아래 정리 줄: 상태 기호 + 이름 + 수(범례를 겸한다). 차분 목록 아래에도 같은 줄이 있다
      var memo = h('div', { class: 'po-memo', role: 'group', 'aria-label': '나를 찾는 사람 메모', hidden: true });  // 장면 위에 띄우는 나를 찾는 사람 메모(시안 .memo — 덱 맨 위와 같은 사람)
      var memoLive = h('p', { class: 'sr-only', role: 'status', 'aria-live': 'polite', 'data-memo-live': '1' });  // 메모가 바뀌면 읽기 프로그램에 알린다(메모 자신은 hidden 이 되기도 하고 다시 그려져 알림이 안 간다)
      var memoSaid = '';
      var stageFrame = h('div', { class: 'po-stagew' }, slots.sceneHost, memo, memoLive);  // 사무실 장면이 보이면 테두리·둥근 모서리 틀(시안 .stage), 메모는 이 틀 안에서 뜬다
      var scenePanel = h('section', { class: 'light po-panel po-scenep', 'aria-labelledby': 'po-scene-h' },
        h('header', { class: 'po-ph' }, h('h2', { id: 'po-scene-h', text: '지금 세션들' }), sceneSub),
        stageFrame, calmList, sumRow, teamRow);
      var deckSlot = h('div');
      var restSlot = h('div', { class: 'po-rest' });
      var prSlot = h('div', { class: 'po-prslot' });  // 검토 요청(PR) 칸: Sauce 홈과 같은 줄들 + 그 안에 승인 기다리는 PR
      var tbSlot = h('div', { class: 'po-tiles po-tb' }, stats.tbTile);  // 팀 기록(아직 안 풀린 문제 수 · 보기): 숫자 칸 줄에서 아래 칸들 옆으로 옮겼다
      var foot = h('div', { class: 'po-foot' }, fixBox, recent, prSlot, tbSlot, slots.whatsSlot);
      var body = h('div', { class: 'page home po-home' }, helloSlot, scenePanel, deckSlot, restSlot);
      root.appendChild(body);

      /* stay: 메모의 "다음" 처럼 포커스를 그 자리에 두고 싶을 때. 덱 카드로 포커스를 옮기면 화면이 덱까지 스크롤돼 방금 누른 메모가 밀려 나간다 */
      function setPick(id) {
        var si = kit.sceneList().filter(function (x) { return x.id === id; })[0];
        pickId = id; pickKind = si ? pickKindOf(si.state) : ''; shutId = null;
        leaveOver();
      }
      function leaveOver() { if (over) { over = false; told = undefined; } }  // 전체 보기에서 나온다: 같은 사람이어도 장면에 다시 알린다
      function pickTop(id, stay) { topId = id; setPick(id); paintDeck(); paintMemo(); if (stay) return; var q = '"' + CSS.escape(id) + '"', c = deckSlot.querySelector('[data-call=' + q + '], [data-call-block=' + q + ']'); if (c) { var f = c.querySelector('a, button'); if (f) f.focus(); } }
      function step(d, stay) {
        if (items.length < 2) return;
        var at = memoId && items.some(function (it) { return it.id === memoId; }) ? memoId : topId;  // 메모가 보이는 일에서 이어 간다(메모가 스스로 고른 사람이 덱 맨 위와 다를 수 있다)
        var i = 0; items.forEach(function (it, n) { if (it.id === at) i = n; });
        pickTop(items[(i + d + items.length) % items.length].id, stay);
      }
      function onKey(e) {
        if (e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
        var t = e.target, tag = t && t.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
        if (e.key === 'Escape') {  // 메모 닫기. 팝업·확인 창이 떠 있으면 그쪽이 Esc 를 쓴다
          if (e.defaultPrevented || document.querySelector('.nb-back, .modal-back') || (t && t.closest && t.closest('[role="dialog"], [role="menu"], [aria-modal="true"]'))) return;
          if (closeMemo()) e.preventDefault();
          return;
        }
        if (e.key !== 'j' && e.key !== 'k') return;
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

      /* 장면에 누구를 볼지 알린다: 세션 id 면 그 사람, null 이면 장면이 스스로 고른다(가장 오래 기다린 사람, 없으면 사무실 전체). 전체 보기 중에는 돌리지 않는다. */
      function syncFocus(want) {
        if (over || told === want) return;
        told = want;
        var sc = slots.scene && slots.scene();
        if (sc && typeof sc.focus === 'function') sc.focus(want);
      }
      /* 메모가 그 사람 옆에 실제로 떠 있는지를 장면에 알린다(떠 있으면 장면이 그 사람 위의 호버 한 줄을 숨긴다 — 메모가 같은 말을 하고 있다). */
      function tellOpen() {
        var open = !memo.hidden && memo.style.visibility !== 'hidden' && !!memoId && !!foc && foc.id === memoId;
        if (open === saidOpen) return;
        saidOpen = open;
        var sc = slots.scene && slots.scene();
        if (sc && typeof sc.setMemoOpen === 'function') sc.setMemoOpen(open);
      }

      /* 메모 자리(승인된 동작 시안 scene.js 와 같은 식): 장면이 알려 준 머리 가운데(host 기준 px)에서 머리 반지름 r 의 1.62배만큼 오른쪽, 자리가 없으면 왼쪽으로 뒤집는다.
         위아래는 머리보다 26px 위에서 시작하되 아래 버튼 줄(58px)을 가리지 않는다. 좁은 화면은 CSS 가 장면 아래에 둔다.
         그 사람이 장면에 있는데 좌표가 없으면(장면이 아직 첫 좌표를 안 줬거나, 끌어서 그 사람이 틀 밖으로 나갔다) 자리만 숨긴다 — 닫힌 것이 아니라 돌아오면 다시 보인다.
         그 세션이 장면에 없으면(끝난 세션의 막힌 일 같은 것) 기본 자리에 꼬리 없이(is-loose). */
      function placeMemo() {
        var narrow = narrowNow();
        stageFrame.classList.toggle('is-under', narrow);  // 메모를 장면 아래 블록으로(theme-post.css). 화면이 좁거나 장면 틀이 좁을 때
        if (memo.hidden) { tellOpen(); return; }
        memo.style.visibility = '';
        if (narrow || !inScene) { memo.style.left = ''; memo.style.top = ''; memo.style.removeProperty('--tail'); memo.classList.remove('is-flip'); memo.classList.toggle('is-loose', !narrow); tellOpen(); announceMemo(); return; }
        if (!foc || foc.id !== memoId) { memo.style.visibility = 'hidden'; tellOpen(); return; }
        if (refocus >= 0) { var rf = memo.querySelectorAll(FOCUSABLE)[refocus]; refocus = -1; if (rf) rf.focus({ preventScroll: true }); }  // 「다음」 으로 넘긴 메모가 자리를 잡았다: 초점을 같은 단추에 돌려놓는다
        var host = slots.sceneHost, W = stageFrame.clientWidth, H = stageFrame.clientHeight, mw = memo.offsetWidth, mh = memo.offsetHeight;
        var ox = host.offsetLeft, oy = host.offsetTop, hx = ox + foc.x, hy = oy + foc.y, gap = (foc.r > 0 ? foc.r : 21) * 1.62;
        var flip = hx + gap + mw > W - 10, x = flip ? hx - gap - mw : hx + gap, y = hy - 26;
        x = Math.max(8, Math.min(x, W - 8 - mw)); y = Math.max(8, Math.min(y, H - mh - 58));
        memo.style.left = Math.round(x) + 'px'; memo.style.top = Math.round(y) + 'px';
        memo.classList.remove('is-loose');
        memo.style.setProperty('--tail', Math.round(Math.max(14, Math.min(mh - 24, hy - y))) + 'px');
        memo.classList.toggle('is-flip', flip);
        tellOpen();
        announceMemo();  // 자리를 기다리느라 숨어 있다 보이게 된 메모도 이때 읽기 프로그램에 알린다(같은 내용은 한 번만)
      }
      /* 장면이 보는 사람이 메모와 다르면(보던 사람이 답을 받아 장면이 먼저 다음 사람으로 갔다) 다음 세션 이벤트를 기다리지 않고 메모를 맞춘다.
         같은 사람으로는 한 번만 부른다 — 좌표는 프레임마다 오고, 메모의 세션이 장면에 없을 때처럼 끝내 안 맞는 경우가 있다. */
      var chased = null, refocus = -1;  // chased: 메모와 다른 사람을 장면이 본다고 알려 와 다시 그리기를 걸어 둔 세션(아래 reconcile 이 그 뒤를 맡는다).  // refocus: 메모가 새 사람 자리를 기다리느라 잠깐 숨은 동안 돌려놓지 못한 초점(메모 안 몇 번째 단추)
      function onFocus(f) {
        foc = f && typeof f.x === 'number' && typeof f.y === 'number' ? f : null;
        placeMemo();
        if (!foc) return;  // 끌어서 틀 밖으로 나갔다 들어올 때마다 다시 그리지 않게 chased 는 그대로 둔다
        if (foc.id === memoId) { chased = null; adopted = null; return; }
        if (gone || chased === foc.id) return;
        chased = foc.id; drawSoon();
      }
      /* 다시 그린 뒤에도 장면이 보는 사람과 메모가 다르면 장면을 따른다(한 사람에 한 번). 장면이 작은 창(PiP)에 가 있는 동안 거기서 사람을 고르거나 전체 보기를 눌러도
         콘솔은 듣지 못한다(번들이 그 창에서는 onPick·onOverview 를 안 부른다) — 돌아온 장면이 보는 사람의 메모를 띄운다. 메모의 세션이 장면에 없어 장면이 다른 사람을 보는 때는 그대로 둔다. */
      var adopted = null;
      function reconcile() {
        if (gone || !officeOn || !foc || foc.id === memoId || chased !== foc.id || adopted === foc.id) return;
        if (!over && memoId && !inScene) return;
        adopted = foc.id;
        if (!sceneSession(foc.id)) return;
        if (items.some(function (x) { return x.id === foc.id; })) topId = foc.id;
        setPick(foc.id); paintDeck(); paintMemo();
      }

      /* 메모 머리의 첫 글: 덱 카드와 같은 종류 이름(질문·승인·계획·확인·고쳐야 함·막힘·확인 못 함). 몇 번째인지(1/6)는 장면 버튼 「나를 찾는 사람」 한 곳에만 있다 —
         전에는 여기 「내 차례 1/4」(건수)와 버튼 「1/6」(사람)이 나란히 다른 수를 보였다. 방금 답해 도장이 남은 카드는 「처리됨」. */
      function memoKind(it) { return it.kind === 'turn' && !it.n ? '처리됨' : kindLabel(it); }

      /* 내 차례 메모(시안 .memo): 덱과 같은 순서의 topId 한 건. 사무실 장면이 보일 때만(차분이거나 번들이 없으면 없다). 여러 건이면 "다음" 으로 돌린다(J·K 도 된다).
         덱은 그대로 아래에 있다. 메모의 동작은 덱 카드와 같은 문장·같은 링크다. */
      function announceMemo() {
        if (!memoId) { memoSaid = ''; return; }  // 메모가 없어졌다가 같은 것이 다시 뜨면 다시 알린다
        if (memo.hidden || memo.style.visibility === 'hidden') return;  // 자리를 기다리느라 숨은 메모는 보이게 될 때(placeMemo) 알린다
        var pick = function (c) { var n = memo.querySelector(c); return n ? n.textContent : ''; };
        var key = [memoId, memo.getAttribute('aria-label'), pick('.po-memo-q'), pick('.po-memo-s')].join('|');  // 지난 시간(몇 분째)은 빼고 판단해 분마다 다시 읽지 않는다
        if (key === memoSaid) return;
        memoSaid = key;
        memoLive.textContent = [memo.getAttribute('aria-label'), pick('.po-memo-kind'), pick('.po-memo-q'), pick('.po-memo-s')].filter(Boolean).join(' · ');
      }
      function paintMemo() {
        var a0 = document.activeElement, fi = a0 && a0 !== document.body && memo.contains(a0) ? Array.prototype.indexOf.call(memo.querySelectorAll(FOCUSABLE), a0) : -1;
        var sl = officeOn ? kit.sceneList() : [];
        function inList(id) { return sl.filter(function (x) { return x.id === id; })[0] || null; }
        function inDeck(id) { return items.filter(function (x) { return x.id === id; })[0] || null; }
        if (pickId) {  // 고른 세션이 목록에서 빠졌거나, 손 든(끝낸) 사람으로 골랐는데 더는 그 상태가 아니면 놓는다(번들 letGo 와 같은 규칙) — 장면이 스스로 고른 사람으로 돌아간다
          var pi = inList(pickId);
          if ((!pi && !inDeck(pickId)) || (pi && pickKind && pickKindOf(pi.state) !== pickKind)) { pickId = null; pickKind = ''; }
        }
        var lead = officeOn && !pickId ? leadOf(sl) : null;
        // 고른 사람 → 장면이 스스로 고른 사람 → (손 든 사람이 장면에 없으면) 덱 맨 위 일
        var id = !officeOn ? null : pickId || lead || (inDeck(topId) ? topId : null);
        var it = id ? inDeck(id) : null, ps = id && !it ? sceneSession(id) : null;
        var next = it ? it.id : ps ? ps.id : null;
        if (next && next !== shutId) shutId = null;  // 다른 사람이 메모에 오면 닫아 둔 것이 풀린다(보던 사람이 답을 받으면 다음 사람 메모가 열린다). 메모가 잠깐 없어졌다(next 없음) 같은 사람으로 돌아오면 닫힌 채다
        clear(memo);
        memoId = next;
        inScene = !!(next && inList(next));
        memo.hidden = memoHidden();
        syncFocus(pickId ? pickId : lead ? null : next);
        if (ps) personMemo(ps);
        if (!it) { if (!ps) placeMemo(); announceMemo(); if (ps) focusIn(fi); reconcile(); return; }
        memo.setAttribute('aria-label', '나를 찾는 사람 메모');
        var s = it.s, name = s.title || HK.folderName(s) || '이름 없는 세션', team = teamOf(PL.teamFlowOf(s)), a = cardAct(it, false);
        var from = it.pend && it.pend.r ? (it.pend.r.createdAt || it.pend.r.createdAtMs) : (it.t || s.updatedAt), w = kit.waited(from);
        var head = [memoKind(it), team, w];
        var sessionHref = '/s/' + encodeURIComponent(s.id), same = a.href === sessionHref;  // 가는 곳이 세션이면 "세션으로" 를 따로 두지 않는다
        memo.className = 'po-memo po-memo-' + it.kind; memo.setAttribute('data-color-role', toneOf(it));
        memo.appendChild(h('div', { class: 'po-memo-h' }, stMark(it.kind, toneOf(it)), h('span', { class: 'po-memo-kind', text: head.filter(Boolean).join(' · ') }),
          items.length > 1 ? h('button', { type: 'button', class: 'po-link po-memo-next', 'aria-label': '다음 일 보기', text: '다음', onClick: function () { step(1, true); } }) : null, closeBtn()));
        memo.appendChild(h('p', { class: 'po-memo-q', text: a.q, title: a.q }));  // 떠 있는 메모는 세 줄·한 줄에서 자른다(theme-post.css) — 전체 글은 title 과 아래 덱 카드에
        memo.appendChild(h('p', { class: 'po-memo-s', text: name, title: name }));
        memo.appendChild(h('div', { class: 'po-memo-acts' }, kit.link(a.href, { class: 'pill acc', text: a.verb }), same ? null : kit.link(sessionHref, { class: 'po-link', text: '세션으로' })));
        placeMemo();
        announceMemo();
        focusIn(fi);
        reconcile();
      }
      /* 메모를 다시 그리기 전에 메모 안에 있던 초점(fi 번째 단추)을 돌려놓는다. 메모가 새 사람 자리를 기다리느라 숨어 있으면 자리를 잡을 때(placeMemo) 돌려놓는다. */
      function focusIn(fi) {
        refocus = -1;
        if (fi < 0 || memo.hidden) return;
        if (memo.style.visibility === 'hidden') { refocus = fi; return; }
        var t = memo.querySelectorAll(FOCUSABLE)[fi]; if (t) t.focus({ preventScroll: true });
      }

      /* 장면에서 누른 사람이 덱(내 차례·막힘·확인 못 함)에 없는 세션일 때의 메모: 상태 · 팀 · 지난 시간, 제목, 세션으로 가는 링크. */
      var PERSON_LINE = { run: 'AI가 일하고 있어요', wait: '팀 승인을 기다리고 있어요', idle: '이어서 할 일이 있으면 세션에서 말해 주세요', done: '이 세션의 일은 끝났어요' };  // 머리 첫 글이 이미 상태 이름(「쉬는 중이에요」 …)이라 같은 말을 되풀이하지 않는다
      var inScene = false;  // 메모의 세션이 장면에 서 있는가(placeMemo)
      function narrowNow() { return (typeof matchMedia === 'function' && matchMedia(NARROW).matches) || stageFrame.clientWidth < UNDER_W; }
      function memoHidden() { return !memoId || over || shutId === memoId; }
      /* 메모 닫기(승인된 동작 시안): Esc · 빈 바닥 클릭 · 메모의 ×. 장면의 줌·조명은 그대로 두고 메모만 접는다. 끌기로는 닫히지 않는다(메모는 그 사람을 따라간다).
         그 사람을 누르거나 「나를 찾는 사람」·「끝낸 일」 버튼, J·K 로 다시 열린다. 초점이 메모 안에 있었으면 장면의 버튼으로 옮긴다(다시 여는 버튼). */
      function closeMemo() {
        if (memo.hidden || !memoId || memo.style.visibility === 'hidden' || !memo.getClientRects().length) return false;  // 안 보이는 메모(자리를 기다리는 중 · 장면이 작은 창에 가 있음)는 닫을 것이 없다
        var had = memo.contains(document.activeElement);
        shutId = memoId; memo.hidden = true; refocus = -1; tellOpen();
        if (had) { var b = slots.sceneHost.querySelector('.of-btn.is-ask:not(:disabled)') || slots.sceneHost.querySelector('.of-btn:not(:disabled)'); if (b) b.focus({ preventScroll: true }); }
        return true;
      }
      function closeBtn() {
        return h('button', { type: 'button', class: 'po-memo-x', 'aria-label': '메모 닫기', title: '닫기 (Esc)', onClick: function () { closeMemo(); } }, closeIcon());
      }
      function sceneSession(id) { return HK.sessionList().filter(function (x) { return x.id === id && x.status !== 'ended'; })[0] || null; }  // 장면에 선 세션(끝난 세션은 장면에 없다). 장면은 이벤트 즉시 바뀌니 다시 그리기를 기다리지 않고 지금 목록에서 찾는다
      function personMemo(s) {
        var st = PS.stateOf(s, L), name = s.title || HK.folderName(s) || '이름 없는 세션', w = kit.waited(s.updatedAt);
        memo.className = 'po-memo po-memo-' + st; memo.removeAttribute('data-color-role');
        memo.setAttribute('aria-label', '세션 메모');
        memo.appendChild(h('div', { class: 'po-memo-h' }, stMark(st), h('span', { class: 'po-memo-kind', text: [PS.LABEL[st], teamOf(PL.teamFlowOf(s)), w].filter(Boolean).join(' · ') }),
          items.length ? h('button', { type: 'button', class: 'po-link po-memo-next', 'aria-label': '나를 찾는 사람 메모로 돌아가기', text: '나를 찾는 사람', onClick: function () { pickTop(topId, true); } }) : null, closeBtn()));
        memo.appendChild(h('p', { class: 'po-memo-q', text: PERSON_LINE[st] || PS.LABEL[st] || '' }));
        memo.appendChild(h('p', { class: 'po-memo-s', text: name, title: name }));
        memo.appendChild(h('div', { class: 'po-memo-acts' }, kit.link('/s/' + encodeURIComponent(s.id), { class: 'pill acc', text: '가서 확인하기' })));
        placeMemo();
      }
      /* 장면에서 사람(via 'person')이나 「나를 찾는 사람」('ask')·「끝낸 일」('done') 버튼을 눌렀다(번들 onPick — 장면은 이미 그 사람을 보고 있다):
         세션으로 바로 가지 않고 그 사람의 메모를 띄운다. 메모의 링크로 세션에 간다. 덱에 있는 세션이면 덱 맨 위도 그 카드로 돌린다.
         장면이 작은 창(PiP)에 가 있으면 번들이 이 콜백을 부르지 않는다(그 창의 정리 목록이 대신한다). */
      function onPick(id) {
        if (gone || !officeOn) return;
        if (!sceneSession(id)) { if (over) { leaveOver(); paintMemo(); } return; }  // 콘솔이 모르는 세션(목록이 막 바뀜): 전체 보기에서는 나온 것으로 맞춘다
        if (items.some(function (x) { return x.id === id; })) { pickTop(id, true); return; }
        setPick(id); paintMemo();
      }
      /* 빈 바닥을 (끌지 않고) 눌렀다: 메모만 닫는다. 좁은 화면은 메모가 장면 아래에 있어 그림을 가리지 않으니 바닥을 눌러도 그대로 둔다(× 와 Esc 로 닫는다). */
      function onBackground() { if (!gone && !narrowNow()) closeMemo(); }
      /* 「전체 보기」: 아무도 보지 않으니 메모를 접는다. 누군가를 고를 때까지 장면을 돌리지 않는다. */
      function onOverview() {
        if (gone) return;
        over = true; memo.hidden = memoHidden(); tellOpen();
      }

      function paintDeck() {
        var mark = focusMark();
        clear(deckSlot);
        if (!items.some(function (it) { return it.id === topId; })) topId = items[0] ? items[0].id : null;
        // 머리에는 숫자를 두지 않는다: 몇 명인지는 장면 아래 정리 줄(상태별)과 장면 버튼 「나를 찾는 사람 N」 이 말한다. 이름은 그 버튼과 같다(같은 사람들, 같은 순서)
        var head = h('header', { class: 'po-ph' }, h('h2', { text: '나를 찾는 사람' }),
          items.length > 1 ? h('span', { class: 'po-hint', text: 'J · K 다음 · 이전' }) : null);
        var stack = h('div', { class: 'po-stack' });
        if (!items.length) stack.appendChild(h('p', { class: 'quiet', text: '지금은 나를 찾는 사람이 없어요.' }));
        items.forEach(function (it) {
          var s = it.s, top = it.id === topId, name = s.title || HK.folderName(s) || '이름 없는 세션';
          var st = PS.stateOf(s, L), href = '/s/' + encodeURIComponent(s.id);
          var from = it.pend && it.pend.r ? (it.pend.r.createdAt || it.pend.r.createdAtMs) : (it.t || s.updatedAt);
          var w = kit.waited(from);
          var attrs = it.kind === 'turn' ? { 'data-call': s.id } : { 'data-call-block': s.id, 'data-block-kind': it.kind === 'unk' ? 'cannot_check' : 'blocked' };
          var hd = h('div', { class: 'po-dc-h' }, PS.avatar(s.id, st), stMark(it.kind, toneOf(it)),
            h('span', { class: 'po-dc-kind', text: kindLabel(it) }), kit.link(href, { class: 'po-dc-s', text: name }),
            it.more || w ? h('span', { class: 'po-dc-wait', text: [it.more ? '요청 +' + it.more : '', w].filter(Boolean).join(' · ') }) : null,  // 한 묶음(좁은 폭에서 시각만 다음 줄로 떨어져 왼쪽에 붙지 않게)
            top ? null : h('button', { type: 'button', class: 'pill line sm', 'aria-expanded': 'false', 'aria-label': name + ' 펼치기', text: '열기', onClick: function () { pickTop(it.id); } }));
          stack.appendChild(h('article', Object.assign({ class: 'po-dc po-dc-' + it.kind + (top ? ' is-top' : ''), 'data-color-role': toneOf(it) }, attrs), hd, top ? cardBody(it) : null));
        });
        deckSlot.appendChild(h('section', { class: 'light po-panel po-deck', 'aria-label': '나를 찾는 사람' }, head, stack));
        focusBack(mark);
      }

      /* 차분: 장면이 없는 대신 같은 세션(장면에 올리는 것과 같은 줄)을 목록으로. 사람 아바타는 정지 그림, 둘째 줄은 상태 기호 + 상태 글 · 앉은 곳. */
      function paintCalm() {
        clear(calmList);
        calmList.hidden = !PS.calm();
        if (calmList.hidden) return;
        // 세션이 많으면(수십 개) 목록이 덱을 몇 화면 아래로 밀어낸다. 앞(내 차례·막힘·일하는 중 순)만 보이고 나머지는 펼쳐 본다
        var all = kit.sceneList(), shown = calmAll ? all : all.slice(0, CALM_MAX);
        shown.forEach(function (s) {
          var name = s.title || '이름 없는 세션';
          calmList.appendChild(h('li', { class: 'po-ml po-ml-' + s.state, 'data-color-role': s.state === 'turn' ? s.tone || null : null },
            kit.link('/s/' + encodeURIComponent(s.id), { class: 'po-ml-a' }, PS.avatar(s.id, s.state, { size: 'sm', name: name }),
              h('span', null, h('b', { text: name }), h('small', null, stMark(s.state, s.state === 'turn' ? s.tone : ''), PS.LABEL[s.state] + ' · ' + PL.seatName(s.state, s.flow))))));
        });
        if (all.length > shown.length) calmList.appendChild(h('li', { class: 'po-ml-more' }, h('button', { type: 'button', class: 'pill line sm', text: '나머지 ' + (all.length - shown.length) + '개 더 보기', onClick: function () { calmAll = true; paintCalm(); var a = calmList.querySelectorAll('a')[CALM_MAX]; if (a) a.focus(); } })));  // 단추가 사라지니 포커스는 새로 보인 첫 줄로
        if (!calmList.firstChild) calmList.appendChild(h('li', { class: 'quiet', text: '지금 일하는 세션이 없어요.' }));
      }

      /* 사무실 장면 아래 팀 이름과 인원 수. 장면이 안 그려지는 차분(fx=0)이거나 사무실 장면이 없으면 숨긴다. */
      function paintTeams() {
        clear(teamRow);
        teamRow.hidden = !window.BHOfficeScene || PS.calm();
        if (teamRow.hidden) return;
        // 숫자는 지금 그 팀 자리에 있는 사람(9회차 D, 장면과 같은 기준 PL.atDesk). 쉬는(카페)·승인 기다리는(리뷰 룸)·끝난(완료) 소속은 title 로만 말한다
        var list = kit.sceneList();
        function cell(name, members, cls, what) {
          var n = members.filter(function (s) { return PL.atDesk(s.state); }).length, away = members.length - n;
          return h('li', { class: (n ? 'has' : '') + (cls ? ' ' + cls : ''), title: what + ' ' + n + '명' + (away ? ' · 카페·리뷰 룸·완료에 ' + away + '명 더' : '') }, h('b', { text: name }), h('span', { text: n + '명' }));
        }
        TEAMS.forEach(function (t) {
          teamRow.appendChild(cell(t[0], list.filter(function (s) { return t[1].indexOf(s.flow) >= 0; }), '', '지금 자리에서 일하는 사람'));
        });
        // 팀이 없는 세션(갈래·근거가 없음). 장면은 일하는 이들을 리셉션에 세운다
        var free = list.filter(function (s) { return !teamOf(s.flow); });
        if (free.some(function (s) { return PL.atDesk(s.state); })) teamRow.appendChild(cell('팀 없음', free, 'po-team-free', '팀이 정해지지 않아 리셉션에 있는 사람'));
      }

      /* 장면 아래 정리 줄. 장면에 선 세션(kit.sceneList — 장면·차분 목록·장면 버튼과 같은 목록, 같은 상태 판정)을 상태별로 센다: 단위는 사람(세션)이다.
         답할 요청이 여럿인 세션도 한 사람이라 요청 건수와는 다른 수다 — 건수는 그 카드의 「요청 +N」 이 말한다. 0 인 상태도 범례라 흐리게 남긴다. */
      function paintSum() {
        var n = {};
        kit.sceneList().forEach(function (s) { n[s.state] = (n[s.state] || 0) + 1; });
        clear(sumRow);
        SUM.forEach(function (k) {
          var c = n[k] || 0;
          sumRow.appendChild(h('li', { class: c ? 'has' : null, 'data-sum': k }, stMark(k), h('span', { text: PS.LABEL[k] }), h('b', { text: String(c) }), h('span', { class: 'sr-only', text: '명' })));
        });
      }

      function noMemo() { memo.hidden = true; memoId = null; pickId = null; pickKind = ''; syncFocus(null); tellOpen(); }  // 장면 칸이 없는 화면(불러오는 중·세션 없음)
      function draw() {
        if (gone) return;
        if (!kit.loaded()) {
          scenePanel.hidden = true; noMemo(); clear(helloSlot); clear(deckSlot); clear(restSlot);
          restSlot.appendChild(kit.conn() === 'down' ? kit.stateBox('warn', '서버에 연결할 수 없어요', '서버가 꺼졌을 수 있어요. 다시 연결을 시도하고 있어요.') : kit.loadingBox('세션을 불러오는 중이에요.'));
          restSlot.appendChild(slots.whatsSlot);  // 새 소식은 세션이 없어도·불러오는 중에도 보인다(Sauce 홈과 같다)
          return;
        }
        var list = HK.sessionList();
        clear(helloSlot); clear(restSlot);
        if (!list.length) {  // 세션이 없으면 Sauce 와 같은 첫 작업 안내(시안: C단계가 다듬는다)
          scenePanel.hidden = true; noMemo(); clear(deckSlot); clear(prSlot); items = []; delete approvals.dataset.compact; approvals.className = 'approvals light po-panel po-mini';
          HK.emptyHome(restSlot, approvals, projects);
          HK.approvalCard(approvals); HK.projectCard(projects);
          restSlot.appendChild(slots.whatsSlot);
          return;
        }
        scenePanel.hidden = false;
        officeOn = !!window.BHOfficeScene && !PS.calm();  // 사무실 장면이 보일 때만 틀·메모(차분이거나 번들이 없으면 지금 그대로)
        stageFrame.classList.toggle('is-office', officeOn);
        approvals.className = 'approvals'; approvals.dataset.compact = '1';  // 검토 요청 칸 안에서는 줄로 그린다(Sauce 홈과 같다)
        clear(prSlot); prSlot.appendChild(h('div', { class: 'light po-panel po-mini' }, HK.homePrBox(list, approvals)));
        sceneSub.textContent = kit.sceneList().length + '개';  // 장면·차분 목록에 서는 세션 수(끝난 세션은 장면에 없다). 세션 수를 말하는 곳은 여기 하나다
        paintCalm();
        paintSum();
        paintTeams();
        var proj = kit.projectOf() || HK.folderName(list[0]);
        helloSlot.appendChild(h('p', { class: 'po-date', text: dateLine(new Date()) + (proj ? ' · ' + proj : '') }));
        helloSlot.appendChild(h('h1', { text: '오늘 내 일' }));
        // 인사 아래 문장("세션 N개 중 N개가 일하고 있어. 네 답을 기다리는 일이 N건 있어.")은 뺐다 — 같은 수를 장면 머리와 장면 아래 정리 줄이 말한다
        items = deckItems(list);
        paintDeck();
        paintMemo();
        if (stats.refresh) stats.refresh();  // 고른 프로젝트가 바뀌었으면 팀 기록 수를 다시 센다(J11)
        // 숫자 칸 줄은 없앴다: 내 차례·AI가 일하는 중은 장면 아래 정리 줄에, 승인 기다리는 PR 은 검토 요청(PR) 칸의 줄들이, 이번 주 산출물은 최근 산출물 칸에, 팀 기록은 아래 칸들 옆에(tbSlot)
        restSlot.appendChild(sessionsPanel(list));  // 내 세션 두 단 목록(글자 아바타·결재란·상태 칩). Sauce 홈은 표(HK.homeTable) 그대로
        if (slots.whatsSlot.parentNode !== foot) foot.appendChild(slots.whatsSlot);  // 세션이 없던 동안 restSlot 으로 옮겨 갔으면 되돌린다
        restSlot.appendChild(foot);
        restSlot.appendChild(projects);
        HK.recentCard(recent, showWeek);
        HK.approvalCard(approvals);
        HK.projectCard(projects);
        HK.fixCard(fixBox);
      }
      redrawNow = function () { if (!gone) draw(); };
      function onPref(ev) { if (ev && ev.detail === 'fx') redrawNow(); }  // 효과 강도가 바뀌면 장면 ↔ 목록
      document.addEventListener('bh-pref', onPref);
      var ro = typeof ResizeObserver === 'function' ? new ResizeObserver(function () { placeMemo(); }) : null;  // 폭이 바뀌면(창 크기·760px 경계) 메모 자리를 다시 잡는다
      if (ro) ro.observe(stageFrame);
      draw();

      /* 열린 PR 의 상태(검사 통과·실패·병합)는 GitHub 에서 바뀌므로 홈이 열려 있는 동안 다시 읽는다(Sauce 홈과 같은 일, #1027 D8). 홈을 떠나면 멈춘다.
         flow-ui.js 의 캐시는 60초가 지나면 스스로 낡은 것으로 치니, 읽었다는 표시만 지우고 부르면 된다(캐시 안이면 네트워크 없이 같은 값을 다시 그린다). */
      var prTimer = setInterval(function () {
        if (gone || !fixBox.isConnected || document.hidden) return;
        delete fixBox.dataset.ready;
        HK.fixCard(fixBox);
      }, MY_PRS_POLL_MS);

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
        onData: drawSoon, onSession: drawSoon, onRequest: drawSoon, onRemoved: draw, onFocus: onFocus, onPick: onPick, onBackground: onBackground, onOverview: onOverview,
        tick: function () { if (!typing()) draw(); },  // 날짜 줄·기다린 시간을 고친다
        title: function () { return ''; },
        destroy: function () { gone = true; clearInterval(prTimer); redrawNow = function () {}; if (ro) ro.disconnect(); document.removeEventListener('keydown', onKey); document.removeEventListener('bh-pref', onPref); }
      };
    }

    return { view: view };
  }

  window.BHPostHome = { create: create, dateLine: dateLine };
})();
