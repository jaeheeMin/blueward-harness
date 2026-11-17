/* Post(우체국) 테마가 세션을 손님으로 바꾸는 순수 규칙(#1013 이어서). DOM 을 만지지 않는다(node 로 시험한다).
   손님 고정 배정(personOf)·상태(stateOf)·창구(stationOf)·자세·아바타 바탕을 한곳에서 정해, 장면(theme-post.js)과 모든 화면의 아바타가 같은 값을 쓴다.
   stateOf·stationOf 는 flow-logic.js(BHLogic)를 넘겨받아 쓴다 — 세션 목록·홈과 같은 groupOf·blockOf 기준이다. */
(function (root) {
  'use strict';

  var WHO = ['mint', 'navy', 'rose', 'sunny', 'sky', 'sage', 'kid'];
  /* 상태 순서(위가 먼저): 내 차례 > 막힘 > 확인 못 함 > 일하는 중 > 승인 기다림 > 끝 > 쉬는 중 */
  var STATES = ['turn', 'blocked', 'unk', 'run', 'wait', 'done', 'idle'];
  var LABEL = { turn: '내 답이 필요해', blocked: '막혔어', unk: '확인 못 함', run: '일하는 중', wait: '승인 기다림', done: '끝났어', idle: '쉬는 중' };
  var GLYPH = { turn: '!', blocked: '✕', unk: '?', done: '✓', wait: '…' };
  var STATION = [
    { name: '요구사항', hint: '무엇을 만들지 쓰기', desk: '쓰기 책상' }, { name: '개발 Spec', hint: '어떻게 만들지 설계', desk: '설계 창구' },
    { name: '개발', hint: 'AI가 만드는 중', desk: '작업실' }, { name: '검토', hint: '팀 승인 받기', desk: '검토 창구' },
    { name: '합쳐짐', hint: '끝, 반영됨', desk: '발송 우체통' }
  ];

  /* 세션 id 로 손님을 고정한다. 새로고침·목록 변화와 무관하다(가이드 6.3). */
  function personOf(sessionId) {
    var hh = 0, s = String(sessionId == null ? '' : sessionId);
    for (var i = 0; i < s.length; i++) hh = (hh * 31 + s.charCodeAt(i)) >>> 0;
    return WHO[hh % WHO.length];
  }

  function upper(v) { return String(v == null ? '' : v).toUpperCase(); }
  function prState(s) { var pr = s && s.flowPr; return pr && pr.number ? upper(pr.state) : ''; }

  /* 내 차례 계산에 쓰는 "아직 답 안 한 요청 번호" 함수(app.js·flow-ui.js 의 openIds). 화면이 한 번 알려 주면 stateOf 가 늘 이걸로 센다.
     없으면 서버가 준 pendingRequestIds 를 그대로 믿어, 방금 답한 요청이 다음 목록 갱신 전까지 내 차례로 남는다(홈 덱·띠와 어긋남). */
  var openIdsFn = null;
  function useOpenIds(fn) { openIdsFn = typeof fn === 'function' ? fn : null; }

  /* 세션 상태(가이드 6.2). L 은 BHLogic. openIds 를 안 주면 useOpenIds 로 받은 것을 쓴다(띠·알림·홈과 같은 내 차례 기준, #1027 D5). */
  function stateOf(s, L, openIds) {
    if (!s) return 'idle';
    var bk = L.blockOf(s);
    if (!bk && s.status !== 'ended' && L.groupOf(s, openIds || openIdsFn || undefined) === 'todo') return 'turn';
    if (bk) return bk.kind === 'cannot_check' ? 'unk' : 'blocked';
    if (s.status === 'running' || s.status === 'starting') return 'run';
    if (s.status === 'ended') return 'done';  // 실제로 돌지 않는 세션은 PR 이 열려 있어도 끝남이다(#1059). 승인 기다림(일하는 중 칸)에 넣지 않는다
    if (prState(s) === 'OPEN' || s.phase === 'approval') return 'wait';
    if (prState(s) === 'MERGED' || s.phase === 'finished' || s.flowFinished) return 'done';
    return 'idle';
  }

  /* 창구 번호 k = 0~4 (가이드 6.1). 갈래의 지금 단계 이름에 "올리고 검토 요청하기"·"합쳐지기 기다리기" 가 있고 PR 이 열려 있으면 검토 창구다. */
  var FLOW_STATION = { srs: 0, 'srs-export': 0, spec: 1, dev: 2, config: 2, standard: 2, fix: 2 };
  function stationOf(s, L) {
    if (!s) return 2;
    if (prState(s) === 'MERGED' || s.flowFinished || s.phase === 'finished') return 4;
    var step = L && L.currentStep ? L.currentStep(s) : null, name = step ? String(step.name || step.id || '') : '';
    if (s.phase === 'approval' || (prState(s) === 'OPEN' && /올리고|합쳐지기/.test(name))) return 3;
    if (s.flowId && FLOW_STATION[s.flowId] != null) return FLOW_STATION[s.flowId];
    return 2;
  }

  function poseOf(state) {
    return state === 'turn' ? 'ask' : state === 'blocked' || state === 'unk' ? 'stuck' : state === 'wait' ? 'wait' : state === 'done' ? 'done' : 'walk';
  }
  /* 아바타 바탕색 갈래: 내 차례 노랑 · 막힘 분홍 · 끝 연두 · 그 밖 베이지(가이드 2.2) */
  function toneOf(state) { return state === 'turn' ? 'turn' : state === 'blocked' ? 'blocked' : state === 'done' ? 'done' : ''; }

  /* ---------- 세션·요청 화면(B단계): 목록 걸러보기 · 창구 안내 · 정보 줄 · 도장 글자 ---------- */

  /* 세션 목록 위의 걸러보기. 할 일 = 내 답·막힘·확인 못 함(시안은 넷을 한 묶음으로 센다), 일하는 중 = 일하는 중·승인 기다림. 쉬는 중은 "전체" 에만 있다.
     묶음 이름이 "내 차례" 면 홈·띠·알림의 "내 차례 N건"(막힘·확인 못 함은 따로 셈)과 같은 이름에 다른 숫자가 나온다. 그래서 "할 일" 이다(내 차례 + 막힘 + 확인 못 함, 세션 수). */
  var FILTERS = [{ id: 'all', label: '전체' }, { id: 'turn', label: '할 일' }, { id: 'run', label: '일하는 중' }, { id: 'done', label: '끝남' }];
  var FILTER_OF = { turn: 'turn', blocked: 'turn', unk: 'turn', run: 'run', wait: 'run', done: 'done' };
  function filterMatch(f, state) { return f === 'all' || FILTER_OF[state] === f; }
  function filterCounts(states) {
    var c = { all: states.length, turn: 0, run: 0, done: 0 };
    states.forEach(function (st) { if (FILTER_OF[st]) c[FILTER_OF[st]]++; });
    return c;
  }
  /* 세션 한 줄 상태 글에서 맨 앞 기호(✕ ? !)를 뗀다 — 기호는 상태 표시(po-st)가 따로 그린다. */
  function statusText(t) { return String(t == null ? '' : t).replace(/^[✕?!]\s*/, ''); }

  /* 세션 머리 오른쪽 안내판(figure.po-here). 첫 줄 "{k+1}번 창구 · {창구 이름}", 둘째 줄은 상태별 반말(가이드 2.4). */
  /* 확인 못 함(unk)은 blockOf 의 cannot_check — 검사를 못 돌린 것이지 손님 자리를 모르는 게 아니다(첫 줄이 이미 "N번 창구"). 쉬는 중은 걷지 않는다(장면에서도 서 있다) */
  var HERE = { turn: '편지를 들고 네 답을 기다려', blocked: '창구에서 막혀 있어', wait: '의자에 앉아 승인을 기다려', done: '편지를 다 부쳤어', unk: '검사를 못 해서 멈췄어', idle: '창구 앞에서 쉬고 있어' };
  function hereTitle(k) { var i = Math.max(0, Math.min(4, k | 0)); return (i + 1) + '번 창구 · ' + STATION[i].desk; }
  function hereLine(state) { return HERE[state] || '다음 창구로 걸어가'; }

  /* 정보 줄: 단계 · 요구사항 · 개발 번호 · 작업 기록 · 검토 요청. 값이 없는 칸은 지어내지 않고 "–" 로 둔다. cells 는 BHLogic.sessionStrip 의 칸들. */
  var INFO = [['단계', 'step'], ['요구사항', 'req'], ['개발 번호', 'dev'], ['작업 기록', 'issue'], ['검토 요청', 'pr']];
  function infoRow(cells, stepName) {
    var by = {};
    (cells || []).forEach(function (c) { by[c.id] = c; });
    var out = INFO.map(function (x) {
      var c = by[x[1]], v = x[1] === 'step' && stepName ? stepName : c && c.value;
      return { id: x[1], label: x[0], value: v == null || v === '' ? '–' : String(v), tone: c && c.tone || '' };
    });
    (cells || []).forEach(function (c) {  // 숫자 띠의 나머지 칸(AI 진행 · SRS 상태)도 잃지 않는다
      if (!INFO.some(function (x) { return x[1] === c.id; })) out.push({ id: c.id, label: c.label, value: String(c.value), tone: c.tone || '' });
    });
    return out;
  }

  var INSP = ['산출물', '검사', '기억', '기록', '기술'];

  /* 요청 화면 한 줄(가이드 2.5): 승인·계획은 검토 창구 직원, 질문은 그 세션 손님. */
  function clerkLine(kind, k) {
    if (kind === 'question' || kind === 'elicitation') return (Math.max(0, Math.min(4, k | 0)) + 1) + '번 창구 앞에서 손님이 편지를 흔들며 네 답을 기다려';
    return '검토 창구 직원이 네 도장을 기다려. 누르면 도장이 찍혀';
  }

  /* 도장 글자. 승인 주 버튼(허락·올리기·계획대로 진행) = 보냄, 질문·MCP 질문에 답을 보냄 = 접수, 거절·아니오·닫기·고쳐 달라고 하기 = 반송.
     decision: allow · allow_session · deny(승인·계획) / answer(질문) / accept · decline · cancel(MCP 질문). */
  var SEAL_TEXT = { allow: '보냄', allow_session: '보냄', answer: '접수', accept: '접수', deny: '반송', decline: '반송', cancel: '반송' };
  function sealOf(decision) { var t = SEAL_TEXT[decision] || '접수'; return { text: t, tone: t === '반송' ? 'no' : 'ok' }; }
  function pad2(n) { return n < 10 ? '0' + n : '' + n; }
  /* 도장 아래 작은 줄 "MM.DD · 창구 이름"(오늘 날짜). */
  function sealSub(d, name) { return pad2(d.getMonth() + 1) + '.' + pad2(d.getDate()) + ' · ' + name; }
  /* 도장을 찍을 창구: 승인·계획은 검토 창구, 질문·MCP 질문은 그 세션이 선 창구. */
  function sealDesk(kind, k) { return kind === 'question' || kind === 'elicitation' ? STATION[Math.max(0, Math.min(4, k | 0))].desk : STATION[3].desk; }

  var api = { FILTERS: FILTERS, filterMatch: filterMatch, filterCounts: filterCounts, statusText: statusText, hereTitle: hereTitle, hereLine: hereLine, infoRow: infoRow, INSP: INSP,
    clerkLine: clerkLine, sealOf: sealOf, sealSub: sealSub, sealDesk: sealDesk, WHO: WHO, STATES: STATES, LABEL: LABEL, GLYPH: GLYPH, STATION: STATION, personOf: personOf, stateOf: stateOf, useOpenIds: useOpenIds, stationOf: stationOf, poseOf: poseOf, toneOf: toneOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHPostLogic = api;
})(typeof window !== 'undefined' ? window : this);
