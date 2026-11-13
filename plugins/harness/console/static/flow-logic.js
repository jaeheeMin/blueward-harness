/* 갈래·도구·문서 칸의 화면 규칙. DOM 을 만지지 않는 순수 함수만 둔다(node 로 시험한다). */
(function (root) {
  'use strict';

  var BAR_LABEL = { done: '끝', now: '지금', wait: '대기', skipped: '건너뜀' };
  // 도구 순서와 서버 데이터를 못 받았을 때의 기본값(플러그인 workflow.json 의 tools 중 늘 보이는 것과 같은 순서)
  var DEFAULT_TOOLS = [
    { id: 'version', name: '설치된 버전 보기', kind: 'skill', skill: 'version' },
    { id: 'sync', name: '최신 상태 받기', kind: 'skill', skill: 'sync' },
    { id: 'update', name: '하네스 갱신', kind: 'skill', skill: 'update' },
    { id: 'handoff', name: '새 세션으로 이어 가기', kind: 'skill', skill: 'handoff' },
    { id: 'wrapup', name: '남은 일 적어 두기', kind: 'skill', skill: 'wrapup' },
    { id: 'prs', name: '내 PR 보기', kind: 'skill', skill: 'prs' },
    { id: 'reload', name: '하네스 다시 불러오기', kind: 'console' },
    { id: 'approvals', name: '내가 승인할 PR', kind: 'skill', skill: 'approvals', requires: 'approver' }
  ];
  var NO_FLOW_ID = 'none';  // 갈래 없이 도구만 쓰는 일(서버 analysis.NO_FLOW 와 같다)
  var CHECK_ORDER =['sync', 'version', 'update', 'reload'];
  var CHECK_NAMES = { sync: '최신 내용 받기', version: '하네스 판', update: '갱신', reload: '다시 불러오기' };
  // 시안 G-13: 새 세션이 스스로 하는 점검은 이 두 줄뿐이다. 갱신·다시 불러오기는 도구 줄(자세히)에서 직접 한다.
  var AUTO_CHECKS = ['sync', 'version'];
  var CHECK_STATES = { done: ['ok', 'done', 'pass', 'passed', 'fresh', 'same'], run: ['running', 'active', 'doing'], fail: ['fail', 'failed', 'error', 'stale', 'differs', 'old'] };
  var JOB_OK = ['done', 'ready', 'complete', 'completed', 'ok', 'success', 'succeeded'];
  var JOB_FAIL = ['error', 'fail', 'failed', 'cancelled', 'canceled'];
  var PREVIEW_KINDS = ['md', 'table', 'slides', 'image'];
  var KIND_BADGE = { md: '글', table: '표', slides: '슬라이드', image: '그림', pdf: 'PDF', doc: '문서' };
  var CHECK_TEXT = { pass: '검사 통과', fail: '검사 실패', pending: '검사 진행 중', none: '검사 없음' };
  var LIVE_ENDED = 'ended';

  function arr(v) { return Array.isArray(v) ? v : []; }
  function lower(v) { return String(v == null ? '' : v).toLowerCase(); }

  function groupOf(s) {
    var g;
    if (s.group === 'todo' || s.group === 'running' || s.group === 'idle') g = s.group;
    else if (arr(s.pendingRequestIds).length || s.turnSkill || s.askedInText) g = 'todo';
    else g = s.status === 'running' || s.status === 'starting' ? 'running' : 'idle';
    // 시안 G-24: 내 PR 의 검사가 실패한 세션(일하는 중 아님·끝난 세션 아님)은 고칠 차례라 내 차례로 센다. 막힘(✕·?)은 호출한 쪽이 따로 거른다.
    if (g === 'idle' && s.status !== 'ended' && prNeedsFix(s)) return 'todo';
    return g;
  }

  /* 훅이 막아 아직 풀리지 않은 세션(#790). { kind: 'blocked'(✕ 막힘) | 'cannot_check'(? 확인 못 함), t } 또는 null.
     막힘 뒤에 내 말·AI 말이 이어졌으면 풀린 걸로 본다. 묻는 요청이 떠 있거나 AI 가 일하는 중이면 그쪽이 먼저라 null.
     대화(chat)를 알면 그걸로, 목록에는 서버가 준 lastBlock.open 으로 센다(open 을 모르는 옛 서버는 null: 열렸는지 알 수 없는 걸 막힘으로 치지 않는다). */
  function blockOf(s) {
    if (!s || s.status === 'ended' || s.status === 'running' || s.status === 'starting' || arr(s.pendingRequestIds).length) return null;
    var chat = arr(s.chat);
    if (s.chat && Array.isArray(s.chat)) {
      for (var i = chat.length - 1; i >= 0; i--) {
        var c = chat[i];
        if (!c || typeof c !== 'object') continue;
        if (c.role === 'me' || c.role === 'ai') return null;
        if (c.role === 'block') return { kind: c.kind === 'cannot_check' ? 'cannot_check' : 'blocked', t: c.t };
      }
      return null;
    }
    var b = s.lastBlock;
    return b && b.open === true ? { kind: b.kind === 'cannot_check' ? 'cannot_check' : 'blocked', t: b.t } : null;
  }
  /* 세션을 세는 갈래. 막힘·확인 못 함은 내 차례와 따로 센다(내 차례 숫자에 섞지 않는다). */
  function counts(list) {
    var c = { total: 0, running: 0, todo: 0, idle: 0, blocked: 0, unsure: 0 };
    list.forEach(function (s) {
      c.total++;
      var b = blockOf(s);
      if (b) c[b.kind === 'cannot_check' ? 'unsure' : 'blocked']++; else c[groupOf(s)]++;
    });
    return c;
  }
  function summaryText(c) {
    return '세션 ' + c.total + '개 · 일하는 중 ' + c.running + ' · 내 차례 ' + c.todo + (c.blocked ? ' · ✕ 막힘 ' + c.blocked : '') + (c.unsure ? ' · ? 확인 못 함 ' + c.unsure : '') + ' · 쉬는 중 ' + c.idle;
  }

  /* ---- 순서 막대 ---- */
  function stepState(step, index, s) {
    var st = lower(step && step.state);
    if (st === 'skipped') return 'skipped';
    if (st === 'done') return 'done';
    if (s.flowFinished) return 'done';
    if (index === s.stepIndex || st === 'active') return 'now';
    return 'wait';
  }
  function barSteps(s) {
    return arr(s && s.flowSteps).map(function (st, i) {
      var state = stepState(st, i, s);
      return { index: i, id: st.id, name: st.name || st.id || '', kind: st.kind, skill: st.skill || '', state: state, label: BAR_LABEL[state], reason: st.reason || '', short: st.short || '' };
    });
  }
  function currentStep(s) {
    var steps = arr(s && s.flowSteps);
    return s && !s.flowFinished && typeof s.stepIndex === 'number' ? steps[s.stepIndex] || null : null;
  }
  function orderText(flow) {
    return arr(flow && flow.steps).map(function (st) {
      return st.kind === 'skill' && st.skill ? st.skill : st.name;
    }).join(' → ');
  }

  /* ---- 다음 단계 버튼 하나 ---- */
  function nextAction(s) {
    if (!s || !s.flowId) return { type: 'pick' };
    if (s.flowFinished) return { type: 'finished' };
    var step = currentStep(s);
    if (!step) return { type: 'none', note: '지금 단계를 읽지 못했어.' };
    var busy = s.status === 'running' || s.status === 'starting';
    var cannot = s.canSend === false ? (s.cannotSendReason || '이 세션에는 지금 요청을 보낼 수 없어.') : '';
    var base = { step: step, stepName: step.name || step.id || '', hint: step.hint || '' };
    function make(extra) { return Object.assign({}, base, extra); }
    if (step.kind === 'skill' && step.skill) {
      var again = lower(step.state) === 'active' && !busy;
      return make({ type: 'skill', skill: step.skill, label: '/harness:' + step.skill + (again ? ' 다시 실행' : ' 실행'),
        disabled: busy || !!cannot, disabledReason: busy ? '지금 Claude Code 가 일하는 중이야.' : cannot, cannotSend: !busy && !!cannot });
    }
    if (step.kind === 'work') return make({ type: 'done', label: '끝났어' });
    if (step.kind === 'human') return make({ type: 'human', label: '끝났어', refreshLabel: '다시 확인' });
    // wait 와 그 밖: 상태를 보여 주고 다시 확인만 한다. 도우미 스킬이 있으면 보조로 둔다.
    return make({ type: 'wait', label: '다시 확인', helper: step.helperSkill || '', helperDisabled: busy || !!cannot });
  }

  /* ---- 시안 G-09: 단계별 질문 한 줄 ---- */
  // 올릴 차례(deliver)는 "질문 + 한 줄 설명 + 단추 둘(올리고 검토 요청 / 아직)". 다른 스킬 단계는 단계 이름과 설명을 그대로 쓴다.
  var ASK_TEXT = {
    deliver: { q: 'GitHub에 올려서 검토 요청(PR)을 만들까?', sub: '팀 승인자가 확인해야 합쳐져.', yes: '올리고 검토 요청',
      later: '알겠어, 아직 안 올릴게', laterSub: '준비되면 아래 단추를 눌러 줘.' }
  };

  /* ---- 건너뛰기 이유 ---- */
  function skipReasonError(text) { return String(text || '').trim() ? '' : '건너뛰는 이유를 적어 줘.'; }

  /* ---- 다음 갈래 ---- */
  function nextOptions(s) {
    var nf = (s && s.nextFlow) || {};
    var opts = arr(nf.options).map(function (o) {
      var label = o.label || o.name || '';
      var count = typeof o.count === 'number' ? ' (' + o.count + '건)' : '';
      return { flow: o.flow || null, label: label + (o.value ? ' · ' + o.value + count : ''), disabled: !!o.disabled,
        clickable: !!o.flow && !o.disabled, ids: arr(o.ids) };
    });
    return { options: opts, hint: nf.hint || '', unknown: nf.unknown || '' };
  }
  function jobOutcome(job) {
    var st = lower(job && job.state);
    var status = lower(job && job.status);
    if (status === 'confirm') return { done: false, confirm: true, prompt: String((job && job.prompt) || ''), warning: String((job && job.warning) || '') };
    if (status === 'canceled') return { done: true, ok: false, canceled: true, error: '취소했어.' };
    if (job && job.error) return { done: true, ok: false, error: String(job.error) };
    if (JOB_FAIL.indexOf(st) >= 0) return { done: true, ok: false, error: (job && job.error) || '새 세션을 만들지 못했어.' };
    if (job && job.sessionId && (!st || JOB_OK.indexOf(st) >= 0)) return { done: true, ok: true, sessionId: job.sessionId };
    if (JOB_OK.indexOf(st) >= 0) return { done: true, ok: !!(job && job.sessionId), sessionId: job && job.sessionId, error: job && job.sessionId ? '' : '새 세션 번호를 받지 못했어.' };
    return { done: false };
  }

  /* ---- 막힘 카드 사유의 영문 이름을 쉬운 말로(#794) ----
     화면에 보이는 글만 바꾼다. 원문은 "검사 원문" 안에 그대로 두고, AI 에게 보내는 글도 원문을 쓴다. */
  var PLAIN_WORDS = [
    [/mcp__[A-Za-z0-9_-]+__[A-Za-z]+/g, 'SAP 연결 도구'],
    [/\binactiveObjects\b/g, '“아직 활성화 안 된 오브젝트 보기”'],
    [/\b(?:activateObjects|activateByName)\b/g, '“오브젝트 활성화”'],
    [/\bsetObjectSource\b/g, '“SAP 소스 쓰기”'],
    [/\bcreateObject\b/g, '“오브젝트 만들기”'],
    [/\bdeleteObject\b/g, '“오브젝트 지우기”'],
    [/\bactivation_gate\b/g, '활성화 확인'],
    [/\b(?:pre_write_guard|mcp_source_guard|agent_delegation_guard)\b/g, '하네스 검사']
    // 이름 모양만 보고 바꾸지 않는다("jaeheeMin/blueward-harness" 같은 저장소 이름·고유 명사가 망가진다). 아는 이름만 바꾼다.
  ];
  function plainReason(text) {
    var out = String(text == null ? '' : text);
    PLAIN_WORDS.forEach(function (r) { out = out.replace(r[0], r[1]); });
    return out;
  }

  /* ---- 지금 하는 일(#818): 서버가 주는 "Skill: harness:srs" · "Bash: git push …" 같은 원문을 쉬운 말로 ----
     입력 원문(명령·경로)은 어디에도 내지 않는다. 원문은 세션 화면 "자세히 > 기술 정보" 에서만 보인다.
     labelFn(스킬 id) 은 스킬 이름표를 돌려주는 함수(없으면 id 그대로). */
  var ACTION_WORDS = [
    [/^(?:Write|Edit|MultiEdit|NotebookEdit)$/, '파일 고치는 중'],
    [/^(?:Read|Glob|Grep|LS)$/, '파일 살펴보는 중'],
    [/^(?:Agent|Task)$/, '보조에게 맡기는 중'],
    [/^(?:WebFetch|WebSearch)$/, '웹에서 찾는 중'],
    [/^Bash$/, '명령 실행 중'],
    [/^TodoWrite$/, '할 일 정리하는 중'],
    [/^Compact$/, '기억을 요약하는 중']
  ];
  function plainAction(text, labelFn) {
    var t = String(text == null ? '' : text).trim();
    if (!t) return '작업하는 중';
    var i = t.indexOf(':'), tool = (i < 0 ? t : t.slice(0, i)).trim(), input = i < 0 ? '' : t.slice(i + 1).trim();
    if (tool === 'Skill') {
      var id = input.split(/\s+/)[0].replace(/^[^:\s]*:/, '');
      if (!id) return '작업하는 중';
      var label = typeof labelFn === 'function' ? labelFn(id) : id;
      return (label || id) + ' 진행 중';
    }
    if (/^mcp__/.test(tool)) return /abap/i.test(tool) ? 'SAP 연결 도구 쓰는 중' : '연결 도구 쓰는 중';
    for (var k = 0; k < ACTION_WORDS.length; k++) if (ACTION_WORDS[k][0].test(tool)) return ACTION_WORDS[k][1];
    return '작업하는 중';
  }

  // 콘솔이 첫 말 앞에 붙인 "/harness:spec" 같은 스킬 명령 줄은 대화 풍선에서만 숨긴다(#818). Claude Code 에게 간 글은 그대로다.
  function hideSkillLine(text) {
    var t = String(text == null ? '' : text), m = /^\/[A-Za-z0-9_-]+:[A-Za-z0-9_-]+[ \t]*(?:\r?\n|$)/.exec(t);
    if (!m) return t;
    var rest = t.slice(m[0].length).replace(/^(?:[ \t]*\r?\n)+/, '');
    return rest.trim() ? rest : t;
  }

  /* ---- 도구 줄 ---- */
  // ctx: { managed(콘솔 세션인가), hasSession(세션 화면인가), approvals({state}) }
  function visibleTools(flowsData, approvals, ctx) {
    var tools = flowsData && arr(flowsData.tools).length ? flowsData.tools : DEFAULT_TOOLS;
    return tools.filter(function (t) {
      if (t.id === 'approvals') return !!(approvals && approvals.state === 'yes');
      if (t.hidden) return false;  // 콘솔 화면에 단추를 내지 않는 도구(예: 콘솔을 여는 open)
      if (t.exposure && t.exposure.visible === false) return false;
      if (t.id === 'reload') return !!(ctx && ctx.hasSession && ctx.managed);
      return true;
    });
  }
  // 프로젝트 준비 안내(templates/·rules/ 가 있는지). 조건을 못 읽었으면 숨기지 않고 '확인 못 함' 으로 알린다.
  function projectNotice(flowsData) {
    var c = flowsData && flowsData.conditions && flowsData.conditions['project-ready'];
    if (!c) return null;
    if (c.state === 'no') {
      return { state: 'no', text: '프로젝트 준비 안 됨 - ' + (c.reason || 'templates/ 나 rules/ 가 없어.') +
        ' 고객사 프로젝트라면 관리자가 처음에 한 번 기본 폴더 구조를 만들어 줘야 해.' };
    }
    if (c.state === 'unknown') return { state: 'unknown', text: '프로젝트 준비 여부를 확인하지 못했어' + (c.reason ? ' - ' + c.reason : '') + '.' };
    return null;
  }
  // 준비됨인데 templates/ 에 고객 양식 원본이 없을 때의 안내. 서버가 없다고 확인한 경우(formsMissing === 'yes')에만 말한다. 못 읽었으면 null.
  var FORMS_MISSING_SHORT = '고객 양식 아직 없음';
  var FORMS_MISSING_TEXT = '고객 양식이 아직 없어 · templates/ 에 고객사 양식 파일을 넣어야 문서를 양식대로 뽑을 수 있어. 양식 없이 md 로만 쓰는 프로젝트면 신경 안 써도 돼.';
  function formsNotice(flowsData) {
    var c = flowsData && flowsData.conditions && flowsData.conditions['project-ready'];
    return c && c.state === 'yes' && flowsData.formsMissing === 'yes' ? { text: FORMS_MISSING_TEXT, short: FORMS_MISSING_SHORT } : null;
  }
  function liveCount(list) { return list.filter(function (s) { return s.status !== LIVE_ENDED; }).length; }
  function reloadStrip(updatePressed, list) {
    var n = liveCount(list);
    return updatePressed && n > 0 ? { count: n, text: '돌고 있는 세션 ' + n + '개 다시 불러오기 필요' } : null;
  }
  function reloadResult(d) {
    if (d && d.queued) return '지금 하는 일이 끝나면 다시 불러올게.';
    var plugin = arr(d && d.plugins).filter(function (p) { return p && p.name === 'harness'; })[0];
    var ver = (d && d.harnessVersion) || (plugin && plugin.version) || '';
    var text = ver ? 'harness ' + ver + ' 로 다시 불러왔어.' : '다시 불러왔어.';
    if (d && d.errorCount) text += ' (오류 ' + d.errorCount + '개)';
    return text;
  }

  /* ---- 새 세션 점검 ---- */
  function checkState(raw) {
    var st = lower(raw);
    if (CHECK_STATES.done.indexOf(st) >= 0) return 'done';
    if (CHECK_STATES.run.indexOf(st) >= 0) return 'run';
    if (CHECK_STATES.fail.indexOf(st) >= 0) return 'fail';
    return 'todo';
  }
  var CHECK_LABEL = { done: '됐어', run: '하는 중', fail: '다시 필요', todo: '아직' };
  // 자동 점검이 아직 안 끝났는가(새 세션이 첫 일을 하기 전). 건너뛴 항목은 끝난 것으로 본다.
  function autoChecksOpen(s) {
    return arr(s && s.startChecks).some(function (c) { return c && AUTO_CHECKS.indexOf(c.id) >= 0 && lower(c.state) === 'pending'; });
  }
  function startChecks(s) {
    var list = arr(s && s.startChecks);
    if (!list.length) return [];
    return AUTO_CHECKS.map(function (id) {
      var hit = list.filter(function (c) { return c && c.id === id; })[0];
      if (!hit) return null;
      var state = checkState(hit.state);
      return { id: id, name: CHECK_NAMES[id], state: state, label: CHECK_LABEL[state], kind: id === 'reload' ? 'console' : 'skill' };
    }).filter(Boolean);
  }

  /* ---- 같은 폴더 ---- */
  function normPath(p) { return String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase(); }
  function otherSessions(cwd, list, selfId) {
    var key = normPath(cwd);
    return key ? list.filter(function (s) { return s.id !== selfId && s.status !== LIVE_ENDED && !s.handedOffTo && normPath(s.cwd) === key; }) : [];
  }
  function sameFolderBusy(s, list) {
    if (!s || s.handedOffTo) return false;
    if (arr(s.sameFolder).length) return true;
    return otherSessions(s.cwd, list, s.id).length > 0;
  }

  /* ---- 만든 문서 ---- */
  function previewKind(path) {
    var m = /\.([a-z0-9]+)$/i.exec(String(path || ''));
    var ext = m ? m[1].toLowerCase() : '';
    if (ext === 'md' || ext === 'txt') return 'md';
    if (ext === 'xlsx' || ext === 'xlsm' || ext === 'csv') return 'table';
    if (ext === 'pptx') return 'slides';
    if (ext === 'png' || ext === 'jpg' || ext === 'jpeg' || ext === 'gif' || ext === 'webp') return 'image';
    if (ext === 'pdf') return 'pdf';
    return 'doc';
  }
  function kindBadge(f) {
    var k = f && f.kind && KIND_BADGE[f.kind] ? f.kind : previewKind(f && f.path);
    return KIND_BADGE[k] || KIND_BADGE.doc;
  }
  function docList(files) {
    return arr(files).filter(function (f) { return f && f.path; }).slice().sort(function (a, b) { return (b.mtime || 0) - (a.mtime || 0); });
  }
  function versionPaths(f) {
    // 서버 versions 는 최신(대표) 파일도 담는다. 이전 판 목록에서는 대표 파일 자신을 뺀다.
    return arr(f && f.versions).map(function (v) { return typeof v === 'string' ? { path: v } : v; })
      .filter(function (v) { return v && v.path && v.path !== (f && f.path); });
  }
  // 미리보기 응답은 { kind, ... } 로도, { md: {...} } 처럼 종류가 키여도 받는다.
  function normPreview(d) {
    if (!d || typeof d !== 'object') return { kind: 'none' };
    var kind = lower(d.kind || d.type);
    var body = d;
    if (!kind) {
      kind = PREVIEW_KINDS.filter(function (k) { return d[k] && typeof d[k] === 'object'; })[0] || (d.none ? 'none' : '');
      body = kind ? d[kind] : d;
    }
    if (kind === 'md') return { kind: 'md', text: String(body.text == null ? '' : body.text) };
    if (kind === 'table') return { kind: 'table', sheets: arr(body.sheets) };
    if (kind === 'slides') return { kind: 'slides', slides: arr(body.slides) };
    if (kind === 'image') return { kind: 'image', url: String(body.url || '') };
    return { kind: 'none', reason: body && body.reason ? String(body.reason) : '' };
  }

  /* ---- 산출물 화면(/docs) ---- */
  // 세션마다 받은 문서 목록을 한 목록으로 모은다. 같은 폴더의 같은 파일은 한 번만(가장 최근에 바뀐 세션 쪽).
  var DOC_GROUPS = [['spec', '요구사항 · 설계'], ['form', '고객 양식'], ['record', '기록'], ['etc', '기타']];
  function docGroup(f) {
    var p = lower(f && f.path), ext = (/\.([a-z0-9]+)$/.exec(p) || [])[1] || '';
    if (/^audit\//.test(p)) return 'record';
    if (ext === 'xlsx' || ext === 'xlsm' || ext === 'pptx' || ext === 'docx' || ext === 'pdf') return 'form';
    if (ext === 'md' || ext === 'markdown') return 'spec';
    return 'etc';
  }
  // 올라간 정도 칩. 서버가 파일마다 판정한 f.upload 가 있으면 그것으로 정한다(커밋 여부·main 과 같은 내용인가·열린 PR 에 들어 있는가).
  // 없으면(옛 서버) 커밋 안 된 파일인가와 이 세션의 PR 상태로 짐작한다. 근거가 없으면 '확인 못 함'.
  function uploadChip(u) {
    var st = u && u.state;
    // '안 올림' 은 노랑(warn) — 시안 G-11·G-14 처럼 손봐야 할 상태로 보인다
    if (st === 'local') return { text: '안 올림', tone: 'warn', title: '아직 커밋 안 됨 · 내 PC에만 있어.' };
    if (st === 'committed') return { text: '안 올림', tone: 'warn', title: '커밋은 됐지만 열린 PR 이 없어 · 아직 팀에 안 올림' };
    if (st === 'merged') return { text: '합쳐짐', tone: 'ok', title: 'main 에 같은 내용이 있어.' };
    if (st === 'review') {
      var nums = arr(u.prs).map(function (p) { return '#' + p.number; }).join(', ');
      return { text: '검토 중', tone: 'ok', title: 'PR ' + nums + ' 에 들어 있어 · 승인 기다림' };
    }
    return { text: '확인 못 함', tone: 'unk', title: u && u.reason ? String(u.reason) : '올렸는지 알 수 없어.' };
  }
  function docChip(f, s, unknown) {
    if (f && f.upload && typeof f.upload === 'object') return uploadChip(f.upload);
    if (unknown) return { text: '확인 못 함', tone: 'unk', title: 'git 상태를 읽지 못해 올렸는지 알 수 없어.' };
    if (f && f.changed) return { text: '안 올림', tone: 'warn', title: '아직 커밋 안 됨 · 내 PC에만 있어.' };
    var pr = s && s.flowPr, st = pr && pr.number ? String(pr.state || '').toUpperCase() : '';
    if (st === 'MERGED') return { text: '합쳐짐', tone: 'ok', title: '이 세션의 PR #' + pr.number + ' 이 합쳐졌어.' };
    if (st === 'OPEN') return { text: '검토 중', tone: 'ok', title: '이 세션의 PR #' + pr.number + ' 이 승인을 기다려.' };
    return { text: '확인 못 함', tone: 'unk', title: '커밋은 됐지만 이 세션에서 PR 상태를 알 수 없어.' };
  }
  // 홈 숫자 칸 "이번 주 산출물"(시안 G-11): mergeDocs 결과 중 최근 7일 안에 바뀐 문서 수. 시각은 초·밀리초 둘 다 받는다.
  var WEEK_SEC = 7 * 24 * 3600;
  function toSec(t) { return t > 1e12 ? t / 1000 : t; }
  function weekDocCount(docs, nowSec) {
    return arr(docs).filter(function (d) { var t = d && d.file && d.file.mtime; return t && nowSec - toSec(t) <= WEEK_SEC; }).length;
  }
  function weekPool(sessions, nowSec, limit) {  // 이번 주에 움직인 세션(최근 순, limit 개까지)
    return arr(sessions).filter(function (s) { return s && !s.handedOffTo && s.updatedAt && nowSec - toSec(s.updatedAt) <= WEEK_SEC; })
      .sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); }).slice(0, limit);
  }
  function mergeDocs(parts) {
    var seen = {}, out = [];
    arr(parts).forEach(function (p) {
      if (!p || !p.session) return;
      docList(p.files).forEach(function (f) {
        var key = normPath(p.session.cwd) + '|' + lower(f.path);
        if (seen[key]) return;
        seen[key] = 1;
        out.push({ key: key, file: f, session: p.session, group: docGroup(f), chip: docChip(f, p.session, p.unknown) });
      });
    });
    out.sort(function (a, b) { return (b.file.mtime || 0) - (a.file.mtime || 0); });
    return out;
  }
  // 문서 한 줄의 글: 이름과 판. SRS.md 처럼 이름이 정해진 문서는 시안처럼 쉬운 이름으로, `이름_v0.2.xlsx` 는 이름 · 판 · 확장자로 나눈다.
  var FRIENDLY = { 'srs.md': '요구사항정의서' };
  function docLabel(path) {
    var base = String(path || '').split('/').pop(), m = /^(.*)_v(\d+(?:\.\d+)*)\.([A-Za-z0-9]+)$/.exec(base);
    if (m) return { name: m[1], ver: m[2], ext: m[3].toLowerCase(), base: base };
    var e = (/\.([A-Za-z0-9]+)$/.exec(base) || [])[1] || '';
    return { name: FRIENDLY[lower(base)] || base, ver: '', ext: e.toLowerCase(), base: base };
  }
  // 고객 양식 결과(시안 G-15): 가장 최근 산출물이 xlsx 이면 그 파일. 아니면 null.
  function latestFormXlsx(docs) {
    var d = arr(docs)[0];
    return d && d.group === 'form' && /\.xlsx$/i.test(d.file.path || '') ? d : null;
  }
  var SOURCE_OF = [[/backlog/i, '요구사항정의서'], [/개발\s*사양서|spec/i, '개발 Spec'], [/cts/i, 'CTS 작업본'], [/role/i, 'Role 작업본'], [/매뉴얼|manual/i, '사용자 매뉴얼 작업본']];
  // "BW_Backlog List_v0.1.xlsx" -> { form: 'Backlog', ver: '0.1', ext: 'xlsx', source: '요구사항정의서' }. 원본을 모르면 source 는 빈 글.
  function formInfo(path) {
    var l = docLabel(path), form = l.name.replace(/^BW[_ ]/i, '').replace(/[_ ]*List$/i, '').trim() || l.name;
    var hit = SOURCE_OF.filter(function (p) { return p[0].test(form); })[0];
    return { form: form, ver: l.ver, ext: l.ext, source: hit ? hit[1] : '' };
  }
  function formSubtitle(path) {
    var i = formInfo(path), v = i.ver ? ' v' + i.ver : '';
    return i.source ? i.source + v + ' → 고객사 ' + i.form + ' 양식(' + i.ext + ')' : '고객사 ' + i.form + ' 양식(' + i.ext + ')' + v;
  }
  // 양식 칸 세기: 시트마다 첫 줄을 칸 이름 줄로 보고, 그 아래 내용이 있는 줄 x 칸 이름 수 = 칸 수. 비어 있는 칸은 이름으로 모은다.
  // 미리보기가 잘렸거나 읽지 못한 시트가 있으면 세지 않고 known:false 로 돌려준다(지어내지 않는다).
  function formCells(p) {
    if (!p || p.kind !== 'table') return { known: false, reason: '표를 읽지 못했어.' };
    var total = 0, filled = 0, blanks = {}, order = [], sheets = arr(p.sheets);
    if (!sheets.length) return { known: false, reason: '시트가 없어.' };
    for (var i = 0; i < sheets.length; i++) {
      var sh = sheets[i];
      if (sh.error || sh.truncated) return { known: false, reason: '표가 커서 일부만 읽었어.' };
      var rows = arr(sh.rows), cell = function (r, c) { var v = r && r[c]; return v == null ? '' : String(v).trim(); };
      var hi = -1;
      for (var r0 = 0; r0 < rows.length && hi < 0; r0++) if (arr(rows[r0]).some(function (v) { return v != null && String(v).trim(); })) hi = r0;
      if (hi < 0) continue;
      var cols = [];
      arr(rows[hi]).forEach(function (v, c) { if (cell(rows[hi], c)) cols.push(c); });
      for (var r = hi + 1; r < rows.length; r++) {
        if (!arr(rows[r]).some(function (v) { return v != null && String(v).trim(); })) continue;
        cols.forEach(function (c) {
          total++;
          if (cell(rows[r], c)) filled++;
          else { var n = cell(rows[hi], c); if (!blanks[n]) { blanks[n] = 1; order.push(n); } }
        });
      }
    }
    if (!total) return { known: false, reason: '내용이 있는 줄이 없어.' };
    return { known: true, total: total, filled: filled, empty: total - filled, blankNames: order };
  }
  function isFormOutput(f) { return docGroup(f) === 'form' && /\.(xlsx|pptx|docx)$/i.test(f.path || ''); }

  /* ---- 승인 카드 ---- */
  function mergeApprovals(list) {
    var out = { state: 'no', reason: '', items: [] }, seen = {};
    list.forEach(function (a) {
      if (!a) return;
      if (a.state === 'yes') {
        out.state = 'yes';
        arr(a.items).forEach(function (it) { if (it && !seen[it.url || it.number]) { seen[it.url || it.number] = 1; out.items.push(it); } });
      } else if (a.state === 'unknown' && out.state !== 'yes') { out.state = 'unknown'; out.reason = a.reason || ''; }
    });
    return out;
  }

  /* ---- 세션 카드 ---- */
  function prBadge(pr) {
    if (!pr || !pr.number) return null;
    return { number: pr.number, url: pr.url || '', title: pr.title || '', text: CHECK_TEXT[pr.checks] || CHECK_TEXT.none, checks: pr.checks || 'none' };
  }
  // 내 PR 이 열려 있고 자동 검사가 실패했다 = 고쳐야 할 PR(홈 G-24). 검사 결과가 없거나 진행 중이면 아니다.
  function prNeedsFix(s) {
    var pr = s && s.flowPr;
    return !!(pr && pr.number && String(pr.state || '').toUpperCase() === 'OPEN' && pr.checks === 'fail');
  }
  function runningSubCount(s) { return arr(s && s.subagents).filter(function (a) { return a && a.state === 'running'; }).length; }

  /* ---- 세션 화면 숫자 띠 ---- */
  // 데이터에 있는 칸만 만든다. 없는 값을 지어내지 않는다(REQ·DEV 는 다음 갈래 옵션의 번호에서만, 이슈는 브랜치 이름에서만 읽는다).
  function issueOf(s) { var m = /^[\w.-]+\/(\d+)-/.exec((s && s.branch) || ''); return m ? m[1] : ''; }
  function reqIds(s) {
    var seen = {}, out = [];
    arr(s && s.nextFlow && s.nextFlow.options).forEach(function (o) {
      arr(o && o.ids).forEach(function (id) { if (/^REQ-\d{1,6}$/.test(id) && !seen[id]) { seen[id] = 1; out.push(id); } });
    });
    return out;
  }
  function joinIds(ids) { return ids.length > 2 ? ids.slice(0, 2).join(', ') + ' 외 ' + (ids.length - 2) + '개' : ids.join(', '); }
  // 진행 %: AI 가 알려 주는 값이 없어서 순서의 끝난 단계 수(끝남·건너뜀) / 전체 단계 수로 계산한다.
  function progressOf(s) {
    var steps = barSteps(s);
    if (!steps.length) return null;
    var done = steps.filter(function (x) { return x.state === 'done' || x.state === 'skipped'; }).length;
    return { done: done, total: steps.length, pct: Math.round(100 * done / steps.length) };
  }
  function prCell(s) {
    var pr = s && s.flowPr;
    if (pr && pr.number) {
      var st = String(pr.state || '').toUpperCase();
      return st === 'MERGED' ? { value: 'PR #' + pr.number + ' 합쳐짐', tone: 'g' } : st === 'CLOSED' ? { value: 'PR #' + pr.number + ' 닫힘', tone: 'w' } : { value: 'PR #' + pr.number + ' 검토 중', tone: 'g' };
    }
    if (arr(s && s.flowUnknown).length) return { value: '확인 못 함', tone: 'u' };
    if (s && s.flowId) return { value: 'PR 아직', tone: 'w' };
    var link = arr(s && s.prLinks).map(function (p) { return typeof p === 'string' ? p : p && p.url; }).map(function (u) { return /\/pull\/(\d+)/.exec(u || ''); }).filter(Boolean)[0];
    return link ? { value: 'PR #' + link[1], tone: '' } : null;
  }
  /* 세션 기억(context) 사용량(#648). 서버가 읽은 s.context = { tokens, window, pct } 를 화면 값으로 바꾼다.
     kind: 'pct'(창 크기를 알아 % 가 있음) / 'tokens'(토큰 수만) / 'unknown'(읽지 못함). 모르는 값은 지어내지 않는다.
     level: 80% 초과 'warn', 90% 이상 'hot'(링 색과 숫자 띠·배너가 같은 기준을 쓴다). */
  function tokenText(n) { return n >= 10000 ? Math.round(n / 10000) + '만 토큰' : n + ' 토큰'; }
  function memoryOf(s) {
    var c = (s && s.context) || {}, t = c.tokens;
    if (typeof t !== 'number' || !isFinite(t) || t <= 0) return { kind: 'unknown', pct: null, tokens: null, level: '', text: '?', title: '기억 사용량 확인 못 함' };
    var pct = typeof c.pct === 'number' && isFinite(c.pct) ? Math.max(0, Math.min(100, Math.round(c.pct))) : null;
    if (pct == null) return { kind: 'tokens', pct: null, tokens: t, level: '', text: tokenText(t), words: tokenText(t), title: '창 크기를 몰라서 %는 확인 못 함 · ' + tokenText(t) + ' 사용' };
    return { kind: 'pct', pct: pct, tokens: t, level: pct >= 90 ? 'hot' : pct > 80 ? 'warn' : '', text: pct + '%', words: tokenText(t), title: tokenText(t) + ' 사용' };
  }
  // 설정·표준 갈래는 진행 원장이 아니라 SRS 의 Status 로 진행을 본다(#718). srs 는 /api/srs-status 응답(아직 못 받았으면 undefined → 칸을 비운다).
  var SRS_STATUS_TEXT = { 'new': '새로 등록', 'planned': '계획됨', 'in process': '진행 중', 'done': '끝', 'on hold': '보류', 'dropped': '취소', 'duplicate': '중복' };
  function srsStatusCell(s, srs) {
    if (!s || (s.flowId !== 'config' && s.flowId !== 'standard') || !srs) return null;
    // 요구사항 번호: 다음 갈래 옵션에 없으면(새 작업으로 바로 시작한 건) 세션 이름의 REQ-/DEV- 번호를 쓴다(REQ 와 DEV 번호는 같다).
    var reqs = reqIds(s), items = srs.state === 'yes' && srs.items ? srs.items : {};
    if (!reqs.length) String(s.title || '').replace(/\b(?:REQ|DEV)-(\d{1,6})\b/g, function (m, n) { var id = 'REQ-' + ('00' + n).slice(-Math.max(3, n.length)); if (reqs.indexOf(id) < 0) reqs.push(id); return m; });
    var got = reqs.map(function (r) { return { id: r, status: String(items[r] && items[r].status || '').trim() }; }).filter(function (x) { return x.status; });
    if (!got.length) return { id: 'srs-status', label: 'SRS 상태', tone: 'u', value: '확인 못 함', title: 'SRS(docs/ssot/SRS.md)의 Status 칸을 읽지 못했거나 이 요구사항을 찾지 못했어.' };
    var text = function (x) { return SRS_STATUS_TEXT[x.status.toLowerCase()] || x.status; };
    var same = got.every(function (x) { return x.status.toLowerCase() === got[0].status.toLowerCase(); });
    return { id: 'srs-status', label: 'SRS 상태', tone: same && got[0].status.toLowerCase() === 'done' ? 'g' : '', value: same ? text(got[0]) : joinIds(got.map(function (x) { return x.id + ' ' + text(x); })),
      title: '이 작업 폴더 SRS 의 Status 칸: ' + got.map(function (x) { return x.id + ' ' + x.status; }).join(', ') };
  }
  // 단계 이름 끝의 괄호 설명("…시작하기(작업 기록과 작업 공간을 자동으로 만들어요)")을 뗀 짧은 이름. 시안의 숫자 띠·순서 알약은 짧은 이름이다.
  // 전체 이름은 호출한 쪽이 title 로 둔다.
  function shortStepName(name) { return String(name || '').replace(/\s*\([^()]*\)\s*$/, '') || String(name || ''); }
  // 화면용 짧은 이름: workflow.json 의 step.short 가 있으면 그것, 없으면 괄호 설명만 뗀 이름.
  function stepShort(st) { return (st && st.short) || shortStepName(st && st.name); }
  // 시안 G-09·10·12·13 숫자 띠: 단계 · AI 진행(갈래가 끝나면 뺀다) · 요구사항 · 개발 번호 · 작업 기록 · 검토 요청. 기억 칸은 없다(기억은 사이드바 링과 배너가 보인다).
  // 값이 없는 칸은 지어내지 않고 건너뛴다.
  function sessionStrip(s, srs) {
    var cells = [], steps = barSteps(s), prog = progressOf(s), approval = s && s.phase === 'approval';
    if (steps.length) {
      var now = steps.filter(function (x) { return x.state === 'now'; })[0];
      cells.push({ id: 'step', label: '단계', tone: 'g', value: s.flowFinished ? steps.length + ' / ' + steps.length + ' 끝' : now ? (now.index + 1) + ' / ' + steps.length + ' ' + (approval ? '승인 기다림' : stepShort(now)) : '확인 못 함',
        title: now && !s.flowFinished ? now.name : null });
      if (!s.flowFinished) cells.push({ id: 'progress', label: 'AI 진행', tone: '', value: approval ? '끝' : prog.pct + '%',
        title: approval ? 'AI 가 할 일은 끝났고 승인자 확인만 남았어.' : '순서 ' + prog.total + '단계 중 ' + prog.done + '단계가 끝난 기준이야(AI 가 직접 알려 준 값이 아니야).' });
    } else cells.push({ id: 'step', label: '단계', tone: '', value: '정해진 갈래 없음' });
    // 시안 G-16: 하네스 검사에 막힌 세션은 단계 칸이 "1 / 3 쓰기 · 막힘" 빨강. 검사를 못 한 건 막힘이 아니라 "확인 못 함" 보라로 따로 말한다.
    var bk = blockOf(s);
    if (bk && steps.length) {
      cells[0].value += bk.kind === 'cannot_check' ? ' · 확인 못 함' : ' · 막힘';
      cells[0].tone = bk.kind === 'cannot_check' ? 'u' : 'r';
    }
    var reqs = reqIds(s);
    if (reqs.length) {
      cells.push({ id: 'req', label: '요구사항', tone: '', value: joinIds(reqs) + (s.flowFinished && s.flowId === 'srs' ? ' 확정' : '') });
      cells.push({ id: 'dev', label: '개발 번호', tone: '', value: joinIds(reqs.map(function (r) { return 'DEV-' + r.slice(4); })) });
    }
    var st = srsStatusCell(s, srs);
    if (st) cells.push(st);
    var issue = issueOf(s);
    if (issue) cells.push({ id: 'issue', label: '작업 기록', tone: '', value: '이슈 #' + issue });
    var pr = prCell(s);
    if (pr) cells.push({ id: 'pr', label: '검토 요청', tone: pr.tone, value: pr.value });
    return cells;
  }
  // 올림·승인 기다림 화면의 줄. 검사 결과는 합친 한 값(checks)만 있어 문서·비밀값 검사를 따로 나누지 않는다.
  // 일반 문서만 바꾼 PR 은 에이전트가 병합해도 되는 예외(rules/governance.md)가 있다. SRS·Spec(SSOT)·src 는 늘 사람이 병합하므로 작은 수정 갈래(fix)에서만 말한다.
  var AGENT_MERGE_NOTE = '문서만 바꾼 PR 은 검사가 통과하면 Claude Code 가 바로 병합하기도 해.';
  // 검사 두 줄: 앞 검사 status 이름(doc-guard·gitleaks)이 읽히면 그 값, 아니면 합친 값(checks)에서만 말한다.
  // 합친 값이 통과면 둘 다 통과(검사 단계가 하나라도 실패하면 합친 값이 실패다). 어느 쪽이 실패했는지 모르면 확인 못 함으로 둔다.
  var STEP_LINES = {
    'doc-guard': { id: 'doc', name: '문서 검사', text: { pass: '양식에 맞아', fail: '양식에 안 맞는 곳이 있어', pending: '아직 돌고 있어' } },
    'gitleaks': { id: 'secret', name: '비밀값 검사', text: { pass: '없음', fail: '비밀값이 발견됐어', pending: '아직 돌고 있어' } }
  };
  var STEP_STATE = { pass: 'ok', fail: 'fail', pending: 'wait' };
  function stepLine(key, pr, overall) {
    var def = STEP_LINES[key], got = pr.stepChecks && pr.stepChecks[key], res = got || (overall === 'pass' ? 'pass' : overall === 'pending' ? 'pending' : '');
    if (!res) return { id: def.id, name: def.name, state: 'unk', text: overall === 'fail' ? '어느 검사가 실패했는지 확인 못 함' : '검사 결과를 확인 못 함' };
    return { id: def.id, name: def.name, state: STEP_STATE[res], text: def.text[res] };
  }
  var TEAM_WAIT = { srs: '요구사항 문서라 승인자 확인이 필요 · 기다리는 중', spec: '개발 Spec 이라 승인자 확인이 필요 · 기다리는 중' };
  function prLines(pr, flowId) {
    if (!pr || !pr.number) return [];
    var overall = pr.checks || 'none';
    var st = String(pr.state || '').toUpperCase();
    var team = st === 'MERGED' ? ['ok', '합쳐졌어'] : st === 'CLOSED' ? ['fail', '합치지 않고 닫혔어'] : ['wait', (TEAM_WAIT[flowId] || '승인자 확인을 기다리는 중') + ' · 승인은 GitHub 에서 해' + (flowId === 'fix' ? ' · ' + AGENT_MERGE_NOTE : '')];
    return [stepLine('doc-guard', pr, overall), stepLine('gitleaks', pr, overall), { id: 'team', name: '팀 승인', state: team[0], text: team[1] }];
  }
  // 승인자를 기다리는 동안 검사가 실패했는지(실패면 AI 에게 고치라고 해야 해서 대화 입력칸을 남긴다)
  function checksFailed(s) { return !!(s && s.flowPr && s.flowPr.checks === 'fail'); }

  /* ---- 승인 기다림·끝남(시안 G-10·12) 문장 ---- */
  function hasBatchim(word) {
    var t = String(word || '').replace(/[\s.·()]+$/g, ''), c = t.charCodeAt(t.length - 1);
    if (c >= 0xAC00 && c <= 0xD7A3) return (c - 0xAC00) % 28 !== 0;
    return /[bcdgklmnpqtx]$/i.test(t) || /[013678]$/.test(t);  // 영문·숫자는 읽는 소리의 받침으로 본다(Spec=스펙은 ㄱ)
  }
  function nextBase(label) { return String(label || '').split(' · ')[0].trim(); }
  function nextShort(label) { return String(label || '').split(' · ')[0].replace(/\s*(만들기|하기)$/, '').trim(); }
  function nextFirst(s) {
    var o = arr(s && s.nextFlow && s.nextFlow.options).filter(function (x) { return x && x.flow && !x.disabled; })[0];
    return o ? { flow: o.flow, short: o.name || nextShort(o.label), label: o.label || o.name || '' } : null;
  }
  function prMerged(s) { var pr = s && s.flowPr; return pr && pr.number && String(pr.state || '').toUpperCase() === 'MERGED' ? pr.number : null; }
  // 사이드바 한 줄: 승인 기다림 · PR #n / 끝 · PR #n 합쳐짐
  function phaseSide(s) {
    var n = s && s.flowPr && s.flowPr.number;
    if (s && s.phase === 'approval') return '승인 기다림' + (n ? ' · PR #' + n : '');
    if (s && s.phase === 'finished') return prMerged(s) ? '끝 · PR #' + prMerged(s) + ' 합쳐짐' : '끝';
    return '';
  }
  // 맨 위 띠(갈래가 끝난 세션을 보고 있을 때): PR #n이 합쳐졌어 — 다음은 <다음 갈래>
  function finishedBand(s) {
    var n = prMerged(s);
    if (!s || s.phase !== 'finished' || !n) return '';
    var nx = nextFirst(s);
    return 'PR #' + n + '이 합쳐졌어' + (nx ? ' — 다음은 ' + nx.short : '');
  }
  function phaseLine(s) {
    if (s && s.phase === 'approval') return 'GitHub에 올렸어 · 팀 승인을 기다리는 중';
    if (s && s.phase === 'finished') {
      var n = prMerged(s), nx = nextFirst(s);
      return (n ? 'PR #' + n + '이 합쳐졌어.' : '이 일은 끝났어.') + (nx ? ' 다음 갈래는 ' + nx.short + (hasBatchim(nx.short) ? '이야' : '야') : '');
    }
    return '';
  }

  /* 개발 준비 상태(#668). /api/dev-ready 응답에서 화면이 쓸 것만 뽑는다. 읽지 못함(unknown)·해당 없음(no)·읽는 중은 null 이고,
     null 이면 종류 버튼에 아무 표시도 하지 않고 개발을 막지도 않는다(지어내지 않는다). */
  function devReadyView(d) {
    if (!d || d.state !== 'yes' || d.loading) return null;
    var need = arr(d.needSpec).filter(function (x) { return x && x.label; });
    // setup 은 표준 건을 포함한 수다(서버 devready). 화면은 표준을 따로 세고 설정은 그만큼 뺀다(#718).
    var standard = Math.min(d.standard | 0, d.setup | 0);
    return { specReady: d.specReady | 0, setup: (d.setup | 0) - standard, standard: standard, need: need, needCount: Math.max(need.length, d.needSpecCount | 0), noReqCount: d.noReqCount | 0 };
  }
  // 종류 버튼 밑에 보일 작은 글. flowId 는 종류 버튼의 갈래. 보일 것이 없으면 null.
  function kindHint(flowId, v) {
    if (!v) return null;
    if (flowId === 'dev') {
      // 요구사항(SRS)이 없는 건은 Spec 이 있어도 센 수에 넣지 않고, 있으면 따로 알린다(#837).
      var noReq = v.noReqCount > 0 ? ' · 요구사항 없는 건 ' + v.noReqCount + '개(요구사항 먼저)' : '';
      return v.specReady === 0 ? { tone: 'dim', text: 'Spec 있는 건 없음 — ' + (noReq ? '요구사항 없는 건 ' + v.noReqCount + '개, 요구사항 먼저' : '개발 Spec 먼저') }
        : { tone: '', text: 'Spec 있는 건 ' + v.specReady + '개' + noReq };
    }
    if (flowId === 'spec') return v.need.length ? { tone: 'hot', text: '할 차례 ' + v.need[0].label + (v.needCount > 1 ? ' 외 ' + (v.needCount - 1) + '건' : '') } : null;
    if (flowId === 'config') return v.setup > 0 ? { tone: '', text: '설정 건 ' + v.setup + '개' } : null;
    if (flowId === 'standard') return v.standard > 0 ? { tone: '', text: '표준 건 ' + v.standard + '개' } : null;
    return null;
  }
  // Spec 이 없다고 확실할 때만 개발을 막는다. 개발 갈래가 아니거나 상태를 모르면 null.
  function devBlock(flowId, v) {
    if (flowId !== 'dev' || !v || v.specReady > 0) return null;
    if (v.noReqCount > 0) return '요구사항(SRS)에 없는 개발은 시작할 수 없어. Spec 이 있어도 안 돼. 먼저 요구사항을 올려서 병합해야 해.';
    return 'Spec 없이 개발은 시작할 수 없어. PR 검사(spec-ready)에서도 막혀. 먼저 개발 Spec 을 만들어 승인받아야 해.';
  }
  // 종류 버튼으로 고른 갈래와 AI 가 고른 갈래가 다르면 AI 쪽({id, reason}), 같거나 어느 한쪽이 없으면 null.
  function kindConflict(found, kindFlowId) {
    if (!kindFlowId || !found || !found.id || found.id === kindFlowId) return null;
    return { id: found.id, reason: found.reason || '' };
  }

  /* 브라우저 알림(#651). 세션 하나의 직전·지금 모델을 비교해 보낼 알림 목록을 낸다(순수 함수).
     prev 가 없으면(처음 본 세션·첫 목록) 비교 기준이 없어 보내지 않는다. cfg 는 {turn, blocked, done}, opts 는 {visible, name, reqKind(rid)}.
     탭이 보이는 상태(opts.visible)면 보내지 않는다. 같은 일의 알림은 같은 tag 라 브라우저가 한 번만 보인다. */
  function notifyEvents(prev, next, cfg, opts) {
    var out = [];
    opts = opts || {}; cfg = cfg || {};
    if (!prev || !next || !next.id || opts.visible) return out;
    var name = opts.name || next.title || '이름 없는 세션';
    var pend = next.pendingRequestIds || [], was = prev.pendingRequestIds || [];
    var fresh = pend.filter(function (r) { return was.indexOf(r) < 0; });
    var turned = (next.group === 'todo' && prev.group !== 'todo') || fresh.length > 0;
    if (cfg.turn && turned) {
      var rid = fresh[0] || pend[0], k = rid && opts.reqKind ? opts.reqKind(rid) : '';
      out.push({ kind: 'turn', tag: 'bh-turn-' + next.id + (fresh.length ? '-' + fresh[0] : ''), title: '내 차례야 · ' + name,
        body: fresh.length ? ((k === 'question' || k === 'elicitation') ? '질문' : k === 'permission' ? '승인' : '답할 일') : '다음 단계', path: rid ? '/r/' + encodeURIComponent(rid) : '/s/' + encodeURIComponent(next.id) });
    }
    var nb = next.lastBlock, pb = prev.lastBlock;
    if (cfg.blocked && nb && nb.t != null && (!pb || nb.t > pb.t)) {
      var cant = nb.kind === 'cannot_check';
      out.push({ kind: 'blocked', tag: 'bh-blocked-' + next.id + '-' + nb.t, title: (cant ? '확인 못 함 · ' : '막혔어 · ') + name,
        body: cant ? '확인하지 못한 일이 있어' : '하네스 훅이 막았어', path: '/s/' + encodeURIComponent(next.id) });
    }
    // 내 차례 알림이 이미 나가는 전환이면 끝남 알림은 겹치므로 생략한다.
    if (cfg.done && prev.group === 'running' && next.group !== 'running' && !out.some(function (e) { return e.kind === 'turn'; })) {
      out.push({ kind: 'done', tag: 'bh-done-' + next.id, title: 'AI가 끝냈어 · ' + name, body: '결과를 확인해 봐', path: '/s/' + encodeURIComponent(next.id) });
    }
    return out;
  }

  // 비밀처럼 보이는 값을 `••••••••` 로 바꾼 글. 서버 trouble.py 의 SECRET_ASSIGN·SECRET_OTHER·PLACEHOLDER·mask_secrets 와 같은 규칙이다(시험이 두 쪽 결과를 맞춰 본다).
  var MASK = '••••••••';
  var SECRET_NAME = '[\\w.-]*(?:secret|password|passwd|pwd|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|credential)[\\w.-]*';
  var SECRET_ASSIGN = new RegExp('\\b(' + SECRET_NAME + ')["\']?\\s*[:=]\\s*(?:"([^"]+)"|\'([^\']+)\'|([^\\s"\']{3,}))', 'gi');
  var SECRET_OTHER = [
    [/\bgh[pousr]_[A-Za-z0-9]{20,}/g, 0], [/\bgithub_pat_[A-Za-z0-9_]{20,}/g, 0], [/\bAKIA[0-9A-Z]{16}\b/g, 0], [/\bsk-[A-Za-z0-9_-]{16,}/g, 0],
    [/\bxox[abprs]-[A-Za-z0-9-]{10,}/g, 0], [/-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|[\s\S]*)/g, 0],
    [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, 0], [/\bBearer\s+[A-Za-z0-9._~+\/-]{16,}/gi, 0], [/:\/\/[^\/\s:@]+:[^\/\s@]{3,}@/g, 1]
  ];
  var PLACEHOLDER = /^[•*x.\-_<>…()\[\]{}#]+$|^<.*>$|^\(생략\)$/i;
  function maskSecrets(text) {
    var s = text == null ? '' : String(text);
    s = s.replace(SECRET_ASSIGN, function (all, name, dq, sq, bare) {
      var value = dq || sq || bare || '';
      if (PLACEHOLDER.test(value.trim())) return all;
      var end = all.length - (dq || sq ? 1 : 0);
      return all.slice(0, end - value.length) + MASK + all.slice(end);
    });
    SECRET_OTHER.forEach(function (o) { s = s.replace(o[0], o[1] ? '://' + MASK + '@' : MASK); });
    return s;
  }

  var api = {
    maskSecrets: maskSecrets, MASK: MASK,
    notifyEvents: notifyEvents,
    devReadyView: devReadyView, kindHint: kindHint, devBlock: devBlock, kindConflict: kindConflict,
    memoryOf: memoryOf, issueOf: issueOf, reqIds: reqIds, progressOf: progressOf, sessionStrip: sessionStrip, shortStepName: shortStepName, stepShort: stepShort, prLines: prLines, checksFailed: checksFailed, phaseSide: phaseSide, finishedBand: finishedBand, phaseLine: phaseLine, nextFirst: nextFirst, nextShort: nextShort, nextBase: nextBase, ASK_TEXT: ASK_TEXT, hasBatchim: hasBatchim, prMerged: prMerged,
    BAR_LABEL: BAR_LABEL, DEFAULT_TOOLS: DEFAULT_TOOLS, groupOf: groupOf, blockOf: blockOf, counts: counts, summaryText: summaryText,
    barSteps: barSteps, currentStep: currentStep, orderText: orderText, nextAction: nextAction, skipReasonError: skipReasonError,
    NO_FLOW_ID: NO_FLOW_ID, nextOptions: nextOptions, jobOutcome: jobOutcome, visibleTools: visibleTools, projectNotice: projectNotice,
    formsNotice: formsNotice, FORMS_MISSING_SHORT: FORMS_MISSING_SHORT, FORMS_MISSING_TEXT: FORMS_MISSING_TEXT,
    plainReason: plainReason, plainAction: plainAction, hideSkillLine: hideSkillLine, reloadStrip: reloadStrip, reloadResult: reloadResult,
    startChecks: startChecks, autoChecksOpen: autoChecksOpen, normPath: normPath, otherSessions: otherSessions, sameFolderBusy: sameFolderBusy,
    previewKind: previewKind, kindBadge: kindBadge, docList: docList, versionPaths: versionPaths, normPreview: normPreview,
    mergeApprovals: mergeApprovals, prBadge: prBadge, prNeedsFix: prNeedsFix, runningSubCount: runningSubCount,
    DOC_GROUPS: DOC_GROUPS, docGroup: docGroup, docChip: docChip, mergeDocs: mergeDocs, weekDocCount: weekDocCount, weekPool: weekPool, isFormOutput: isFormOutput, docLabel: docLabel, latestFormXlsx: latestFormXlsx, formInfo: formInfo, formSubtitle: formSubtitle, formCells: formCells
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHLogic = api;
})(typeof window !== 'undefined' ? window : this);
