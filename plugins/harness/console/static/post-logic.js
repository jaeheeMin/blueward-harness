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
  /* 단계 번호 2 는 개발·설정·표준·유지보수 갈래가 같이 쓴다(장면의 자리는 팀마다 따로). 안내판·정보 칸의 단계 이름은 갈래 일에 맞게 부른다(9회차 ②). */
  var STAGE_OF = { config: '설정', standard: '표준', fix: '수정' };
  function stageName(k, flow) {
    var i = Math.max(0, Math.min(4, k | 0));
    return (i === 2 && STAGE_OF[flow]) || STATION[i].name;
  }
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
    var tf = teamFlowOf(s);  // 콘솔 갈래가 없는 세션은 근거·쓴 갈래 스킬로 정한 팀(J15)
    if (tf && FLOW_STATION[tf] != null) return FLOW_STATION[tf];
    return 2;
  }

  /* 장면(office-post.js)이 사람을 세우는 곳: 승인 기다림은 리뷰 룸, 끝은 완료, 쉬는 중은 카페, 그 밖(내 차례·막힘·확인 못 함·일하는 중)은 팀 자리(팀이 없으면 리셉션).
     홈 팀 칸 숫자는 이 기준으로 지금 그 자리에 있는 사람만 센다(9회차 D) — 소속 인원을 세면 쉬는 사람이 팀 칸엔 있고 장면의 그 책상엔 없다. */
  function atDesk(state) { return state !== 'wait' && state !== 'done' && state !== 'idle'; }

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
    return team ? team + ' · ' + stageName(i, flow) : '팀 없음';
  }
  function hereLine(state) { return HERE[state] || '지금 일하고 있어'; }

  /* 정보 줄: 단계 · 요구사항 · 개발 번호 · 작업 기록 · 검토 요청. 값이 없는 칸은 지어내지 않고 "–" 로 둔다. cells 는 BHLogic.sessionStrip 의 칸들. */
  var INFO = [['단계', 'step'], ['요구사항', 'req'], ['개발 번호', 'dev'], ['작업 기록', 'issue'], ['검토 요청', 'pr']];
  function infoRow(cells, stepName) {
    var by = {};
    (cells || []).forEach(function (c) { by[c.id] = c; });
    var out = INFO.map(function (x) {
      var c = by[x[1]], v = x[1] === 'step' && stepName ? stepName : c && c.value;
      return { id: x[1], label: x[0], value: v == null || v === '' ? '–' : String(v), tone: c && c.tone || '', title: c && c.title || '' };
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
  /* 도장이 잠깐 남은 홈 카드의 한 줄: 한 일 + 찍힌 도장 글자(카드 위 도장과 같은 말). */
  var STAMP_DID = { '보냄': '승인했어', '접수': '답했어', '반송': '돌려보냈어' };
  function stampedLine(decision) { var t = sealOf(decision).text; return '방금 ' + STAMP_DID[t] + ' — ' + t + ' 도장을 찍었어'; }
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

  /* 팀 배정. 순서(2026-11-19 사용자 판정, 9회차 ④): ① 콘솔에서 시작한 갈래(flowId) ② 이슈·요구사항 근거(reqBasisOf — 브랜치 이슈의 DEV 번호) ③ 쓴 갈래 스킬 ④ 팀 없음.
     근거가 스킬보다 먼저다 — 요구사항을 쓴 세션이 같은 세션에서 start 로 설정 건을 시작하면 그 설정 건의 팀이다.
     ③ 스킬 → 팀은 workflow.json 에서 그 스킬이 어느 갈래의 단계인지로 정한 것 중 팀이 하나로 정해지는 것만이다(srs → 요구분석팀, spec → 설계팀).
     start·deliver 처럼 여러 갈래가 같이 쓰는 스킬과 도구 스킬은 팀을 정하지 않는다. 지금 쓰는 갈래 스킬, 없으면 가장 나중에 쓴 갈래 스킬인데,
     그 뒤에 start 를 썼으면(새 일을 시작함) 앞 갈래 스킬은 팀을 정하지 않는다(9회차 C — 갈래 스킬을 한 번 쓰면 끝까지 그 팀에 남던 것).
     돌려주는 값: { flow: 팀을 정한 갈래('' = 팀 없음), by: 'flow'|'req'|'skill'|'', skill, issue, dev, req, devNo } — 정보 칸이 같은 근거의 번호를 보인다(①). */
  var SKILL_TEAM_FLOW = { srs: 'srs', spec: 'spec' };
  function skillFlowOf(s) {
    if (s.currentSkill && SKILL_TEAM_FLOW[s.currentSkill]) return s.currentSkill;
    var used = Array.isArray(s.usedSkills) ? s.usedSkills : [];
    for (var i = used.length - 1; i >= 0; i--) {
      if (used[i] === 'start') return '';
      if (SKILL_TEAM_FLOW[used[i]]) return used[i];
    }
    return '';
  }
  function teamBasisOf(s) {
    if (!s) return { flow: '', by: '' };
    if (s.flowId) return { flow: s.flowId, by: 'flow' };
    var b = reqBasisOf(s, reqsFn ? reqsFn(s.cwd) : null);
    if (b.flow) return b;
    var sk = skillFlowOf(s);
    return sk ? Object.assign({}, b, { flow: SKILL_TEAM_FLOW[sk], by: 'skill', skill: sk }) : b;
  }
  function teamFlowOf(s) { return teamBasisOf(s).flow; }

  /* 정보 칸(9회차 ①): 콘솔 갈래가 없는 세션은 단계 칸이 「정해진 갈래 없음」, 번호 칸이 비어 안내판의 팀과 달라 보였다.
     팀을 정한 근거가 있으면 단계 칸은 안내판과 같은 단계 이름(풀이는 title), 요구사항·개발 번호 칸은 그 근거의 번호. 근거가 없으면 칸을 그대로 둔다. */
  function teamCells(cells, s, k) {
    var out = (cells || []).slice();
    if (!s || s.flowId) return out;
    var b = teamBasisOf(s), has = function (id) { return out.some(function (c) { return c.id === id; }); };
    if (b.flow && teamOf(b.flow)) {
      var why = b.by === 'skill' ? '쓴 스킬 /harness:' + b.skill : '브랜치 이슈 #' + b.issue + ' 의 ' + b.dev;
      out = out.map(function (c) { return c.id === 'step' ? { id: 'step', label: c.label, tone: '', value: stageName(k, b.flow), title: '콘솔에서 고른 갈래가 아니야. ' + teamOf(b.flow) + '을 정한 근거: ' + why } : c; });
    }
    if (b.req && !has('req')) out.push({ id: 'req', label: '요구사항', tone: '', value: b.req });
    if (b.dev && !has('dev')) out.push({ id: 'dev', label: '개발 번호', tone: '', value: b.dev });
    return out;
  }

  /* 팀 배정 J15 나머지(7회차, 9회차부터 갈래 스킬보다 먼저): 콘솔 갈래가 없는 세션은 브랜치의 이슈가 가리키는 요구사항으로 개발·설정·표준(·설계) 팀을 정한다.
     d = 그 세션 폴더의 /api/pipeline 결과(요구사항 items·열린 PR·열린 이슈의 DEV 번호). 근거가 갈래를 정하지 못하면 ''(팀 없음) — 짐작하지 않는다.
     1) 브랜치 `{type}/{이슈번호}-…`(branching.md)의 이슈 제목에 `[DEV-xxx]`(개발 본체) 나 `(DEV-xxx)`(하위 작업)가 있어야 한다(start·spec 스킬이 붙인다).
     2) 그 번호의 SRS 다음 단계가 설정·표준이면 config·standard(그 갈래는 [DEV-xxx] 로 start 하고 Spec 이 없다).
     3) 개발 요구사항이면: 이 브랜치가 코드 폴더(d.workPrefix, 기본 src/)를 바꿨으면(작업 중 변경·같은 브랜치 열린 작업 PR) dev, 그 번호의 Spec 파일만 바꿨으면 spec.
        바꾼 게 없으면 맨 앞 [DEV-xxx] 본체 이슈이고 Spec·요구사항이 main 에 있을 때만 dev(start: "SRS·Spec 단계는 그 이슈를 브랜치에 쓰지 않는다",
        Spec·요구사항이 없으면 개발을 시작하지 않고 spec 스킬이 같은 DEV 브랜치를 이어 쓸 수 있다). 그 밖(하위 작업이 아직 아무것도 안 바꿈)은 못 가른다.
     브랜치 접두어(feat/fix/docs)·이슈 라벨(type:*)·start 뒤 도구 스킬(atc·cts·role·unittest·manual)은 갈래를 정하지 않아 쓰지 않는다. 유지보수(fix 갈래)는 근거가 없어 콘솔에서 고른 세션만 앉는다. */
  var reqsFn = null;
  function useReqs(fn) { reqsFn = typeof fn === 'function' ? fn : null; }
  var BRANCH_ISSUE = /^[a-z]+\/(\d+)-/;
  function touches(paths, test) { return (Array.isArray(paths) ? paths : []).some(function (p) { return String(p).split(' -> ').some(test); }); }
  function pad3(n) { var t = String(n); return t.length >= 3 ? t : ('00' + t).slice(-3); }
  /* 근거와 번호: { flow, by: 'req'(팀을 정했을 때)|'', issue, dev, req, devNo }. 번호는 팀을 못 정해도 이슈가 가리키면 낸다(정보 칸은 사실만 보인다).
     바꾼 파일은 작업 중 변경(changedFiles)과 이 브랜치가 커밋한 파일 요약(branchTouch {code, specs}, 서버 pipeline.branch_touch — 커밋 뒤 푸시 전에도 남는다, 9회차 ③). */
  function reqBasisOf(s, d) {
    var none = { flow: '', by: '' };
    if (!s || !d || d.state !== 'yes' || !d.issues || d.issues.state !== 'ok') return none;
    var m = BRANCH_ISSUE.exec(String(s.branch || '')), iss = m && d.issues.byIssue ? d.issues.byIssue[m[1]] : null;
    if (!iss) return none;
    var it = (Array.isArray(d.items) ? d.items : []).filter(function (x) { return x && x.number === iss.dev; })[0];
    var b = { flow: '', by: '', issue: m[1], devNo: iss.dev, dev: it ? it.dev : 'DEV-' + pad3(iss.dev), req: it ? it.req || '' : '' };
    function team(flow) { b.flow = flow; b.by = flow ? 'req' : ''; return b; }
    if (!it) return b;
    if (it.kind === '설정') return team('config');
    if (it.kind === '표준') return team('standard');
    if (it.unsure || (it.req && it.next !== '개발')) return b;  // 다음 단계 미정·빈 칸: 개발인지 모른다
    var specRe = new RegExp('^docs/spec/(DEV-0*' + iss.dev + '(?![0-9])|$)'), prs = (Array.isArray(it.prs) ? it.prs : []).filter(function (p) { return p && p.branch && p.branch === s.branch; });
    var work = typeof d.workPrefix === 'string' && d.workPrefix ? d.workPrefix : 'src/';  // 코드 폴더: 서버(pipeline.py WORK_PREFIX)가 작업 PR 을 가르는 값과 같게(J13)
    var bt = s.branchTouch && typeof s.branchTouch === 'object' ? s.branchTouch : {};
    if (bt.code || touches(s.changedFiles, function (p) { return p.indexOf(work) === 0; }) || prs.some(function (p) { return p.kind === 'work'; })) return team('dev');
    if ((Array.isArray(bt.specs) && bt.specs.indexOf(iss.dev) >= 0) || touches(s.changedFiles, function (p) { return specRe.test(p); }) || prs.some(function (p) { return p.kind === 'spec'; })) return team('spec');
    return team(iss.main && it.spec && it.req ? 'dev' : '');  // Spec·요구사항이 main 에 있는 본체 이슈만 바꾼 게 없어도 개발(없으면 spec 스킬이 이어 쓰는 중일 수 있다)
  }
  function reqFlowOf(s, d) { return reqBasisOf(s, d).flow; }

  var api = { TEAMS: TEAMS, teamOf: teamOf, teamFlowOf: teamFlowOf, teamBasisOf: teamBasisOf, teamCells: teamCells, stageName: stageName, atDesk: atDesk, reqFlowOf: reqFlowOf, reqBasisOf: reqBasisOf, useReqs: useReqs, SKILL_TEAM_FLOW: SKILL_TEAM_FLOW, turnLine: turnLine, turnVerb: turnVerb, projectView: projectView, FILTERS: FILTERS, filterMatch: filterMatch, filterCounts: filterCounts, statusText: statusText, hereTitle: hereTitle, hereLine: hereLine, infoRow: infoRow, INSP: INSP,
    clerkLine: clerkLine, sealOf: sealOf, stampedLine: stampedLine, sealSub: sealSub, sealDesk: sealDesk, WHO: WHO, STATES: STATES, LABEL: LABEL, GLYPH: GLYPH, STATION: STATION, personOf: personOf, stateOf: stateOf, useOpenIds: useOpenIds, stationOf: stationOf, poseOf: poseOf, toneOf: toneOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHPostLogic = api;
})(typeof window !== 'undefined' ? window : this);
