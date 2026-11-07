/* 갈래·도구·문서 칸의 화면 규칙. DOM 을 만지지 않는 순수 함수만 둔다(node 로 시험한다). */
(function (root) {
  'use strict';

  var BAR_LABEL = { done: '끝', now: '지금', wait: '대기', skipped: '건너뜀' };
  // 도구 순서와 서버 데이터를 못 받았을 때의 기본값(플러그인 workflow.json 의 tools 중 늘 보이는 것과 같은 순서)
  var DEFAULT_TOOLS = [
    { id: 'version', name: '플러그인 판 보기', kind: 'skill', skill: 'version' },
    { id: 'sync', name: '최신 상태 받기', kind: 'skill', skill: 'sync' },
    { id: 'update', name: '플러그인 갱신', kind: 'skill', skill: 'update' },
    { id: 'handoff', name: '새 세션에 인계', kind: 'skill', skill: 'handoff' },
    { id: 'wrapup', name: '남은 일 이슈로', kind: 'skill', skill: 'wrapup' },
    { id: 'prs', name: '내 PR 보기', kind: 'skill', skill: 'prs' },
    { id: 'reload', name: '플러그인 다시 불러오기', kind: 'console' },
    { id: 'approvals', name: '내가 승인할 PR', kind: 'skill', skill: 'approvals', requires: 'approver' }
  ];
  var NO_FLOW_ID = 'none';  // 갈래 없이 도구만 쓰는 일(서버 analysis.NO_FLOW 와 같다)
  var CHECK_ORDER =['sync', 'version', 'update', 'reload'];
  var CHECK_NAMES = { sync: '최신 받기', version: '판 확인', update: '갱신', reload: '다시 불러오기' };
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
    if (s.group === 'todo' || s.group === 'running' || s.group === 'idle') return s.group;
    if (arr(s.pendingRequestIds).length || s.turnSkill || s.askedInText) return 'todo';
    return s.status === 'running' || s.status === 'starting' ? 'running' : 'idle';
  }

  function counts(list) {
    var c = { total: 0, running: 0, todo: 0, idle: 0 };
    list.forEach(function (s) { c.total++; c[groupOf(s)]++; });
    return c;
  }
  function summaryText(c) {
    return '세션 ' + c.total + '개 · 일하는 중 ' + c.running + ' · 내 차례 ' + c.todo + ' · 쉬는 중 ' + c.idle;
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
      return { index: i, id: st.id, name: st.name || st.id || '', kind: st.kind, skill: st.skill || '', state: state, label: BAR_LABEL[state], reason: st.reason || '' };
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
    if (!step) return { type: 'none', note: '지금 단계를 읽지 못했어요.' };
    var busy = s.status === 'running' || s.status === 'starting';
    var cannot = s.canSend === false ? (s.cannotSendReason || '이 세션에는 지금 요청을 보낼 수 없어요.') : '';
    var base = { step: step, stepName: step.name || step.id || '', hint: step.hint || '' };
    function make(extra) { return Object.assign({}, base, extra); }
    if (step.kind === 'skill' && step.skill) {
      var again = lower(step.state) === 'active' && !busy;
      return make({ type: 'skill', skill: step.skill, label: '/harness:' + step.skill + (again ? ' 다시 실행' : ' 실행'),
        disabled: busy || !!cannot, disabledReason: busy ? '지금 Claude Code 가 일하는 중이에요.' : cannot });
    }
    if (step.kind === 'work') return make({ type: 'done', label: '끝났어요' });
    if (step.kind === 'human') return make({ type: 'human', label: '끝났어요', refreshLabel: '다시 확인' });
    // wait 와 그 밖: 상태를 보여 주고 다시 확인만 한다. 도우미 스킬이 있으면 보조로 둔다.
    return make({ type: 'wait', label: '다시 확인', helper: step.helperSkill || '', helperDisabled: busy || !!cannot });
  }

  /* ---- 건너뛰기 이유 ---- */
  function skipReasonError(text) { return String(text || '').trim() ? '' : '건너뛰는 이유를 적어 주세요.'; }

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
    if (status === 'canceled') return { done: true, ok: false, canceled: true, error: '취소했어요.' };
    if (job && job.error) return { done: true, ok: false, error: String(job.error) };
    if (JOB_FAIL.indexOf(st) >= 0) return { done: true, ok: false, error: (job && job.error) || '새 세션을 만들지 못했어요.' };
    if (job && job.sessionId && (!st || JOB_OK.indexOf(st) >= 0)) return { done: true, ok: true, sessionId: job.sessionId };
    if (JOB_OK.indexOf(st) >= 0) return { done: true, ok: !!(job && job.sessionId), sessionId: job && job.sessionId, error: job && job.sessionId ? '' : '새 세션 번호를 받지 못했어요.' };
    return { done: false };
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
      return { state: 'no', text: '프로젝트 준비 안 됨 - ' + (c.reason || 'templates/ 나 rules/ 가 없어요.') +
        ' 고객사 프로젝트 저장소라면 관리자가 도구 줄의 "프로젝트 구조 만들기" 를 한 번 해야 해요.' };
    }
    if (c.state === 'unknown') return { state: 'unknown', text: '프로젝트 준비 여부를 확인하지 못했어요' + (c.reason ? ' - ' + c.reason : '') + '.' };
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
    if (d && d.queued) return '지금 하는 일이 끝나면 다시 불러올게요.';
    var plugin = arr(d && d.plugins).filter(function (p) { return p && p.name === 'harness'; })[0];
    var ver = (d && d.harnessVersion) || (plugin && plugin.version) || '';
    var text = ver ? 'harness ' + ver + ' 로 다시 불러왔어요.' : '다시 불러왔어요.';
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
  var CHECK_LABEL = { done: '됐어요', run: '하는 중', fail: '다시 필요', todo: '아직' };
  function startChecks(s) {
    var list = arr(s && s.startChecks);
    if (!list.length) return [];
    return CHECK_ORDER.map(function (id) {
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
  function sessionStrip(s) {
    var cells = [], steps = barSteps(s), prog = progressOf(s);
    if (steps.length) {
      var now = steps.filter(function (x) { return x.state === 'now'; })[0];
      cells.push({ id: 'step', label: '단계', tone: 'g', value: s.flowFinished ? steps.length + ' / ' + steps.length + ' 끝' : now ? (now.index + 1) + ' / ' + steps.length + ' ' + now.name : '확인 못 함' });
      cells.push({ id: 'progress', label: 'AI 진행', tone: '', value: s.flowFinished ? '끝' : prog.pct + '%',
        title: '순서 ' + prog.total + '단계 중 ' + prog.done + '단계가 끝난 기준이야(AI 가 직접 알려 준 값이 아니야).' });
    } else cells.push({ id: 'step', label: '단계', tone: '', value: '정해진 갈래 없음' });
    var reqs = reqIds(s);
    if (reqs.length) {
      cells.push({ id: 'req', label: '요구사항', tone: '', value: joinIds(reqs) });
      cells.push({ id: 'dev', label: '개발 번호', tone: '', value: joinIds(reqs.map(function (r) { return 'DEV-' + r.slice(4); })) });
    }
    var issue = issueOf(s);
    if (issue) cells.push({ id: 'issue', label: '작업 기록(이슈)', tone: '', value: '이슈 #' + issue });
    var mem = memoryOf(s);
    cells.push({ id: 'memory', label: '기억', tone: mem.kind === 'unknown' ? 'u' : mem.level ? 'w' : '', value: mem.kind === 'unknown' ? '확인 못 함' : mem.text, title: mem.title });
    var pr = prCell(s);
    if (pr) cells.push({ id: 'pr', label: '검토 요청(PR)', tone: pr.tone, value: pr.value });
    return cells;
  }
  // 올림·승인 기다림 화면의 줄. 검사 결과는 합친 한 값(checks)만 있어 문서·비밀값 검사를 따로 나누지 않는다.
  // 일반 문서만 바꾼 PR 은 에이전트가 병합해도 되는 예외(rules/governance.md)가 있다. SRS·Spec(SSOT)·src 는 늘 사람이 병합하므로 작은 수정 갈래(fix)에서만 말한다.
  var AGENT_MERGE_NOTE = '문서만 바꾼 PR 은 검사가 통과하면 Claude Code 가 바로 병합하기도 해.';
  function prLines(pr, flowId) {
    if (!pr || !pr.number) return [];
    var checks = { pass: ['ok', '모두 통과했어'], fail: ['fail', '실패한 검사가 있어'], pending: ['wait', '아직 돌고 있어'], none: ['unk', '검사 결과를 확인 못 함'] }[pr.checks || 'none'] || ['unk', '검사 결과를 확인 못 함'];
    var st = String(pr.state || '').toUpperCase();
    var team = st === 'MERGED' ? ['ok', '합쳐졌어'] : st === 'CLOSED' ? ['fail', '합치지 않고 닫혔어'] : ['wait', '승인자 확인을 기다리는 중 · 승인은 GitHub 에서 해' + (flowId === 'fix' ? ' · ' + AGENT_MERGE_NOTE : '')];
    return [{ id: 'checks', name: '자동 검사(문서·비밀값 등)', state: checks[0], text: checks[1] }, { id: 'team', name: '팀 승인·합치기', state: team[0], text: team[1] }];
  }

  /* 개발 준비 상태(#668). /api/dev-ready 응답에서 화면이 쓸 것만 뽑는다. 읽지 못함(unknown)·해당 없음(no)·읽는 중은 null 이고,
     null 이면 종류 버튼에 아무 표시도 하지 않고 개발을 막지도 않는다(지어내지 않는다). */
  function devReadyView(d) {
    if (!d || d.state !== 'yes' || d.loading) return null;
    var need = arr(d.needSpec).filter(function (x) { return x && x.label; });
    return { specReady: d.specReady | 0, setup: d.setup | 0, need: need, needCount: Math.max(need.length, d.needSpecCount | 0) };
  }
  // 종류 버튼 밑에 보일 작은 글. flowId 는 종류 버튼의 갈래. 보일 것이 없으면 null.
  function kindHint(flowId, v) {
    if (!v) return null;
    if (flowId === 'dev') return v.specReady === 0 ? { tone: 'dim', text: 'Spec 있는 건 없음 — 개발 Spec 먼저' } : { tone: '', text: 'Spec 있는 건 ' + v.specReady + '개' };
    if (flowId === 'spec') return v.need.length ? { tone: 'hot', text: '할 차례 ' + v.need[0].label + (v.needCount > 1 ? ' 외 ' + (v.needCount - 1) + '건' : '') } : null;
    if (flowId === 'config') return v.setup > 0 ? { tone: '', text: '설정 건 ' + v.setup + '개' } : null;
    return null;
  }
  // Spec 이 없다고 확실할 때만 개발을 막는다. 개발 갈래가 아니거나 상태를 모르면 null.
  function devBlock(flowId, v) {
    if (flowId !== 'dev' || !v || v.specReady > 0) return null;
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
        body: fresh.length ? (k === 'question' ? '질문' : k === 'permission' ? '승인' : '답할 일') : '다음 단계', path: rid ? '/r/' + encodeURIComponent(rid) : '/s/' + encodeURIComponent(next.id) });
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

  var api = {
    notifyEvents: notifyEvents,
    devReadyView: devReadyView, kindHint: kindHint, devBlock: devBlock, kindConflict: kindConflict,
    memoryOf: memoryOf, issueOf: issueOf, reqIds: reqIds, progressOf: progressOf, sessionStrip: sessionStrip, prLines: prLines,
    BAR_LABEL: BAR_LABEL, DEFAULT_TOOLS: DEFAULT_TOOLS, groupOf: groupOf, counts: counts, summaryText: summaryText,
    barSteps: barSteps, currentStep: currentStep, orderText: orderText, nextAction: nextAction, skipReasonError: skipReasonError,
    NO_FLOW_ID: NO_FLOW_ID, nextOptions: nextOptions, jobOutcome: jobOutcome, visibleTools: visibleTools, projectNotice: projectNotice,
    formsNotice: formsNotice, FORMS_MISSING_SHORT: FORMS_MISSING_SHORT, FORMS_MISSING_TEXT: FORMS_MISSING_TEXT,
    reloadStrip: reloadStrip, reloadResult: reloadResult,
    startChecks: startChecks, normPath: normPath, otherSessions: otherSessions, sameFolderBusy: sameFolderBusy,
    previewKind: previewKind, kindBadge: kindBadge, docList: docList, versionPaths: versionPaths, normPreview: normPreview,
    mergeApprovals: mergeApprovals, prBadge: prBadge, runningSubCount: runningSubCount,
    DOC_GROUPS: DOC_GROUPS, docGroup: docGroup, docChip: docChip, mergeDocs: mergeDocs, weekDocCount: weekDocCount, weekPool: weekPool, isFormOutput: isFormOutput
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHLogic = api;
})(typeof window !== 'undefined' ? window : this);
