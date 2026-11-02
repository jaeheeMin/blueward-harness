/* 갈래·도구·문서 칸의 화면 규칙. DOM 을 만지지 않는 순수 함수만 둔다(node 로 시험한다). */
(function (root) {
  'use strict';

  var BAR_LABEL = { done: '끝', now: '지금', wait: '대기', skipped: '건너뜀' };
  // 도구 순서와 서버 데이터를 못 받았을 때의 기본값(서버 flows.json 의 tools 와 같은 순서)
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
  var CHECK_ORDER = ['sync', 'version', 'update', 'reload'];
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
    if (arr(s.pendingRequestIds).length || s.turnSkill) return 'todo';
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
    if (status === 'confirm') return { done: false, confirm: true, prompt: String((job && job.prompt) || '') };
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
      if (t.exposure && t.exposure.visible === false) return false;
      if (t.id === 'reload') return !!(ctx && ctx.hasSession && ctx.managed);
      return true;
    });
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

  var api = {
    BAR_LABEL: BAR_LABEL, DEFAULT_TOOLS: DEFAULT_TOOLS, groupOf: groupOf, counts: counts, summaryText: summaryText,
    barSteps: barSteps, currentStep: currentStep, orderText: orderText, nextAction: nextAction, skipReasonError: skipReasonError,
    nextOptions: nextOptions, jobOutcome: jobOutcome, visibleTools: visibleTools, reloadStrip: reloadStrip, reloadResult: reloadResult,
    startChecks: startChecks, normPath: normPath, otherSessions: otherSessions, sameFolderBusy: sameFolderBusy,
    previewKind: previewKind, kindBadge: kindBadge, docList: docList, versionPaths: versionPaths, normPreview: normPreview,
    mergeApprovals: mergeApprovals, prBadge: prBadge, runningSubCount: runningSubCount
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHLogic = api;
})(typeof window !== 'undefined' ? window : this);
