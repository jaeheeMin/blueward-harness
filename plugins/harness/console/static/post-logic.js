/* Post(Cozy Office) 테마가 세션을 사람으로 바꾸는 순수 규칙(#1013 이어서). DOM 을 만지지 않는다(node 로 시험한다).
   사람 고정 배정(personOf)·상태(stateOf)·단계 번호(stationOf)·자세·아바타 바탕을 한곳에서 정해, 장면(theme-post.js)과 모든 화면의 아바타가 같은 값을 쓴다.
   stateOf·stationOf 는 flow-logic.js(BHLogic)를 넘겨받아 쓴다 — 세션 목록·홈과 같은 groupOf·blockOf 기준이다. */
(function (root) {
  'use strict';

  var WHO = ['mint', 'navy', 'rose', 'sunny', 'sky', 'sage', 'kid'];
  /* 상태 순서(위가 먼저): 내 차례 > 막힘 > 확인 못 함 > 일하는 중 > 승인 기다림 > 끝 > 쉬는 중 */
  var STATES = ['turn', 'blocked', 'unk', 'run', 'wait', 'done', 'idle'];
  var LABEL = { turn: '내 답이 필요해', blocked: '막혔어', unk: '확인 못 함', run: '일하는 중', wait: '승인 기다림', done: '끝났어', idle: '쉬는 중' };
  var GLYPH = { turn: '!', blocked: '✕', unk: '?', done: '✓', wait: '…' };
  /* desk = 팀과 무관한 곳(검토 3 = 리뷰 룸, 끝 4 = 완료). 0~2 는 세션의 팀 이름으로 부른다(hereTitle·placeOf·sealDesk). */
  var STATION = [
    { name: '요구사항', hint: '무엇을 만들지 쓰기' }, { name: '개발 Spec', hint: '어떻게 만들지 설계' },
    { name: '개발', hint: 'AI가 만드는 중' }, { name: '검토', hint: '팀 승인 받기', desk: '리뷰 룸' },
    { name: '합쳐짐', hint: '끝, 반영됨', desk: '완료' }
  ];
  /* 사무실 장면(office-post.js) 아래 팀 요약과 같은 팀 표. 갈래(flowId) → 팀. 요구사항·Spec·개발 자리(0~2)는 세션의 팀 이름으로 부른다(설정·표준·유지보수 갈래도 개발 단계 번호 2 를 쓴다). */
  var TEAMS = [['요구분석팀', ['srs', 'srs-export']], ['설계팀', ['spec']], ['개발팀', ['dev']], ['기능컨설팅팀', ['config']], ['표준화팀', ['standard']], ['유지보수팀', ['fix']]];
  function teamOf(flow) {
    for (var i = 0; i < TEAMS.length; i++) if (TEAMS[i][1].indexOf(flow) >= 0) return TEAMS[i][0];
    return '';
  }

  /* 세션 id 로 사람을 고정한다. 새로고침·목록 변화와 무관하다(가이드 6.3). */
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

  /* 단계 번호 k = 0~4 (가이드 6.1). 갈래의 지금 단계 이름에 "올리고 검토 요청하기"·"합쳐지기 기다리기" 가 있고 PR 이 열려 있으면 검토(리뷰 룸)다. */
  var FLOW_STATION = { srs: 0, 'srs-export': 0, spec: 1, dev: 2, config: 2, standard: 2, fix: 2 };
  function stationOf(s, L) {
    if (!s) return 2;
    if (prState(s) === 'MERGED' || s.flowFinished || s.phase === 'finished') return 4;
    var step = L && L.currentStep ? L.currentStep(s) : null, name = step ? String(step.name || step.id || '') : '';
    if (s.phase === 'approval' || (prState(s) === 'OPEN' && /올리고|합쳐지기/.test(name))) return 3;
    var tf = teamFlowOf(s);  // 터미널 세션은 쓴 갈래 스킬의 팀(J15)
    if (tf && FLOW_STATION[tf] != null) return FLOW_STATION[tf];
    return 2;
  }

  function poseOf(state) {
    return state === 'turn' ? 'ask' : state === 'blocked' || state === 'unk' ? 'stuck' : state === 'wait' ? 'wait' : state === 'done' ? 'done' : 'walk';
  }
  /* 아바타 바탕색 갈래: 내 차례 노랑 · 막힘 분홍 · 끝 연두 · 그 밖 베이지(가이드 2.2) */
  function toneOf(state) { return state === 'turn' ? 'turn' : state === 'blocked' ? 'blocked' : state === 'done' ? 'done' : ''; }

  /* ---------- 세션·요청 화면(B단계): 목록 걸러보기 · 자리 안내 · 정보 줄 · 도장 글자 ---------- */

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

  /* 세션 머리 오른쪽 안내판(figure.po-here). 첫 줄은 지금 앉은 곳 "{팀} · {단계}"(리뷰 룸·완료는 "리뷰 룸 · 검토"·"완료 · 합쳐짐", 팀이 없으면 "팀 없음"), 둘째 줄은 상태별 반말(가이드 2.4). */
  /* 확인 못 함(unk)은 blockOf 의 cannot_check — 검사를 못 돌린 것이지 자리를 모르는 게 아니다(첫 줄이 이미 앉은 곳). 쉬는 중은 걷지 않는다(장면에서도 앉아 있다) */
  var HERE = { turn: '네 답을 기다리고 있어', blocked: '막혀서 멈춰 있어', wait: '의자에 앉아 승인을 기다려', done: '일을 다 마쳤어', unk: '검사를 못 해서 멈췄어', idle: '잠깐 쉬고 있어' };
  /* k = 단계 번호(0~4), flow = 세션의 팀을 정한 갈래(teamFlowOf). 번호 0~2 인데 팀이 없으면(갈래 없는 세션은 단계 2 로 두지만 팀 자리는 없다) "팀 없음". */
  function hereTitle(k, flow) {
    var i = Math.max(0, Math.min(4, k | 0));
    if (i === 3) return STATION[3].desk + ' · ' + STATION[3].name;
    if (i === 4) return STATION[4].desk + ' · ' + STATION[4].name;
    var team = teamOf(flow);
    return team ? team + ' · ' + STATION[i].name : '팀 없음';
  }
  function hereLine(state) { return HERE[state] || '지금 일하고 있어'; }

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

  /* 고른 프로젝트(저장소)로 세션 거르기(#1070). folders: 서버 /api/repos 의 폴더별 판정 { cwd: { state, key, name, top, folder } },
     project: { key, top }(고른 저장소와 고른 폴더의 맨 위 폴더) 또는 null(거르지 않음). 돌려주는 값: { list: 보이는 세션(순서 그대로), tag: { 세션 id: { kind, text } } }.
     같은 저장소면 보이고, 고른 폴더와 맨 위 폴더가 다르면(같은 저장소의 작업용 폴더·worktree) 폴더 이름을 붙인다. 다른 저장소는 뺀다.
     git 저장소가 아니거나(no) 판정하지 못한(unknown, 폴더 없음 등) 세션은 감추지도 어느 저장소라고 지어내지도 않고 보이되 그렇다고 붙인다.
     아직 판정을 받지 못한 폴더(목록에 없음)는 보이고 아무것도 붙이지 않는다(곧 받는다). */
  var PROJECT_TAG = { no: 'git 저장소 아님', unknown: '저장소 확인 못 함' };
  function projectView(list, folders, project) {
    var tag = {};
    if (!project || !project.key || !folders) return { list: list.slice(), tag: tag };
    var out = list.filter(function (s) {
      var f = s && s.cwd ? folders[s.cwd] : { state: 'unknown' };
      if (!f) return true;
      if (f.state === 'yes') {
        if (f.key !== project.key) return false;
        if (f.top && project.top && f.top !== project.top) tag[s.id] = { kind: 'folder', text: f.folder || f.top };
        return true;
      }
      tag[s.id] = { kind: f.state === 'no' ? 'nogit' : 'unknown', text: PROJECT_TAG[f.state] || PROJECT_TAG.unknown };
      return true;
    });
    return { list: out, tag: tag };
  }

  var INSP = ['산출물', '검사', '기억', '기록', '기술'];

  /* 요청 화면 한 줄(가이드 2.5): 승인·계획은 리뷰 룸의 검토 담당, 질문은 그 세션이 앉은 곳. 앉은 곳을 모르면(팀 없음·완료) 곳 이름 없이 말한다. */
  function placeOf(k, flow) {
    var i = Math.max(0, Math.min(4, k | 0));
    if (i === 3) return STATION[3].desk;
    return i < 3 && teamOf(flow) ? teamOf(flow) + ' 자리' : '';
  }
  function clerkLine(kind, k, flow) {
    if (kind === 'question' || kind === 'elicitation') { var at = placeOf(k, flow); return (at ? at + '에서 ' : '세션이 ') + '손을 들고 네 답을 기다려'; }
    return '리뷰 룸에서 검토 담당이 네 승인을 기다려. 누르면 승인 도장이 찍혀';
  }

  /* 도장 글자. 승인 주 버튼(허락·올리기·계획대로 진행) = 보냄, 질문·MCP 질문에 답을 보냄 = 접수, 거절·아니오·닫기·고쳐 달라고 하기 = 반송.
     decision: allow · allow_session · deny(승인·계획) / answer(질문) / accept · decline · cancel(MCP 질문). */
  var SEAL_TEXT = { allow: '보냄', allow_session: '보냄', answer: '접수', accept: '접수', deny: '반송', decline: '반송', cancel: '반송' };
  function sealOf(decision) { var t = SEAL_TEXT[decision] || '접수'; return { text: t, tone: t === '반송' ? 'no' : 'ok' }; }
  function pad2(n) { return n < 10 ? '0' + n : '' + n; }
  /* 도장 아래 작은 줄 "MM.DD · 자리 이름"(오늘 날짜). 자리를 모르면(name 이 빈 글) 날짜만. */
  function sealSub(d, name) { return pad2(d.getMonth() + 1) + '.' + pad2(d.getDate()) + (name ? ' · ' + name : ''); }
  /* 도장을 찍는 곳: 승인·계획은 리뷰 룸, 질문·MCP 질문은 그 세션이 앉은 곳(팀 자리·리뷰 룸·완료, 팀이 없으면 빈 글 — 요청 줄(clerkLine)처럼 곳 이름 없이). */
  function sealDesk(kind, k, flow) {
    if (kind !== 'question' && kind !== 'elicitation') return STATION[3].desk;
    var i = Math.max(0, Math.min(4, k | 0));
    return i >= 3 ? STATION[i].desk : teamOf(flow) ? teamOf(flow) + ' 자리' : '';
  }

  /* 갈래 세션의 차례 글(세션 머리 제목·사이드 줄·홈 덱). 서버의 차례(turnSkill)는 git 상태로 짐작한 start·deliver·prs 라 갈래 단계와 어긋난다:
     srs·spec 첫 단계는 main 에서 시작해 "작업 시작", 구현 중 변경이 있으면 "올릴 준비". Post 는 갈래의 지금 단계를 따른다.
     갈래가 없거나 끝났거나 지금 단계를 모르면 null(원래 글). 올리기 단계에 올릴 변경이 있으면(G-09) 원래 글이 맞아 null. */
  function flowNow(s, L) {
    if (!s || !s.flowId || s.flowFinished || !L) return null;
    var st = L.currentStep(s);
    if (!st) return null;
    return { name: L.shortStepName(st.name || st.id), short: L.stepShort(st), deliver: st.kind === 'skill' && st.skill === 'deliver', wait: st.kind === 'wait' };
  }
  function turnLine(s, L) {
    var t = flowNow(s, L);
    if (!t || (t.deliver && s.turnSkill === 'deliver')) return null;
    return t.wait ? '지금은 ' + t.name + ' 단계야.' : '이제 ' + t.name + ' 차례야.';
  }
  /* 사이드 줄 "내 차례 · …" 의 뒤 글: 올리기 단계가 아니면 갈래 단계 짧은 이름(구현·설정·기록 …). */
  function turnVerb(s, L) {
    var t = flowNow(s, L);
    return t && !t.deliver ? t.short : null;
  }

  /* 팀 배정(J15, 2026-11-18 사용자 판정): 갈래(flowId)가 있으면 그대로, 없으면(터미널에서 연 세션) 쓴 갈래 스킬로 맞는 팀의 갈래를 돌려준다.
     스킬 → 팀은 workflow.json 에서 그 스킬이 어느 갈래의 단계인지로 정한 것 중 팀이 하나로 정해지는 것만이다(srs → 요구분석팀, spec → 설계팀).
     start·deliver 처럼 여러 갈래가 같이 쓰는 스킬과 도구 스킬은 팀을 정하지 않는다(개발·설정·표준·유지보수 갈래의 첫 단계는 모두 start 라 스킬만으로는 못 가른다).
     여러 스킬을 썼으면 지금 쓰는 스킬, 없으면 가장 나중에 쓴 갈래 스킬. 없으면 ''(팀 없음). */
  var SKILL_TEAM_FLOW = { srs: 'srs', spec: 'spec' };
  function teamFlowOf(s) {
    if (!s) return '';
    if (s.flowId) return s.flowId;
    if (s.currentSkill && SKILL_TEAM_FLOW[s.currentSkill]) return SKILL_TEAM_FLOW[s.currentSkill];
    var used = Array.isArray(s.usedSkills) ? s.usedSkills : [];
    for (var i = used.length - 1; i >= 0; i--) if (SKILL_TEAM_FLOW[used[i]]) return SKILL_TEAM_FLOW[used[i]];
    return '';
  }

  var api = { TEAMS: TEAMS, teamOf: teamOf, teamFlowOf: teamFlowOf, SKILL_TEAM_FLOW: SKILL_TEAM_FLOW, turnLine: turnLine, turnVerb: turnVerb, projectView: projectView, FILTERS: FILTERS, filterMatch: filterMatch, filterCounts: filterCounts, statusText: statusText, hereTitle: hereTitle, hereLine: hereLine, infoRow: infoRow, INSP: INSP,
    clerkLine: clerkLine, sealOf: sealOf, sealSub: sealSub, sealDesk: sealDesk, WHO: WHO, STATES: STATES, LABEL: LABEL, GLYPH: GLYPH, STATION: STATION, personOf: personOf, stateOf: stateOf, useOpenIds: useOpenIds, stationOf: stationOf, poseOf: poseOf, toneOf: toneOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHPostLogic = api;
})(typeof window !== 'undefined' ? window : this);
