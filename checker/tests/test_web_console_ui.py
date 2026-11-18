"""웹 콘솔 화면 파일(static/*.js) 시험 (#558). node 가 있으면 순서 막대·버튼 노출 규칙을 가짜 DOM 위에서 확인한다.

서버(*.py)와는 상관없다. 화면이 믿는 API 모양은 flow-logic.js 의 순수 함수로 모아 두었다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "plugins" / "harness" / "console" / "static"
JS_FILES = sorted(STATIC.glob("*.js"))
NODE = shutil.which("node")

_RUNNER = r"""
const assert = require('assert');
const path = require('path');
const dir = process.argv[2];
const L = require(path.join(dir, 'flow-logic.js'));

/* ---- 가짜 DOM: 화면 조각이 쓰는 만큼만 ---- */
function Text(s) { this.nodeType = 3; this.text = String(s); this.parentNode = null; }
function El(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.parentNode = null; this._text = null; this.listeners = {}; this.dataset = {}; }
El.prototype = {
  nodeType: 1,
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); this._text = null; return c; },
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; },
  get firstChild() { return this.children[0] || null; },
  replaceChildren() { this.children = []; for (const c of arguments) this.appendChild(c); },
  setAttribute(k, v) { this.attrs[k] = String(v); },
  get className() { return this.attrs['class'] || ''; }, set className(v) { this.attrs['class'] = v; },
  get hidden() { return 'hidden' in this.attrs; }, set hidden(v) { if (v) this.attrs.hidden = ''; else delete this.attrs.hidden; },
  set textContent(v) { this.children = []; this._text = String(v); },
  get textContent() { return this._text !== null ? this._text : this.children.map(t => t.nodeType === 3 ? t.text : t.textContent).join(''); },
  addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); },
  get isConnected() { return true; },
  click() { (this.listeners.click || []).forEach(f => f({ preventDefault() {} })); }
};
global.document = { createElement: t => new El(t), createTextNode: s => new Text(s), body: new El('body'), addEventListener() {}, removeEventListener() {} };
global.window = { BHLogic: L };
function h(tag, props) {
  const el = new El(tag);
  Object.keys(props || {}).forEach(k => {
    const v = props[k];
    if (v == null || v === false) return;
    if (k === 'class') el.attrs['class'] = v;
    else if (k === 'text') el.textContent = v;
    else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'disabled' || k === 'value') el[k] = v;
    else el.attrs[k] = v === true ? '' : String(v);
  });
  const add = c => { if (c == null || c === false) return; if (Array.isArray(c)) return c.forEach(add); el.appendChild(typeof c === 'object' ? c : new Text(c)); };
  for (let i = 2; i < arguments.length; i++) add(arguments[i]);
  return el;
}
function find(el, pred, out) {
  out = out || [];
  if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach(c => find(c, pred, out)); }
  return out;
}
const tick = () => new Promise(r => setTimeout(r, 0));
function makeKit(routes, sessions) {
  const calls = [];
  const kit = {
    h, clear(el) { el.children = []; el._text = null; return el; }, qs(o) { const p = Object.keys(o).filter(k => o[k]).map(k => k + '=' + encodeURIComponent(o[k])); return p.length ? '?' + p.join('&') : ''; },
    listOf(d, k) { return Array.isArray(d) ? d : (d && Array.isArray(d[k]) ? d[k] : []); },
    api(method, url, body) {
      calls.push([method, url, body]);
      const key = method + ' ' + url.split('?')[0];
      if (!(key in routes)) return Promise.reject({ status: 404, message: 'nf' });
      const r = routes[key];
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(typeof r === 'function' ? r(body, url) : r);
    },
    sessions: new Map((sessions || []).map(s => [s.id, s])), requests: new Map(),
    icon() { return new El('svg'); }, link(href, p) { return h('a', Object.assign({ href }, p)); }, go() {},
    baseName: p => String(p || '').split(/[\\/]/).filter(Boolean).pop() || '', fmtSize: n => n + 'B', clock: v => String(v), safeHttp: u => /^https?:/.test(u) ? u : null,
    mergeSession() {}, refreshSession() {}, kindOf: () => 'permission', skillLabel: s => s, topline: () => h('div'),
    stateBox: () => h('div'), loadingBox: () => h('div'), loaded: () => true, conn: () => 'ok'
  };
  return { kit, calls };
}
function loadUI(kit) {
  delete require.cache[require.resolve(path.join(dir, 'flow-ui.js'))];
  require(path.join(dir, 'flow-ui.js'));
  return window.BHFlowUI.create(kit);
}
const FLOWS = { flows: [{ id: 'srs', name: '요구사항', description: 'SRS', steps: [{ kind: 'skill', skill: 'srs', name: 'SRS 쓰기' }, { kind: 'skill', skill: 'deliver', name: '제출' }, { kind: 'wait', name: '승인' }] }],
  tools: L.DEFAULT_TOOLS.map(t => Object.assign({}, t, { exposure: { visible: true, state: 'yes', reason: '' } })) };
const steps = (...states) => states.map((state, i) => ({ id: 's' + i, name: '단계' + i, kind: 'skill', skill: 'x' + i, state }));

const cases = {
  bar_states() {
    const s = { flowId: 'f', stepIndex: 2, flowSteps: steps('done', 'skipped', 'active', 'pending') };
    assert.deepStrictEqual(L.barSteps(s).map(x => x.state), ['done', 'skipped', 'now', 'wait']);
    assert.deepStrictEqual(L.barSteps(s).map(x => x.label), ['끝', '건너뜀', '지금', '대기']);
    // 지금 단계가 아직 pending 이어도 stepIndex 가 가리키면 지금으로 강조한다
    assert.strictEqual(L.barSteps({ stepIndex: 1, flowSteps: steps('done', 'pending', 'pending') })[1].state, 'now');
    assert.strictEqual(L.barSteps({ stepIndex: 1, flowSteps: steps('done', 'pending', 'pending') }).filter(x => x.state === 'now').length, 1);
    // 갈래가 끝나면 건너뜀만 빼고 모두 끝
    const fin = L.barSteps({ flowFinished: true, stepIndex: 3, flowSteps: steps('done', 'skipped', 'done') });
    assert.deepStrictEqual(fin.map(x => x.state), ['done', 'skipped', 'done']);
    assert.deepStrictEqual(L.barSteps({}), []);
  },
  next_action_one_button() {
    const base = { flowId: 'f', canSend: true, status: 'idle' };
    const at = (i, steps_) => Object.assign({}, base, { stepIndex: i, flowSteps: steps_ });
    const skill = L.nextAction(at(0, [{ id: 'a', name: 'A', kind: 'skill', skill: 'srs', state: 'pending' }]));
    assert.strictEqual(skill.type, 'skill'); assert.strictEqual(skill.skill, 'srs'); assert.strictEqual(skill.label, '/harness:srs 실행'); assert.strictEqual(skill.disabled, false);
    const work = L.nextAction(at(0, [{ id: 'a', name: 'A', kind: 'work', state: 'active' }]));
    assert.strictEqual(work.type, 'done'); assert.strictEqual(work.label, '끝났어'); assert.ok(!('skill' in work));
    const human = L.nextAction(at(0, [{ id: 'a', name: 'A', kind: 'human', state: 'active', hint: '넣기' }]));
    assert.strictEqual(human.type, 'human'); assert.strictEqual(human.refreshLabel, '다시 확인'); assert.strictEqual(human.hint, '넣기');
    const wait = L.nextAction(at(0, [{ id: 'a', name: 'A', kind: 'wait', state: 'active', helperSkill: 'prs' }]));
    assert.strictEqual(wait.type, 'wait'); assert.strictEqual(wait.label, '다시 확인'); assert.strictEqual(wait.helper, 'prs');
    // Claude Code 가 일하는 중이거나 보낼 수 없으면 스킬 버튼은 막는다
    const busy = L.nextAction(Object.assign(at(0, [{ id: 'a', name: 'A', kind: 'skill', skill: 'srs', state: 'active' }]), { status: 'running' }));
    assert.strictEqual(busy.disabled, true);
    const noSend = L.nextAction(Object.assign(at(0, [{ id: 'a', name: 'A', kind: 'skill', skill: 'srs', state: 'pending' }]), { canSend: false, cannotSendReason: '끝난 세션' }));
    assert.strictEqual(noSend.disabled, true); assert.strictEqual(noSend.disabledReason, '끝난 세션');
    assert.strictEqual(L.nextAction({}).type, 'pick');
    assert.strictEqual(L.nextAction({ flowId: 'f', flowFinished: true, flowSteps: [] }).type, 'finished');
    assert.strictEqual(L.nextAction({ flowId: 'f', stepIndex: 5, flowSteps: [] }).type, 'none');
  },
  skip_needs_reason() {
    assert.ok(L.skipReasonError('   ')); assert.ok(L.skipReasonError('')); assert.strictEqual(L.skipReasonError(' 이유 '), '');
  },
  tools_always_and_conditions() {
    const ids = (flows, appr, ctx) => L.visibleTools(flows, appr, ctx).map(t => t.id);
    // 서버 데이터가 없어도 기본 도구가 보인다(승인자가 아니면 approvals 는 없고, 콘솔 세션이 아니면 reload 도 없다)
    assert.deepStrictEqual(ids(null, null, { hasSession: true, managed: false }), ['version', 'sync', 'update', 'handoff', 'wrapup', 'prs']);
    assert.deepStrictEqual(ids(FLOWS, { state: 'no' }, { hasSession: true, managed: true }), ['version', 'sync', 'update', 'handoff', 'wrapup', 'prs', 'reload']);
    assert.ok(ids(FLOWS, { state: 'yes' }, { hasSession: true, managed: true }).includes('approvals'));
    assert.ok(!ids(FLOWS, { state: 'unknown' }, { hasSession: true, managed: true }).includes('approvals'));
    // 새 작업 화면(세션 없음)에는 reload 가 없다
    assert.ok(!ids(FLOWS, { state: 'yes' }, { hasSession: false }).includes('reload'));
    // 서버가 숨기라고 한 도구는 숨긴다
    const hidden = { tools: [{ id: 'version', skill: 'version', exposure: { visible: false } }, { id: 'sync', skill: 'sync' }] };
    assert.deepStrictEqual(ids(hidden, null, { hasSession: true }), ['sync']);
    // workflow.json 이 단추를 내지 않는다고 한 도구(콘솔을 여는 open)도 숨긴다
    assert.deepStrictEqual(ids({ tools: [{ id: 'open', skill: 'open', hidden: true }, { id: 'sync', skill: 'sync' }] }, null, { hasSession: true }), ['sync']);
  },
  no_flow_id_and_job_warning() {
    assert.strictEqual(L.NO_FLOW_ID, 'none');  // 서버 analysis.NO_FLOW 와 같은 값
    const o = L.jobOutcome({ status: 'confirm', prompt: 'p', warning: '23건 중 20건만' });
    assert.ok(o.confirm && o.warning === '23건 중 20건만' && L.jobOutcome({ status: 'confirm', prompt: 'p' }).warning === '');
  },
  project_notice_says_not_ready_or_unknown_and_stays_quiet_when_ready() {
    const cond = (state, reason) => ({ conditions: { 'project-ready': { state, reason } } });
    assert.strictEqual(L.projectNotice(null), null);
    assert.strictEqual(L.projectNotice({}), null);  // 조건 자체를 못 받았으면 말할 근거가 없다
    assert.strictEqual(L.projectNotice(cond('yes', '')), null);
    const no = L.projectNotice(cond('no', 'templates 가 없습니다.'));
    assert.strictEqual(no.state, 'no'); assert.ok(no.text.includes('프로젝트 준비 안 됨') && no.text.includes('templates 가 없습니다.'));
    const unk = L.projectNotice(cond('unknown', 'git 을 실행하지 못했습니다.'));
    assert.strictEqual(unk.state, 'unknown'); assert.ok(unk.text.includes('확인하지 못했어') && !unk.text.includes('준비 안 됨'));
  },
  forms_notice_only_when_ready_and_server_says_missing() {
    const d = (state, forms) => ({ conditions: { 'project-ready': { state } }, formsMissing: forms });
    const n = L.formsNotice(d('yes', 'yes'));
    assert.ok(n.text.includes('고객 양식이 아직 없어') && n.text.includes('templates/') && n.text.includes('md 로만 쓰는 프로젝트면 신경 안 써도 돼'));
    assert.strictEqual(n.short, '고객 양식 아직 없음');
    assert.strictEqual(L.formsNotice(d('yes', 'no')), null);       // 양식이 있다
    assert.strictEqual(L.formsNotice(d('yes', 'unknown')), null);  // 못 읽었으면 말하지 않는다
    assert.strictEqual(L.formsNotice(d('yes', undefined)), null);
    assert.strictEqual(L.formsNotice(d('no', 'yes')), null);       // 준비 안 됨 안내가 따로 있다
    assert.strictEqual(L.formsNotice(null), null);
    assert.strictEqual(L.projectNotice(d('yes', 'yes')), null);    // 준비됨 판정은 그대로
  },
  pr_team_line_mentions_agent_merge_only_in_small_fix_flow() {
    const pr = { number: 6, state: 'OPEN', checks: 'pass' };
    const team = (flow) => L.prLines(pr, flow).find(l => l.id === 'team').text;
    assert.ok(team('fix').includes('승인은 GitHub 에서 해') && team('fix').includes('문서만 바꾼 PR 은 검사가 통과하면 Claude Code 가 바로 병합하기도 해.'));
    assert.ok(!team('srs').includes('바로 병합하기도'));  // SRS·Spec·개발 PR 은 늘 사람이 병합한다
    assert.ok(!team(undefined).includes('바로 병합하기도'));
    assert.strictEqual(L.prLines({ number: 6, state: 'MERGED', checks: 'pass' }, 'fix').find(l => l.id === 'team').text, '합쳐졌어');
  },
  reload_strip_and_result() {
    const live = [{ id: 'a', status: 'idle' }, { id: 'b', status: 'ended' }, { id: 'c', status: 'running' }];
    assert.strictEqual(L.reloadStrip(false, live), null);
    assert.strictEqual(L.reloadStrip(true, [{ id: 'b', status: 'ended' }]), null);
    assert.deepStrictEqual(L.reloadStrip(true, live), { count: 2, text: '돌고 있는 세션 2개 다시 불러오기 필요' });
    assert.strictEqual(L.reloadResult({ ok: true, harnessVersion: '0.10.140', plugins: [], errorCount: 0 }), 'harness 0.10.140 로 다시 불러왔어.');
    assert.strictEqual(L.reloadResult({ ok: true, plugins: [{ name: 'harness', version: '0.10.9' }], errorCount: 2 }), 'harness 0.10.9 로 다시 불러왔어. (오류 2개)');
    assert.ok(L.reloadResult({ queued: true }).includes('끝나면'));
  },
  summary_counts() {
    const list = [{ id: 1, group: 'todo', pendingRequestIds: ['q'] }, { id: 2, group: 'running' }, { id: 3, status: 'running' }, { id: 4 }, { id: 5, pendingRequestIds: ['r'] }];
    assert.strictEqual(L.summaryText(L.counts(list)), '세션 5개 · 일하는 중 2 · 내 차례 2 · 쉬는 중 1');
    assert.strictEqual(L.summaryText(L.counts([])), '세션 0개 · 일하는 중 0 · 내 차례 0 · 쉬는 중 0');
  },
  my_turn_is_only_real_requests() {
    // #1027 D5·D-3: main 에서 쉬는 세션(start)·남의 승인 대기(prs) 짐작, 글로 물은 추정(askedInText), 답할 요청 없는 서버 todo 는 내 차례가 아니다.
    // 올릴 변경이 있는 작업 브랜치(deliver)는 내 차례다(시안 G-11)
    assert.strictEqual(L.groupOf({ id: 1, status: 'idle', turnSkill: 'deliver' }), 'todo');
    assert.strictEqual(L.groupOf({ id: 11, status: 'idle', turnSkill: 'start' }), 'idle');
    assert.strictEqual(L.groupOf({ id: 12, status: 'idle', turnSkill: 'prs' }), 'idle');
    assert.strictEqual(L.groupOf({ id: 13, status: 'running', turnSkill: 'deliver' }), 'running');
    assert.strictEqual(L.groupOf({ id: 2, status: 'idle', askedInText: true }), 'idle');
    assert.strictEqual(L.groupOf({ id: 3, status: 'idle', group: 'todo' }), 'idle');
    assert.strictEqual(L.groupOf({ id: 4, status: 'starting' }), 'running');
    assert.strictEqual(L.groupOf({ id: 5, status: 'waiting', group: 'todo', pendingRequestIds: ['r1'] }), 'todo');
    // 화면이 이미 처리됐다고 아는 요청(openIds 가 비움)이면 서버가 todo 라 해도 내 차례가 아니다
    assert.strictEqual(L.groupOf({ id: 6, status: 'waiting', group: 'todo', pendingRequestIds: ['r1'] }, () => []), 'idle');
    assert.strictEqual(L.groupOf({ id: 7, status: 'running', group: 'todo', pendingRequestIds: ['r1'] }, () => []), 'running');
    const pr = { number: 9, state: 'OPEN', checks: 'fail' };
    const list = [
      { id: 'a', status: 'waiting', group: 'todo', pendingRequestIds: ['r1', 'r2'] },
      { id: 'b', status: 'idle', turnSkill: 'start', askedInText: true },
      { id: 'c', status: 'idle', flowPr: pr },
      { id: 'd', status: 'ended', pendingRequestIds: ['r3'] },
      { id: 'e', status: 'idle', flowPr: pr, lastBlock: { kind: 'blocked', open: true } }
    ];
    // 띠·알림·레일·홈 타일은 이 한 목록의 길이를 쓴다: 요청 둘 + 고칠 PR 하나. 추정·끝난 세션·막힘은 뺀다
    assert.deepStrictEqual(L.turnItems(list).map(t => t.s.id + ':' + t.kind + ':' + t.rid), ['a:request:r1', 'a:request:r2', 'c:fix:']);
    assert.deepStrictEqual(L.turnItems([{ id: 'x', status: 'idle', turnSkill: 'deliver' }]).map(t => t.kind), ['turn']);
    assert.deepStrictEqual(L.turnItems([{ id: 'y', status: 'idle', turnSkill: 'deliver', flowPr: pr }]).map(t => t.kind), ['fix']);  // 고칠 PR 이 먼저
    assert.strictEqual(L.NO_TURN_TEXT, '지금 네가 할 일은 없어');
  },
  session_order_is_stable_within_a_group() {
    // #1027 D-6: 묶음은 지키고 같은 묶음 안에서는 시작 시각(없으면 id)으로 고정 — updatedAt 이 움직여도 순서는 그대로
    const mk = (id, startedAt, updatedAt, extra) => Object.assign({ id, status: 'idle', startedAt, updatedAt }, extra || {});
    const list = [mk('old', 100, 900), mk('new', 300, 100), mk('mid', 200, 500), mk('run', 50, 1, { status: 'running' }),
      mk('done', 400, 1, { status: 'ended' }), mk('ask', 10, 1, { status: 'waiting', pendingRequestIds: ['r'] })];
    const order = (l) => l.slice().sort((a, b) => L.sessionOrder(a, b)).map(s => s.id).join(',');
    assert.strictEqual(order(list), 'ask,run,new,mid,old,done');
    list.forEach(s => { s.updatedAt = 1000 - s.updatedAt; });  // 상태가 바뀌어 updatedAt 이 뒤집혀도
    assert.strictEqual(order(list), 'ask,run,new,mid,old,done');
    // 시작 시각이 없으면 id
    assert.strictEqual(['b', 'a'].map(id => ({ id, status: 'idle' })).sort((x, y) => L.sessionOrder(x, y)).map(s => s.id).join(','), 'a,b');
  },
  check_state_knows_skipped() {
    // #1027 B-3: 건너뛴 점검을 "아직" 으로 읽지 않는다
    const got = L.startChecks({ startChecks: [{ id: 'sync', state: 'skipped' }, { id: 'version', state: 'pending' }] });
    assert.deepStrictEqual(got.map(c => c.state + ':' + c.label), ['skipped:건너뜀', 'todo:아직']);
  },
  pr_cell_prefers_session_pr_links() {
    // #1027 D-1: flowPr 가 없어도 이 세션이 gh pr create 로 만든 PR(prCreated)이 있으면 "PR 아직" 이 아니라 번호를 보인다.
    // 갈래 세션은 prLinks(출력에 스친 남의 PR 주소)를 쓰지 않는다 — 실사용 시험에서 다른 브랜치의 #32 가 보였다
    const steps = [{ id: 's', name: 's', state: 'active' }];
    const cell = (extra) => L.sessionStrip(Object.assign({ flowId: 'f', flowSteps: steps }, extra)).slice(-1)[0];
    assert.strictEqual(cell({ prCreated: 'https://github.com/o/r/pull/77' }).value, 'PR #77');
    assert.strictEqual(cell({ prCreated: 'https://github.com/o/r/pull/78', flowUnknown: ['gh'] }).value, 'PR #78');
    assert.strictEqual(cell({ prLinks: ['https://github.com/o/r/pull/32'] }).value, 'PR 아직');
    assert.strictEqual(cell({}).value, 'PR 아직');
    assert.strictEqual(cell({ flowPr: { number: 5, state: 'OPEN' }, prCreated: 'https://github.com/o/r/pull/77' }).value, 'PR #5 검토 중');
  },
  pr_badge_says_waiting_for_approval() {
    // #1027 항목 12: 승인 대기 검사의 실패는 서버가 checks 에서 빼고 awaitApproval 로 알린다 — 고치기가 아니라 승인 기다림
    const pr = { number: 3, state: 'OPEN', checks: 'pass', awaitApproval: true };
    assert.strictEqual(L.prBadge(pr).text, '승인 기다리는 중');
    assert.strictEqual(L.prBadge({ number: 3, state: 'OPEN', checks: 'fail', awaitApproval: true }).text, '검사 실패');
    assert.strictEqual(L.prNeedsFix({ flowPr: pr }), false);
    assert.strictEqual(L.groupOf({ id: 1, status: 'idle', flowPr: pr }), 'idle');
    // 실사용 시험: 합쳐진 PR 이 표에서 "검사 진행 중" 으로 보였다 — 병합·닫힘이 검사 상태보다 먼저다
    assert.strictEqual(L.prBadge({ number: 34, state: 'MERGED', checks: 'pending' }).text, '합쳐짐');
    assert.strictEqual(L.prBadge({ number: 35, state: 'CLOSED', checks: 'fail' }).text, '닫힘');
  },
  fix_pr_counts_as_todo() {
    // 시안 G-24: 검사 실패한 내 PR 세션은 내 차례. 일하는 중·끝난 세션·막힘은 아니다
    const pr = { number: 812, state: 'OPEN', checks: 'fail' };
    const fix = { id: 1, group: 'idle', status: 'idle', flowPr: pr };
    assert.strictEqual(L.groupOf(fix), 'todo');
    assert.strictEqual(L.groupOf({ id: 2, group: 'running', status: 'running', flowPr: pr }), 'running');
    assert.strictEqual(L.groupOf({ id: 3, group: 'idle', status: 'ended', flowPr: pr }), 'idle');
    assert.strictEqual(L.groupOf({ id: 4, group: 'idle', status: 'idle', flowPr: { number: 3, state: 'OPEN', checks: 'pending' } }), 'idle');
    const blocked = { id: 5, group: 'idle', status: 'idle', flowPr: pr, lastBlock: { kind: 'blocked', open: true } };
    const c = L.counts([fix, blocked]);
    assert.strictEqual(c.todo, 1); assert.strictEqual(c.blocked, 1);
  },
  same_folder() {
    const a = { id: 'a', cwd: 'C:\\Work\\Proj\\', status: 'idle' };
    const list = [a, { id: 'b', cwd: 'c:/work/proj', status: 'running' }, { id: 'c', cwd: 'c:/work/proj', status: 'ended' }, { id: 'd', cwd: 'c:/other', status: 'idle' }];
    assert.deepStrictEqual(L.otherSessions(a.cwd, list, 'a').map(s => s.id), ['b']);
    assert.strictEqual(L.sameFolderBusy(a, list), true);
    assert.strictEqual(L.sameFolderBusy({ id: 'd', cwd: 'c:/other', status: 'idle' }, list), false);
    assert.strictEqual(L.sameFolderBusy({ id: 'z', cwd: 'c:/x', sameFolder: ['q'] }, list), true);
    assert.deepStrictEqual(L.otherSessions('', list, null), []);
    // 다음 세션으로 넘어간 세션은 경고에서 빠진다(양쪽 모두)
    const moved = { id: 'm', cwd: 'c:/work/proj', status: 'idle', handedOffTo: 'a' };
    assert.deepStrictEqual(L.otherSessions(a.cwd, list.concat([moved]), 'a').map(s => s.id), ['b']);
    assert.strictEqual(L.sameFolderBusy(a, [a, moved]), false);
    assert.strictEqual(L.sameFolderBusy(moved, list), false);
  },
  start_checks() {
    assert.deepStrictEqual(L.startChecks({}), []);
    const got = L.startChecks({ startChecks: [{ id: 'reload', state: 'todo' }, { id: 'sync', state: 'ok' }, { id: 'update', state: 'running' }, { id: 'version', state: 'fail' }] });
    // 시안 G-13: 새 세션이 스스로 하는 점검은 최신 내용 받기·하네스 판 두 줄뿐(갱신·다시 불러오기는 도구 줄)
    assert.deepStrictEqual(got.map(c => c.id), ['sync', 'version']);
    assert.deepStrictEqual(got.map(c => c.state), ['done', 'fail']);
    assert.deepStrictEqual(got.map(c => c.name), ['최신 내용 받기', '하네스 판']);
    assert.strictEqual(L.autoChecksOpen({ startChecks: [{ id: 'sync', state: 'done' }, { id: 'version', state: 'pending' }] }), true);
    assert.strictEqual(L.autoChecksOpen({ startChecks: [{ id: 'sync', state: 'done' }, { id: 'version', state: 'skipped' }, { id: 'update', state: 'pending' }] }), false);
    assert.strictEqual(L.autoChecksOpen({}), false);
  },
  start_checks_unknown_and_fail_with_reason() {
    // 훅·판 확인 결과: 확인 못 함(unknown)·다시 필요(fail)와 사유(#1059). 점검이 끝나지 않은 것(pending)과는 다르다
    const got = L.startChecks({ startChecks: [{ id: 'sync', state: 'unknown', reason: '원격이 없어' }, { id: 'version', state: 'fail', reason: '더 새 판이 있어(0.10.9)' }] });
    assert.deepStrictEqual(got.map(c => [c.state, c.label, c.reason]), [['unknown', '확인 못 함', '원격이 없어'], ['fail', '다시 필요', '더 새 판이 있어(0.10.9)']]);
    assert.strictEqual(L.startChecks({ startChecks: [{ id: 'sync', state: 'pending' }] })[0].label, '아직');
    assert.strictEqual(L.startChecks({ startChecks: [{ id: 'sync', state: 'done' }] })[0].reason, '');
  },
  next_flow_and_job() {
    const s = { nextFlow: { options: [{ flow: 'spec', label: '개발 Spec 만들기', value: '개발', count: 3 }, { flow: null, label: '권한(준비 중)', disabled: true }, { flow: null, label: '끝' }], hint: 'h', unknown: '' } };
    const o = L.nextOptions(s).options;
    assert.deepStrictEqual(o.map(x => x.clickable), [true, false, false]);
    assert.strictEqual(o[0].label, '개발 Spec 만들기 · 개발 (3건)'); assert.strictEqual(o[1].disabled, true);
    assert.deepStrictEqual(L.jobOutcome({ state: 'running' }), { done: false });
    assert.deepStrictEqual(L.jobOutcome({ state: 'done', sessionId: 'n1' }), { done: true, ok: true, sessionId: 'n1' });
    assert.strictEqual(L.jobOutcome({ state: 'error', error: '실패' }).ok, false);
    assert.strictEqual(L.jobOutcome({ state: 'done' }).ok, false);
  },
  docs_and_preview() {
    const files = [{ path: 'a.md', mtime: 1 }, { path: 'b.xlsx', mtime: 5 }, { path: 'c.pptx', mtime: 3 }, { nope: 1 }];
    assert.deepStrictEqual(L.docList(files).map(f => f.path), ['b.xlsx', 'c.pptx', 'a.md']);
    assert.deepStrictEqual(['a.md', 'b.xlsx', 'c.pptx', 'd.png', 'e.pdf', 'f.docx'].map(L.previewKind), ['md', 'table', 'slides', 'image', 'pdf', 'doc']);
    assert.strictEqual(L.normPreview({ kind: 'md', text: '# 가' }).text, '# 가');
    assert.strictEqual(L.normPreview({ table: { sheets: [{ name: 'S', rows: [[1]] }] } }).sheets[0].name, 'S');
    assert.strictEqual(L.normPreview({ slides: { slides: [{ index: 1, texts: ['t'] }] } }).slides.length, 1);
    assert.strictEqual(L.normPreview({ image: { url: '/x.png' } }).url, '/x.png');
    assert.strictEqual(L.normPreview({ kind: 'none' }).kind, 'none'); assert.strictEqual(L.normPreview(null).kind, 'none');
    assert.deepStrictEqual(L.versionPaths({ versions: ['v0.1.xlsx', { path: 'v0.2.xlsx' }, {}] }).map(v => v.path), ['v0.1.xlsx', 'v0.2.xlsx']);
    // 서버 versions 는 대표(최신) 파일도 담는다 -> 이전 판 목록에서는 빠진다
    assert.deepStrictEqual(L.versionPaths({ path: 'a_v0.2.md', versions: [{ path: 'a_v0.2.md' }, { path: 'a_v0.1.md' }] }).map(v => v.path), ['a_v0.1.md']);
    assert.deepStrictEqual(L.versionPaths({ path: 'a_v0.1.md', versions: [{ path: 'a_v0.1.md' }] }), []);
  },
  approvals_merge() {
    assert.deepStrictEqual(L.mergeApprovals([{ state: 'no' }, null]), { state: 'no', reason: '', items: [] });
    const m = L.mergeApprovals([{ state: 'yes', items: [{ number: 1, url: 'u1' }] }, { state: 'yes', items: [{ number: 1, url: 'u1' }, { number: 2, url: 'u2' }] }, { state: 'unknown', reason: 'x' }]);
    assert.strictEqual(m.state, 'yes'); assert.strictEqual(m.items.length, 2);
    assert.deepStrictEqual(L.mergeApprovals([{ state: 'unknown', reason: 'gh 실패' }]), { state: 'unknown', reason: 'gh 실패', items: [] });
    assert.strictEqual(L.prBadge({ number: 7, url: 'u', checks: 'fail' }).text, '검사 실패');
    assert.strictEqual(L.prBadge(null), null);
  },
  async dom_tools_row() {
    const run = async (approvals, managed) => {
      const { kit } = makeKit({ 'GET /api/flows': FLOWS, 'GET /api/approvals': approvals });
      const ui = loadUI(kit);
      const row = ui.toolsRow(() => ({ session: { id: 's1', managed, cwd: '/w' }, cwd: '/w' }));
      row.update(); await tick(); await tick();
      return find(row.el, e => e.attrs['data-tool']).map(e => e.attrs['data-tool']);
    };
    assert.deepStrictEqual(await run({ state: 'no' }, false), ['version', 'sync', 'update', 'handoff', 'wrapup', 'prs']);
    assert.deepStrictEqual(await run({ state: 'yes', items: [] }, true), ['version', 'sync', 'update', 'handoff', 'wrapup', 'prs', 'reload', 'approvals']);
    // 서버 응답이 전부 404 여도 도구 줄은 남는다
    const { kit } = makeKit({});
    const ui = loadUI(kit);
    const row = ui.toolsRow(() => ({ session: { id: 's1', managed: false, cwd: '/w' }, cwd: '/w' }));
    row.update(); await tick(); await tick();
    assert.strictEqual(find(row.el, e => e.attrs['data-tool']).length, 6);
  },
  async dom_tool_run_and_update_strip() {
    const { kit, calls } = makeKit({ 'GET /api/flows': FLOWS, 'GET /api/approvals': { state: 'no' }, 'POST /api/sessions/s1/skills/update/run': {}, 'POST /api/reload-all': { ok: true } },
      [{ id: 's1', status: 'idle', managed: true }, { id: 's2', status: 'running' }]);
    const ui = loadUI(kit);
    const row = ui.toolsRow(() => ({ session: kit.sessions.get('s1'), cwd: '/w' }));
    row.update(); await tick(); await tick();
    const strip = () => find(row.el, e => (e.attrs['class'] || '') === 'reload-strip')[0];
    assert.ok(strip().hidden);
    find(row.el, e => e.attrs['data-tool'] === 'update')[0].click(); await tick(); await tick();
    assert.ok(!strip().hidden); assert.ok(strip().textContent.includes('돌고 있는 세션 2개'));
    find(strip(), e => e.tag === 'button')[0].click(); await tick(); await tick();
    assert.ok(calls.some(c => c[1] === '/api/reload-all'));
    assert.ok(strip().hidden);
    // reload 를 서버가 아직 안 만들었으면 조용히 숨기지 않고 알려 준다
    find(row.el, e => e.attrs['data-tool'] === 'reload')[0].click(); await tick(); await tick();
    assert.ok(find(row.el, e => (e.attrs['class'] || '').includes('tools-note'))[0].textContent.includes('아직 준비 안 됨'));
  },
  async dom_flow_panel_buttons() {
    const { kit } = makeKit({});
    const ui = loadUI(kit);
    const panel = ui.flowPanel();
    const sess = (kind, extra) => Object.assign({ id: 's1', cwd: '/w', flowId: 'srs', flowName: '요구사항', stepIndex: 0, status: 'idle', canSend: true,
      flowSteps: [{ id: 'a', name: '지금', kind, skill: kind === 'skill' ? 'srs' : undefined, state: 'active' }, { id: 'b', name: '다음', kind: 'skill', skill: 'deliver', state: 'pending' }] }, extra);
    const buttons = () => find(panel.el, e => e.tag === 'button').map(e => e.textContent);
    panel.update(sess('skill')); assert.deepStrictEqual(buttons(), ['/harness:srs 다시 실행', '이 단계 건너뛰기']);
    panel.update(sess('work')); assert.deepStrictEqual(buttons(), ['끝났어', '이 단계 건너뛰기']);
    panel.update(sess('wait')); assert.deepStrictEqual(buttons(), ['다시 확인', '이 단계 건너뛰기']);
    panel.update(sess('human')); assert.deepStrictEqual(buttons(), ['끝났어', '다시 확인', '이 단계 건너뛰기']);
    // 순서 막대: 지금 단계 하나만 강조
    assert.strictEqual(find(panel.el, e => e.tag === 'li' && e.attrs['aria-current'] === 'step').length, 1);
    assert.strictEqual(find(panel.el, e => e.tag === 'li' && (e.attrs['class'] || '').includes('step')).length, 2);
    // 끝난 갈래: 다음 갈래 버튼, 준비 중은 비활성
    panel.update(sess('skill', { flowFinished: true, nextFlow: { options: [{ flow: 'spec', label: '개발 Spec 만들기' }, { flow: null, disabled: true, label: '권한 양식' }] } }));
    const fin = find(panel.el, e => e.tag === 'button');
    assert.deepStrictEqual(fin.map(b => b.textContent), ['새 세션에서 개발 Spec 시작', '넘길 내용 고치기', '여기서 계속', '권한 양식준비 중']);
    assert.ok(!fin[0].disabled && fin[3].disabled === true);
    assert.ok(panel.el.textContent.includes('개발 Spec 만들기 — 새 세션에서 시작하길 권해') && panel.el.textContent.includes('새 세션에 넘길 것'));
    find(panel.el, e => e.attrs['data-next-stay'])[0].click();  // [여기서 계속] 은 이 세션에서 이어 가기(되돌리는 단추가 남는다)
    assert.ok(panel.el.textContent.includes('이 세션에서 계속 이어 가는 중이야') && find(panel.el, e => e.attrs['data-next-again']).length === 1);
    // 시안 G-09: 올릴 차례는 질문 한 줄 + 단추 둘, 건너뛰기는 같은 줄의 글자 단추. [아직] 은 카드를 접는다
    panel.update(Object.assign(sess('skill'), { flowSteps: [{ id: 'd', name: '올리고 검토 요청하기', kind: 'skill', skill: 'deliver', state: 'pending' }] }));
    assert.deepStrictEqual(buttons(), ['올리고 검토 요청', '아직', '이 단계 건너뛰기']);
    assert.ok(panel.el.textContent.includes('GitHub에 올려서 검토 요청(PR)을 만들까?') && panel.el.textContent.includes('네 차례'));
    find(panel.el, e => e.attrs['data-ask-later'])[0].click();
    assert.deepStrictEqual(buttons(), ['올리고 검토 요청', '이 단계 건너뛰기']);
    // 질문이 떠 있으면 같은 일의 할 일 카드를 두지 않고, 승인을 기다리는 동안에도 두지 않는다(시안 G-10·13)
    panel.update(sess('skill', { pendingRequestIds: ['q1'] })); assert.deepStrictEqual(buttons(), []);
    panel.update(sess('wait', { phase: 'approval' })); assert.deepStrictEqual(buttons(), []);
    // 판정 불능 사유를 숨기지 않는다
    panel.update(sess('wait', { flowUnknown: ['gh 를 못 읽음'] }));
    assert.ok(panel.el.textContent.includes('판정 불능 · gh 를 못 읽음'));
    panel.destroy();
  },
  async dom_flow_picker_hides_by_exposure() {
    const flows = { flows: [{ id: 'srs', name: '요구사항', steps: [], exposure: { visible: true } }, { id: 'atc', name: 'ATC', steps: [], exposure: { visible: false } }] };
    const { kit } = makeKit({ 'GET /api/flows': flows });
    const ui = loadUI(kit);
    const panel = ui.flowPanel();
    panel.update({ id: 's1', cwd: '/w', status: 'idle' }); await tick(); await tick();
    assert.deepStrictEqual(find(panel.el, e => e.attrs['data-flow']).map(e => e.attrs['data-flow']), ['srs']);
    assert.ok(panel.el.textContent.includes('어떤 일이야?'));
    panel.destroy();
    // 갈래 데이터를 못 쓰면(503) 준비 안 됨으로 알린다
    const err = Object.assign(new Error('x'), { status: 503 });
    const { kit: kit2 } = makeKit({ 'GET /api/flows': err });
    const p2 = loadUI(kit2).flowPanel();
    p2.update({ id: 's1', cwd: '/w2', status: 'idle' }); await tick(); await tick();
    assert.ok(p2.el.textContent.includes('아직 준비 안 됨'));
    p2.destroy();
  },
  session_strip_only_known_cells() {
    const cls = (c) => (c.value || '');
    const s = { branch: 'feat/636-x', flowId: 'srs', stepIndex: 1, flowSteps: steps('done', 'active', 'pending'), flowPr: { number: 6, state: 'OPEN', checks: 'pass' } };
    const cells = L.sessionStrip(s);
    // 요구사항·개발 번호는 데이터(다음 갈래의 REQ 번호)가 없으면 만들지 않는다
    assert.deepStrictEqual(cells.map(c => c.id), ['step', 'progress', 'issue', 'pr']);  // 기억 칸은 없다(링·배너가 보인다)
    assert.strictEqual(cls(cells[0]), '2 / 3 단계1');
    assert.strictEqual(cls(cells[1]), '33%'); assert.ok(cells[1].title.includes('3단계 중 1단계'));  // 근거를 같이 보인다
    assert.strictEqual(cls(cells[2]), '이슈 #636'); assert.strictEqual(cls(cells[3]), 'PR #6 검토 중');
    assert.deepStrictEqual(cells.map(c => c.label), ['단계', 'AI 진행', '작업 기록', '검토 요청']);
    // 승인을 기다리는 동안: 단계 "승인 기다림", AI 진행은 "끝"
    const ap = L.sessionStrip(Object.assign({}, s, { phase: 'approval', stepIndex: 2, flowSteps: steps('done', 'done', 'active') }));
    assert.deepStrictEqual([ap[0].value, ap[1].value], ['3 / 3 승인 기다림', '끝']);
    assert.deepStrictEqual(L.progressOf(s), { done: 1, total: 3, pct: 33 });
    // 갈래가 없으면 단계 칸만 "정해진 갈래 없음", 진행 %·PR 칸은 만들지 않는다
    assert.deepStrictEqual(L.sessionStrip({ id: 'x' }).map(c => [c.id, c.value]), [['step', '정해진 갈래 없음']]);
    // 끝난 갈래: 다음 갈래 옵션의 REQ 번호에서만 요구사항·개발 번호를 읽는다
    const fin = L.sessionStrip({ flowId: 'srs', flowFinished: true, flowSteps: steps('done', 'done'), flowPr: { number: 6, state: 'MERGED' },
      nextFlow: { options: [{ flow: 'spec', label: 'Spec', ids: ['REQ-001', 'REQ-002', 'REQ-003', 'bad'] }, { ids: ['REQ-001'] }] } });
    const by = Object.fromEntries(fin.map(c => [c.id, c.value]));
    assert.deepStrictEqual(by, { step: '2 / 2 끝', req: 'REQ-001, REQ-002 외 1개 확정', dev: 'DEV-001, DEV-002 외 1개', pr: 'PR #6 합쳐짐' });  // 갈래가 끝나면 AI 진행 칸은 없다
    // PR 이 아직 없으면 "PR 아직", 읽지 못했으면 "확인 못 함"
    assert.strictEqual(L.sessionStrip({ flowId: 'f', flowSteps: steps('active') }).slice(-1)[0].value, 'PR 아직');
    assert.strictEqual(L.sessionStrip({ flowId: 'f', flowSteps: steps('active'), flowUnknown: ['gh'] }).slice(-1)[0].value, '확인 못 함');
    // 검토 요청 줄: 검사는 합친 한 값, 팀 승인은 PR 상태에서만 읽는다
    assert.deepStrictEqual(L.prLines(null), []);
    const lines = L.prLines({ number: 6, state: 'OPEN', checks: 'none' });
    assert.deepStrictEqual(lines.map(l => [l.id, l.state]), [['doc', 'unk'], ['secret', 'unk'], ['team', 'wait']]);
    assert.deepStrictEqual(lines.map(l => l.name), ['문서 검사', '비밀값 검사', '팀 승인']);
    // 합친 값이 통과면 둘 다 통과, 실패인데 어느 쪽인지 모르면 지어내지 않는다, status 이름(doc-guard·gitleaks)이 읽히면 그대로
    assert.deepStrictEqual(L.prLines({ number: 6, state: 'OPEN', checks: 'pass' }).map(l => l.state), ['ok', 'ok', 'wait']);
    assert.deepStrictEqual(L.prLines({ number: 6, state: 'MERGED', checks: 'fail' }).map(l => l.state), ['unk', 'unk', 'ok']);
    const named = L.prLines({ number: 6, state: 'OPEN', checks: 'fail', stepChecks: { 'doc-guard': 'pass', 'gitleaks': 'fail' } });
    assert.deepStrictEqual(named.map(l => [l.state, l.text]), [['ok', '양식에 맞아'], ['fail', '비밀값이 발견됐어'], ['wait', named[2].text]]);
    assert.ok(L.prLines({ number: 6, state: 'OPEN', checks: 'pending' }, 'srs')[2].text.startsWith('요구사항 문서라 승인자 확인이 필요 · 기다리는 중'));
    // 승인 기다림·끝남의 글(시안 G-10·12)
    const done = { phase: 'finished', flowPr: { number: 6, state: 'MERGED' }, nextFlow: { options: [{ flow: 'spec', name: '개발 Spec', label: '개발 Spec 만들기', ids: ['REQ-001'] }] } };
    assert.strictEqual(L.finishedBand(done), 'PR #6이 합쳐졌어 — 다음은 개발 Spec');
    assert.strictEqual(L.phaseLine(done), 'PR #6이 합쳐졌어. 다음 갈래는 개발 Spec이야');
    assert.strictEqual(L.phaseSide(done), '끝 · PR #6 합쳐짐');
    assert.strictEqual(L.phaseSide({ phase: 'approval', flowPr: { number: 7, state: 'OPEN' } }), '승인 기다림 · PR #7');
    assert.strictEqual(L.phaseLine({ phase: 'approval' }), 'GitHub에 올렸어 · 팀 승인을 기다리는 중');
    assert.strictEqual(L.finishedBand({ phase: 'approval' }), ''); assert.strictEqual(L.finishedBand({ phase: 'finished', flowPr: null }), '');
    assert.strictEqual(L.phaseLine({ phase: 'finished', flowPr: { number: 3, state: 'MERGED' }, nextFlow: { options: [{ flow: 'config', name: '설정', label: '설정하기' }] } }), 'PR #3이 합쳐졌어. 다음 갈래는 설정이야');
    assert.strictEqual(L.checksFailed({ flowPr: { checks: 'fail' } }), true); assert.strictEqual(L.checksFailed({ flowPr: { checks: 'pass' } }), false);
  },
  memory_of_pct_tokens_unknown_and_levels() {
    // % 는 서버가 창 크기를 알 때만 온다. 없으면 토큰 수만, 아무것도 없으면 확인 못 함.
    assert.deepStrictEqual(L.memoryOf({}).kind, 'unknown'); assert.strictEqual(L.memoryOf({}).text, '?');
    assert.strictEqual(L.memoryOf({ context: { tokens: null, window: null, pct: null } }).kind, 'unknown');
    const tok = L.memoryOf({ context: { tokens: 241482, window: null, pct: null } });
    assert.deepStrictEqual([tok.kind, tok.text, tok.pct, tok.level], ['tokens', '24만 토큰', null, '']);
    assert.ok(!/%/.test(tok.text));
    const lv = (pct) => L.memoryOf({ context: { tokens: 1000, window: 1000, pct } }).level;
    assert.deepStrictEqual([lv(64), lv(80), lv(81), lv(89), lv(90), lv(92)], ['', '', 'warn', 'warn', 'hot', 'hot']);  // 링 색: 80% 초과 노랑, 90% 이상 빨강
    assert.strictEqual(L.memoryOf({ context: { tokens: 5, window: 10, pct: 92 } }).text, '92%');
    // 숫자 띠에는 기억 칸이 없다(시안 G-09·10·12·13): 기억은 사이드바 링과 배너가 보인다
    assert.ok(!L.sessionStrip({ context: { tokens: 920000, window: 1000000, pct: 92 } }).some(c => c.id === 'memory'));
  },
  async dom_flow_cells_use_easy_words_and_review_adds_next_flow() {
    // 순서 칸은 스킬 명령이 아니라 단계의 plain·easy(데이터)로 쓰고, 확인 화면은 첫 칸 강조 + brief + 다음 갈래 칸을 더한다(G-05·06)
    const steps = [
      { id: 'srs', name: 'SRS 쓰기', short: '쓰기', plain: '요구사항 쓰기', easy: 'AI가 몇 가지 물어봐', kind: 'skill', skill: 'srs' },
      { id: 'deliver', name: '올리고 검토 요청하기', short: '올리기', plain: 'GitHub에 올리기', easy: '올리기 전에 너한테 물어', brief: '올리기 전에 물어봐', kind: 'skill', skill: 'deliver' },
      { id: 'merge', name: '승인받고 합쳐지기 기다리기', short: '승인·합치기', kind: 'wait' }];
    const flows = { flows: [{ id: 'srs', name: '요구사항', steps, next: { srsColumn: { branches: { '개발': { flow: 'spec', label: '개발 Spec 만들기' }, '미정': { flow: null, label: 'x' } } } } },
                            { id: 'spec', name: '개발 Spec', steps: [] }], tools: [] };
    const { kit } = makeKit({ 'GET /api/flows': flows });
    const ui = loadUI(kit);
    const pv = ui.flowPreview();
    pv.update({ cwd: '/w', flowId: 'srs' }); await tick(); await tick();
    const cells = (el) => find(el, e => (e.attrs['class'] || '').split(' ').includes('fs')).map(e => e.textContent);
    assert.deepStrictEqual(cells(pv.el), ['1 요구사항 쓰기AI가 몇 가지 물어봐', '2 GitHub에 올리기올리기 전에 너한테 물어', '3 승인·합치기밖에서 일이 끝나길 기다려']);
    assert.ok(!pv.el.textContent.includes('/harness:'));
    pv.destroy();
    const ch = ui.flowChooser();
    ch.update({ cwd: '/w', found: { id: 'srs', confident: true, reason: '요구사항을 더하는 일' }, selected: 'srs', userPicked: false, kindFlowId: '', kindName: '', ready: null, insist: false, onPick: () => {}, onKeep: () => {} });
    await tick(); await tick();
    assert.deepStrictEqual(cells(ch.el), ['1 요구사항 쓰기이번 세션', '2 GitHub에 올리기올리기 전에 물어봐', '3 승인·합치기밖에서 일이 끝나길 기다려', '4 개발 Spec다음 세션']);
    assert.ok(find(ch.el, e => (e.attrs['class'] || '').split(' ').includes('now')).length === 1);
    // 갈래 설명은 AI 말 한 줄(line)로 합쳐지고, 따로 "어떤 일이야?" 제목이나 "이 일은" 줄은 없다
    assert.ok(ch.line.textContent.includes('이 일은 요구사항 갈래야.') && ch.line.textContent.includes('요구사항을 더하는 일'));
    assert.ok(!ch.el.textContent.includes('어떤 일이야?') && !ch.el.textContent.includes('이 일은'));
    // 다른 갈래로 바꾸기는 아래 단추 줄(tail)에, 고르는 칸은 grid 에
    assert.ok(ch.tail.textContent.includes('다른 갈래로 바꾸기'));
    ch.destroy();
  },
  async dom_pr_card_flow_preview_and_compact_panel() {
    const { kit } = makeKit({ 'GET /api/flows': FLOWS });
    const ui = loadUI(kit);
    assert.strictEqual(ui.prCard({}), null);
    const card = ui.prCard({ flowPr: { number: 6, state: 'OPEN', url: 'https://github.com/o/r/pull/6', title: 'docs: SRS', checks: 'pending' } });
    assert.ok(card.textContent.includes('PR #6 · docs: SRS') && card.textContent.includes('GitHub에서 보기'));
    assert.deepStrictEqual(find(card, e => e.attrs['data-line']).map(e => e.attrs['data-line'] + ':' + e.attrs['class'].split(' ')[1]), ['doc:wait', 'secret:wait', 'team:wait']);
    // 이렇게 진행돼: 갈래 id 가 있으면 그 순서 칸, 없으면 안내 글
    const pv = ui.flowPreview();
    pv.update({ cwd: '/w', flowId: 'srs' }); await tick(); await tick();
    const fs = find(pv.el, e => (e.attrs['class'] || '').split(' ').includes('fs'));
    assert.deepStrictEqual(fs.map(e => e.children[0].textContent), ['1 SRS 쓰기', '2 제출', '3 승인']);
    pv.update({ cwd: '/w', flowId: '', note: '순서는 나중에 알려 줘' });
    assert.ok(pv.el.textContent === '순서는 나중에 알려 줘' && !find(pv.el, e => e.attrs['data-flow-cells']).length);
    pv.destroy();
    // 세션 화면용 compact 칸: 갈래 이름·순서 막대는 제목 아래 알약이 맡고, 버튼은 그대로다
    const panel = ui.flowPanel({ compact: true });
    panel.update({ id: 's1', cwd: '/w', flowId: 'srs', flowName: '요구사항', stepIndex: 0, status: 'idle', canSend: true,
      flowSteps: [{ id: 'a', name: '지금', kind: 'skill', skill: 'srs', state: 'active' }, { id: 'b', name: '다음', kind: 'skill', skill: 'deliver', state: 'pending' }] });
    assert.deepStrictEqual(find(panel.el, e => e.tag === 'button').map(e => e.textContent), ['/harness:srs 다시 실행', '이 단계 건너뛰기']);
    assert.strictEqual(find(panel.el, e => e.tag === 'ol').length, 0);
    assert.ok(!panel.el.textContent.includes('요구사항') && panel.el.textContent.includes('지금 할 일 · 지금'));
    panel.destroy();
  },
  async dom_home_cards() {
    const sessions = [
      { id: 'a', title: '요구사항 쓰기', cwd: 'C:\Work\proj-a', branch: 'feat/636-req', group: 'todo', pendingRequestIds: ['r1'], flowId: 'srs', flowName: '요구사항', stepIndex: 1,
        flowSteps: steps('done', 'active', 'pending'), flowPr: { number: 4, state: 'open', url: 'https://github.com/o/r/pull/4', checks: 'pass' } },
      { id: 'b', title: '', cwd: '/home/x/proj-b', group: 'running', currentAction: '파일 읽는 중', subagents: [{ state: 'running' }, { state: 'done' }] },
    ];
    const { kit } = makeKit({ 'GET /api/approvals': { state: 'yes', items: [{ number: 9, title: '문서', url: 'https://github.com/o/r/pull/9', author: 'kim' }] } }, sessions);
    kit.requests.set('r1', { id: 'r1', status: 'pending' });
    const ui = loadUI(kit);
    const root = h('div');
    ui.homeView(root); await tick(); await tick();
    const text = root.textContent;
    assert.ok(!text.includes('세션 2개 ·'));  // 시안 G-11: 제목 아래 요약 줄은 없다(타일이 같은 숫자)
    assert.ok(text.includes('proj-a') && text.includes('proj-b'));
    assert.ok(find(root, e => e.tag === 'span' && (e.attrs.title || '').includes('서브에이전트 1개 실행 중')).length === 1 && !text.includes('서브에이전트 1개 실행 중'));  // 상태 칸은 칩 하나, 둘째 줄은 title
    assert.ok(text.includes('PR #4 · 검사 통과') && text.includes('이슈 #636'));
    // 시안 G-11: 검토 요청(PR) 칸 안에서는 큰 카드 없이 줄 하나("내가 승인할 PR #n …"). 머리와 문장이 붙어 나오지 않는다
    assert.ok(text.includes('내가 승인할 PR #') && !text.includes('내가 승인할 PR 1건') && !text.includes('건지금'));
    // 숫자 타일(시안 G-11): 내 차례 / 일하는 중 / 이번 주 산출물, 승인 기다리는 PR 은 데이터를 받은 뒤에만 보인다
    const tiles = find(root, e => (e.attrs['class'] || '').split(' ').includes('tile2'));
    assert.deepStrictEqual(tiles.slice(0, 2).map(t => t.textContent), ['내 차례1', 'AI가 일하는 중1']);
    const weekTile = find(root, e => e.attrs['data-week-tile'])[0];
    assert.ok(weekTile && weekTile.textContent.startsWith('이번 주 산출물') && !text.includes('쉬는 중0'));
    const prTile = find(root, e => e.attrs['data-pr-tile'])[0];
    assert.ok(!prTile.hidden && prTile.textContent === '승인 기다리는 PR1');
    // 내 차례 노랑 카드는 요청 화면으로 보낸다. 기억 %는 데이터가 없어 지어내지 않는다.
    const call = find(root, e => e.attrs['data-call'] === 'a')[0];
    assert.ok(call && call.textContent.includes('가서 승인하기'));
    assert.strictEqual(find(call, e => e.tag === 'a')[0].attrs.href, '/r/r1');
    const row = find(root, e => e.attrs['data-session'] === 'a')[0];
    assert.ok((row.attrs['class'] || '').includes('attn'));
    assert.ok(row.textContent.includes('내 차례'));
    assert.strictEqual(find(row, e => e.tag === 'li' && e.attrs['aria-current'] === 'step').length, 1);
    const unk = find(row, e => (e.attrs['class'] || '').includes('unk'))[0];
    assert.ok(unk.textContent === '?' && unk.attrs.title === '기억 사용량 확인 못 함');
    assert.ok(!/\d+%/.test(root.textContent));
    // 승인자가 아니면 카드도 타일도 없다
    const { kit: k2 } = makeKit({ 'GET /api/approvals': { state: 'no' } }, sessions);
    const root2 = h('div'); loadUI(k2).homeView(root2); await tick(); await tick();
    assert.ok(!root2.textContent.includes('내가 승인할 PR'));
    assert.ok(find(root2, e => e.attrs['data-pr-tile'])[0].hidden);
    // 판정 불능은 사유와 함께 보인다
    const { kit: k3 } = makeKit({ 'GET /api/approvals': { state: 'unknown', reason: 'gh 로그인 안 됨' } }, sessions);
    const root3 = h('div'); loadUI(k3).homeView(root3); await tick(); await tick();
    assert.ok(root3.textContent.includes('판정 불능 · gh 로그인 안 됨'));
    assert.ok(find(root3, e => e.attrs['data-pr-tile'])[0].textContent.includes('확인 못 함'));
    // 내 차례가 없으면 노랑 카드가 없다
    const { kit: k4 } = makeKit({ 'GET /api/approvals': { state: 'no' } }, [sessions[1]]);
    const root4 = h('div'); loadUI(k4).homeView(root4); await tick(); await tick();
    assert.strictEqual(find(root4, e => e.attrs['data-call']).length, 0);
    // 내 차례가 여러 건이어도 카드는 한 장(가장 오래 기다린 것) + "외 n건" 알약. 누르면 펼치고 다시 누르면 접는다. (#667)
    const many = [
      { id: 'n1', title: '새것', cwd: '/w/a', group: 'todo', pendingRequestIds: ['q1'], updatedAt: 300 },
      { id: 'n2', title: '가장 오래', cwd: '/w/b', group: 'todo', pendingRequestIds: ['q2'], updatedAt: 100 },
      { id: 'n3', title: '중간', cwd: '/w/c', group: 'todo', pendingRequestIds: ['q3'], updatedAt: 200 },
    ];
    const { kit: k5 } = makeKit({ 'GET /api/approvals': { state: 'no' } }, many);
    const root5 = h('div'); loadUI(k5).homeView(root5); await tick(); await tick();
    assert.deepStrictEqual(find(root5, e => e.attrs['data-call']).map(e => e.attrs['data-call']), ['n2']);
    const tog = find(root5, e => e.attrs['data-calls-toggle'])[0];
    assert.strictEqual(tog.tag, 'button'); assert.strictEqual(tog.textContent, '외 2건'); assert.strictEqual(tog.attrs['aria-expanded'], 'false');
    assert.strictEqual(find(root5, e => e.tag === 'details').length, 0);
    tog.click();
    assert.deepStrictEqual(find(root5, e => e.attrs['data-call']).map(e => e.attrs['data-call']), ['n2', 'n3', 'n1']);
    assert.strictEqual(tog.textContent, '접기'); assert.strictEqual(tog.attrs['aria-expanded'], 'true');
    tog.click();
    assert.deepStrictEqual(find(root5, e => e.attrs['data-call']).map(e => e.attrs['data-call']), ['n2']);
    // 한 건뿐이면 알약이 없다
    const { kit: k6 } = makeKit({ 'GET /api/approvals': { state: 'no' } }, [many[0]]);
    const root6 = h('div'); loadUI(k6).homeView(root6); await tick(); await tick();
    assert.strictEqual(find(root6, e => e.attrs['data-calls-toggle']).length, 0);
  },
  async dom_home_trouble_and_fix_pr() {
    // 시안 G-24: 홈에 "팀 기록 · 아직 안 풀린 문제 n건 [보기]" 칸과 "고쳐야 할 내 PR n건" 줄이 더해진다
    const mine = { state: 'ok', items: [
      { number: 812, title: '판매오더 조회 앱', url: 'https://github.com/o/r/pull/812', branch: 'feat/4-so', checks: 'fail' },
      { number: 3, title: 'CTS', url: 'https://github.com/o/r/pull/3', branch: 'docs/6', checks: 'pending' },
      { number: 820, title: '세션 없는 PR', url: 'https://github.com/o/r/pull/820', branch: 'docs/20', checks: 'fail' }] };
    const sessions = [{ id: 'a', title: '판매오더', cwd: '/w/proj-a', branch: 'feat/4-so', group: 'idle', canSend: true,
      flowId: 'srs', flowSteps: steps('done', 'active', 'pending'), flowPr: { number: 812, state: 'OPEN', checks: 'fail' } }];
    const sent = [];
    const routes = { 'GET /api/approvals': { state: 'no' }, 'GET /api/my-prs': mine,
      'GET /api/trouble': { loading: false, projects: [{ ok: true, name: 'r' }], stats: { open: 3 } },
      'POST /api/sessions/a/messages': body => { sent.push(body.text); return { sent: true }; } };
    const { kit } = makeKit(routes, sessions);
    const root = h('div'); loadUI(kit).homeView(root); await tick(); await tick(); await tick();
    const tb = find(root, e => e.attrs['data-trouble-tile'])[0];
    assert.ok(tb.textContent.startsWith('팀 기록') && tb.textContent.includes('아직 안 풀린 문제 3건') && tb.textContent.endsWith('보기'));
    assert.strictEqual(find(tb, e => e.tag === 'a')[0].attrs.href, '/troubles');
    // 검사가 실패한 내 PR 만(진행 중인 #3 은 아니다). 세션 없는 PR 도 읽는다. 머리의 건수는 첫 줄에만
    const rows = find(root, e => e.attrs['data-fix-pr']);
    assert.deepStrictEqual(rows.map(e => e.attrs['data-fix-pr']), ['812', '820']);
    assert.ok(rows[0].textContent.includes('고쳐야 할 내 PR 2건') && rows[0].textContent.includes('#812 판매오더 조회 앱 · 검사 실패') && rows[0].textContent.includes('AI 에게 고치라고 하기'));
    // 세션이 있고 보낼 수 있으면 그 세션에 말을 보낸다
    find(rows[0], e => e.tag === 'button')[0].click(); await tick(); await tick();
    assert.strictEqual(sent.length, 1); assert.ok(sent[0].includes('#812') && sent[0].includes('자동 검사가 실패'));
    // 내 차례로 세지만(홈 타일 숫자) 노랑 내 차례 카드는 없다 — 빨간 줄이 그 일을 한다
    assert.strictEqual(find(root, e => e.attrs['data-call']).length, 0);
    assert.strictEqual(find(root, e => (e.attrs['class'] || '').includes('tile2') && e.textContent.startsWith('내 차례'))[0].textContent.replace(/\D+/g, ''), '1');
    // 세션 표 칩은 "고쳐야 함"
    assert.strictEqual(find(find(root, e => e.attrs['data-session'] === 'a')[0], e => (e.attrs['class'] || '') === 'tag')[0].textContent, '고쳐야 함');
    // 기록을 못 읽으면 0건이 아니라 확인 못 함, 내 PR 을 못 읽으면 줄이 아니라 확인 못 함 줄
    const bad = Object.assign({}, routes, { 'GET /api/trouble': { loading: false, projects: [{ ok: false, name: 'r', reason: 'gh 로그인 안 됨' }], stats: { open: 0 } },
      'GET /api/my-prs': { state: 'unknown', reason: 'gh 로 내 PR 목록을 읽지 못했습니다' } });
    const { kit: k2 } = makeKit(bad, sessions);
    const root2 = h('div'); loadUI(k2).homeView(root2); await tick(); await tick(); await tick();
    const tb2 = find(root2, e => e.attrs['data-trouble-tile'])[0];
    assert.ok(tb2.textContent.includes('확인 못 함 · gh 로그인 안 됨') && !tb2.textContent.includes('0건') && tb2.attrs['class'].includes('unk'));
    const rows2 = find(root2, e => e.attrs['data-fix-pr']);
    assert.deepStrictEqual(rows2.map(e => e.attrs['data-fix-pr']), ['unknown']);
    assert.ok(rows2[0].textContent.includes('? 확인 못 함 · ') && rows2[0].textContent.includes('내 PR 목록을 읽지 못했습니다') && !find(rows2[0], e => e.tag === 'button').length);
    // 실패한 PR 이 없으면 줄이 없다. 열린 문제가 0건이면 "0건"
    const none = Object.assign({}, routes, { 'GET /api/my-prs': { state: 'ok', items: [mine.items[1]] }, 'GET /api/trouble': { projects: [{ ok: true, name: 'r' }], stats: { open: 0 } } });
    const { kit: k3 } = makeKit(none, sessions);
    const root3 = h('div'); loadUI(k3).homeView(root3); await tick(); await tick(); await tick();
    assert.strictEqual(find(root3, e => e.attrs['data-fix-pr']).length, 0);
    assert.ok(find(root3, e => e.attrs['data-trouble-tile'])[0].textContent.includes('아직 안 풀린 문제 0건'));
    // 그 PR 의 세션이 없거나 보낼 수 없으면 새 작업 입력칸에 문장을 넣어 간다
    let started = '';
    const { kit: k4 } = makeKit(routes, [Object.assign({}, sessions[0], { canSend: false })]);
    k4.startNew = t => { started = t; };
    const root4 = h('div'); loadUI(k4).homeView(root4); await tick(); await tick(); await tick();
    find(find(root4, e => e.attrs['data-fix-pr'] === '820')[0], e => e.tag === 'button')[0].click();
    assert.ok(started.includes('#820') && started.includes('자동 검사가 실패'));
  },
  dev_ready_hints_and_block() {
    // 읽지 못함·해당 없음·읽는 중은 null: 종류 버튼에 아무 표시도 없고 개발을 막지도 않는다
    for (const d of [null, { state: 'unknown' }, { state: 'no' }, { state: 'yes', loading: true }]) {
      const v = L.devReadyView(d);
      assert.strictEqual(v, null);
      ['dev', 'spec', 'config', 'srs', ''].forEach(f => assert.strictEqual(L.kindHint(f, v), null));
      assert.strictEqual(L.devBlock('dev', v), null);
    }
    const none = L.devReadyView({ state: 'yes', specReady: 0, setup: 1, needSpec: [{ number: 1, label: 'REQ-001(구매오더)' }, { number: 2, label: 'REQ-002(판매)' }], needSpecCount: 2 });
    assert.deepStrictEqual(L.kindHint('dev', none), { tone: 'dim', text: 'Spec 있는 건 없음 — 개발 Spec 먼저' });
    assert.deepStrictEqual(L.kindHint('spec', none), { tone: 'hot', text: '할 차례 REQ-001(구매오더) 외 1건' });
    assert.deepStrictEqual(L.kindHint('config', none), { tone: '', text: '설정 건 1개' });
    assert.strictEqual(L.kindHint('srs', none), null);
    assert.ok(L.devBlock('dev', none).includes('Spec 없이 개발은 시작할 수 없어'));
    assert.strictEqual(L.devBlock('spec', none), null);
    const some = L.devReadyView({ state: 'yes', specReady: 2, setup: 0, needSpec: [], needSpecCount: 0 });
    assert.strictEqual(L.kindHint('dev', some).text, 'Spec 있는 건 2개');
    assert.strictEqual(L.kindHint('spec', some), null);
    assert.strictEqual(L.kindHint('config', some), null);
    assert.strictEqual(L.devBlock('dev', some), null);
    // 요구사항(SRS)이 없는 건은 Spec 이 있어도 세지 않고 따로 알린다(#837)
    const noReq = L.devReadyView({ state: 'yes', specReady: 0, setup: 0, needSpec: [], needSpecCount: 0, noReq: [{ number: 9, label: 'DEV-009(x)' }], noReqCount: 1 });
    assert.strictEqual(L.kindHint('dev', noReq).text, 'Spec 있는 건 없음 — 요구사항 없는 건 1개, 요구사항 먼저');
    assert.ok(L.devBlock('dev', noReq).includes('요구사항(SRS)에 없는 개발은 시작할 수 없어'));
    const mixed = L.devReadyView({ state: 'yes', specReady: 2, setup: 0, needSpec: [], needSpecCount: 0, noReqCount: 1 });
    assert.strictEqual(L.kindHint('dev', mixed).text, 'Spec 있는 건 2개 · 요구사항 없는 건 1개(요구사항 먼저)');
    assert.strictEqual(L.devBlock('dev', mixed), null);
  },
  standard_kind_hint_and_srs_status_cell() {
    // 숫자 띠·큰 순서 알약은 단계 이름 끝 괄호 설명을 뗀 짧은 이름(시안 G-09·12), 전체는 title
    assert.strictEqual(L.shortStepName('표준 건 작업 시작하기(그 [DEV-xxx] 로, 작업 기록과 작업 공간을 자동으로 만들어)'), '표준 건 작업 시작하기');
    assert.strictEqual(L.shortStepName('SRS 쓰기'), 'SRS 쓰기');
    assert.strictEqual(L.shortStepName('(괄호만)'), '(괄호만)');  // 다 지워지면 원래 이름
    // step.short(workflow.json)가 있으면 그것, 없으면 괄호만 뗀 이름
    assert.strictEqual(L.stepShort({ name: '올리고 검토 요청하기', short: '올리기' }), '올리기');
    assert.strictEqual(L.stepShort({ name: '표준 건 작업 시작하기(설명)' }), '표준 건 작업 시작하기');
    const shortStep = { flowId: 'srs', flowSteps: [{ name: 'SRS 쓰기', short: '쓰기', state: 'done' }, { name: '올리고 검토 요청하기', short: '올리기', state: 'now' }, { name: '승인받고 합쳐지기 기다리기', short: '승인·합치기', state: 'todo' }], stepIndex: 1 };
    const shortCell = L.sessionStrip(shortStep, undefined).find(c => c.id === 'step');
    if (shortCell && shortCell.value !== '확인 못 함') { assert.strictEqual(shortCell.value, '2 / 3 올리기'); assert.strictEqual(shortCell.title, '올리고 검토 요청하기'); }
    const longStep = { flowId: 'standard', flowSteps: [{ name: '표준 건 작업 시작하기(그 [DEV-xxx] 로, 작업 기록과 작업 공간을 자동으로 만들어)', state: 'now' }, { name: '올리기', state: 'todo' }], stepIndex: 0 };
    const stepCell = L.sessionStrip(longStep, undefined).find(c => c.id === 'step');
    if (stepCell && stepCell.value !== '확인 못 함') { assert.ok(!stepCell.value.includes('(')); assert.ok(stepCell.title.includes('자동으로 만들어)')); }
    // 설정 수(setup)는 표준 건을 포함한다: 화면은 표준을 따로 세고 설정은 그만큼 뺀다(#718)
    const v = L.devReadyView({ state: 'yes', specReady: 1, setup: 3, standard: 2, needSpec: [], needSpecCount: 0 });
    assert.deepStrictEqual(L.kindHint('config', v), { tone: '', text: '설정 건 1개' });
    assert.deepStrictEqual(L.kindHint('standard', v), { tone: '', text: '표준 건 2개' });
    const onlyStd = L.devReadyView({ state: 'yes', specReady: 0, setup: 2, standard: 2, needSpec: [], needSpecCount: 0 });
    assert.strictEqual(L.kindHint('config', onlyStd), null);
    assert.strictEqual(L.kindHint('standard', L.devReadyView({ state: 'yes', specReady: 0, setup: 1, needSpec: [], needSpecCount: 0 })), null);
    assert.strictEqual(L.kindHint('standard', null), null);
    // 새 작업 종류 버튼: '설정하기' 바로 뒤에 표준 종류, standard 갈래로 시작
    const app = require('fs').readFileSync(path.join(dir, 'app.js'), 'utf8');
    assert.ok(/\['설정하기'[^\n]*'config'[^\n]*\],\s*\n\s*\['표준 기능으로 처리', 'SAP 표준 앱으로 끝나는 건', 'standard',/.test(app));
    // SRS 상태 칸: 설정·표준 갈래에서만, 받은 값(없으면 칸을 비움). 못 읽으면 확인 못 함
    const mk = (flowId, extra) => Object.assign({ flowId, flowSteps: [], title: 'REQ-002(판매) 표준 처리' }, extra);
    const ids = (s, srs) => L.sessionStrip(s, srs).map(c => c.id);
    const srs = { state: 'yes', items: { 'REQ-002': { status: 'In Process', next: '표준' }, 'REQ-003': { status: 'Done', next: '표준' } } };
    assert.ok(!ids(mk('standard'), undefined).includes('srs-status'));          // 아직 못 받음
    assert.ok(!ids(mk('dev'), srs).includes('srs-status'));                     // 개발 갈래엔 없다
    const cell = L.sessionStrip(mk('standard'), srs).find(c => c.id === 'srs-status');
    assert.deepStrictEqual([cell.label, cell.value], ['SRS 상태', '진행 중']); assert.ok(cell.title.includes('In Process'));
    assert.strictEqual(L.sessionStrip(mk('config', { title: 'DEV-003 설정' }), srs).find(c => c.id === 'srs-status').value, '끝');
    assert.strictEqual(L.sessionStrip(mk('config', { title: 'DEV-003 설정' }), srs).find(c => c.id === 'srs-status').tone, 'g');
    const two = mk('standard', { nextFlow: { options: [{ ids: ['REQ-002', 'REQ-003'] }] } });
    assert.strictEqual(L.sessionStrip(two, srs).find(c => c.id === 'srs-status').value, 'REQ-002 진행 중, REQ-003 끝');
    for (const bad of [{ state: 'unknown' }, { state: 'no' }, { state: 'yes', items: {} }]) {
      const c = L.sessionStrip(mk('standard'), bad).find(x => x.id === 'srs-status');
      assert.strictEqual(c.value, '확인 못 함');
    }
    assert.strictEqual(L.sessionStrip(mk('standard', { title: '이름에 번호 없음' }), srs).find(x => x.id === 'srs-status').value, '확인 못 함');
  },
  kind_conflict_rules() {
    const ai = { id: 'spec', confident: false, alternativeId: 'dev', reason: 'Spec 이 없어' };
    assert.deepStrictEqual(L.kindConflict(ai, 'dev'), { id: 'spec', reason: 'Spec 이 없어' });
    assert.strictEqual(L.kindConflict(ai, 'spec'), null);  // 같으면 묻지 않는다
    assert.strictEqual(L.kindConflict(ai, ''), null);      // 종류를 안 골랐으면 지금 동작 그대로
    assert.strictEqual(L.kindConflict(null, 'dev'), null);
  },
  async dom_ask_card_when_ai_differs() {
    const flows = { flows: ['spec', 'dev'].map(id => ({ id, name: id === 'spec' ? '개발 Spec' : '개발하기', steps: [{ kind: 'skill', skill: id, name: id }] })), tools: [] };
    const { kit } = makeKit({ 'GET /api/flows': flows });
    const ui = loadUI(kit);
    const ai = { id: 'spec', confident: false, alternativeId: 'dev', reason: 'Spec 이 없어서 먼저 해야 해' };
    const none = L.devReadyView({ state: 'yes', specReady: 0, setup: 0, needSpec: [], needSpecCount: 0 });
    const picks = [], keeps = [];
    const base = { cwd: '/w', found: ai, selected: null, userPicked: false, kindFlowId: 'dev', kindName: '그래도 개발하기', ready: none, insist: false,
      onPick: id => picks.push(id), onKeep: () => keeps.push(1) };
    const ch = ui.flowChooser();
    ch.update(base); await tick(); await tick();
    // AI 와 다르면 갈래 카드 대신 묻는 카드: AI 이유와 두 버튼. 두 후보 고르기 칩은 없다.
    assert.ok(ch.el.textContent.includes('AI 는 개발 Spec 부터 하자고 해 — Spec 이 없어서 먼저 해야 해'));
    assert.strictEqual(find(ch.el, e => e.attrs['data-flow']).length, 0);
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask-block']).length, 0);
    const sw = find(ch.el, e => e.attrs['data-ask-switch'])[0], keep = find(ch.el, e => e.attrs['data-ask-keep'])[0];
    assert.ok(sw.textContent.includes('개발 Spec 쪽으로 바꾸기 (추천)')); assert.strictEqual(keep.textContent, '그래도 개발하기');
    sw.click(); assert.deepStrictEqual(picks, ['spec']);
    keep.click(); assert.strictEqual(keeps.length, 1);
    // Spec 없음이 확실하고 "그래도" 를 눌렀으면 막는 글
    ch.update(Object.assign({}, base, { insist: true })); await tick(); await tick();
    assert.ok(find(ch.el, e => e.attrs['data-ask-block'])[0].textContent.includes('Spec 없이 개발은 시작할 수 없어. PR 검사(spec-ready)에서도 막혀'));
    // 상태를 모르면(ready null) 막는 글 없이 추천 카드만
    ch.update(Object.assign({}, base, { insist: true, ready: null })); await tick(); await tick();
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask-block']).length, 0);
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask-switch']).length, 1);
    // 종류를 안 골랐으면 지금 동작: 확신 없을 때 두 후보 묻기
    ch.update(Object.assign({}, base, { kindFlowId: '', kindName: '' })); await tick(); await tick();
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask']).length, 0);
    assert.deepStrictEqual(find(ch.el, e => e.attrs['data-flow'] && e.tag === 'button' && (e.attrs['class'] || '').includes('btn')).slice(0, 2).map(e => e.attrs['data-flow']), ['spec', 'dev']);
    // AI 도 같은 갈래면 묻지 않고, Spec 이 없다고 확실하면 시작을 막는 글만 보인다
    ch.update(Object.assign({}, base, { found: { id: 'dev', confident: true, reason: '' }, selected: 'dev', userPicked: true })); await tick(); await tick();
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask']).length, 0);
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask-block']).length, 1);
    // 이미 사용자가 갈래를 고른 뒤에는 다시 묻지 않는다
    ch.update(Object.assign({}, base, { userPicked: true, selected: 'spec' })); await tick(); await tick();
    assert.strictEqual(find(ch.el, e => e.attrs['data-ask']).length, 0);
  },
  async dom_home_empty() {
    const { kit } = makeKit({ 'GET /api/approvals': { state: 'no' } }, []);
    const went = [];
    kit.startNew = t => went.push(t); kit.go = p => went.push('go:' + p);
    const root = h('div');
    loadUI(kit).homeView(root); await tick(); await tick();
    assert.ok(root.textContent.includes('아직 시작한 작업이 없어'));
    // 자주 하는 일 6개 + 숫자 타일 3개(산출물 수는 구할 수 없어 확인 못 함)
    const kinds = find(root, e => e.attrs['data-kind']);
    assert.deepStrictEqual(kinds.map(k => k.attrs['data-kind']), ['요구사항정의서', '개발 Spec', '사용자 매뉴얼', 'CTS 관리대장', 'Role 정리', '개발하기']);
    const tiles = find(root, e => (e.attrs['class'] || '').split(' ').includes('tile2'));
    assert.deepStrictEqual(tiles.map(t => t.textContent), ['내 차례0', '일하는 중0', '만든 산출물0']);  // 시안 G-04 는 세 타일 모두 0
    kinds[0].click();
    assert.ok(went[0].includes('요구사항정의서'));
    // 입력창에 적은 글은 새 작업으로 넘어간다
    const input = find(root, e => e.tag === 'input')[0];
    input.value = '구매오더 조회 앱 요구사항 써 줘';
    find(root, e => e.tag === 'form')[0].listeners.submit[0]({ preventDefault() {} });
    assert.strictEqual(went[1], '구매오더 조회 앱 요구사항 써 줘');
    assert.strictEqual(find(root, e => (e.attrs['class'] || '').includes('call')).length, 0);
  },
  plain_action_logic() {
    const lab = id => ({ srs: '요구사항 문서' }[id] || id);
    const P = t => L.plainAction(t, lab);
    assert.strictEqual(P('Skill: harness:srs'), '요구사항 문서 진행 중');
    assert.strictEqual(P('Skill: srs'), '요구사항 문서 진행 중');
    assert.strictEqual(P('Skill: harness:zzz'), 'zzz 진행 중');  // 이름표가 없으면 스킬 id
    assert.strictEqual(P('Bash: git push origin main'), '명령 실행 중');
    for (const t of ['Write', 'Edit: a.md', 'MultiEdit: a', 'NotebookEdit: a']) assert.strictEqual(P(t), '파일 고치는 중');
    for (const t of ['Read: a.md', 'Glob: *.md', 'Grep: x', 'LS: .']) assert.strictEqual(P(t), '파일 살펴보는 중');
    assert.strictEqual(P('Agent: 조사'), '보조에게 맡기는 중');
    assert.strictEqual(P('Task'), '보조에게 맡기는 중');
    assert.strictEqual(P('WebSearch: x'), '웹에서 찾는 중');
    assert.strictEqual(P('mcp__abap-adt__getObjectSource: zcl'), 'SAP 연결 도구 쓰는 중');
    assert.strictEqual(P('mcp__other__tool'), '연결 도구 쓰는 중');
    assert.strictEqual(P('TodoWrite'), '할 일 정리하는 중');
    assert.strictEqual(P('Weird: x'), '작업하는 중');
    assert.strictEqual(P(''), '작업하는 중');
    assert.strictEqual(P(null), '작업하는 중');
    assert.strictEqual(P('Skill'), '작업하는 중');
    assert.ok(!P('Bash: rm -rf secret').includes('secret'));  // 입력 원문은 내지 않는다
    assert.strictEqual(L.plainAction('Skill: harness:srs'), 'srs 진행 중');  // 이름표 함수가 없어도 깨지지 않는다
    // 첫 내 말 풍선: 콘솔이 붙인 스킬 명령 줄만 숨긴다
    assert.strictEqual(L.hideSkillLine('/harness:spec\n구매오더 조회\n\n참고 파일: @docs/ssot/SRS.md'), '구매오더 조회\n\n참고 파일: @docs/ssot/SRS.md');
    assert.strictEqual(L.hideSkillLine('/harness:spec\n\n구매오더'), '구매오더');
    assert.strictEqual(L.hideSkillLine('/other-plugin:do_it\r\n내용'), '내용');
    assert.strictEqual(L.hideSkillLine('/harness:spec'), '/harness:spec');  // 남는 말이 없으면 그대로
    assert.strictEqual(L.hideSkillLine('/harness:spec 이어서 해 줘'), '/harness:spec 이어서 해 줘');  // 줄 전체가 명령일 때만
    assert.strictEqual(L.hideSkillLine('그냥 말\n/harness:spec\n뒤'), '그냥 말\n/harness:spec\n뒤');
    assert.strictEqual(L.hideSkillLine(undefined), '');
  },
  docs_logic() {
    const g = p => L.docGroup({ path: p });
    assert.deepStrictEqual(['docs/SRS.md', 'audit/log.md', 'out/CTS_v0.2.xlsx', 'img/a.png', 'x/매뉴얼.pptx', 'a.pdf'].map(g), ['spec', 'record', 'form', 'etc', 'form', 'form']);
    // 올림 칩의 근거는 커밋 여부와 이 세션의 PR 상태뿐이다. 근거가 없으면 확인 못 함이다.
    const merged = { number: 6, state: 'MERGED' }, open = { number: 6, state: 'OPEN' };
    assert.strictEqual(L.docChip({ changed: true }, { flowPr: merged }, false).text, '안 올림');
    assert.strictEqual(L.docChip({ changed: true }, { flowPr: merged }, false).tone, 'warn');  // 시안 G-11·G-14: 안 올림은 노랑
    assert.strictEqual(L.docChip({ changed: false, upload: { state: 'local' } }, {}, false).tone, 'warn');
    assert.strictEqual(L.docChip({ changed: false, upload: { state: 'committed' } }, {}, false).tone, 'warn');
    assert.strictEqual(L.docChip({ changed: false }, { flowPr: open }, false).text, '검토 중');
    assert.strictEqual(L.docChip({ changed: false }, { flowPr: merged }, false).text, '합쳐짐');
    assert.deepStrictEqual([L.docChip({ changed: false }, {}, false).text, L.docChip({ changed: false }, {}, false).tone], ['확인 못 함', 'unk']);
    assert.strictEqual(L.docChip({ changed: false }, { flowPr: merged }, true).text, '확인 못 함');  // git 을 못 읽었으면 PR 상태가 있어도 단정하지 않는다
    // 서버가 파일마다 판정한 upload 가 있으면 PR 상태 짐작 대신 그것을 쓴다(#652)
    const up = (state, extra) => L.docChip({ changed: false, upload: Object.assign({ state }, extra) }, { flowPr: merged }, false);
    assert.deepStrictEqual([up('local').text, up('committed').text, up('merged').text, up('review', { prs: [{ number: 5 }, { number: 8 }] }).text, up('unknown').text],
      ['안 올림', '안 올림', '합쳐짐', '검토 중', '확인 못 함']);
    assert.ok(up('review', { prs: [{ number: 5 }, { number: 8 }] }).title.includes('#5, #8') && !up('merged').title.includes('세션'));
    assert.ok(up('committed').title.includes('열린 PR 이 없어') && up('local').title.includes('커밋 안 됨'));
    assert.strictEqual(up('unknown', { reason: 'gh 실패' }).title, 'gh 실패');
    assert.strictEqual(L.docChip({ changed: false, upload: { state: 'committed' } }, {}, true).text, '안 올림');  // 서버 판정이 있으면 세션 쪽 짐작은 쓰지 않는다
    // 같은 폴더(경로 표기만 다른)의 같은 파일은 한 번만, 먼저 준 세션 쪽
    const a = { id: 'a', cwd: 'C:/w/p' }, b = { id: 'b', cwd: 'c:\\w\\p\\' };
    const out = L.mergeDocs([{ session: a, files: [{ path: 'docs/SRS.md', mtime: 5, changed: true }] }, { session: b, files: [{ path: 'docs/srs.md', mtime: 9 }, { path: 'x.xlsx', mtime: 1 }] }]);
    assert.deepStrictEqual(out.map(d => [d.session.id, d.group]), [['a', 'spec'], ['b', 'form']]);
    assert.ok(L.isFormOutput({ path: 'a.xlsx' }) && L.isFormOutput({ path: 'a.pptx' }) && !L.isFormOutput({ path: 'a.pdf' }) && !L.isFormOutput({ path: 'a.md' }));
    // 이번 주 산출물(시안 G-11): 최근 7일 안에 바뀐 문서만 센다. 시각은 초·밀리초 둘 다
    const now = 1000000000, day = 86400;
    const docs = [{ file: { mtime: now - day } }, { file: { mtime: (now - 2 * day) * 1000 } }, { file: { mtime: now - 8 * day } }, { file: {} }];
    assert.strictEqual(L.weekDocCount(docs, now), 2);
    const ss = [{ id: 'old', updatedAt: now - 9 * day }, { id: 'new', updatedAt: now - 60 }, { id: 'mid', updatedAt: now - 3 * day }, { id: 'gone', updatedAt: now, handedOffTo: 'x' }];
    assert.deepStrictEqual(L.weekPool(ss, now, 20).map(s => s.id), ['new', 'mid']);
    assert.deepStrictEqual(L.weekPool(ss, now, 1).map(s => s.id), ['new']);
  },
  async dom_docs_attach() {
    // 첨부(#998): 이름·크기만 보이고 열기·내려받기·미리보기가 없다. 빼기·넣기는 서버에 보내고, 답으로 다시 그린다.
    const s1 = { id: 's1', title: '계약 세션', cwd: '/w/p', updatedAt: 9, canSend: true };
    const att = [{ id: 'a1', name: '화면.png', type: 'image/png', size: 2048, listed: true }, { id: 'a2', name: '계약서.pdf', type: 'application/pdf', size: 1000, listed: false }];
    const files = { files: [{ path: 'docs/SRS_v0.1.md', kind: 'md', size: 100, mtime: 20, changed: true, versions: [] }], attachments: att };
    const { kit, calls } = makeKit({ 'GET /api/sessions/s1/files': files, 'GET /api/sessions/s1/files/preview': { kind: 'md', text: '# SRS' },
      'POST /api/sessions/s1/attachments/pick': b => { att.forEach(a => { if (a.id === b.id) a.listed = b.listed; }); return { attachments: att.map(a => Object.assign({}, a)) }; } }, [s1]);
    window.BHMarkdown = { render: t => h('div', { text: t }) };
    const root = h('div');
    const view = loadUI(kit).docsPage(root); for (let i = 0; i < 6; i++) await tick();
    const rows = () => find(root, e => e.attrs['data-attach']);
    assert.deepStrictEqual(rows().map(e => e.attrs['data-attach']), ['a1', 'a2']);  // 뺀 것은 '뺀 첨부' 접힘 안에
    assert.ok(root.textContent.includes('첨부한 파일') && root.textContent.includes('화면.png') && root.textContent.includes('2048B') && root.textContent.includes('뺀 첨부 1개'));
    const first = rows()[0];
    assert.ok(!first.textContent.includes('열기') && find(first, e => e.tag === 'a').length === 0);  // 열 수 없다
    assert.deepStrictEqual(find(first, e => e.tag === 'button').map(e => e.textContent), ['빼기']);
    assert.ok(root.textContent.includes('열 수 없어'));
    find(first, e => e.tag === 'button')[0].click(); await tick(); await tick();
    assert.ok(calls.some(c => c[0] === 'POST' && c[1] === '/api/sessions/s1/attachments/pick' && c[2].id === 'a1' && c[2].listed === false));
    assert.ok(root.textContent.includes('뺀 첨부 2개'));
    find(rows().filter(e => e.attrs['data-attach'] === 'a2')[0], e => e.tag === 'button')[0].click(); await tick(); await tick();
    assert.ok(calls.some(c => c[2] && c[2].id === 'a2' && c[2].listed === true) && root.textContent.includes('뺀 첨부 1개'));
    view.destroy();
    process.exit(0);
  },
  async dom_docs_panel_forms_only() {
    // #1037: 세션 오른쪽 "만든 산출물" 에는 양식 파일(xlsx·pptx·docx)만 보인다. md·그 밖의 파일은 목록에서 빠진다.
    const s1 = { id: 's1', title: '세션', cwd: '/w/p', updatedAt: 9, canSend: true, status: 'idle' };
    window.BHMarkdown = { render: t => h('div', { text: t }) };
    async function run(files) {
      const { kit, calls } = makeKit({ 'GET /api/sessions/s1/files': { files }, 'GET /api/sessions/s1/files/preview': { kind: 'table', sheets: [{ name: 'Backlog', rows: [['ID'], ['R1']] }] } }, [s1]);
      const panel = loadUI(kit).docsPanel(() => {});
      panel.update(s1); for (let i = 0; i < 6; i++) await tick();
      return { panel, calls, rows: find(panel.el, e => (e.attrs['class'] || '').includes('drow')).map(e => e.attrs['data-path']) };
    }
    // md 만 있는 세션: 목록에 md 가 없고 안내만, 미리보기 요청도 없다
    const a = await run([{ path: 'docs/status/1037-x.md', kind: 'md', size: 9, mtime: 5, changed: true }, { path: 'notes.txt', kind: 'txt', size: 1, mtime: 4 }]);
    assert.deepStrictEqual(a.rows, []);
    assert.ok(a.panel.el.textContent.includes('아직 양식으로 뽑은 산출물이 없어'));
    assert.ok(!a.panel.el.textContent.includes('1037-x.md') && !a.calls.some(c => /preview/.test(c[1])));
    assert.strictEqual(a.panel.has(), false);  // Sauce 는 이 칸을 두지 않고, Post 는 산출물 탭에 같은 안내(noDocs)를 보인다
    // 양식 파일이 있는 세션: 그 파일만 보이고 가장 최근 양식 파일이 미리보기로 열린다(md 가 더 최근이어도)
    const b = await run([{ path: 'docs/status/1037-x.md', kind: 'md', size: 9, mtime: 50, changed: true }, { path: 'out/BW_Backlog List_v0.1.xlsx', kind: 'xlsx', size: 18000, mtime: 30, changed: true },
      { path: 'out/old.pptx', kind: 'pptx', size: 5, mtime: 10 }, { path: 'out/note.pdf', kind: 'pdf', size: 5, mtime: 60 }]);
    assert.deepStrictEqual(b.rows, ['out/BW_Backlog List_v0.1.xlsx', 'out/old.pptx']);
    assert.ok(b.calls.some(c => c[0] === 'GET' && c[1].startsWith('/api/sessions/s1/files/preview') && decodeURIComponent(c[1]).includes('BW_Backlog List_v0.1.xlsx')));
    assert.ok(!b.panel.el.textContent.includes('1037-x.md') && !b.panel.el.textContent.includes('아직 양식으로'));
    assert.strictEqual(b.panel.has(), true);
    // Windows 경로 표기(\)여도 확장자·폴더 판정이 같다
    assert.ok(L.isFormOutput({ path: 'out\\BW_Backlog List_v0.1.xlsx' }) && L.isFormOutput({ path: 'C:\\w\\p\\a.DOCX' }) && !L.isFormOutput({ path: 'docs\\status\\a.md' }) && !L.isFormOutput({ path: 'audit\\a.xlsx' }));
    process.exit(0);
  },
  async dom_home_recent_forms_only() {
    // #1067: 홈 "최근 산출물" 목록과 "이번 주 산출물" 숫자도 양식 파일(xlsx·pptx·docx)만 센다. 없으면 탭과 같은 안내
    const now = Math.floor(Date.now() / 1000);
    const s1 = { id: 's1', title: '세션', cwd: '/w/p', updatedAt: now, canSend: true };
    async function run(files) {
      const { kit } = makeKit({ 'GET /api/sessions/s1/files': { files } }, [s1]);
      const box = h('div'); let week = 'none';
      loadUI(kit).homeKit.recentCard(box, n => { week = n; });
      for (let i = 0; i < 6; i++) await tick();
      return { text: box.textContent, rows: find(box, e => e.attrs['data-doc']).map(e => e.attrs['data-doc']), week };
    }
    const a = await run([{ path: 'docs/SRS_v0.1.md', kind: 'md', size: 9, mtime: now - 5 }, { path: 'out/a.pdf', kind: 'pdf', size: 1, mtime: now - 4 }]);
    assert.deepStrictEqual(a.rows, []); assert.strictEqual(a.week, 0);
    assert.ok(a.text.includes('아직 양식으로 뽑은 산출물이 없어.') && !a.text.includes('SRS_v0.1'));
    const b = await run([{ path: 'docs/SRS_v0.1.md', kind: 'md', size: 9, mtime: now - 1 }, { path: 'out/BW_Backlog_v0.1.xlsx', kind: 'xlsx', size: 9, mtime: now - 3 }, { path: 'out/m.pptx', kind: 'pptx', size: 9, mtime: now - 2 }]);
    assert.deepStrictEqual(b.rows, ['out/m.pptx', 'out/BW_Backlog_v0.1.xlsx']); assert.strictEqual(b.week, 2);
    process.exit(0);
  },
  async dom_docs_page_forms_only_empty() {
    // #1067: 산출물 탭에 md·작업 파일만 있으면 목록은 비고 안내만 보인다(양식 파일이 하나도 없을 때)
    const s1 = { id: 's1', title: '세션', cwd: '/w/p', updatedAt: 9, canSend: true };
    const { kit, calls } = makeKit({ 'GET /api/sessions/s1/files': { files: [{ path: 'docs/SRS_v0.1.md', kind: 'md', size: 9, mtime: 5, changed: true }, { path: 'notes.txt', kind: 'txt', size: 1, mtime: 4 }] } }, [s1]);
    window.BHMarkdown = { render: t => h('div', { text: t }) };
    const root = h('div');
    const view = loadUI(kit).docsPage(root); for (let i = 0; i < 5; i++) await tick();
    assert.ok(root.textContent.includes('아직 양식으로 뽑은 산출물이 없어.'));
    assert.ok(!root.textContent.includes('SRS_v0.1') && !root.textContent.includes('notes.txt') && find(root, e => (e.attrs['class'] || '').includes('drow')).length === 0);
    assert.ok(!calls.some(c => /preview/.test(c[1])));
    view.destroy();
    process.exit(0);
  },
  async dom_docs_page() {
    const s1 = { id: 's1', title: 'SRS 세션', cwd: '/w/p', updatedAt: 9, canSend: true, flowPr: { number: 6, state: 'OPEN' } };
    const files = { files: [
      { path: 'docs/SRS_v0.2.md', kind: 'md', size: 100, mtime: 20, changed: false, versions: ['docs/SRS_v0.1.md', 'docs/SRS_v0.2.md'] },
      { path: 'out/BW_Backlog_v0.1.xlsx', kind: 'xlsx', size: 18000, mtime: 30, changed: true, versions: ['out/BW_Backlog_v0.0.xlsx', 'out/BW_Backlog_v0.1.xlsx'] },
      { path: 'audit/log.md', kind: 'md', size: 5, mtime: 10, changed: true }, { path: 'out/note.pdf', kind: 'pdf', size: 5, mtime: 40 },
      { path: 'out/매뉴얼_v0.1.pptx', kind: 'pptx', size: 7, mtime: 8, changed: false }] };
    const table = { kind: 'table', sheets: [{ name: 'Backlog', rows: [['ID', 'Title', 'Source'], ['R1', 'a', ''], ['R2', 'b', 'x']] }] };
    const { kit, calls } = makeKit({ 'GET /api/sessions/s1/files': files,
      'GET /api/sessions/s1/files/preview': (b, url) => (/xlsx/.test(url) ? table : { kind: 'md', text: '# SRS\n\n버전: 0.2\n\n본문' }),
      'POST /api/sessions/s1/messages': { ok: true }, 'POST /api/sessions/s1/files/open': { ok: true } }, [s1]);
    window.BHMarkdown = { render: t => h('div', { text: t }) };
    const root = h('div');
    const view = loadUI(kit).docsPage(root); for (let i = 0; i < 5; i++) await tick();
    const btn = txt => find(root, e => e.tag === 'button' && e.textContent === txt)[0];
    const sentTo = () => calls.filter(c => c[0] === 'POST' && c[1] === '/api/sessions/s1/messages');
    // 가장 최근 산출물이 고객 양식 xlsx 이면 목록 없이 결과 화면(시안 G-15): 제목 · 원본 → 양식 · 칸 수 · 넓은 미리보기 · 빈 칸 안내
    for (const need of ['산출물 · 고객 양식', '고객 양식으로 뽑았어', '요구사항정의서 v0.1 → 고객사 Backlog 양식(xlsx)', 'BW_Backlog_v0.1.xlsx', '18000B', '양식 칸 6개 중 5개 채움',
      '미리보기 · Backlog 시트', '비어 있는 칸 1개', 'Source 칸이 비어 있어', '폴더에서 보기', '내려받기', '문서 목록 보기']) assert.ok(root.textContent.includes(need), need);
    assert.ok(!root.textContent.includes('내가 만든 문서') && find(root, e => (e.attrs['class'] || '').includes('dlist')).length === 0);
    assert.strictEqual(find(root, e => (e.attrs['class'] || '') === 'sheet-tabs').length, 0);  // 시트가 하나면 시트 탭은 없다
    assert.deepStrictEqual(find(root, e => e.tag === 'th').map(e => e.textContent), ['ID', 'Title', 'Source']);
    const dl = find(root, e => e.tag === 'a' && e.textContent === '내려받기')[0];
    assert.ok(dl.attrs.href.startsWith('/api/sessions/s1/files/download?path=') && dl.attrs.href.includes('BW_Backlog_v0.1.xlsx') && dl.attrs.download === 'BW_Backlog_v0.1.xlsx');
    btn('폴더에서 보기').click(); await tick(); await tick();
    assert.ok(calls.some(c => c[1] === '/api/sessions/s1/files/open' && c[2].mode === 'reveal' && c[2].path === 'out/BW_Backlog_v0.1.xlsx'));
    // 빈 칸을 알려 주고 다시 뽑아 달라고 하면 이 세션에 말을 보낸다
    const inp = find(root, e => e.attrs.id === 'doc-ask')[0];
    assert.strictEqual(inp.attrs.placeholder, '예: 출처는 구매팀 김OO, 10/28 회의야');
    inp.listeners.input[0]({ target: { value: '출처는 구매팀' } });
    btn('보내기').click(); await tick(); await tick();
    assert.ok(sentTo().length === 1 && sentTo()[0][2].text.includes('out/BW_Backlog_v0.1.xlsx') && sentTo()[0][2].text.includes('비어 있는 칸') && sentTo()[0][2].text.includes('출처는 구매팀'));
    // '문서 목록 보기' → 목록에는 양식 파일(xlsx·pptx·docx)만. md·기록 폴더 파일·pdf 는 없다(#1067)
    btn('문서 목록 보기').click(); for (let i = 0; i < 4; i++) await tick();
    for (const need of ['내가 만든 문서', '고객 양식', 'BW_Backlog', 'v0.1 · xlsx', '매뉴얼', '검토 중', '안 올림', '이전 판 1개', '안 올림 = 내 PC에만 · 검토 중 = 승인 기다림 · 합쳐짐 = 팀 공용본']) assert.ok(root.textContent.includes(need), need);
    for (const no of ['요구사항 · 설계', '기록', 'SRS', 'log.md', 'note.pdf', '고객 양식으로 뽑았어', '확인 못 함 = 알 수 없음']) assert.ok(!root.textContent.includes(no), no);
    assert.deepStrictEqual(find(root, e => (e.attrs['class'] || '').includes('drow') && !(e.attrs['class'] || '').includes('sub')).map(e => e.attrs['data-path']).sort(), ['out/BW_Backlog_v0.1.xlsx', 'out/매뉴얼_v0.1.pptx']);
    assert.ok(!btn('xlsx로 뽑기') && !btn('열기'));
    // 목록에서 xlsx 를 고르면 고객 양식 결과 카드(뽑기 버튼 없음), 목록은 그대로
    find(root, e => e.attrs['data-path'] === 'out/BW_Backlog_v0.1.xlsx')[0].click(); await tick(); await tick();
    const card = find(root, e => e.attrs['data-form-card'])[0];
    assert.ok(card && card.textContent.includes('BW_Backlog_v0.1.xlsx') && card.textContent.includes('18000B') && card.textContent.includes('양식 칸 6개 중 5개 채움') && card.textContent.includes('내려받기'));
    assert.ok(find(root, e => (e.attrs['class'] || '').includes('dlist')).length === 1 && !btn('xlsx로 뽑기'));
    view.destroy();
    process.exit(0);
  },
  docs_form_logic() {
    // 양식 칸 세기: 첫 줄이 칸 이름, 아래 내용 있는 줄 x 칸 이름 수. 비어 있는 칸은 이름으로 모은다. 못 읽었거나 잘렸으면 세지 않는다.
    const t = rows => ({ kind: 'table', sheets: [{ name: 'S', rows }] });
    assert.deepStrictEqual(L.formCells(t([['ID', 'T'], ['1', 'a'], ['2', 'b']])), { known: true, total: 4, filled: 4, empty: 0, blankNames: [] });
    assert.deepStrictEqual(L.formCells(t([['ID', 'T', 'Src'], ['1', 'a'], [], ['2', '', ' ']])), { known: true, total: 6, filled: 3, empty: 3, blankNames: ['Src', 'T'] });
    assert.strictEqual(L.formCells(t([['ID', 'T']])).known, false);  // 내용 줄이 없으면 칸 수를 말하지 않는다
    assert.strictEqual(L.formCells({ kind: 'table', sheets: [{ name: 'S', rows: [['a'], ['b']], truncated: true }] }).known, false);
    assert.strictEqual(L.formCells({ kind: 'table', sheets: [{ name: 'S', rows: [], error: 'x' }] }).known, false);
    assert.strictEqual(L.formCells({ kind: 'md', text: '' }).known, false);
    assert.strictEqual(L.formCells(null).known, false);
    assert.strictEqual(L.formCells({ kind: 'table', sheets: [] }).known, false);
    // 이름·원본·부제
    assert.deepStrictEqual(L.docLabel('docs/ssot/SRS.md'), { name: '요구사항정의서', ver: '', ext: 'md', base: 'SRS.md' });
    assert.deepStrictEqual(L.docLabel('CTS 관리대장_v0.2.xlsx'), { name: 'CTS 관리대장', ver: '0.2', ext: 'xlsx', base: 'CTS 관리대장_v0.2.xlsx' });
    assert.strictEqual(L.formSubtitle('x/BW_Backlog List_v0.1.xlsx'), '요구사항정의서 v0.1 → 고객사 Backlog 양식(xlsx)');
    assert.strictEqual(L.formSubtitle('개발사양서_v0.3.xlsx'), '개발 Spec v0.3 → 고객사 개발사양서 양식(xlsx)');
    assert.strictEqual(L.formSubtitle('모르는 양식_v0.1.xlsx'), '고객사 모르는 양식 양식(xlsx) v0.1');  // 원본을 모르면 지어내지 않는다
    // 가장 최근 산출물이 xlsx 양식일 때만 결과 화면
    const d = (path, group) => ({ key: path, file: { path }, group });
    assert.strictEqual(L.latestFormXlsx([d('a.xlsx', 'form'), d('s.md', 'spec')]).key, 'a.xlsx');
    assert.strictEqual(L.latestFormXlsx([d('s.md', 'spec'), d('a.xlsx', 'form')]), null);
    assert.strictEqual(L.latestFormXlsx([d('a.pptx', 'form')]), null);
    assert.strictEqual(L.latestFormXlsx([]), null);
  },
  async dom_start_checks_and_blocked_cards() {
    const { kit } = makeKit({}, []);
    const ui = loadUI(kit);
    const p = ui.startChecksPanel();
    p.update({ id: 's1', canSend: true, startChecks: [{ id: 'sync', state: 'done' }, { id: 'version', state: 'pending' }] });
    assert.ok(!p.el.hidden && p.el.attrs['class'] === 'q startchecks');
    assert.deepStrictEqual(find(p.el, e => e.attrs['data-check']).map(e => e.attrs['data-check'] + ':' + e.attrs['class']), ['sync:crow ok', 'version:crow todo']);
    assert.ok(p.el.textContent.includes('시작 점검 · 자동') && p.el.textContent.includes('최신 내용 받기') && p.el.textContent.includes('됐어'));
    assert.strictEqual(find(p.el, e => e.tag === 'button').length, 0);  // 스스로 하는 줄이라 버튼이 없다(잘못됐을 때만 다시 하기)
    p.update({ id: 's1', canSend: true, startChecks: [{ id: 'sync', state: 'done' }, { id: 'version', state: 'fail' }] });
    assert.deepStrictEqual(find(p.el, e => e.tag === 'button').map(b => b.textContent), ['다시 하기']);
    p.update({ id: 's1', canSend: true, startChecks: [{ id: 'sync', state: 'unknown', reason: '원격이 없어' }, { id: 'version', state: 'fail', reason: '더 새 판이 있어(0.10.9)' }] });
    assert.deepStrictEqual(find(p.el, e => e.attrs['data-check']).map(e => e.attrs['data-check'] + ':' + e.attrs['class']), ['sync:crow unk', 'version:crow fail']);
    assert.ok(p.el.textContent.includes('확인 못 함') && p.el.textContent.includes('원격이 없어') && p.el.textContent.includes('다시 필요') && p.el.textContent.includes('더 새 판이 있어(0.10.9)'));
    p.update({ id: 's1', startChecks: [] }); assert.ok(p.el.hidden);
    p.destroy();
    // 검사 실패는 ✕ 막힘, 결과를 못 읽으면 ? 확인 못 함, 통과·진행 중에는 둘 다 없다
    const card = checks => ui.prCard({ flowPr: { number: 6, state: 'OPEN', title: 't', checks } });
    const fail = card('fail'), unk = card('none');
    assert.ok(fail.attrs['class'].includes('blocked') && fail.textContent.includes('✕ 막힘') && !fail.textContent.includes('? 확인 못 함'));
    assert.ok(unk.attrs['class'].includes('unsure') && unk.textContent.includes('? 확인 못 함') && unk.textContent.includes('통과도 실패도 아니야'));
    for (const c of ['pass', 'pending']) { const ok = card(c); assert.ok(!/blocked|unsure/.test(ok.attrs['class']) && !ok.textContent.includes('✕ 막힘') && !ok.textContent.includes('? 확인 못 함'), c); }
  },
  api_notice_words_and_times() {
    const A = require(path.join(dir, 'api-notice.js'));
    const now = new Date(2026, 10, 10, 9, 0).getTime(), sec = ms => Math.floor(ms / 1000);
    const at = new Date(2026, 10, 10, 15, 5).getTime(), later = new Date(2026, 10, 12, 8, 30).getTime();
    assert.strictEqual(A.clockText(sec(at), now), '오늘 15:05');
    assert.strictEqual(A.clockText(sec(later), now), '11월 12일 08:30');
    assert.strictEqual(A.clockText(null, now), '');
    const idle = { status: 'idle' };
    let n = A.notice(Object.assign({ apiIssue: { kind: 'auth', status: 401, error: 'authentication_failed', raw: 'Invalid API key · Fix external API key' } }, idle), now);
    assert.strictEqual(n.kind, 'auth'); assert.strictEqual(n.sideTone, 'err');
    assert.ok(n.title.includes('로그인이 풀렸어') && n.body.includes('/login') && n.side.includes('로그인'));
    assert.ok(n.raw.includes('Invalid API key') && n.raw.includes('상태 401'));
    n = A.notice(Object.assign({ apiIssue: { kind: 'model', status: 404 } }, idle), now);
    assert.ok(n.title.includes('모델') && n.sideTone === 'err');
    n = A.notice(Object.assign({ apiIssue: { kind: 'other', status: 500, raw: 'boom' } }, idle), now);
    assert.ok(n.title.includes('오류') && n.raw.includes('boom'));
    // 모르는 종류·빈 원문도 성공으로 치지 않는다
    for (const k of ['unknown', 'weird']) {
      n = A.notice(Object.assign({ apiIssue: { kind: k } }, idle), now);
      assert.strictEqual(n.kind, 'unknown'); assert.ok(n.title.includes('알 수 없는 오류') && n.raw === '(원문 없음)' && n.sideTone === 'err');
    }
    // 재시도: 일하는 중에만, n/max 와 다음 시도 초
    const retry = { kind: 'retry', attempt: 3, max: 10, delayMs: 2060 };
    n = A.notice({ status: 'running', apiIssue: retry }, now);
    assert.ok(n.title.includes('다시 시도하는 중 3/10') && n.body.includes('3초 뒤') && n.sideTone === '');
    assert.strictEqual(A.notice({ status: 'idle', apiIssue: retry }, now), null);
    // 한도: 걸리면 풀리는 시각(현지), 경고면 미리 알림, 지난 시각이면 없음
    n = A.notice({ status: 'idle', rateLimit: { status: 'rejected', type: 'five_hour', resetsAt: sec(at) } }, now);
    assert.ok(n.kind === 'limit' && n.body.includes('오늘 15:05') && n.side.includes('오늘 15:05') && n.sideTone === 'err');
    n = A.notice({ status: 'idle', apiIssue: { kind: 'limit', status: 429 } }, now);
    assert.ok(n.kind === 'limit' && n.body.includes('확인 못 했어'));
    n = A.notice({ status: 'running', rateLimit: { status: 'allowed_warning', type: 'seven_day', utilization: 0.99, resetsAt: sec(later) } }, now);
    assert.ok(n.kind === 'limit_warn' && n.tone === 'warn' && n.body.includes('7일 사용량이 99%') && n.body.includes('11월 12일 08:30') && n.side === '');
    assert.strictEqual(A.notice({ status: 'idle', rateLimit: { status: 'allowed_warning', resetsAt: sec(now) - 60 } }, now), null);
    n = A.notice({ status: 'idle', rateLimit: { status: 'mystery' } }, now);
    assert.ok(n.kind === 'limit_unknown' && n.body.includes('mystery'));
    assert.strictEqual(A.notice({ status: 'idle' }, now), null);
  },
  notice_logic_bubble_dismiss_verbs_and_limits() {
    const N = require(path.join(dir, 'notice-logic.js'));
    const items = [{ id: 'req:a' }, { id: 'blk:s:blocked:1' }, { id: 'api:s:1' }];
    assert.strictEqual(N.pickBubble(items, {}).id, 'req:a');  // 급한 순서(목록 순서) 첫 건
    assert.strictEqual(N.pickBubble(items, { 'req:a': true }).id, 'blk:s:blocked:1');  // 닫은 건 건너뛴다
    assert.strictEqual(N.pickBubble(items, { 'req:a': true, 'blk:s:blocked:1': true, 'api:s:1': true }), null);
    assert.strictEqual(N.pickBubble([], {}), null);
    // 더는 없는 알림의 닫은 표시는 잊어 같은 일이 다시 생기면 다시 뜨고, 화면 따라 있다 없다 하는 알림(ver·merged)은 지우지 않는다
    assert.deepStrictEqual(N.pruneDismissed({ 'req:a': true, 'req:gone': true, 'ver:1': true, 'merged:s': true }, items), { 'req:a': true, 'ver:1': true, 'merged:s': true });
    // 승인 단추 말: 기본 / 지우기 / 올리기 (승인 화면과 같다)
    assert.deepStrictEqual(N.permVerbs({ toolInput: { command: 'touch a' } }), ['이번만 허락', '하지 마']);
    assert.deepStrictEqual(N.permVerbs({ risk: 'irreversible', toolInput: { command: 'rm -rf x' } }), ['이번만 지워', '지우지 마']);
    assert.deepStrictEqual(N.permVerbs({ risk: 'irreversible', toolInput: { command: 'git push origin main' } }), ['이번만 올려', '올리지 마']);
    assert.strictEqual(N.canAllowSession({ risk: 'irreversible' }), false);
    assert.strictEqual(N.canAllowSession({ permissionSuggestions: [] }), false);
    assert.strictEqual(N.canAllowSession({ toolInput: {} }), true);
    assert.strictEqual(N.isInstantQuestion([{ question: 'q', options: [{ label: 'a' }] }]), true);
    assert.strictEqual(N.isInstantQuestion([{ question: 'q', multiSelect: true, options: [{ label: 'a' }] }]), false);
    assert.strictEqual(N.isInstantQuestion([{ question: 'q', options: [{ label: 'a' }] }, { question: 'r', options: [{ label: 'b' }] }]), false);
    // 한도: 값이 없으면 "알 수 없음" — 0% 로 꾸미지 않는다
    const now = new Date(2026, 10, 10, 9, 0).getTime(), sec = ms => Math.floor(ms / 1000);
    const at = sec(new Date(2026, 10, 10, 15, 5).getTime()), later = sec(new Date(2026, 10, 12, 8, 30).getTime());
    let v = N.limitView([], now, false);
    assert.ok(v.unknown && v.text === '한도 알 수 없어' && !v.text.includes('%') && v.title.includes('0% 라는 뜻이 아니야'));
    assert.ok(N.limitView(undefined, now, true).title.includes('읽지 못했어'));
    // 값이 있으면 종류별로: 쓴 비율 · 풀리는 시각, 경고·참은 모양(⚠ ✕)이 붙는다
    v = N.limitView([{ type: 'five_hour', status: 'allowed', utilization: 0.42, resetsAt: at, t: sec(now) - 60 },
      { type: 'seven_day', status: 'allowed_warning', utilization: 0.91, resetsAt: later, t: sec(now) - 3600 }], now);
    assert.ok(!v.unknown && v.chips.length === 2);
    assert.strictEqual(v.chips[0].text, '5시간 42% · 15:05'); assert.strictEqual(v.chips[0].tone, ''); assert.strictEqual(v.chips[0].stale, false);
    assert.strictEqual(v.chips[1].text, '⚠ 주간 91% · 11월 12일 08:30'); assert.strictEqual(v.chips[1].tone, 'warn');
    assert.ok(v.chips[1].stale && v.chips[1].title.includes('오래된 값') && v.chips[0].title.includes('08:59 에 받은 값'));
    v = N.limitView([{ type: 'five_hour', status: 'rejected', utilization: 1, resetsAt: at, t: sec(now) }], now);
    assert.ok(v.chips[0].tone === 'err' && v.chips[0].text.startsWith('✕ ') && v.chips[0].title.includes('한도가 찼어'));
    // 쓴 비율을 안 알려 준 값은 ? — 퍼센트를 지어내지 않는다
    v = N.limitView([{ type: 'five_hour', status: 'allowed', utilization: null, resetsAt: at, t: sec(now) }], now);
    assert.strictEqual(v.chips[0].text, '5시간 ? · 15:05'); assert.ok(v.chips[0].title.includes('알려 주지 않았어') && !/\d%/.test(v.text));
    v = N.limitView([{ type: 'five_hour', status: 'mystery', utilization: 0.1, resetsAt: at, t: sec(now) }], now);
    assert.ok(v.chips[0].tone === 'unk' && v.chips[0].title.includes('상태를 몰라(mystery)'));
    // 풀릴 시각이 지난 값은 지금 쓴 비율이 아니라서 버린다(그것뿐이면 알 수 없음)
    assert.ok(N.limitView([{ type: 'five_hour', status: 'allowed', utilization: 0.9, resetsAt: sec(now) - 60, t: sec(now) - 7200 }], now).unknown);
    // 단위 방어: 0~1 은 비율, 1 초과 100 이하는 이미 퍼센트, 그 밖(음수·100 초과·숫자 아님)은 ?
    const one = u => N.limitView([{ type: 'five_hour', status: 'allowed', utilization: u, resetsAt: at, t: sec(now) }], now).chips[0].text;
    assert.strictEqual(one(0), '5시간 0% · 15:05'); assert.strictEqual(one(1), '5시간 100% · 15:05'); assert.strictEqual(one(42), '5시간 42% · 15:05'); assert.strictEqual(one(100), '5시간 100% · 15:05');
    for (const bad of [-0.1, 100.5, 250, 'x', true, NaN, Infinity]) assert.strictEqual(one(bad), '5시간 ? · 15:05', String(bad));
    // 빈 status 는 managed.py 처럼 allowed
    v = N.limitView([{ type: 'five_hour', status: '', utilization: 0.5, resetsAt: at, t: sec(now) }], now);
    assert.ok(v.chips[0].tone === '' && v.chips[0].title.includes('여유 있어') && v.chips[0].text === '5시간 50% · 15:05');
    // 닫은 알림 표시가 100개를 넘으면 최근 것을 남긴다(저장 때 slice(-100) 과 같다)
    const many = {}; for (let i = 0; i < 120; i++) many['ver:' + i] = true;
    const kept = Object.keys(N.pruneDismissed(many, []));
    assert.strictEqual(kept.length, 100); assert.strictEqual(kept[0], 'ver:20'); assert.strictEqual(kept[99], 'ver:119');
    // 팝업에서 다 보여 줄 수 있는 승인만 빠른 허락 단추를 둔다
    assert.strictEqual(N.fitsPopup({ toolName: 'Bash', toolInput: { command: 'touch a' } }), true);
    assert.strictEqual(N.fitsPopup({ toolName: 'Bash', toolInput: { command: 'x'.repeat(600) } }), true);
    for (const r of [{ toolName: 'Bash', toolInput: { command: 'x'.repeat(601) } }, { toolName: 'Bash', toolInput: { command: 'a', dangerouslyDisableSandbox: true } },
      { toolName: 'Bash', toolInput: { command: 'a', run_in_background: true } }, { toolName: 'Write', toolInput: { file_path: 'a', content: 'b' } }, { toolName: 'Edit', toolInput: { file_path: 'a' } },
      { toolName: 'ExitPlanMode', toolInput: { plan: 'p' } }, { toolName: 'Bash', mcp: { server: 's' }, toolInput: { command: 'a' } }, { toolName: 'Bash', toolInput: {} }, null]) {
      assert.strictEqual(N.fitsPopup(r), false, JSON.stringify(r));
    }
  },
  notify_events_compare_previous_and_next() {
    const on = { turn: true, blocked: true, done: true }, off = { turn: false, blocked: false, done: false };
    const base = { id: 's1', title: '구매오더', group: 'idle', pendingRequestIds: [], lastBlock: null };
    const ev = (prev, next, cfg, opts) => L.notifyEvents(prev, next, cfg || on, Object.assign({ visible: false, name: '구매오더', reqKind: r => (r === 'q1' ? 'question' : 'permission') }, opts));
    assert.deepStrictEqual(ev(undefined, Object.assign({}, base, { group: 'todo' })), []);  // 비교 기준이 없으면(첫 목록) 무알림
    // todo 로 새로 들어옴 / 새 요청(질문·승인) — 각각 한 번, 끈 스위치와 보이는 탭은 무알림
    let e = ev(base, Object.assign({}, base, { group: 'todo' }));
    assert.strictEqual(e.length, 1); assert.strictEqual(e[0].kind, 'turn'); assert.strictEqual(e[0].title, '내 차례야 · 구매오더');
    assert.strictEqual(e[0].body, '다음 단계'); assert.strictEqual(e[0].path, '/s/s1');
    e = ev(base, Object.assign({}, base, { group: 'todo', pendingRequestIds: ['q1'] }));
    assert.strictEqual(e.length, 1); assert.strictEqual(e[0].body, '질문'); assert.strictEqual(e[0].path, '/r/q1'); assert.ok(e[0].tag.includes('s1') && e[0].tag.includes('q1'));
    e = ev(Object.assign({}, base, { group: 'todo', pendingRequestIds: ['q1'] }), Object.assign({}, base, { group: 'todo', pendingRequestIds: ['q1', 'a2'] }));
    assert.strictEqual(e.length, 1); assert.strictEqual(e[0].body, '승인'); assert.strictEqual(e[0].path, '/r/a2');
    assert.deepStrictEqual(ev(Object.assign({}, base, { group: 'todo' }), Object.assign({}, base, { group: 'todo' })), []);  // 그대로면 다시 보내지 않는다
    assert.deepStrictEqual(ev(base, Object.assign({}, base, { group: 'todo' }), off), []);
    assert.deepStrictEqual(ev(base, Object.assign({}, base, { group: 'todo' }), on, { visible: true }), []);
    // 새 block: 시각이 직전보다 새로울 때만. cannot_check 는 다른 제목
    const b1 = Object.assign({}, base, { lastBlock: { t: 10, kind: 'blocked' } });
    e = ev(base, b1); assert.strictEqual(e.length, 1); assert.strictEqual(e[0].title, '막혔어 · 구매오더'); assert.strictEqual(e[0].path, '/s/s1');
    assert.deepStrictEqual(ev(b1, Object.assign({}, b1)), []);
    e = ev(b1, Object.assign({}, base, { lastBlock: { t: 11, kind: 'cannot_check' } })); assert.strictEqual(e[0].title, '확인 못 함 · 구매오더');
    assert.deepStrictEqual(ev(base, b1, { turn: true, blocked: false, done: true }), []);
    // running -> idle 은 끝남 한 번. running -> todo 는 내 차례가 대신 나가 겹치지 않는다
    const run = Object.assign({}, base, { group: 'running' });
    e = ev(run, base); assert.strictEqual(e.length, 1); assert.strictEqual(e[0].title, 'AI가 끝냈어 · 구매오더');
    e = ev(run, Object.assign({}, base, { group: 'todo' })); assert.deepStrictEqual(e.map(x => x.kind), ['turn']);
    e = ev(run, Object.assign({}, base, { group: 'todo' }), { turn: false, blocked: false, done: true }); assert.deepStrictEqual(e.map(x => x.kind), ['done']);
    assert.deepStrictEqual(ev(base, run), []);  // 시작은 알리지 않는다
  },
  attach_textarea_keys() {
    // 이어서 요청 칸: 여러 줄 textarea. Enter 보내기, Shift+Enter 줄바꿈, 한글 조합 중 Enter 는 안 보냄, 자동완성 목록이 열려 있으면 안 보냄
    delete require.cache[require.resolve(path.join(dir, 'attach.js'))];
    const A = require(path.join(dir, 'attach.js'));
    let sent = 0, blocked = false, typed = null;
    const c = A.composer(h, { id: 'follow', placeholder: '예', onInput: v => { typed = v; }, onSend: () => { sent++; }, isBlocked: () => blocked });
    assert.strictEqual(c.field.tag, 'textarea'); assert.strictEqual(c.field.attrs.id, 'follow'); assert.strictEqual(c.field.attrs.rows, '1');
    assert.ok(c.field.className.includes('comp-in'));  // 한 줄 칸과 같은 글꼴·자리를 쓰는 클래스
    const key = (o) => { let prevented = false; (c.field.listeners.keydown || []).forEach(f => f(Object.assign({ key: 'Enter', keyCode: 13, preventDefault() { prevented = true; } }, o))); return prevented; };
    assert.strictEqual(key({}), true); assert.strictEqual(sent, 1);
    assert.strictEqual(key({ shiftKey: true }), false); assert.strictEqual(sent, 1);          // 줄바꿈은 브라우저가 한다
    assert.strictEqual(key({ isComposing: true }), false); assert.strictEqual(key({ keyCode: 229 }), false); assert.strictEqual(sent, 1);
    assert.strictEqual(key({ key: 'a' }), false); assert.strictEqual(sent, 1);
    blocked = true; assert.strictEqual(key({}), false); assert.strictEqual(sent, 1); blocked = false;
    (c.field.listeners.input || []).forEach(f => f({ target: { value: '한 줄\n두 줄' } })); assert.strictEqual(typed, '한 줄\n두 줄');
    assert.ok(A.enterSends({ key: 'Enter' }) && !A.enterSends({ key: 'Enter', shiftKey: true }) && !A.enterSends({ key: 'Enter', isComposing: true }));
  },
  attach_plain_option_for_new_task_field() {
    // 새 작업 입력칸(#1038): 같은 composer 를 쓰되 Enter 는 줄바꿈(보내지 않음)이고 높이는 바깥 CSS 가 정한다. 칸 모양은 cls·rows 로 고른다.
    delete require.cache[require.resolve(path.join(dir, 'attach.js'))];
    const A = require(path.join(dir, 'attach.js'));
    window.FileReader = function () { this.readAsDataURL = (f) => { this.result = 'data:' + f.type + ';base64,QUJD'; setTimeout(() => this.onload(), 0); }; };
    let sent = 0, typed = null;
    const c = A.composer(h, { id: 'brief', cls: 'textarea', rows: '3', plain: true, placeholder: '', onInput: v => { typed = v; }, onSend() { sent++; } });
    assert.strictEqual(c.field.attrs.id, 'brief'); assert.strictEqual(c.field.attrs.rows, '3'); assert.ok(c.field.className.includes('textarea') && !c.field.className.includes('comp-in'));
    let prevented = false;
    (c.field.listeners.keydown || []).forEach(f => f({ key: 'Enter', keyCode: 13, preventDefault() { prevented = true; } }));
    assert.strictEqual(prevented, false); assert.strictEqual(sent, 0);
    assert.ok(!c.field.style || !c.field.style.height);  // 높이를 자동으로 바꾸지 않는다
    (c.field.listeners.input || []).forEach(f => f({ target: { value: '한 줄\n두 줄' } })); assert.strictEqual(typed, '한 줄\n두 줄');
    // 다시 그릴 때 첨부·글·안내가 새 칸으로 이어진다(keep/restore)
    c.add([{ name: '화면.png', type: 'image/png', size: 10 }, { name: 'a.docx', type: 'application/x', size: 10 }]);
    const kept = c.keep(), note = c.keptNote();
    assert.ok(note.includes('a.docx'));
    const d = A.composer(h, { id: 'brief', cls: 'textarea', rows: '3', plain: true, placeholder: '' });
    d.restore(kept, '이어진 글', note);
    assert.strictEqual(d.field.value, '이어진 글'); assert.strictEqual(d.count(), 1); assert.ok(d.chips.hidden === false);
    return tick().then(() => { assert.deepStrictEqual(d.payload().map(a => a.name), ['화면.png']); assert.ok(!d.busy()); });  // 읽던 첨부는 같은 객체에 채워진다
  },
  attach_chips_limits_and_remove() {
    delete require.cache[require.resolve(path.join(dir, 'attach.js'))];
    const A = require(path.join(dir, 'attach.js'));
    window.FileReader = function () { this.readAsDataURL = (f) => { this.result = 'data:' + f.type + ';base64,QUJD'; setTimeout(() => this.onload(), 0); }; };
    const c = A.composer(h, { id: 'f', placeholder: '', onSend() {} });
    const chips = () => find(c.chips, e => e.className === 'attach-chip');
    const note = () => find(c.chips, e => e.className === 'attach-note').map(e => e.textContent).join('|');
    const png = (n, size) => ({ name: n, type: 'image/png', size: size || 1000 }), pdf = (n, size) => ({ name: n, type: 'application/pdf', size: size || 1000 });
    assert.strictEqual(c.chips.hidden, true);
    c.add([png('화면.png'), pdf('계약서.pdf')]);
    assert.strictEqual(chips().length, 2); assert.strictEqual(c.chips.hidden, false); assert.ok(c.busy());
    return tick().then(() => {
      assert.ok(!c.busy());
      assert.deepStrictEqual(c.payload().map(a => [a.name, a.media_type, a.data]), [['화면.png', 'image/png', 'QUJD'], ['계약서.pdf', 'application/pdf', 'QUJD']]);
      assert.ok(find(c.chips, e => e.tag === 'img' && e.attrs.src.startsWith('data:image/png')).length === 1);  // 이미지는 작은 그림
      assert.ok(chips()[1].textContent.includes('계약서.pdf') && chips()[1].textContent.includes('PDF'));      // PDF 는 이름
      // 형식 밖·큰 것·빈 것은 조용히 버리지 않고 한 줄로 알린다
      c.add([{ name: 'a.docx', type: 'application/vnd.openxmlformats', size: 10 }]);
      assert.ok(note().includes('a.docx') && note().includes('PDF')); assert.strictEqual(chips().length, 2);
      c.add([png('big.png', 6 * 1024 * 1024)]); assert.ok(note().includes('5MB')); assert.strictEqual(chips().length, 2);
      c.add([pdf('big.pdf', 21 * 1024 * 1024)]); assert.ok(note().includes('20MB'));
      c.add([png('a.png'), png('b.png'), png('c.png'), png('d.png')]);  // 2 + 3 = 5개까지, 하나는 개수 초과
      assert.strictEqual(chips().length, 5); assert.ok(note().includes('5개'));
      // 빼기(×)
      const x = find(chips()[0], e => e.tag === 'button')[0]; assert.ok(x.attrs['aria-label'].includes('화면.png'));
      x.click(); assert.strictEqual(chips().length, 4); assert.ok(!c.meta().some(m => m.name === '화면.png'));
      // 서버 대화 기록의 첨부(이름·형식·크기)는 빼기 없이 보인다
      const row = A.chatChips(h, [{ name: '화면.png', type: 'image/png', size: 2048 }, { name: '계약서.pdf', type: 'application/pdf', size: 1 }]);
      assert.strictEqual(find(row, e => e.tag === 'button').length, 0); assert.ok(row.textContent.includes('계약서.pdf'));
      assert.strictEqual(A.chatChips(h, []), null);
      // 터미널에서 연 세션은 단추를 감추고 붙이지 않는다
      c.setEnabled(false); assert.strictEqual(c.pick.hidden, true); assert.strictEqual(chips().length, 0);
      c.add([png('x.png')]); assert.strictEqual(chips().length, 0); assert.ok(note().includes('터미널'));
      c.reset(); assert.strictEqual(c.field.value, '');
    });
  },
  attach_paste_drop_and_file_button() {
    delete require.cache[require.resolve(path.join(dir, 'attach.js'))];
    const A = require(path.join(dir, 'attach.js'));
    window.FileReader = function () { this.readAsDataURL = (f) => { this.result = 'data:' + f.type + ';base64,QUJD'; setTimeout(() => this.onload(), 0); }; };
    const c = A.composer(h, { id: 'f', placeholder: '', onSend() {} });
    const fire = (el, name, ev) => { let prevented = false; (el.listeners[name] || []).forEach(f => f(Object.assign({ preventDefault() { prevented = true; } }, ev))); return prevented; };
    const file = (n, t) => ({ name: n, type: t, size: 500 });
    // 글 붙여 넣기는 그대로 두고, 파일이 든 붙여 넣기만 가로챈다
    assert.strictEqual(fire(c.field, 'paste', { clipboardData: { files: [], items: [] } }), false); assert.strictEqual(c.count(), 0);
    assert.strictEqual(fire(c.field, 'paste', { clipboardData: { files: [file('붙인.png', 'image/png')] } }), true); assert.strictEqual(c.count(), 1);
    // 끌어 놓기
    const zone = h('div'); c.bindDrop(zone);
    assert.strictEqual(fire(zone, 'drop', { dataTransfer: { files: [] } }), false);
    assert.strictEqual(fire(zone, 'drop', { dataTransfer: { files: [file('a.pdf', 'application/pdf')] } }), true); assert.strictEqual(c.count(), 2);
    assert.strictEqual(fire(zone, 'dragover', { dataTransfer: { types: ['Files'] } }), true);
    // 파일 고르기 단추: 숨은 input 을 누르고, 고른 파일을 붙인다
    const btn = find(c.pick, e => e.tag === 'button')[0], input = find(c.pick, e => e.tag === 'input')[0];
    assert.strictEqual(input.attrs.type, 'file'); assert.ok(input.attrs.accept.includes('application/pdf') && input.attrs.accept.includes('image/webp'));
    let clicked = 0; input.listeners.click = [() => { clicked++; }]; btn.click(); assert.strictEqual(clicked, 1);
    fire(input, 'change', { target: { files: [file('b.webp', 'image/webp')], value: 'x' } }); assert.strictEqual(c.count(), 3);
    assert.strictEqual(A.typeOf({ name: 'scan.PDF', type: '' }), 'application/pdf');  // 형식이 비어 오면 확장자로
    return tick();
  }
};

(async () => {
  const name = process.argv[3];
  assert.ok(cases[name], '없는 시험 ' + name);
  await cases[name]();
  process.exit(0);  // 홈의 1분 타이머(setInterval)가 node 를 붙잡아 두지 않게
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

CASES = re.findall(r"^  (?:async )?(\w+)\(\) \{", _RUNNER[_RUNNER.index("const cases = {"):], flags=re.M)


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    path = tmp_path_factory.mktemp("ui") / "run_ui.js"
    path.write_text(_RUNNER, encoding="utf-8")
    return path


@pytest.mark.skipif(not NODE, reason="node 없음")
@pytest.mark.parametrize("case", CASES)
def test_ui_logic_and_dom(runner, case):
    out = subprocess.run([NODE, str(runner), str(STATIC), case], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr


def test_all_cases_found():
    assert len(CASES) >= 14, CASES


@pytest.mark.skipif(not NODE, reason="node 없음")
@pytest.mark.parametrize("js", JS_FILES, ids=lambda p: p.name)
def test_node_check_every_static_js(js):
    out = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr


def test_index_loads_modules_before_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = [html.index(f'src="/{n}"') for n in ("md.js", "flow-logic.js", "flow-ui.js", "app.js")]
    assert order == sorted(order)


def test_static_js_rules():
    for js in JS_FILES:
        text = js.read_text(encoding="utf-8")
        assert "innerHTML" not in text.replace("innerHTML 을", "") or js.name == "md.js", js.name
        assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", text), f"빈 catch: {js.name}"
        assert not re.search(r"\.then\(\s*null\s*,\s*function\s*\([^)]*\)\s*\{\s*\}\s*\)", text), f"빈 오류 처리: {js.name}"


def test_session_screen_has_no_skill_button_row_and_keeps_slash_assist():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "skillBar" not in app and "skill-bar" not in css
    assert "withAssist(" in app and "skillItems" in app  # / 자동완성은 그대로


_THEME_NODE = r"""
const [file, seed] = process.argv.slice(1);
const store = seed ? JSON.parse(seed) : {};
global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
const style = {};
global.window = {};
const dataset = {}, events = [], attrs = {};
global.CustomEvent = function (n, o) { this.type = n; this.detail = o && o.detail; };
global.document = { documentElement: { style, dataset, setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: k => { delete attrs[k]; } }, dispatchEvent: e => events.push(e.detail) };
require(file);
const BH = window.BH;
const attrsInit = Object.assign({}, attrs), prefsInit = [BH.getFx(), BH.getMode(), BH.modeOf()];
const out = { first: BH.getScale(), zoom: style.zoom, keys: Object.keys(BH).sort().join(','), theme0: [BH.getTheme(), dataset.theme] };
BH.setScale('1.15');
out.afterSet = [BH.getScale(), store['bh-zoom'], style.zoom];
BH.setScale('nonsense');
out.afterBad = [BH.getScale(), style.zoom];
BH.setTheme('post');
out.themePost = [BH.getTheme(), store['bh-theme'], dataset.theme];
BH.setTheme('nonsense');
out.themeBad = [BH.getTheme(), store['bh-theme'], dataset.theme];
out.themeIds = BH.THEMES.map(x => x.id).join(',');
out.events = events.join(',');
// Post 전용 설정: 효과 강도(bh-fx) · 밝기(bh-mode). html[data-fx]·[data-mode] 는 Post 일 때만 걸린다.
out.attrs0 = attrsInit;
out.prefs0 = prefsInit;
BH.setFx('2'); BH.setFx('9');
out.fx = [BH.getFx(), store['bh-fx'], attrs['data-fx']];
BH.setMode('dark'); BH.setMode('zzz');
out.mode = [BH.getMode(), store['bh-mode'], attrs['data-mode'], BH.modeOf()];
BH.setMode('auto');
out.modeAuto = [BH.getMode(), attrs['data-mode'], BH.modeOf()];
BH.setTheme('sauce');
out.attrsSauce = Object.assign({}, attrs);
BH.setTheme('post');
out.attrsBack = Object.assign({}, attrs);
out.events2 = events.slice(2).join(',');
process.stdout.write(JSON.stringify(out));
"""


def _theme_run(seed: dict | None = None) -> dict:
    import json
    out = subprocess.run([NODE, "-e", _THEME_NODE, str(STATIC / "theme.js"), json.dumps(seed or {})], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_theme_js_only_keeps_text_scale():
    r = _theme_run()
    assert r["first"] == "1" and r["zoom"] == "1"  # 시안(가)대로 보통 = 배율 없음(#721)
    assert r["keys"] == "FX,MODES,SCALES,THEMES,getFx,getMode,getScale,getTheme,modeOf,read,setFx,setMode,setScale,setTheme,write"  # 글자 크기 + 테마(#1013). 옛 디자인 전환은 없다
    assert r["afterSet"] == ["1.15", "1.15", "1.15"]
    assert r["afterBad"] == ["1.15", "1.15"]  # 모르는 값은 저장도 적용도 하지 않는다(바로 앞 값 유지)
    assert _theme_run({"bh-zoom": "0.9"})["zoom"] == "0.9"
    assert _theme_run({"bh-zoom": "zzz"})["first"] == "1"
    assert _theme_run({"bh-scale": "1.15"})["first"] == "1"  # 옛 키(보통이 1.15 였다)는 읽지 않는다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_theme_js_saves_and_applies_theme():
    # 테마 저장·적용(#1013): 기본 sauce, 모르는 값은 sauce, 바뀌면 이벤트
    r = _theme_run()
    assert r["theme0"] == ["sauce", "sauce"]  # 기본은 Sauce, 첫 페인트 전에 html[data-theme] 으로 걸린다
    assert r["themeIds"] == "sauce,post"
    assert r["themePost"] == ["post", "post", "post"]
    assert r["themeBad"] == ["post", "post", "post"]  # 모르는 값은 저장도 적용도 하지 않는다
    assert r["events"] == "sauce,post"  # 바뀔 때 bh-theme 이벤트(장면이 새로 고침 없이 붙고 떨어진다)
    assert _theme_run({"bh-theme": "post"})["theme0"] == ["post", "post"]
    assert _theme_run({"bh-theme": "zzz"})["theme0"] == ["sauce", "sauce"]  # 모르는 저장값은 Sauce


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_theme_js_saves_post_fx_and_mode():
    # Post 전용 설정(D단계): 효과 강도 0·1·2(기본 1) · 밝기 auto·light·dark(기본 auto = 테마 기본 = 밝게). Sauce 에는 data 속성이 걸리지 않는다.
    r = _theme_run()
    assert r["attrs0"] == {}  # 기본 테마는 Sauce 라서 data-fx·data-mode 가 없다
    assert r["prefs0"] == ["1", "auto", "light"]
    assert r["fx"] == ["2", "2", "2"]  # 고르면 저장하고 바로 건다(모르는 '9' 는 저장도 적용도 하지 않는다)
    assert r["mode"] == ["dark", "dark", "dark", "dark"]
    assert r["modeAuto"] == ["auto", "light", "light"]  # 테마 기본 = Post 의 기본 밝기(밝게). 운영체제 설정은 따르지 않는다
    assert r["attrsSauce"] == {}  # Sauce 로 바꾸면 속성을 뗀다
    assert r["attrsBack"] == {"data-fx": "2", "data-mode": "light"}  # 다시 Post 면 저장된 값으로
    assert r["events2"] == "fx,mode,mode,sauce,post"  # 바뀔 때 bh-pref(fx·mode) 이벤트 — 장면과 오늘 화면이 새로 고침 없이 반영
    post = _theme_run({"bh-theme": "post", "bh-fx": "0", "bh-mode": "dark"})
    assert post["attrs0"] == {"data-fx": "0", "data-mode": "dark"}  # 첫 페인트 전에 건다
    assert post["prefs0"] == ["0", "dark", "dark"]
    bad = _theme_run({"bh-theme": "post", "bh-fx": "9", "bh-mode": "zzz"})
    assert bad["attrs0"] == {"data-fx": "1", "data-mode": "light"}  # 모르는 저장값은 기본


def test_post_fx_and_dark_rules_are_post_only():
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    assert css.count(':root[data-theme="post"][data-mode="dark"] {') == 1  # 어두운 값은 이 한 블록
    assert ':root[data-theme="post"][data-fx="0"]' in css  # 차분(움직임 0)
    scene = (STATIC / "theme-post.js").read_text(encoding="utf-8")
    assert "window-b.svg" in scene and "calm()" in scene and "bh-pref" in scene  # 화려 = 창문 구름, 차분 = 장면 없음, 설정이 바뀌면 다시
    settings = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "themeNow === 'post'" in settings and "BH.setFx" in settings and "BH.setMode" in settings


def test_post_theme_css_stays_under_data_theme_post():
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    body = re.sub(r"@keyframes\s+[\w-]+\s*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", body)  # 키프레임 이름은 post 전용(po-*)이라 통째로 뺀다
    assert all(k.startswith("po-") for k in re.findall(r"@keyframes\s+([\w-]+)", css))
    for sel in re.findall(r"([^{}]+)\{", body):
        if sel.strip().startswith("@"):  # @media·@container 는 안의 규칙이 따로 검사된다
            continue
        for part in sel.split(","):
            assert part.strip().startswith(':root[data-theme="post"]'), part.strip()  # Sauce 에는 한 줄도 닿지 않는다
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/theme.js"') < html.index("</head>") and 'src="/theme.js"' in html.split("</head>")[0]  # 첫 페인트 전 동기 로드
    assert 'href="/theme-post.css"' in html and 'src="/theme-post.js"' in html


def test_post_home_uses_office_scene():
    # 오늘 화면 장면은 사무실(#1033): index 가 싣고, sceneList 가 flow·t 를 주고, 팀 요약이 창구 요약 줄을 대신하며, 차분이면 목록이 남는다
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/post/office/office-post.js"') < html.index('src="/theme-post.js"') < html.index('src="/app.js"')
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "flow: s.flowId || ''" in app and "t: s.updatedAt" in app
    assert "window.BHOfficeScene" in app and "attachScene(sceneHost)" in app
    assert "officeList" not in app and "list: sceneList" in app  # 제목을 이스케이프하지 않고 그대로 준다(장면이 textContent 로 쓴다)
    bundle = (STATIC / "post" / "office" / "office-post.js").read_text(encoding="utf-8")
    assert "innerHTML" not in bundle and "outerHTML" not in bundle and "insertAdjacentHTML" not in bundle  # 제목의 <b>·& 가 글자 그대로 보인다
    scene = (STATIC / "theme-post.js").read_text(encoding="utf-8")
    assert "function attach(host, opts, office)" in scene and "office.attach(host, opts)" in scene and "calm()" in scene
    home = (STATIC / "post-home.js").read_text(encoding="utf-8")
    for team in ("요구분석팀", "설계팀", "개발팀", "기능컨설팅팀", "표준화팀", "유지보수팀"):
        assert team in home
    assert "paintTeams()" in home and "paintCalm()" in home and "po-maplist" in home
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    assert ".po-stage.is-office" in css and "aspect-ratio" in css


def test_office_bundle_supports_pip():
    # 사무실 장면 번들이 작은 창(Document PiP)을 지원한다(#1036). 번들은 innerHTML 계열을 쓰지 않고, 테마를 바꾸면 theme-post.js 가 PiP 를 닫는다
    bundle = (STATIC / "post" / "office" / "office-post.js").read_text(encoding="utf-8")
    assert "documentPictureInPicture" in bundle and "작은 창으로 보기" in bundle and "여기로 돌려놓기" in bundle
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function"):
        assert bad not in bundle
    scene = (STATIC / "theme-post.js").read_text(encoding="utf-8")
    assert "documentPictureInPicture" in scene and "closePip(); return drop()" in scene


def test_post_home_field_memo_layout():
    # Post 오늘 화면 장면 칸(#1056, 시안 C): 사무실 장면이 틀 안에 폭 전체로 보이고 그 위에 내 차례 메모가 뜬다. 나머지(덱·숫자 칸·표·범례·팀 줄·띠·배지)는 그대로
    home = (STATIC / "post-home.js").read_text(encoding="utf-8")
    for needle in ("po-memo", "po-stagew", "paintMemo()", "text: '다음'", "세션으로", "cardAct(it, false)", "cardAct(it, true)"):
        assert needle in home
    # 메모 자리: 번들의 onFocus 좌표를 받고, 보여 주는 항목이 바뀌면 scene.focus(id). 옛 번들(focus 없음)도 동작
    assert "onFocus: onFocus" in home and "typeof sc.focus === 'function'" in home and "sc.focus(id)" in home
    assert "matchMedia(NARROW)" in home and "(max-width: 760px)" in home
    # 장면 칸 밖은 그대로: 덱·숫자 카드 줄·Sauce 와 같은 홈 표·범례·팀 요약 줄
    for keep in ("paintDeck()", "tiles2 po-tiles", "po-legend", "po-teams", "네 답을 기다리는 일이 "):
        assert keep in home
    # 내 세션(#1065): Post 는 두 단 목록, 위쪽 띠·strip 은 없다. Sauce 표는 그대로
    for need in ("sessionsPanel(list)", "po-mine", "po-kyul", "po-stc", "po-ava", "L.barSteps(s)", "L.stepShort(", "'정해진 갈래 없음'", "'내 세션 ' + list.length + '개'"):
        assert need in home
    assert "appendChild(HK.homeTable(" not in home and "po-strip" not in home and "표로 보기" not in home
    for chip in ("내 차례", "일하는 중", "승인 기다림", "쉬는 중", "끝남", "확인 못 함", "막힘"):
        assert f"'{chip}'" in home
    flow_ui = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    assert "function homeTable(list)" in flow_ui and "['작업', '단계', '번호', '기억', '상태']" in flow_ui  # Sauce 홈 표
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function attachScene(host, extra)" in app and "Object.assign({ list: sceneList" in app and "onFocus: function (f)" in app
    assert "scene: function () { return postScene; }" in app
    assert "prail-badge" in app and "prail-dot" not in app and "nb-chip" not in app  # 위쪽 띠(말풍선)와 레일 숫자 배지는 그대로
    scene = (STATIC / "theme-post.js").read_text(encoding="utf-8")
    assert "office.attach(host, opts)" in scene and "typeof o.focus === 'function'" in scene and "focus: function (id)" in scene
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    for needle in (".po-memo", ".po-memo.is-flip::before", ".po-stagew.is-office", "@media (max-width: 760px)", ".po-tiles .tile2", ".po-legend", ".po-teams"):
        assert needle in css
    for need in (".po-kyul", ".po-kyulc", ".po-stc-blocked", "ul.po-mine", "columns: 2", "columns: 1", ".po-memo.is-loose::before", ".po-stagew:has(.bh-office-away) .po-memo"):
        assert need in css  # 두 단·1100px 이하 한 단·결재란 자리·꼬리 없는 메모·작은 창(PiP) 중 메모 숨김
    for gone in (".po-strip", ".nb-chip", ".prail-dot"):
        assert gone not in css
    for line in css.splitlines():
        if line.startswith(":root[data-theme=\"post\"] .po-memo"):
            assert not any(f"font-size: {n}px" in line for n in range(23, 100))  # 글자 22px 이하


def test_post_home_memo_follows_scene_bundle():
    # 메모가 사람 옆에 안 붙던 원인(#1065): 갈래 없는 세션은 리셉션 한 자리뿐이라 메모 세션이 안 그려졌다. 번들이 focus(id) 한 세션을 먼저 앉히고 다시 그린다
    bundle = (STATIC / "post" / "office" / "office-post.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "eval(", "new Function", "import("):
        assert bad not in bundle
    assert "wantId" in bundle and "bh-office-away" in bundle  # 작은 창(PiP) 중 메모 숨김은 이 줄을 CSS :has() 로 본다
    home = (STATIC / "post-home.js").read_text(encoding="utf-8")
    assert "is-loose" in home and "foc.id !== memoId" in home


def test_main_scroller_is_containing_block_for_sr_only():
    # 문서가 안쪽 .main 스크롤 칸보다 더 내려가던 문제: .sr-only 는 absolute 1px 이라 .main 이 위치 기준이 아니면 스크롤 칸 밖(문서)으로 빠져 문서 스크롤 높이를 늘린다
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".sr-only { position: absolute;" in css
    main_rule = [ln for ln in css.splitlines() if ln.startswith(".main { overflow-y: auto") or ln.startswith(".main { position: relative; overflow-y: auto")]
    assert main_rule and main_rule[0].startswith(".main { position: relative; overflow-y: auto")


_POST_LOGIC_NODE = r"""
const path = require('path');
const dir = process.argv[1];
const L = require(path.join(dir, 'flow-logic.js'));
const P = require(path.join(dir, 'post-logic.js'));
const mk = o => Object.assign({ id: 's', status: 'idle' }, o);
const out = {};
out.who = P.WHO.join(',');
out.p = ['a', 'fake-f0906301', 'fake-2c31bdc7', ''].map(P.personOf);
out.same = P.personOf('fake-f0906301') === P.personOf('fake-f0906301');
const ids = Array.from({ length: 200 }, (_, i) => 'sess-' + i);
out.spread = new Set(ids.map(P.personOf)).size;
out.states = [
  mk({ pendingRequestIds: ['r1'] }), mk({ status: 'running' }), mk({ lastBlock: { kind: 'blocked', open: true } }), mk({ lastBlock: { kind: 'cannot_check', open: true } }),
  mk({ flowPr: { number: 3, state: 'OPEN', checks: 'pass' } }), mk({ flowPr: { number: 3, state: 'MERGED' } }), mk({ status: 'ended' }), mk({}),
  mk({ status: 'running', pendingRequestIds: ['r1'] }), mk({ flowPr: { number: 3, state: 'OPEN', checks: 'fail' } }),
  mk({ status: 'ended', flowPr: { number: 3, state: 'OPEN', checks: 'pass' } }), mk({ status: 'ended', flowPr: { number: 3, state: 'CLOSED' } })
].map(s => P.stateOf(s, L));
const st = (flowId, name, extra) => mk(Object.assign({ flowId, flowSteps: [{ id: 'x', name }], stepIndex: 0 }, extra));
out.stations = [
  mk({}), st('srs', 'SRS 쓰기'), st('srs-export', '백로그 엑셀 뽑기'), st('spec', 'Spec 쓰기'), st('dev', '구현'), st('fix', '고치기'), st('config', '설정'), st('standard', '표준'),
  st('srs', '올리고 검토 요청하기', { flowPr: { number: 3, state: 'OPEN' } }), st('dev', '합쳐지기 기다리기', { flowPr: { number: 3, state: 'OPEN' } }),
  st('srs', '올리고 검토 요청하기'), st('spec', 'Spec 쓰기', { flowPr: { number: 3, state: 'MERGED' } }), st('dev', '구현', { flowFinished: true }), mk({ phase: 'approval' }), st('mystery', 'x')
].map(s => P.stationOf(s, L));
out.poses = P.STATES.map(P.poseOf).join(',');
out.tones = P.STATES.map(P.toneOf).join(',');
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_post_logic_person_state_station():
    r = subprocess.run([NODE, "-e", _POST_LOGIC_NODE, str(STATIC)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["who"] == "mint,navy,rose,sunny,sky,sage,kid"
    assert out["same"] and out["spread"] == 7  # 세션 id 해시: 같은 id 는 늘 같은 사람, 여럿이면 일곱 명이 고루 나온다
    assert all(x in out["who"].split(",") for x in out["p"])
    # 가이드 6.3 의 해시(h = h*31 + 문자코드, 부호 없는 32비트)와 같은 값: 'a' = 97 % 7 = 6 → kid
    assert out["p"][0] == "kid" and out["p"][3] == "mint"
    # 6.2: 내 차례 > 막힘 > 확인 못 함 > 일하는 중 > 승인 기다림 > 끝 > 쉬는 중. 일하는 중인 세션은 대기 요청이 있어도 내 차례다(groupOf 가 먼저).
    assert out["states"] == ["turn", "run", "blocked", "unk", "wait", "done", "done", "idle", "turn", "turn", "done", "done"]
    # 끝난 세션은 PR 이 열려 있어도 끝남이다 — 승인 기다림(일하는 중 칸)에 넣지 않는다(#1059)
    assert out["states"][10] == "done" and out["states"][4] == "wait"
    # 6.1: 합쳐짐 4 · 검토 3 · 개발 2 · 설계 1 · 쓰기 0 · 갈래 없음 2
    assert out["stations"] == [2, 0, 0, 1, 2, 2, 2, 2, 3, 3, 0, 4, 4, 3, 2]
    assert out["poses"] == "ask,stuck,stuck,walk,wait,done,walk" and out["tones"] == "turn,blocked,,,,done,"  # 세션·요청 화면 규칙은 아래 test_post_session_logic_filters_info_and_seals


_POST_SESSION_NODE = r"""
const path = require('path');
const P = require(path.join(process.argv[1], 'post-logic.js'));
const out = {};
out.filters = P.FILTERS.map(f => f.id).join(',');
const states = ['turn', 'blocked', 'unk', 'run', 'wait', 'idle', 'done', 'turn'];
out.counts = P.filterCounts(states);
out.match = P.FILTERS.map(f => states.map(s => P.filterMatch(f.id, s) ? 1 : 0).join(''));
out.status = ['✕ 막힘 · 고친 뒤 이어서', '? 확인 못 함 · 검사를 못 했어', '내 차례 · 승인하기', '', null].map(P.statusText);
out.here = [0, 3, 4, 9, -2].map(P.hereTitle);
out.lines = P.STATES.map(P.hereLine);
const cell = (id, value, tone) => ({ id, label: id === 'progress' ? 'AI 진행' : id, value, tone: tone || '' });
out.info = P.infoRow([cell('step', '1 / 3 쓰기', 'g'), cell('req', 'REQ-007'), cell('pr', 'PR #301', 'w'), cell('progress', '40%')], 'SRS 쓰기').map(c => [c.label, c.value, c.tone]);
out.infoEmpty = P.infoRow([], '').map(c => c.value).join('|');
out.insp = P.INSP.join(',');
out.seal = ['allow', 'allow_session', 'deny', 'answer', 'accept', 'decline', 'cancel', 'nothing'].map(d => P.sealOf(d).text + ':' + P.sealOf(d).tone);
out.sub = P.sealSub(new Date(2026, 10, 7), '검토 창구');
out.desk = [['permission', 1], ['plan', 1], ['question', 1], ['elicitation', 4]].map(a => P.sealDesk(a[0], a[1]));
out.clerk = [P.clerkLine('permission', 0), P.clerkLine('plan', 0), P.clerkLine('question', 0), P.clerkLine('elicitation', 2)];
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_post_session_logic_filters_info_and_seals():
    r = subprocess.run([NODE, "-e", _POST_SESSION_NODE, str(STATIC)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # 걸러보기: 내 차례 = 내 답 · 막힘 · 확인 못 함, 일하는 중 = 일하는 중 · 승인 기다림, 쉬는 중은 전체에만
    assert out["filters"] == "all,turn,run,done"
    assert out["counts"] == {"all": 8, "turn": 4, "run": 2, "done": 1}
    assert out["match"] == ["11111111", "11100001", "00011000", "00000010"]
    assert out["status"] == ["막힘 · 고친 뒤 이어서", "확인 못 함 · 검사를 못 했어", "내 차례 · 승인하기", "", ""]
    assert out["here"] == ["1번 창구 · 쓰기 책상", "4번 창구 · 검토 창구", "5번 창구 · 발송 우체통", "5번 창구 · 발송 우체통", "1번 창구 · 쓰기 책상"]
    # 가이드 2.4 둘째 줄(반말). STATES 순서: turn blocked unk run wait done idle
    assert out["lines"] == ["편지를 들고 네 답을 기다려", "창구에서 막혀 있어", "검사를 못 해서 멈췄어", "다음 창구로 걸어가", "의자에 앉아 승인을 기다려", "편지를 다 부쳤어", "창구 앞에서 쉬고 있어"]
    # 정보 줄은 늘 다섯 칸(없으면 –) 뒤에 숫자 띠의 나머지 칸(AI 진행 따위)
    assert out["info"][:5] == [["단계", "SRS 쓰기", "g"], ["요구사항", "REQ-007", ""], ["개발 번호", "–", ""], ["작업 기록", "–", ""], ["검토 요청", "PR #301", "w"]]
    assert out["info"][5] == ["AI 진행", "40%", ""] and len(out["info"]) == 6
    assert out["infoEmpty"] == "–|–|–|–|–" and out["insp"] == "산출물,검사,기억,기록,기술"
    # 도장: 승인 주 버튼 보냄 · 질문 답 접수 · 거절·아니오·닫기 반송
    assert out["seal"] == ["보냄:ok", "보냄:ok", "반송:no", "접수:ok", "접수:ok", "반송:no", "반송:no", "접수:ok"]
    assert out["sub"] == "11.07 · 검토 창구"
    assert out["desk"] == ["검토 창구", "검토 창구", "설계 창구", "발송 우체통"]
    assert out["clerk"] == ["검토 창구 직원이 네 도장을 기다려. 누르면 도장이 찍혀"] * 2 + ["1번 창구 앞에서 손님이 편지를 흔들며 네 답을 기다려", "3번 창구 앞에서 손님이 편지를 흔들며 네 답을 기다려"]


def test_post_session_ui_wiring():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = [html.index(f'src="/{n}"') for n in ("post-logic.js", "theme-post.js", "post-session.js", "post-home.js", "app.js")]
    assert order == sorted(order)
    js = (STATIC / "post-session.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "'role', 'status'" in js and "PL.sealOf" in js
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # 도장은 처리 API 가 성공한 뒤(.then)에만 찍는다 — 실패 쪽에서는 markStamp 를 부르지 않는다
    for call in ("markStamp(rid, 'question', 'answer'", "markStamp(rid, isPlan(req) ? 'plan' : 'permission', d)", "markStamp(rid, 'elicitation', action"):
        i = app.index(call)
        assert ".then(function" in app[max(0, i - 400):i], call
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    seal = re.search(r"\.po-seal \{[^}]*\}", css).group(0)
    assert "width: 108px" in seal and "height: 108px" in seal and "border: 4px double" in seal and "rotate(-14deg)" in seal and ".38s" in seal
    assert "font-size: 22px" in re.search(r"\.po-seal b \{[^}]*\}", css).group(0)
    assert "scale(2.4)" in css and "prefers-reduced-motion" in css
    assert "width: 112px" in css  # 좁은 화면 창구 안내판


def test_post_outputs_tab_lists_each_file_once():
    # #1037: 산출물 탭은 양식 파일 목록(docs 칸)과 빈 안내만 둔다. "바뀐 파일" 목록(regions.files)은 기술 탭에만 있다.
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "sec('만든 산출물', [regions.side, regions.noDocs])" in app
    assert "sec('기술 정보', [regions.files, regions.tech, regions.perm, regions.tools])" in app
    assert "regions.files" not in re.search(r"sec\('만든 산출물'[^\n]*", app).group(0).split("//")[0]
    ui = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    assert ".filter(L.isFormOutput)" in ui and "아직 양식으로 뽑은 산출물이 없어" in ui
    # #1067: 산출물 탭(/docs, docsPage)도 같은 함수로 거르고 빈 안내가 같다
    assert "files: kit.listOf(d, 'files').filter(L.isFormOutput)" in ui and "'아직 양식으로 뽑은 산출물이 없어.'" in ui
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.sess-side \.docs-pane \.preview \{[^}]*font-size: 13px", css)


def test_post_scripts_loaded_in_order_and_use_shared_logic():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = [html.index(f'src="/{n}"') for n in ("flow-logic.js", "post-logic.js", "theme-post.js", "post-home.js", "app.js")]
    assert order == sorted(order)
    scene = (STATIC / "theme-post.js").read_text(encoding="utf-8")
    assert "PL.personOf(s.id)" in scene and "i % WHO.length" not in scene  # 손님은 세션 id 로 고정(목록 순번 아님)
    assert "BHPostScene = {" in scene and "avatar: avatar" in scene
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    for needle in (".prail", ".ptop-", ".po-av", ".po-dc", "@container shell (max-width: 760px)", '#app[data-intro="1"]'):
        assert needle in css, needle


def test_no_theme_or_design_switch_left():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    theme = (STATIC / "theme.js").read_text(encoding="utf-8")
    for needle in ("data-design", "data-tone", "design-quick", "getDesign", "setDesign", "BH.DESIGNS"):  # 테마(getTheme·BH.THEMES)는 #1013 에서 다시 생겼다
        assert needle not in app and needle not in css and needle not in theme, needle
    # 설정 화면에는 글자 크기와 테마(#1013)가 있고 디자인 고르기는 없다
    settings = app[app.index("function settingsView"):app.index("/* ---------- 시작 ---------- */")]
    assert "글자 크기" in settings and "BH.THEMES" in settings and "디자인" not in settings


def _lum(hex_color: str) -> float:
    c = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a: str, b: str) -> float:
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _root_vars(css: str) -> dict:
    block = re.search(r"\n:root \{(.*?)\n\}", css, re.S).group(1)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


# 글자와 바탕으로 같이 쓰이는 짝. 밝은 판의 회색 글씨도 포함한다.
_TEXT_PAIRS = [("text", "bg"), ("text", "surface"), ("sec", "bg"), ("sec", "surface"), ("muted", "bg"), ("muted", "surface"),
               ("accent", "bg"), ("accent", "surface"), ("attn", "bg"), ("attn", "surface"), ("btnink", "btn"), ("onaccent", "accent"),
               ("text", "st-now-bg"), ("st-now", "st-now-bg"), ("muted", "st-now-bg"), ("st-done", "surface"), ("st-done", "st-done-bg"),
               ("st-turn", "st-turn-bg"), ("sec", "st-turn-bg"), ("muted", "st-turn-bg"), ("text", "st-turn-bg"), ("st-turn-ink", "st-turn-btn"),
               ("st-fail-ink", "st-fail-bg"), ("st-fail-ink", "surface"), ("st-unk-ink", "st-unk-bg"), ("st-unk-ink", "surface"),
               ("lightink", "light"), ("lmuted", "light"), ("lightink", "card"), ("lmuted", "card"), ("lightink", "attn"), ("accent", "lightink"),
               ("okink", "okbg"), ("lightink", "okbg"), ("lmuted", "stbg")]


def test_sauce_text_contrast_is_at_least_4_5():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    v = _root_vars(css)
    low = [(f, b, round(_ratio(v[f], v[b]), 2)) for f, b in _TEXT_PAIRS if _ratio(v[f], v[b]) < 4.5]
    assert not low, low
    assert _ratio(v["edge"], v["surface"]) >= 3 and _ratio(v["edge"], v["bg"]) >= 3  # 입력·버튼 테두리
    assert v["bg"] == "#131a19" and v["surface"] == "#0e1a19" and v["accent"] == "#3ddc91" and v["light"] == "#edf7f5" and v["attn"] == "#ffcd48"


def test_no_text_larger_than_22px_and_no_native_widgets():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    sizes = [(m.group(0), float(m.group(1))) for m in re.finditer(r"font-size:\s*(\d+(?:\.\d+)?)px", css)]
    assert sizes and not [m for m, n in sizes if n > 22], [m for m, n in sizes if n > 22]
    assert "clamp(" not in "".join(re.findall(r"font-size:[^;]*;", css))
    # 기본 체크박스·select 화살표는 쓰지 않고 직접 그린다
    assert "input[type=checkbox] {" in css and "appearance: none" in css and "select.input" in css
    assert css.count("@font-face") == 2 and css.index("@font-face") < css.index(":root {")


def test_app_frame_ann_only_with_todo_and_menu_paths():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # 맨 위 띠는 내 차례가 없으면 만들지 않는다(buildAnn 이 만들고 renderAnn 은 달라진 곳만 고친다, #793)
    ann =app[app.index("function renderAnn"):app.index("function projectOf")]
    assert re.search(r"function buildAnn\(d, annEl\) \{\s*if \(d\.todo\.length\) \{", ann) and "내 차례 ' + d.todo.length + '건 — ' + (first.fix ?" in ann and "'“' + first.sname + '” 세션에서 답이 필요해'" in ann and "'“' + first.sname + '” PR 의 검사 실패를 고쳐야 해'" in ann  # 제목에 조사가 바로 붙지 않게(#790), 검사 실패 PR 은 고치라는 문구(G-24)
    # 메뉴: 내 일 → /, 작업 → 가장 위 세션, 산출물 → /docs, 새 작업 → /new, 설정 → /settings.
    head = app[app.index("function renderHead"):app.index("function renderSide")]
    assert "link('/', { text: '내 일'" in head and "link(newHref(), { text: '새 작업'" in head and "link('/settings'" in head
    assert "'/s/' + encodeURIComponent(rows[0].id)" in head and "link('/docs', { text: '산출물'" in head
    assert "p === '/docs'" in app and "docs: docsView" in app
    # 세션 목록: 기억은 값이 있으면 링, 못 읽으면 ? 와 툴팁만(memRing), 세션이 없으면 점선 상자와 새 세션 버튼
    side = app[app.index("function renderSide"):app.index("function renderRail")]
    assert "memRing(s)" in side
    ring = app[app.index("function memRing"):app.index("function renderSide")]
    assert "text: '?'" in ring and "ring unk" in ring
    assert "기억 사용량 확인 못 함" in (STATIC / "flow-logic.js").read_text(encoding="utf-8")
    assert "아직 세션이 없어. 새 작업을 시작하면 여기에 생겨." in side and "+ 새 세션" in side
    assert "logo-sauce.png" in head and (STATIC / "logo-sauce.png").is_file() and not (STATIC / "blueward-logo.png").exists()


def test_event_storm_is_coalesced_not_redrawn_per_event():
    """훅 이벤트가 초당 수십 번 와도 세션 읽기·그리기는 몰아서 한다(#793). 이 줄들이 빠지면 세션이 많을 때 화면이 다시 느려진다."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    flow = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    refresh = app[app.index("function refreshSession"):app.index("function refreshRequest")]
    assert "if (sessTimers[id]) return;" in refresh and "SESS_GAP_OTHER" in refresh and "?chat=0&lite=1" in refresh  # 세션마다 읽기를 하나로 묻고, 안 보는 세션은 대화·기록을 뺀다
    assert "function drawSoon" in app and "onSession: function (sid) { if (sid === id) drawSoon(); }" in app  # 세션 화면은 0.25초에 한 번, 프레임에 맞춰
    assert "function drawSoon" in flow and "onSession: drawSoon" in flow  # 홈 표는 0.5초에 한 번
    assert "function patchChildren" in app and "function keepLeading" in app  # 바뀐 곳만 고친다
    recent = flow[flow.index("function recentCard"):flow.index("function recentCard") + 3000]
    assert "5000 - (Date.now() -" in recent and "box._later" in recent  # 최근 산출물은 5초에 한 번까지만 다시 읽는다
    assert flow.count("/files?cache=1") == 1 and flow.count("return sessionDocs(s)") == 2  # 목록·홈이 세션마다 부르는 /files 는 서버 기억(3초)을 쓴다(한 함수로 부른다)


def test_design_states_have_shape_cues_not_only_color():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for needle in ("\\2713", "\\2715", "content: '!", "content: '?'", "dashed", "\\25CF"):
        assert needle in css, needle


def test_markdown_table_cells_do_not_break_per_letter():
    """#904: .md 의 overflow-wrap:anywhere 를 표 칸이 물려받으면 좁은 미리보기에서 REQ-001 이 글자마다 쪼개진다.
    표 칸은 낱말 단위로만 줄을 바꾸고 첫 열은 한 줄, 넘치는 표는 .md-table 가로 스크롤. (실제 그림은 G-09 SRS 미리보기로 확인)"""
    css = re.sub(r"\s+", " ", (STATIC / "app.css").read_text(encoding="utf-8"))
    assert ".md { font-size: 15px; line-height: 1.7; overflow-wrap: anywhere; }" in css  # 이 규칙을 물려받는 것이 원인
    assert ".md th, .md td { overflow-wrap: normal; word-break: keep-all; }" in css
    assert ".md td:first-child { white-space: nowrap; }" in css
    assert ".md .md-table { overflow-x: auto; max-width: 100%; }" in css
    assert css.index(".md { font-size") < css.index(".md th, .md td { overflow-wrap: normal")  # 뒤에 와야 이긴다


def test_new_ui_copy_says_claude_code_not_claude():
    for name in ("flow-ui.js", "flow-logic.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"Claude(?! Code)", text), name


# ---- 작업 화면(세션·질문·승인·새 작업)을 가짜 DOM 에서 실제로 그려 본다 (#636) ----

SMOKE = Path(__file__).with_name("console_ui_smoke.js")  # 가짜 DOM 에서 app.js 를 그대로 돌리는 도우미
_STEPS = [{"id": "a", "name": "SRS 쓰기", "kind": "skill", "skill": "srs", "state": "done"},
          {"id": "b", "name": "올리고 검토 요청하기", "kind": "skill", "skill": "deliver", "state": "active"},
          {"id": "c", "name": "승인받고 합쳐지기 기다리기", "kind": "wait", "state": "pending"}]
_PR = {"number": 6, "state": "OPEN", "url": "https://github.com/o/r/pull/6", "title": "docs: SRS", "checks": "pass"}


def _session(sid, **extra):
    base = {"id": sid, "title": "구매오더 조회 앱 요구사항", "cwd": "C:/w/proj", "branch": "docs/4-req", "status": "idle", "managed": True, "canSend": True,
            "pendingRequestIds": [], "flowId": "srs", "flowName": "요구사항 만들기·바꾸기", "stepIndex": 1, "flowSteps": _STEPS, "flowPr": _PR,
            "report": "## 다 썼어\n- REQ-001", "startedAt": 1700000000, "updatedAt": 1700000100, "log": [], "subagents": [], "prLinks": [], "changedFiles": []}
    base.update(extra)
    return base


def _smoke(tmp_path, route, sessions, requests=None, extra=None, actions=None, ls=None):
    import json
    data = dict(extra or {})
    if ls:
        data["__ls"] = ls  # 새로고침 뒤 브라우저에 남아 있는 localStorage 흉내
    data |= {"GET /api/sessions": {"sessions": sessions}, "GET /api/flows": {"flows": [{"id": "srs", "name": "요구사항", "steps": _STEPS}], "tools": []},
            "GET /api/approvals": {"state": "no"}, "GET /api/models": {"options": [{"value": "", "label": "기본"}], "effortOptions": [{"value": "", "label": "기본"}], "permissionOptions": [{"value": "", "label": "기본"}]},
            "GET /api/folders/recent": (extra or {}).get("GET /api/folders/recent", {"folders": ["C:/w/proj"]})}
    for s in sessions:
        data["GET /api/sessions/" + s["id"]] = s
        data["GET /api/sessions/" + s["id"] + "/files"] = {"files": [{"path": "docs/SRS.md", "mtime": 5, "changed": True}]}
    for r in requests or []:
        data["GET /api/requests/" + r["id"]] = r
    src, out = tmp_path / "data.json", tmp_path / "out.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    run = subprocess.run([NODE, str(SMOKE), str(STATIC), "x", str(src), route, str(out), json.dumps(actions or [])], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["errors"] == [], got["errors"]
    return got


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_work_screen_session_matches_design(tmp_path):
    q = {"id": "q1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "rm x", "description": "옛 파일 지우기"}}
    got = _smoke(tmp_path, "s/s1", [_session("s1", status="running", managed=True, currentAction="Edit docs/SRS.md", pendingRequestIds=["q1"])], [q])
    text, dump = got["text"], got["dump"]
    assert text.startswith("요구사항 만들기·바꾸기 · 내 응답을 기다리는 중구매오더 조회 앱 요구사항")
    # 시안: 순서 알약·층 그림은 "올릴 차례"(G-09)·"갈래 끝남"(G-12)에만. 확인을 기다리는 화면(G-17)엔 없다
    assert "<ol.stepbar.big>" not in dump and "<div.strip>" in dump
    turn = _smoke(tmp_path, "s/s1", [_session("s1", status="idle", managed=True, turnSkill="deliver")])
    assert "<ol.stepbar.big>" in turn["dump"]
    for cell in ("단계2 / 3 올리고 검토 요청하기", "AI 진행33%", "작업 기록이슈 #4", "검토 요청PR #6 검토 중"):
        assert cell in text, cell
    assert "요구사항REQ" not in text and "개발 번호" not in text  # 데이터가 없는 칸은 지어내지 않는다
    assert "<section.light.talk>" in dump and "<aside.sess-side.run>" in dump and "<div.comp>" in dump
    for need in ("다 썼어", "이 일의 순서", "문서 검사", "양식에 맞아", "비밀값 검사", "팀 승인", "네 차례", "승인하기", "작업 멈추기", "만든 산출물", "docs/SRS.md"):
        assert need in text, need
    assert "기억" not in text.split("검토 요청PR")[0].split("단계")[-1]  # 숫자 띠에 기억 칸은 없다


def _chat_items(n):
    return [{"t": 1700000000 + i, "role": "me" if i % 2 == 0 else "ai", "text": f"대화{i:02d}번"} for i in range(n)]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_chat_screen_folds_before_the_last_12_and_hides_report_when_chat_exists(tmp_path):
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=_chat_items(15), chatPartial=True)])
    text, dump = got["text"], got["dump"]
    assert "… 앞 대화 3개 접힘" in text
    assert "대화00번" not in text and "대화02번" not in text and "대화03번" in text and "대화14번" in text
    assert dump.count("<div.me>") + dump.count("<div.ai>") == 12
    assert "터미널에서 한 대화는 내 말과 AI 마지막 답만 보여." in text
    assert "다 썼어" not in text  # 대화가 있으면 마지막 보고 하나만 따로 그리지 않는다
    few = _smoke(tmp_path, "s/s1", [_session("s1", chat=_chat_items(12))])
    assert "앞 대화" not in few["text"] and "대화00번" in few["text"] and "터미널에서 한 대화" not in few["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_chat_screen_draws_waiting_request_once_in_place_and_answers_as_one_line(tmp_path):
    chat = [{"t": 1, "role": "me", "text": "시작해 줘"},
            {"t": 2, "role": "req", "id": "q0", "kind": "question", "title": "색은?", "answer": "Red"},
            {"t": 3, "role": "req", "id": "p0", "kind": "permission", "title": "Bash 사용", "answer": "허락함"},
            {"t": 4, "role": "req", "id": "p9", "kind": "permission", "title": "Edit 사용", "answer": None},
            {"t": 5, "role": "req", "id": "q1", "kind": "question", "title": "우선순위는?", "answer": None}]
    q1 = {"id": "q1", "sessionId": "s1", "kind": "question", "status": "pending", "questions": [{"question": "우선순위는?", "options": [{"label": "높음"}]}]}
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat, pendingRequestIds=["q1"], status="waiting")], [q1])
    text, dump = got["text"], got["dump"]
    assert dump.count("<div.qgroup>") == 1  # 질문은 대화 안 자리에서 한 번만, 그 자리에서 바로 고른다(시안 G-13). 머리 글에도 같은 말이 있어 글자 수는 세지 않는다
    assert dump.count("<div.reqnote>") == 3 and dump.index("<div.reqnote>") < dump.index("<div.qgroup>")
    # 시안 G-07: 보기 + 콘솔이 더하는 '직접 적기'. 하나만 고르는 질문 하나라 [답 보내기] 는 '직접 적기' 를 고를 때만 생긴다
    assert dump.count("<button.qopt>") == 2 and "직접 적기" in text and "직접 적어 답하기" not in text and "답 보내기" not in text
    assert "질문: 색은? → Red" in text and "승인 요청: Bash 사용 → 허락함" in text
    assert "승인 요청: Edit 사용 → 처리 결과를 알 수 없어" in text  # 답이 없고 대기도 아니면 지어내지 않는다
    assert text.index("시작해 줘") < text.index("질문: 색은? → Red")


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_chat_screen_falls_back_to_report_for_sessions_without_chat(tmp_path):
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=[])])
    assert "다 썼어" in got["text"] and "앞 대화" not in got["text"]
    got = _smoke(tmp_path, "s/s1", [_session("s1")])  # 옛 서버 응답엔 chat 키가 없다
    assert "다 썼어" in got["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_in_progress_session_step_bar_ends_with_upcoming_next_flow(tmp_path):
    """#858 시안 G-09: 올릴 차례(진행 중)인 세션의 순서 알약 끝에 서버가 미리 계산한 다음 갈래(upcomingFlow). 모르거나 없으면 알약을 만들지 않는다."""
    up = {"options": [{"flow": "spec", "name": "개발 Spec", "label": "개발 Spec 만들기", "value": "개발", "count": 2, "ids": ["REQ-001", "REQ-002"]}], "hint": ""}
    base = dict(turnSkill="deliver", status="idle")
    got = _smoke(tmp_path, "s/s1", [_session("s1", upcomingFlow=up, **base)])
    assert "<ol.stepbar.big>" in got["dump"] and "→ 다음: 개발 Spec" in got["text"] and "<li.step.next>" in got["dump"]
    unknown = _smoke(tmp_path, "s/s1", [_session("s1", upcomingFlow={"options": [], "hint": "", "unknown": "SRS 를 읽지 못해"}, **base)])
    assert "→ 다음" not in unknown["text"] and "<ol.stepbar.big>" in unknown["dump"]  # 모르면 지어내지 않는다
    old = _smoke(tmp_path, "s/s1", [_session("s1", **base)])  # 옛 서버 응답엔 upcomingFlow 가 없다
    assert "→ 다음" not in old["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_work_screen_finished_session_shows_handoff_card(tmp_path):
    nxt = {"options": [{"flow": "spec", "label": "개발 Spec 만들기", "value": "개발", "count": 1, "ids": ["REQ-001"]}, {"flow": None, "label": "권한 양식", "disabled": True}], "hint": "", "unknown": ""}
    steps = [dict(s, state="done") for s in _STEPS]
    got = _smoke(tmp_path, "s/s2", [_session("s2", flowFinished=True, phase="finished", group="idle", stepIndex=2, flowSteps=steps, flowPr=dict(_PR, state="MERGED"), nextFlow=nxt)])
    text = got["text"]
    for need in ("→ 다음: 개발 Spec", "요구사항 만들기·바꾸기 · 끝남", "PR #6이 합쳐졌어. 다음 갈래는 개발 Spec이야", "다음 일", "개발 Spec 만들기 — 새 세션에서 시작하길 권해", "새 세션에 넘길 것",
                 "REQ-001 — DEV-001 번호로 개발 Spec 하기", "새 세션에서 개발 Spec 시작", "넘길 내용 고치기", "여기서 계속", "새 세션은 최신 내용 받기와 플러그인 판 확인을 스스로 해", "권한 양식준비 중",
                 "요구사항REQ-001 확정", "개발 번호DEV-001", "단계3 / 3 끝", "PR #6 합쳐짐"):
        assert need in text, need
    assert "<div.nextflow.handoff>" in got["dump"] and "<ol.stepbar.big>" in got["dump"]
    assert "AI 진행" not in text and "<div.q.prcard>" not in got["dump"] and "<aside.sess-side>" in got["dump"]  # 끝남: AI 진행 칸·PR 카드 없음, 산출물 칸은 숨김(hidden)
    assert "내 차례" not in got["ann"] and "PR #6이 합쳐졌어 — 다음은 개발 Spec" in got["ann"]
    assert "끝 · PR #6 합쳐짐" in got["side"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_work_screen_question_shows_each_sentence_once(tmp_path):
    one = {"id": "q1", "sessionId": "s1", "kind": "question", "status": "pending",
           "questions": [{"question": "이 앱은 얼마나 급해?", "header": "우선순위", "options": [{"label": "반드시 필요"}, {"label": "중요", "description": "이번 달 안에"}]}]}
    got = _smoke(tmp_path, "r/q1", [_session("s1", pendingRequestIds=["q1"])], [one])
    text = got["text"]
    assert text.count("이 앱은 얼마나 급해?") == 1  # 질문 문장이 제목과 카드에 두 번 나오지 않는다(#635)
    assert text.startswith("요구사항 만들기·바꾸기 · 내 답을 기다리는 중구매오더 조회 앱 요구사항")
    for need in ("질문 · 우선순위", "반드시 필요", "중요이번 달 안에", "다른 답이 있으면 직접 적어 줘", "답 보내기"):
        assert need in text, need
    assert got["dump"].count("<button.qopt>") == 2 and "<div.q>" in got["dump"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_work_screen_permission_card_and_edit_names(tmp_path):
    bash = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "cwd": "C:/w/proj",
            "toolInput": {"command": "rm x.xlsx", "description": "옛 파일 지우기"}, "permissionSuggestions": [1], "note": "touch 는 목록에 없어", "suggestionText": ["Bash(rm *) 허용 규칙 추가"]}
    edit = {"id": "p2", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Edit", "toolInput": {"file_path": "docs/a.md", "old_string": "가", "new_string": "나"}}
    risky = {"id": "p3", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "curl x", "dangerouslyDisableSandbox": True}}
    sess = [_session("s1", pendingRequestIds=["p1", "p2", "p3"])]
    got = _smoke(tmp_path, "r/p1", sess, [bash, edit, risky])
    for need in ("확인 필요", "옛 파일 지우기", "자세히 (명령 원문)", "이번만 허락", "하지 마", "이 세션이 끝날 때까지만 적용돼", "묻는 이유: touch 는 목록에 없어", "도구에 넘기는 입력 전체"):  # #1018
        assert need in got["text"], need
    assert "<details.more>" in got["dump"] and "<details[open].more>" not in got["dump"]  # 쉬운 설명이 있는 명령은 원문을 접어 둔다
    got = _smoke(tmp_path, "r/p2", sess, [bash, edit, risky])
    assert "원래 글가바꾼 글나" in got["text"] and "<details[open].more>" in got["dump"]  # #634 이름, 고치는 일은 열어 둔다
    got = _smoke(tmp_path, "r/p3", sess, [bash, edit, risky])
    assert "샌드박스를 끄고 실행해" in got["text"] and "<details[open].more>" in got["dump"]  # 위험 표시는 접지 않는다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1018_card_explains_with_korean_reason_and_moves_ai_description_into_details(tmp_path):
    req = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "note": "touch 는 목록에 없어",
           "toolInput": {"command": "touch a", "description": "Create the file"}, "hasSuggestions": True, "suggestionText": ["이 세션: 허용 규칙 추가 - Bash(touch:*)"]}
    got = _smoke(tmp_path, "r/p1", [_session("s1", pendingRequestIds=["p1"])], [req])
    text = got["text"]
    assert text.index("묻는 이유: touch 는 목록에 없어") < text.index("자세히 (명령 원문)") < text.index("Create the file")  # 영어 설명은 "자세히" 안에만
    assert "<span.sm>Create the file" not in got["dump"] and "<details.more>" in got["dump"]
    nonote = dict(req, id="p2", note="")
    got = _smoke(tmp_path, "r/p2", [_session("s1", pendingRequestIds=["p2"])], [nonote])
    assert "묻는 이유" not in got["text"] and "<details[open].more>" in got["dump"]  # 쉬운 말 이유가 없으면 AI 설명이 유일한 안내라 펼쳐 둔다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1018_just_handled_request_title_is_the_result_not_already_handled(tmp_path):
    perm = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "touch a"}, "note": "x"}
    sess = [_session("s1", pendingRequestIds=["p1"])]
    ok = _smoke(tmp_path, "r/p1", sess, [perm], extra={"POST /api/requests/p1/answer": {}}, actions=[{"click": "[data-decide=allow]"}])
    assert "허락했어." in ok["text"] and "이미 처리된 요청이야" not in ok["text"]
    no = _smoke(tmp_path, "r/p1", sess, [perm], extra={"POST /api/requests/p1/answer": {}}, actions=[{"click": "[data-decide=deny]"}])
    assert "하지 말라고 했어." in no["text"] and "이미 처리된 요청이야" not in no["text"]
    plan = {"id": "pl1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "ExitPlanMode", "toolInput": {"plan": "# 계획\n- a"}}
    ok = _smoke(tmp_path, "r/pl1", [_session("s1", pendingRequestIds=["pl1"])], [plan], extra={"POST /api/requests/pl1/answer": {}}, actions=[{"click": "[data-decide=allow]"}])
    assert "이 계획대로 진행하기로 했어." in ok["text"] and "이미 처리된 계획이야" not in ok["text"]
    old = dict(perm, status="answered", resolution="allow", outcome="허용함")  # 다시 열어 본 처리된 요청은 예전 글 그대로
    got = _smoke(tmp_path, "r/p1", sess, [old])
    assert "이미 처리된 요청이야" in got["text"] and "허락했어." in got["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
@pytest.mark.parametrize("res, title", [("allow", "허락했어."), ("allow_session", "허락했어."), ("deny", "하지 말라고 했어."), ("closed", "닫힌 요청"),
                                       ("terminal", "터미널에서 처리됨"), ("handoff", "터미널로 넘어감"), ("expired", "닫힌 요청"), ("", "닫힌 요청"), ("zzz", "닫힌 요청")])
def test_1018_result_comes_from_resolution_code_not_korean_outcome_text(tmp_path, res, title):
    # 한글 outcome 이 무엇이든(예: 허용함) 코드가 없으면 허락으로 읽지 않는다 — 코드만 본다
    req = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "closed" if res in ("closed", "terminal", "handoff", "expired", "") else "answered",
           "toolName": "Bash", "toolInput": {"command": "touch a"}, "outcome": "허용함", "resolution": res}
    got = _smoke(tmp_path, "r/p1", [_session("s1")], [req])
    assert title in got["text"]
    if res in ("", "zzz"):
        assert "허락했어." not in got["text"]
    if res == "allow_session":
        assert "이 세션에서는 같은 작업을 다시 묻지 않아." in got["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1018_bypass_phrases_js_matches_json_and_strips_same_as_server():
    import json
    import subprocess
    js = r"""
const L = require(process.argv[1] + '/flow-logic.js');
const s = ['a 를 고치십시오. DELIVER=1 을 붙이십시오.', 'DELIVER=1 로 우회하십시오.', '첫 줄\n--no-verify 를 쓰십시오.\n셋째 줄', 'engine_spec.py 를 확인하십시오.', '훅을 끄고 다시 하십시오.', '평범해.'];
process.stdout.write(JSON.stringify({ patterns: L.BYPASS_PATTERNS, out: s.map(L.stripBypass), plain: L.plainReason('DELIVER=1 을 붙여 다시 실행하십시오.') }));
"""
    run = subprocess.run([NODE, "-e", js, str(STATIC)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    rules = json.loads((STATIC.parent / "bypass_phrases.json").read_text(encoding="utf-8"))
    assert got["patterns"] == rules["patterns"]  # 화면 목록과 서버 데이터 파일이 같은 목록
    import sys
    sys.path.insert(0, str(STATIC.parent))
    import bypass_filter
    samples = ['a 를 고치십시오. DELIVER=1 을 붙이십시오.', 'DELIVER=1 로 우회하십시오.', '첫 줄\n--no-verify 를 쓰십시오.\n셋째 줄', 'engine_spec.py 를 확인하십시오.', '훅을 끄고 다시 하십시오.', '평범해.']
    assert got["out"] == [bypass_filter.strip_bypass(x) for x in samples]
    assert got["plain"] == ""


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1018_block_card_hides_bypass_sentence_and_does_not_send_it_to_ai(tmp_path):
    reason = "푸시는 /harness:deliver 스킬이 수행합니다.\n다음: /harness:deliver 를 실행하십시오. 이미 그 스킬 절차를 따르는 중이라면 명령 앞에 DELIVER=1 을 붙여 다시 실행하십시오."
    chat = [{"t": 1, "role": "block", "text": reason, "hook": "pre-bash-git-guard", "kind": "blocked", "fix": "/harness:deliver 를 실행하십시오."}]
    s = _session("s1", chat=chat, canSend=True)
    got = _smoke(tmp_path, "s/s1", [s], extra={"POST /api/sessions/s1/messages": {}}, actions=[{"click": "[data-block-send]"}])
    assert "DELIVER=1" not in got["text"] and "/harness:deliver 를 실행하십시오." in got["text"]
    assert got["posts"] and "DELIVER" not in got["posts"][0][2] and "deliver 를 실행하십시오" in got["posts"][0][2]
    raw = _smoke(tmp_path, "s/s1", [s], actions=[{"click": "[data-block-raw]"}])
    assert "DELIVER=1" in raw["text"]  # 원문은 "검사 원문" 안에만


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1018_session_title_and_log_lines_are_masked_on_screen(tmp_path):
    fake = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    s = _session("s1", title=f"배포 token={fake} password=hunter2hunter", log=[{"time": 1, "text": f"요청: password=hunter2hunter {fake}"}])
    for route in ("s/s1", "/"):
        got = _smoke(tmp_path, route, [s])
        assert "hunter2hunter" not in got["text"] and fake not in got["text"], route
    assert "••••" in _smoke(tmp_path, "s/s1", [s])["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_work_screen_irreversible_card_is_yellow_and_cannot_be_remembered(tmp_path):
    """시안 17: 되돌릴 수 없는 일 카드. 꼬리표, 쉬운 말 제목, 하네스 안내, 이번만 허락 / 하지 마만."""
    rm = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "risk": "irreversible", "riskNote": "작업 폴더 밖 파일을 쓰려 해",
          "toolInput": {"command": 'rm "C:/Users/x/Desktop/old.xlsx"'}, "permissionSuggestions": [1], "hasSuggestions": True, "suggestionText": ["Bash(rm *) 허용 규칙 추가"]}
    plain = {"id": "p2", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "touch a"}, "hasSuggestions": True}
    sess = [_session("s1", pendingRequestIds=["p1", "p2"])]
    got = _smoke(tmp_path, "r/p1", sess, [rm, plain])
    text, dump = got["text"], got["dump"]
    for need in ("확인 필요 · 되돌릴 수 없어", "작업 폴더 밖 파일을 쓰려 해", "하네스는 되돌릴 수 없는 일은 항상 사람에게 물어.", "이번만 지워", "지우지 마", "자세히 (명령 원문)", "이유 적기(선택)"):
        assert need in text, need  # 단추는 행동을 그대로 말한다(시안 17)
    assert "이번만 허락" not in text
    assert "<div.bad.irrev>" in dump and "<span.muted-line>" in dump and "<span.warn-line>" not in dump  # 하네스 안내 줄은 강조 없이 연한 글
    assert "<details.more>" in dump and "AI에게 말하기" in text  # 이유 입력칸은 접혀 있고, 카드 아래에 말하기 입력창이 있다
    push = dict(rm, id="p4", toolInput={"command": "git push origin main"}, riskNote="GitHub 에 올리려 해")
    up = _smoke(tmp_path, "r/p4", [_session("s1", pendingRequestIds=["p4"])], [push])
    assert "이번만 올려" in up["text"] and "올리지 마" in up["text"]
    other = dict(rm, id="p5", toolInput={"command": "chmod 777 a"}, riskNote="권한을 바꾸려 해")
    gen = _smoke(tmp_path, "r/p5", [_session("s1", pendingRequestIds=["p5"])], [other])
    assert "이번만 허락" in gen["text"] and "하지 마" in gen["text"]
    assert "irreversible" not in text  # 값 그대로를 화면에 쓰지 않는다
    assert "다시 묻지 않기" not in text  # 되돌릴 수 없는 일은 기억시키지 못한다
    got = _smoke(tmp_path, "r/p2", sess, [rm, plain])
    assert "<div.bad>" in got["dump"] and "irrev" not in got["dump"] and "되돌릴 수 없어" not in got["text"]
    assert "허용하고 이 세션에서 다시 묻지 않기" in got["text"]  # 일반 카드는 그대로


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_plan_card_shows_plan_markdown_with_two_buttons_and_reason(tmp_path):
    """#861: 계획 모드의 ExitPlanMode 요청은 도구 입력 덩어리가 아니라 계획 카드. [이 계획대로 진행] 은 허락, [고쳐 달라고 하기] 는 사유를 적어 거절."""
    plan = {"id": "pl1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "ExitPlanMode", "cwd": "C:/w/proj",
            "toolInput": {"plan": "﻿# 고칠 순서\n- 문서 먼저\n- 검사 돌리기", "planFilePath": "C:\\w\\.claude\\plans\\x.md"}}
    sess = [_session("s1", pendingRequestIds=["pl1"])]
    got = _smoke(tmp_path, "r/pl1", sess, [plan])
    text, dump = got["text"], got["dump"]
    for need in ("계획", "고칠 순서", "문서 먼저", "이 계획대로 진행", "고쳐 달라고 하기", "자세히 (도구 입력 전체)", "계획 파일", "AI에게 말하기", "내 계획 확인을 기다리는 중"):
        assert need in text, need
    assert "<div.bad.plan>" in dump
    assert "# 고칠 순서" not in text.split("자세히")[0] and "<h3.md-h>고칠 순서</h3>" in dump  # 마크다운으로 그려진다. Windows 계획 파일 맨 앞의 BOM 이 제목을 깨뜨리지 않는다(실측). 원문은 "자세히" 안에만
    assert "이번만 허락" not in text and "확인 필요" not in text  # 일반 승인 카드가 아니다
    assert "이유 적기" not in text and "고쳐 달라고 보내기" not in text  # 사유 칸은 [고쳐 달라고 하기] 를 눌러야 열린다
    ok = _smoke(tmp_path, "r/pl1", sess, [plan], extra={"POST /api/requests/pl1/answer": {}}, actions=[{"click": "[data-decide=allow]"}])
    assert ok["posts"] == [["POST", "/api/requests/pl1/answer", '{"decision":"allow"}']]
    assert "이 계획대로 진행하기로 했어." in ok["text"] and "권한 모드가 기본으로 돌아가고" in ok["text"]
    open_ = _smoke(tmp_path, "r/pl1", sess, [plan], actions=[{"click": "[data-plan-revise]"}])
    assert "어떻게 고치면 좋을지 적어 줘" in open_["text"] and "고쳐 달라고 보내기" in open_["text"]
    sent = _smoke(tmp_path, "r/pl1", sess, [plan], extra={"POST /api/requests/pl1/answer": {}},
                  actions=[{"click": "[data-plan-revise]"}, {"type": "#plan-why", "value": "문서만 먼저 해 줘"}, {"click": "[data-decide=deny]"}])
    assert sent["posts"] == [["POST", "/api/requests/pl1/answer", '{"decision":"deny","reason":"문서만 먼저 해 줘"}']]
    assert "고쳐 달라고 전했어." in sent["text"] and "전달한 이유: 문서만 먼저 해 줘" in sent["text"]
    # 계획 글이 없으면(실측: 계획 파일을 안 쓰면 input 이 {}) 계획 카드에 "계획 본문이 없어" 를 사실대로 적는다. 빈 계획을 보여 주는 척하지 않는다
    for odd_input in ({}, {"plan": 3}, {"plan": "  "}):
        odd = _smoke(tmp_path, "r/pl1", sess, [dict(plan, toolInput=odd_input)])
        assert "계획 본문이 없어" in odd["text"] and "<p.warn-line>" in odd["dump"] and "이 계획대로 진행" in odd["text"] and "이번만 허락" not in odd["text"]
    assert "계획 본문이 없어" not in got["text"]
    # 긴 계획은 접어 두고 [계획 전체 보기] 로 연다
    longp = dict(plan, toolInput={"plan": "\n".join(f"- 할 일 {i}" for i in range(60))})
    folded = _smoke(tmp_path, "r/pl1", sess, [longp])
    assert "<div.report-body.clip>" in folded["dump"] and "계획 전체 보기" in folded["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_plan_waiting_is_told_in_plain_words_in_chat_side_and_home(tmp_path):
    plan = {"id": "pl1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "ExitPlanMode", "title": "계획 확인",
            "toolInput": {"plan": "## 계획\n- 하나"}}
    sess = [_session("s1", pendingRequestIds=["pl1"], status="idle", chat=[{"t": 3, "role": "req", "id": "pl1", "kind": "permission", "title": "계획 확인", "answer": None}])]
    work = _smoke(tmp_path, "s/s1", sess, [plan])
    for need in ("내 계획 확인을 기다리는 중", "AI가 계획을 세웠어", "계획 보기"):
        assert need in work["text"], need
    assert "승인하기" not in work["text"]
    home = _smoke(tmp_path, "", sess, [plan])
    for need in ("계획 확인", "가서 계획 보기"):
        assert need in home["text"], need
    assert "가서 승인하기" not in home["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_session_screen_shows_auto_mode_unavailable_note(tmp_path):
    note = "auto 모드를 쓸 수 없는 것 같아. 이유는 확인 못 함 (claude 가 알려 준 모드 원문: default)"
    got = _smoke(tmp_path, "s/s1", [_session("s1", permissionChoice="auto", permissionMode="default", permissionNote=note)])
    assert note in got["text"]
    clean = _smoke(tmp_path, "s/s1", [_session("s1", permissionChoice="auto", permissionMode="auto")])
    assert "auto 모드를 쓸 수 없는 것 같아" not in clean["text"]


_MCP_BAD = {"state": "problem", "canReconnect": True, "servers": [
    {"name": "abap-adt", "status": "failed", "label": "연결하지 못했어", "problem": True, "error": "Connection closed", "canReconnect": True},
    {"name": "echosrv", "status": "connected", "label": "연결됨", "problem": False, "error": "", "canReconnect": False}]}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_session_screen_mcp_status_quiet_when_ok_loud_when_failed_honest_for_terminal(tmp_path):
    ok = _smoke(tmp_path, "s/s1", [_session("s1", mcp={"state": "ok", "canReconnect": True, "servers": [
        {"name": "echosrv", "status": "connected", "label": "연결됨", "problem": False, "error": "", "canReconnect": False}]})])
    assert "data-mcp" not in ok["dump"] and "연결이 안 된 도구" not in ok["text"] and "echosrv" not in ok["text"]  # 모두 연결됐으면 조용하다
    none = _smoke(tmp_path, "s/s1", [_session("s1", mcp={"state": "none", "servers": [], "canReconnect": False})])
    assert "data-mcp" not in none["dump"]
    bad = _smoke(tmp_path, "s/s1", [_session("s1", mcp=_MCP_BAD)])
    assert "연결이 안 된 도구가 있어" in bad["text"] and "abap-adt — 연결하지 못했어" in bad["text"] and "다시 연결" in bad["text"]
    assert "Connection closed" in bad["text"] and "echosrv" not in bad["text"]  # 사유는 "자세히" 안, 멀쩡한 서버는 안 보인다
    assert "<details.mcp-more>" in bad["dump"] and "<div.banner.mcp>" in bad["dump"]
    term = _smoke(tmp_path, "s/s1", [_session("s1", managed=False, mcp={"state": "unknown", "servers": [], "canReconnect": False})])
    # 터미널 세션은 띠 없이(시안 G-09) "자세히 > 기술 정보" 에서 모른다고 말한다. 연결됨이라 하지 않는다
    assert "data-mcp" not in term["dump"] and "다시 연결" not in term["text"]
    assert "여기서는 연결됐는지 확인할 수 없어" in term["text"] and "모두 연결됨" not in term["text"]
    assert "모두 연결됨" in ok["text"] and "연결 안 됨: abap-adt" in bad["text"]
    auth = _smoke(tmp_path, "s/s1", [_session("s1", mcp={"state": "problem", "canReconnect": True, "servers": [
        {"name": "notion", "status": "needs-auth", "label": "로그인이 필요해(터미널에서 /mcp 로 로그인해 줘)", "problem": True, "error": "", "canReconnect": False}]})])
    assert "로그인이 필요해" in auth["text"] and "다시 연결" not in auth["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_session_screen_mcp_reconnect_button_posts_server_name(tmp_path):
    fixed = {"state": "ok", "canReconnect": True, "servers": []}
    extra = {"POST /api/sessions/s1/mcp/reconnect": {"ok": True, "session": _session("s1", mcp=fixed)}}
    got = _smoke(tmp_path, "s/s1", [_session("s1", mcp=_MCP_BAD)], extra=extra, actions=[{"click": ".mcp-again"}])
    posts = [p for p in got["posts"] if p[1].endswith("/mcp/reconnect")]
    assert len(posts) == 1 and "abap-adt" in posts[0][2], got["posts"]
    assert "연결이 안 된 도구가 있어" not in got["text"]  # 연결되면 알림이 사라진다
    fail = _smoke(tmp_path, "s/s1", [_session("s1", mcp=_MCP_BAD)], actions=[{"click": ".mcp-again"}])  # 길이 없으면 404 로 실패한다
    assert "연결이 안 된 도구가 있어" in fail["text"] and "다시 연결하지 못했어" in fail["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_permission_card_for_mcp_tool_speaks_plainly_and_folds_raw_name(tmp_path):
    req = {"id": "m1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "mcp__abap-adt__getObjectSource",
           "toolInput": {"objectSourceUrl": "/sap/bc/adt/x"}, "hasSuggestions": False,
           "mcp": {"server": "abap-adt", "tool": "getObjectSource", "display": "Get Object Source"}}
    got = _smoke(tmp_path, "r/m1", [_session("s1", pendingRequestIds=["m1"])], [req])
    assert "SAP 시스템 도구(abap-adt)의 'Get Object Source' 을(를) 써도 될까?" in got["text"]
    assert "Claude Code가 mcp__" not in got["text"] and "<details.more>" in got["dump"]
    assert "자세히 (도구 이름·넘기는 값)" in got["text"] and "<details[open].more>" not in got["dump"]  # 되돌릴 수 있는 요청은 접어 둔다
    # 되돌릴 수 없는 MCP 요청(SAP 소스 쓰기 등)은 넘기는 값을 보고 정하도록 펼쳐 둔다
    irrev = dict(req, id="m3", toolName="mcp__abap-adt__setObjectSource", risk="irreversible", riskNote="SAP 소스를 바꾸려 해",
                 toolInput={"objectSourceUrl": "/sap/bc/adt/x", "source": "REPORT z."},
                 mcp={"server": "abap-adt", "tool": "setObjectSource", "display": "Set Object Source"})
    got3 = _smoke(tmp_path, "r/m3", [_session("s1", pendingRequestIds=["m3"])], [irrev])
    assert "<details[open].more>" in got3["dump"] and "REPORT z." in got3["text"]
    other = dict(req, id="m2", mcp={"server": "notion", "tool": "search", "display": ""}, toolName="mcp__notion__search")
    got2 = _smoke(tmp_path, "r/m2", [_session("s1", pendingRequestIds=["m2"])], [other])
    assert "연결 도구(notion)의 'search' 을(를) 써도 될까?" in got2["text"]  # SAP 이 아니면 SAP 이라 하지 않고 display_name 이 없으면 도구 이름


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_session_screen_api_error_card_side_and_ann(tmp_path):
    """#865: 오류로 끝난 세션은 대화 판에 ⚠ 카드(원문은 자세히 안), 목록·띠에도 오류로. 훅 막힘 카드(✕·?)와 섞지 않는다."""
    issue = {"kind": "auth", "status": 401, "error": "authentication_failed", "raw": "Invalid API key · Fix external API key"}
    got = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue=issue, chat=[{"t": 1, "role": "me", "text": "해 줘"}])])
    text, dump = got["text"], got["dump"]
    assert "<div.bad.q.apierr.err>" in dump and "로그인이 풀렸어" in text and "/login" in text
    assert "Invalid API key" not in text  # 원문은 자세히를 눌러야
    assert "✕ 막힘" not in text and "? 확인 못 함" not in text
    assert "로그인이 풀렸어" in got["side"] and "끝난 세션" not in got["side"]
    assert "⚠ 오류 1건" in got["ann"] and "로그인이 풀렸어" in got["ann"]
    opened = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue=issue, chat=[{"t": 1, "role": "me", "text": "해 줘"}])], actions=[{"click": "[data-api-more]"}])
    assert "Invalid API key · Fix external API key" in opened["text"] and "상태 401" in opened["text"]
    # 모르는 모양은 알 수 없는 오류로
    unk = _smoke(tmp_path, "s/s1", [_session("s1", status="ended", apiIssue={"kind": "unknown", "error": "error_during_execution"})])
    assert "알 수 없는 오류로 끝났어" in unk["text"] and "알 수 없는 오류" in unk["side"] and "끝난 세션" not in unk["side"]
    # 재시도 중은 오류가 아니라 안내(띠에 오류로 세지 않는다)
    retry = _smoke(tmp_path, "s/s1", [_session("s1", status="running", group="running", apiIssue={"kind": "retry", "attempt": 2, "max": 10, "delayMs": 1190})])
    assert "<div.bad.q.apierr.info>" in retry["dump"] and "다시 시도하는 중 2/10" in retry["text"] and "2초 뒤" in retry["text"]
    assert "오류" not in retry["ann"] and "다시 시도 중 2/10" in retry["side"]
    clean = _smoke(tmp_path, "s/s1", [_session("s1")])
    assert "apierr" not in clean["dump"] and "오류" not in clean["ann"]
    # 홈 표: 오류 세션의 상태 칩은 '끝남' 이 아니라 ⚠ 오류
    home = _smoke(tmp_path, "", [_session("s1", status="ended", apiIssue=issue)], extra=_start())
    assert "<span.tagx.err>" in home["dump"] and "⚠ 오류 · 로그인이 풀렸어" in home["text"] and "<span.tag.ok>" not in home["dump"]
    # 혼자 있는 [자세히] 는 테두리 단추로 보인다(#900: quiet-edge 는 밝은 판에서 글자만 보였다)
    assert "<button.pill.line>" in got["dump"] and "<button.pill.line.quiet-edge>" not in got["dump"].split("apierr", 1)[1].split("</div", 1)[0]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_api_error_holds_next_step_until_login_or_limit(tmp_path):
    """#900: 로그인 풀림·사용 한도·쓸 수 없는 모델이면 다음 단계 [실행] 대신 '먼저 할 일' 을 두고, 넘길 수도 있다. 다른 오류는 막지 않는다."""
    chat = [{"t": 1, "role": "me", "text": "해 줘"}]
    for kind, title in (("auth", "로그인한 뒤 이어서 하자"), ("limit", "한도가 풀린 뒤 이어서 하자"), ("model", "다른 모델로 새로 시작하자")):
        got = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue={"kind": kind, "t": 5}, chat=chat)])
        assert "<div.nextstep.ask>" in got["dump"] and title in got["text"] and "다시 멈춰" in got["text"], kind
        assert "네 차례" not in got["text"] and "⚠ 오류 · 먼저 할 일" in got["text"], kind
    skipped = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue={"kind": "auth", "t": 5}, chat=chat)], actions=[{"click": "[data-hold-skip]"}])
    assert "네 차례" in skipped["text"] and "로그인한 뒤 이어서 하자" not in skipped["text"]
    nopick = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue={"kind": "auth", "t": 5}, chat=chat, flowId=None, flowName=None, flowSteps=[], stepIndex=0)])
    assert "로그인한 뒤 이어서 하자" in nopick["text"] and "어떤 일이야?" not in nopick["text"] and "그래도 먼저 일 고르기" in nopick["text"]
    other = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue={"kind": "other", "t": 5}, chat=chat)])
    assert "먼저 할 일" not in other["text"] and "네 차례" in other["text"]  # 일시적일 수 있는 서버 오류는 다시 해 볼 수 있다
    # 한도가 apiIssue 없이 rateLimit(rejected) 로만 와도 같다
    rl = _smoke(tmp_path, "s/s1", [_session("s1", rateLimit={"status": "rejected", "t": 6, "resetsAt": 4102444800}, chat=chat)])
    assert "한도가 풀린 뒤 이어서 하자" in rl["text"]
    # 모델 오류 안내는 없는 '설정' 이 아니라 새 작업의 고급 설정을 가리킨다
    model = _smoke(tmp_path, "s/s1", [_session("s1", apiIssue={"kind": "model", "t": 5}, chat=chat)])
    assert "설정에서 다른 모델로" not in model["text"] and "고급 설정" in model["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_work_screen_new_task_has_kinds_flow_and_advanced_fold(tmp_path):
    got = _smoke(tmp_path, "new", [], extra={"GET /api/folders/last": {"path": "C:/w/proj"}})
    text = got["text"]
    assert text.startswith("새 작업무엇을 할까?")
    for kind in ("요구사항정의서", "개발 Spec", "사용자 매뉴얼", "CTS 관리대장", "Role 정리", "개발하기", "설정하기", "ATC 지적 고치기", "작은 수정", "잘 모르겠어"):
        assert kind in text, kind
    assert got["dump"].count("<button.kind") == 9  # 시안 G-05 의 아홉 칸. 설정하기·표준 기능은 "그 밖의 종류" 줄(칸 줄 수가 시안과 같게)
    assert "그 밖의 종류" in text and "<div.kinds-more" in got["dump"]
    for need in ("하고 싶은 일을 한두 줄로", "참고 파일(회의록 · 고객 메일 · 기존 양식)", "이렇게 진행돼", "작업 폴더는 이 프로젝트로 자동으로 정해져.", "작업 시작", "고급 설정 (모델 · 생각 깊이 · 권한)", "권한 모드"):
        assert need in text, need
    assert "/harness:" not in text.split("이렇게 진행돼")[1].split("작업 폴더")[0]  # 순서 칸은 스킬 명령이 아니라 쉬운 말
    # 시안 순서: 고급 설정은 작업 시작 줄 아래
    assert text.index("작업 시작") < text.index("고급 설정")
    assert "<details.more>" in got["dump"]  # 모델·생각 깊이·권한은 접힌 "고급" 안에 그대로 있다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_has_folder_pick_button_and_attach(tmp_path):
    """새 작업 화면(#1038): 클립 단추는 "작업 폴더에서 고르기", 내 컴퓨터의 그림·PDF 는 첨부 단추. 눌러도 @ 는 하나만 남는다.
    가짜 화면(console_ui_smoke.js)은 Post 새 작업 배치(classList)를 그리지 못해 Sauce 만 본다. Post 는 실제 브라우저로 확인했다."""
    acts = [{"click": ".refbox"}, {"read": "#brief"}, {"click": ".refbox"}, {"read": "#brief"}]
    got = _smoke(tmp_path, "new", [], extra={"GET /api/folders/last": {"path": "C:/w/proj"}}, actions=acts)
    assert "작업 폴더에서 고르기" in got["text"] and "그림(png·jpg·gif·webp)과 PDF 만 붙일 수 있어" in got["text"]
    assert "<span.attach-pick>" in got["dump"] and "<textarea.textarea" in got["dump"] and "<div.attach-box" in got["dump"]
    assert got["values"] == ["@", "@"]  # 두 번 눌러도 "@ @" 가 되지 않는다(목록 열고 닫기는 브라우저 실측)
    assert [x for x in got["posts"] if "/start" in x[1]] == []


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_start_sends_no_attachments_key_when_none_attached(tmp_path):
    got = _smoke(tmp_path, "new?id=A1", [_session("s9")], extra=_review_extra(_CONFIDENT_FLOW), actions=[{"click": ".pill.dark.big"}])
    body = json.loads([x[2] for x in got["posts"] if "/start" in x[1]][0])
    assert "attachments" not in body


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_file_list_request_is_not_queued_behind_other_gets():
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "UNQUEUED_GET = /^\\/api\\/files\\?/" in src and "UNQUEUED_GET.test(path)" in src
    assert "'/api/files' + qs(" in src  # 목록 요청은 이 주소 모양이라 줄 세우지 않는 규칙에 걸린다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_default_folder_priority(tmp_path):
    """기본 폴더: 세션에서 왔으면 그 세션 → 마지막으로 시작한 폴더 → 없으면 기본값 없이 목록 펼침. 최근 폴더 첫 줄·다른 세션은 쓰지 않는다. (#667)"""
    other = _session("s9", cwd="C:/other/busy")  # 방금까지 움직인 다른 저장소 세션
    mine = _session("s1", cwd="C:/mine/repo")
    recent = {"GET /api/folders/recent": {"folders": ["C:/other/busy", "C:/mine/repo"]}}
    # 1) 세션 화면에서 왔다
    got = _smoke(tmp_path, "new?from=s1", [other, mine], extra=dict(recent, **{"GET /api/folders/last": {"path": "C:/last/one"}}))
    assert "repo" in got["head"] and "one" not in got["head"] and "작업 폴더는 이 프로젝트로 자동으로 정해져." in got["text"]  # 프로젝트 이름은 헤더(경로 조각이 아니라 이름)
    assert "GET /api/folders/last" not in got["calls"]  # 세션 폴더가 있으면 서버 기억을 묻지 않는다
    # 2) 그냥 새 작업: 서버가 기억한 마지막 폴더
    got = _smoke(tmp_path, "new", [other, mine], extra=dict(recent, **{"GET /api/folders/last": {"path": "C:/last/one"}}))
    assert "one" in got["head"] and "바꾸기" in got["text"] and "프로젝트를 고르" not in got["text"]
    # 3) 둘 다 없으면 기본값 없이 "폴더를 골라 줘 [고르기]" 한 줄(최근 폴더 첫 줄을 쓰지 않는다). 목록은 처음부터 펼치지 않는다(시안 G-05, #721)
    got = _smoke(tmp_path, "new", [other, mine], extra=dict(recent, **{"GET /api/folders/last": {"path": None}}))
    assert "폴더를 골라 줘" in got["text"] and "busy" not in got["head"] and "고르기" in got["text"] and "닫기" not in got["text"]
    assert "C:/other/busy" not in got["text"]  # 후보 목록은 [고르기] 를 눌러야 보인다
    # 4) 새 세션 버튼은 세션 화면에서만 출처 세션을 넘긴다
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "'/new?from=' + encodeURIComponent(sid)" in app and app.count("link(newHref(),") == 5  # 헤더 메뉴 · 목록 아래 + 새 세션 · 접힌 레일 + · Post 레일 새 작업 · Post 목록 아래 + 새 세션
    assert "recent[0]" not in app


def _folder_rows():
    return {"GET /api/folders/recent": [
        {"path": "C:/p/ready2", "name": "ready2", "ready": "yes", "sessions": 2},
        {"path": "C:/p/ready0", "name": "ready0", "ready": "yes", "sessions": 0},
        {"path": "C:/p/needs", "name": "needs", "ready": "no", "sessions": 0},
        {"path": "C:/p/busy", "name": "busy", "ready": "unknown", "checking": True, "sessions": 0},
        {"path": "C:/p/unk", "name": "unk", "ready": "unknown", "checking": False, "sessions": 0}],
        "GET /api/folders/last": {"path": None}}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_folder_cards_show_ready_chips_without_blurring_unknown(tmp_path):
    """폴더 카드 칩(시안 02): 준비됨 · 세션 n / 준비됨 / 준비 필요 / 확인하는 중 / 확인 못 함. 읽지 못한 것은 준비됨도 준비 필요도 아니다."""
    got = _smoke(tmp_path, "new", [], extra=_folder_rows(), actions=[{"click": "[data-folder-toggle]"}])  # 목록은 [고르기] 를 눌러야 펼친다(#721)
    assert re.findall(r"<span\.chip2([\w.]*)>", got["dump"]) == [".ok", ".ok", ".warn", "", ".unk"]
    # 카드 한 장마다 이름 · 경로 · 칩 순서로 글이 이어진다(가짜 DOM 의 dump 는 text 속성 글을 안 보여 줘 본문 글로 본다)
    text = got["text"]
    for card in ("ready2C:/p/ready2준비됨 · 세션 2", "ready0C:/p/ready0준비됨NE","needsC:/p/needs준비 필요", "busyC:/p/busy확인하는 중", "unkC:/p/unk확인 못 함"):
        assert card in text, card
    # 옛 서버 응답(ready 키 없음)은 준비됨으로 치지 않는다
    old = _smoke(tmp_path, "new", [], extra={"GET /api/folders/recent": {"folders": ["C:/w/proj"]}, "GET /api/folders/last": {"path": None}}, actions=[{"click": "[data-folder-toggle]"}])
    assert re.findall(r"<span\.chip2([\w.]*)>", old["dump"]) == [".unk"] and "projC:/w/proj확인 못 함" in old["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_first_pick_of_unready_folder_shows_prepare_screen_and_make_starts_scaffold(tmp_path):
    shown = {"GET /api/folders/intro": {"ready": "no", "seen": False, "show": True, "canSetup": True}, "POST /api/folders/intro/seen": {"seen": True}}
    pick = [{"click": "[data-folder-toggle]"}, {"click": ".folder-opt", "index": 2}]
    got = _smoke(tmp_path, "new", [], extra=dict(_folder_rows(), **shown), actions=pick)
    text = got["text"]
    for need in ("프로젝트 준비", "needs 준비하기", "이 폴더엔 아직 하네스 구조가 없어", "네 차례", "표준 구조를 만들까? 한 번만 하면 돼",
                 "만들고 나면 GitHub에 올려서 팀 승인을 받아. 그다음부터 문서를 쓸 수 있어.", "만들기", "나중에", "만들어지는 것",
                 "templates/", "고객 양식 넣는 곳", "rules/", "문서 검사 기준", "docs/ssot/", "요구사항정의서 자리", "audit/", "변경 기록",
                 "만든 뒤 할 일", "고객 양식 파일을 templates/에 넣기", "GitHub에 올려 승인받기", "첫 작업 시작"):
        assert need in text, need
    assert "하고 싶은 일을 한두 줄로" not in text and "<select" not in got["dump"]
    assert any(p[:2] == ["POST", "/api/folders/intro/seen"] and "C:/p/needs" in p[2] for p in got["posts"])  # 보여 줬다고 서버에 남긴다
    # [만들기] -> 그 폴더에서 scaffold 도구로 새 작업을 시작한다(입력칸에 도구를 넣고 분석을 시작하는 기존 경로)
    made = _smoke(tmp_path, "new", [], extra=dict(_folder_rows(), **shown), actions=pick + [{"click": "[data-intro-make]"}])
    new = [p for p in made["posts"] if p[1] == "/api/new"]
    assert len(new) == 1 and "/harness:scaffold" in new[0][2] and "C:/p/needs" in new[0][2], new
    # [나중에] -> 원래 새 작업 화면으로 돌아가고 작업을 시작하지 않는다
    later = _smoke(tmp_path, "new", [], extra=dict(_folder_rows(), **shown), actions=pick + [{"click": "[data-intro-later]"}])
    assert "하고 싶은 일을 한두 줄로" in later["text"] and "needs" in later["head"] and "작업 폴더는 이 프로젝트로 자동으로 정해져." in later["text"] and "프로젝트 준비" not in later["text"]
    assert not [p for p in later["posts"] if p[1] == "/api/new"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_prepare_screen_for_non_admin_says_ask_admin_without_make_button(tmp_path):
    """준비 안 된 폴더: 관리자가 아니면(false) [만들기]·만들어지는 것 칸 없이 관리자에게 말하라고만 한다. 확인 못 함(null)은 그 사실을 문구 끝에 붙인다."""
    pick = [{"click": "[data-folder-toggle]"}, {"click": ".folder-opt", "index": 2}]
    base = {"ready": "no", "seen": False, "show": True}
    for can, tail in ((False, ""), (None, " (관리자인지 확인하지 못했어)")):
        extra = dict(_folder_rows(), **{"GET /api/folders/intro": dict(base, canSetup=can), "POST /api/folders/intro/seen": {"seen": True}})
        got = _smoke(tmp_path, "new", [], extra=extra, actions=pick)
        assert "이 폴더는 아직 하네스 준비가 안 됐어. 관리자에게 준비해 달라고 말해 줘." + tail in got["text"], can
        for gone in ("만들기", "표준 구조를 만들까", "만들어지는 것", "만든 뒤 할 일", "나중에"):
            assert gone not in got["text"], (can, gone)
        assert "[data-intro-make]" not in got["dump"] and "확인" in got["text"]
        # [확인] -> 원래 새 작업 화면으로 돌아가고 작업을 시작하지 않는다
        back = _smoke(tmp_path, "new", [], extra=extra, actions=pick + [{"click": "[data-intro-ok]"}])
        assert "하고 싶은 일을 한두 줄로" in back["text"] and not [x for x in back["posts"] if x[1] == "/api/new"]
    assert "(관리자인지 확인하지 못했어)" not in _smoke(tmp_path, "new", [], extra=dict(_folder_rows(), **{"GET /api/folders/intro": dict(base, canSetup=False), "POST /api/folders/intro/seen": {"seen": True}}), actions=pick)["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_prepare_screen_shows_checking_line_then_switches_when_admin_is_known(tmp_path):
    """서버가 관리자 여부를 읽는 중이면(adminChecking) 03 은 바로 뜨되 한 줄만 보이고, 다시 물어 결과가 오면 바뀐다. 최종 화면을 그린 뒤에만 seen 을 한 번 남긴다."""
    pick = [{"click": "[data-folder-toggle]"}, {"click": ".folder-opt", "index": 2}]
    checking = {"ready": "no", "seen": False, "show": True, "canSetup": None, "adminChecking": True}
    extra = dict(_folder_rows(), **{"GET /api/folders/intro": checking, "POST /api/folders/intro/seen": {"seen": True}})
    now = _smoke(tmp_path, "new", [], extra=extra, actions=pick)
    assert "관리자인지 확인하는 중이야." in now["text"] and "프로젝트 준비" in now["text"] and "needs 준비하기" in now["text"]
    for gone in ("만들기", "확인하지 못했어", "표준 구조를 만들까", "만들어지는 것"):
        assert gone not in now["text"], gone
    assert "[data-intro-ok]" not in now["dump"] and not [p for p in now["posts"] if p[1] == "/api/folders/intro/seen"]  # 단추도 seen 도 아직 없다
    for can, want, tail in ((True, "표준 구조를 만들까? 한 번만 하면 돼", ""), (False, "관리자에게 준비해 달라고 말해 줘.", ""), (None, "관리자에게 준비해 달라고 말해 줘.", "(관리자인지 확인하지 못했어)")):
        done = {"ready": "no", "seen": False, "show": True, "canSetup": can, "adminChecking": False}
        got = _smoke(tmp_path, "new", [], extra=extra, actions=pick + [{"set": {"GET /api/folders/intro": done}}, {"wait": 1800}])
        assert want in got["text"] and "확인하는 중이야" not in got["text"] and tail in got["text"], can
        assert len([p for p in got["posts"] if p[1] == "/api/folders/intro/seen"]) == 1, can
    # 10번을 다시 물어도 못 읽으면 확인 못 함 화면(여기선 시간을 줄일 수 없어 코드 상수만 확인한다)
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "INTRO_MAX_TRIES = 10" in app and "setTimeout(function () { askIntro(p); }, 1500)" in app


def _review_extra(flow, **kw):
    """분석이 끝난 새 작업 화면(new?id=A1)을 흉내 내는 서버 답."""
    return dict({"GET /api/new/A1": {"status": "ready", "cwd": "C:/w/proj", "text": "요구사항을 쓰자", "result": {
        "understood": "요구사항을 이해했어", "candidates": [], "extraQuestions": [], "flow": flow}},
        "POST /api/new/A1/start": {"id": "s9"}}, **kw)


_CONFIDENT_FLOW = {"id": "srs", "name": "요구사항", "confident": True, "reason": "r"}
_UNSURE_FLOW = {"id": "xx", "name": "이름X", "confident": False, "alternativeId": "yy", "alternativeName": "이름Y", "reason": "r"}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_start_success_moves_to_the_session_screen(tmp_path):
    got = _smoke(tmp_path, "new?id=A1", [_session("s9")], extra=_review_extra(_CONFIDENT_FLOW), actions=[{"click": ".pill.dark.big"}])
    assert [x[1] for x in got["posts"] if "/start" in x[1]] == ["/api/new/A1/start"]
    assert got["path"] == "/s/s9" and "작업을 시작했어" not in got["text"] and "작업 화면으로 이동" not in got["text"]
    # 시작 답에 id 가 없으면 옛 링크 한 줄로 남는다(이동할 곳을 모른다)
    noid = _smoke(tmp_path, "new?id=A1", [], extra=_review_extra(_CONFIDENT_FLOW, **{"POST /api/new/A1/start": {}}), actions=[{"click": ".pill.dark.big"}])
    assert noid["path"] == "/new" and "작업을 시작했어." in noid["text"] and "작업 화면으로 이동" in noid["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_unsure_classification_blocks_start_until_user_picks_and_uses_server_names(tmp_path):
    extra = _review_extra(_UNSURE_FLOW)
    got = _smoke(tmp_path, "new?id=A1", [], extra=extra)
    assert "어느 쪽에 더 가까운지 위에서 먼저 골라 줘." in got["text"]
    assert "이름X" in got["text"] and "이름Y" in got["text"] and "xx" not in got["text"] and "yy" not in got["text"]  # id 대신 서버가 준 이름
    assert got["ariaDisabled"] == ["이대로 시작"] and "이대로 시작" not in got["disabledButtons"]  # disabled 가 아니라 aria-disabled
    # 막힌 단추를 누르면 시작하지 않고 고르는 카드로 화면을 옮기고 그 안 첫 단추에 초점을 둔다
    pressed = _smoke(tmp_path, "new?id=A1", [], extra=extra, actions=[{"click": ".pill.dark.big"}])
    assert not [x for x in pressed["posts"] if "/start" in x[1]] and pressed["scrolled"] == [["flowchoose", '{"block":"center"}']] and pressed["active"] == ["button", "xx"]
    # 칩을 고르면 풀려서 시작된다
    picked = _smoke(tmp_path, "new?id=A1", [_session("s9")], extra=extra, actions=[{"click": "[data-flow=yy]"}, {"click": ".pill.dark.big"}])
    assert [x[1] for x in picked["posts"] if "/start" in x[1]] == ["/api/new/A1/start"] and picked["path"] == "/s/s9"
    # 확신하는 분류는 막지 않는다
    assert _smoke(tmp_path, "new?id=A1", [], extra=_review_extra(_CONFIDENT_FLOW))["ariaDisabled"] == []


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_unknown_kind_says_ai_decides_the_order_and_same_folder_warning_counts_only_working_sessions(tmp_path):
    unknown = [{"click": "[data-kind]", "index": 8}]  # 종류 칸 아홉 개 중 아홉째가 '잘 모르겠어'
    got = _smoke(tmp_path, "new", [], extra={"GET /api/folders/last": {"path": "C:/w/proj"}}, actions=unknown)
    assert "AI가 요청을 읽고 어떤 순서로 할지 정해 줘." in got["text"] and "그 도구 스킬로 바로 시작해" not in got["text"]
    tool = _smoke(tmp_path, "new", [], extra={"GET /api/folders/last": {"path": "C:/w/proj"}}, actions=[{"click": "[data-kind]", "index": 2}])  # 사용자 매뉴얼
    assert "정해진 순서 없이 그 도구 스킬로 바로 시작해." in tool["text"]  # 도구 스킬 종류는 그대로
    last = {"GET /api/folders/last": {"path": "C:/w/proj"}}
    for status, warn in (("idle", False), ("waiting", False), ("ended", False), ("running", True), ("starting", True)):
        got = _smoke(tmp_path, "new", [_session("s1", status=status)], extra=last)
        assert ("다른 세션이 일하고 있어" in got["text"]) is warn, status


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_new_task_prepare_screen_not_shown_when_seen_ready_or_unknown(tmp_path):
    for state in ({"ready": "no", "seen": True, "show": False}, {"ready": "yes", "seen": False, "show": False},
                  {"ready": "unknown", "seen": False, "show": False}):
        got = _smoke(tmp_path, "new", [], extra=dict(_folder_rows(), **{"GET /api/folders/intro": state}), actions=[{"click": "[data-folder-toggle]"}, {"click": ".folder-opt", "index": 2}])
        assert "하고 싶은 일을 한두 줄로" in got["text"] and "준비하기" not in got["text"], state
        assert not [p for p in got["posts"] if p[1] == "/api/folders/intro/seen"], state
    # 안내를 못 읽으면(오류) 막지 않고 원래 화면으로 간다
    err = _smoke(tmp_path, "new", [], extra=_folder_rows(), actions=[{"click": "[data-folder-toggle]"}, {"click": ".folder-opt", "index": 2}])
    assert "하고 싶은 일을 한두 줄로" in err["text"] and "준비하기" not in err["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_docs_screen_groups_files_and_has_menu(tmp_path):
    got = _smoke(tmp_path, "docs", [_session("s1")])
    for need in ("내가 만든 문서", "아직 양식으로 뽑은 산출물이 없어."):  # #1067: 기본 시험 세션의 파일은 SRS.md 하나뿐이라 양식 파일이 없다
        assert need in got["text"], need
    assert "SRS.md" not in got["text"] and "요구사항 · 설계" not in got["text"]
    assert "산출물" in got["head"] and "GET /api/sessions/s1/files?cache=1" in got["calls"]  # 새 서버 API 없이 세션별 문서 목록을 모은다(서버 기억을 쓰는 ?cache=1, #793)


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_settings_screen_matches_design(tmp_path):
    got = _smoke(tmp_path, "settings", [_session("s1")])
    text, dump = got["text"], got["dump"]
    for need in ("보기와 알림", "글자 크기", "작게", "보통", "크게", "AI가 묻는 범위", "연결 상태", "GitHub", "하네스 판", "프로젝트", "고급", "AI 모델", "생각 깊이"):
        assert need in text, need
    assert dump.count("<button.scale>") == 3 and dump.count("<button.radio>") >= 1  # 시안 .seg / .radio 모양, 기본 위젯 없음
    assert "<select" not in dump and "<input" not in dump
    assert "화면 밝기" not in text  # 다크 한 벌뿐이라 넣지 않았다
    assert dump.count("<button.swrow>") == 4 and "내 차례가 오면" in text and "헤더에 계정 한도 보이기" in text  # 알림 스위치 셋(#651, 별도 시험에서 본다) + 한도 표시 하나(#1039)
    assert "연결돼 있어" in text and "준비 여부 확인 못 함" in text  # 조건 값이 없으면 준비됐다고 단정하지 않는다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_settings_ask_range_has_three_steps_tied_to_server_and_default_permission_has_auto(tmp_path):
    perms = {"GET /api/models": {"options": [{"value": "", "label": "기본"}], "effortOptions": [{"value": "", "label": "기본"}],
                                 "permissionOptions": [{"value": "", "label": "기본(그때그때 확인)"}, {"value": "acceptEdits", "label": "파일 고치기는 자동 허용"},
                                                       {"value": "plan", "label": "계획만 세우기"}, {"value": "auto", "label": "알아서 하되 위험한 건 AI가 막기"}]}}
    got = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(perms, **{"GET /api/settings/ask": {"level": "needed"}}))
    text, dump = got["text"], got["dump"]
    for need in ("AI가 묻는 범위", "꼭 필요할 때만 (권장)", "문서를 바꿀 때마다", "모든 명령마다",
                 "어떤 걸 골라도 위험한 일(main에 바로 올리기 · 강제 덮어쓰기 · SAP 운영 쓰기)은 하네스가 막아."):
        assert need in text, need
    # 시안 G-19: 설정엔 "AI가 묻는 범위" 하나만. 권한 모드(계획만·auto 포함)는 새 작업 고급 설정에서 고른다
    assert "기본 권한" not in text and "data-perm-opt" not in dump
    new = _smoke(tmp_path, "new", [], extra=perms)
    assert "권한 모드" in new["text"] and "<select.input>" in new["dump"]  # 새 작업 고급 설정의 권한 모드 고르기(선택지는 /api/models 의 permissionOptions)
    assert "GET /api/settings/ask" in got["calls"]
    assert text.count("꼭 필요할 때만") == 1
    # 단계를 누르면 서버에 저장한다
    pick = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(perms, **{"GET /api/settings/ask": {"level": "needed"}, "PUT /api/settings/ask": {"level": "edits"}}),
                  actions=[{"click": "[data-ask-opt=edits]"}])
    assert any(p[0] == "PUT" and p[1] == "/api/settings/ask" and '"level":"edits"' in p[2].replace(" ", "") for p in pick["posts"]), pick["posts"]
    # 서버가 설정 파일을 못 읽어 가장 엄격한 단계로 물러났으면 그 이유를 보인다
    strict = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(perms, **{"GET /api/settings/ask": {"level": "all", "problem": "설정을 읽지 못해 모든 명령마다 물어"}}))
    assert "설정을 읽지 못해 모든 명령마다 물어" in strict["text"]
    assert "설정을 읽지 못해" not in text  # 정상이면 안 보인다
    # 서버 설정을 읽지 못하면 고르지 못하게 둔다(고른 척하지 않는다)
    broken = _smoke(tmp_path, "settings", [_session("s1")], extra=perms)
    assert "묻는 범위를 읽지 못했어" in broken["text"]
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "value: 'bypassPermissions'" not in app and "dangerously-skip-permissions" not in app  # bypass 는 고를 수 없다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_header_project_follows_the_folder_on_screen(tmp_path):
    other = _session("s1", cwd="C:/other/templete-func", repo="templete-func")
    got = _smoke(tmp_path, "new", [other], extra={"GET /api/folders/last": {"path": "C:/w/proj"}})
    assert "proj" in got["head"] and "w/proj" not in got["head"] and "templete-func" not in got["head"]  # 새 작업은 고른 작업 폴더를 따른다(가장 위 세션 것이 아니다)
    got = _smoke(tmp_path, "s/s1", [other])
    assert "templete-func" in got["head"]
    got = _smoke(tmp_path, "settings", [other, _session("s2", cwd="C:/w/proj")])
    assert "templete-func" not in got["head"] and "proj" not in got["head"].replace("프로젝트", "")  # 프로젝트가 여럿이면 비운다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_session_screen_checks_card_blocked_card_and_fold(tmp_path):
    checks = [{"id": "sync", "state": "done"}, {"id": "version", "state": "pending"}]
    got = _smoke(tmp_path, "s/s1", [_session("s1", startChecks=checks, flowPr=dict(_PR, checks="fail"))])
    dump, text = got["dump"], got["text"]
    assert dump.index("<section.light.talk>") < dump.index("<div.msgs>") < dump.index("<div.q.startchecks>") < dump.index("<div.msgs-list>")  # 시작 점검은 대화 맨 위 ✓ 줄 카드(같은 .msgs 안)
    assert "<div.crow.ok>" in dump and "<div.crow.todo>" in dump and "시작 점검 · 자동" in text
    assert "<div.q.prcard.blocked>" in dump and "✕ 막힘" in text and "<div.q.prcard.unsure>" not in dump  # (아래 표시 약속 범례에도 같은 글이 있어 카드 모양으로 가린다)
    # 시안에 없는 옛 칸은 모두 "자세히" 안으로 접힌다(기능은 그대로)
    fold = dump.index("<details.more.fold>")
    for block in ("<section.toolsrow>", "<select.input>", "<section.mt-64>", "<details.tech>"):  # 도구 줄 · 권한 모드 · 기록 · 기술 정보
        assert dump.count(block) == 1 and dump.index(block) > fold, block
    for need in ("자세히 (도구", "권한 모드", "이 세션에서 일어난 일", "기술 정보 보기"):
        assert need in text, need
    assert dump.index("<section.light.talk>") < fold
    got = _smoke(tmp_path, "s/s1", [_session("s1", flowPr=dict(_PR, checks="none"))])
    assert "<div.q.prcard.unsure>" in got["dump"] and "? 확인 못 함" in got["text"] and "통과도 실패도 아니야" in got["text"]


def test_third_chunk_css_and_legend():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for needle in (".q.blocked", ".q.unsure", ".tagx.fail", ".tagx.unk", ".seg button", ".radio", ".rd.on", ".dgrid", ".drow", ".chip2", ".legend", ".dresult", ".folder-opt.proj"):
        assert needle in css, needle
    assert "border: 2px solid var(--danger)" in css and "border: 2px dashed var(--st-unk)" in css  # 막힘 = 빨간 실선, 확인 못 함 = 보라 점선
    ui = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    assert "표시 약속" in ui and "✕ 막힘" in ui and "? 확인 못 함" in ui and "내 차례" in ui


def test_work_screen_css_blocks_and_responsive_rules():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for needle in (".sess-grid", ".strip", ".msgs", ".ask", ".qopt", ".bad", ".todo", ".crow", ".flow", ".fs", ".docs-pane", "details.more"):
        assert needle in css, needle
    # 시안 .split: 넓을 때 옆, 좁을 때 줄바꿈으로 아래(flex-wrap)
    assert re.search(r"\.sess-grid \{ display: flex; flex-wrap: wrap; gap: 18px;", css) and ".sess-grid > .talk { flex: 999 1 480px;" in css
    assert re.search(r"@container shell \(max-width: 760px\) \{ \.iso \{ display: none; \} \}", css)  # 좁은 창에서는 층 그림을 숨긴다
    assert "details.more > summary::-webkit-details-marker { display: none; }" in css  # 접힘 삼각형은 직접 그린다


# 첫 화면(시안 01) 시험용 점검 결과
_OK_CHECKS = [{"id": "github", "name": "GitHub 연결", "state": "ok", "detail": "me"},
              {"id": "version", "name": "하네스 판", "state": "ok", "detail": "0.10.168"},
              {"id": "claude", "name": "Claude Code 로그인", "state": "unknown", "detail": "확인 못 함 · 콘솔이 로그인 상태를 읽을 수 없어"}]


def _start(**kw):
    return {"GET /api/start-checks": dict({"firstRun": False, "loading": False, "blocking": False, "newVersion": None, "checks": _OK_CHECKS}, **kw)}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_intro_screen_first_run_and_blocking(tmp_path):
    got = _smoke(tmp_path, "", [_session("s1")], extra=_start(firstRun=True))
    text, dump = got["text"], got["dump"]
    for need in ("처음 열었어", "Blueward Harness에 온 걸 환영해", "GitHub 연결", "하네스 판", "Claude Code 로그인", "확인 못 함", "이렇게 써", "프로젝트 고르기", "시작하기"):
        assert need in text, need
    assert "<div.crow.ok>" in dump and "<div.crow.unk>" in dump and "다시 점검" not in text  # 확인 못 함은 ? 줄, 문제로 치지 않는다
    assert "<div.ptitle>" not in dump and "<section.light.intro-box>" in dump  # 홈을 그리지 않고 가운데 판 하나(헤더·목록은 CSS 가 숨긴다)
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert '#app[data-intro="1"] .top' in css and '#app[data-intro="1"] .side' in css
    blocked = [dict(_OK_CHECKS[0], state="fail", detail="로그인이 안 돼 있어", fix="터미널에서 gh auth login 을 하고 다시 점검해 줘.")] + _OK_CHECKS[1:]
    got = _smoke(tmp_path, "", [_session("s1")], extra=_start(blocking=True, checks=blocked))  # 첫 실행이 아니어도 막는 문제면 뜬다
    assert "먼저 고칠 게 있어" in got["text"] and "gh auth login" in got["text"] and "다시 점검" in got["text"] and "<div.crow.fail>" in got["dump"]
    assert "시작하기" not in got["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_intro_not_shown_after_first_run_and_old_version_is_a_strip(tmp_path):
    got = _smoke(tmp_path, "", [_session("s1")], extra=_start())
    assert "처음 열었어" not in got["text"] and "시작하기" not in got["text"]  # 이미 본 PC 는 홈이 그대로 열린다
    got = _smoke(tmp_path, "", [_session("s1", pendingRequestIds=["q1"])], extra=_start(newVersion="0.10.169"),
                 requests=[{"id": "q1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "ls"}}])
    assert "하네스 새 판 0.10.169" in got["ann"] and "/harness:update" in got["ann"] and "내 차례" in got["ann"]  # 내 차례 띠와 함께 둘 다 보인다
    got = _smoke(tmp_path, "settings", [_session("s1")], extra=_start())
    assert "처음 화면 다시 보기" in got["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_first_run_start_leads_to_project_pick_then_home_or_prepare_screen(tmp_path):
    """시안 G-01 -> G-02: [시작하기] 는 바로 홈이 아니라 프로젝트 고르기로 간다. 확정은 [이 프로젝트로]."""
    extra = dict(_folder_rows(), **_start(firstRun=True), **{"POST /api/folders/last": {"path": "C:/p/ready2", "name": "ready2"}, "POST /api/start-checks/seen": {"firstRun": False}})
    start = [{"click": "[data-intro-start]"}]
    got = _smoke(tmp_path, "", [], extra=extra, actions=start)
    text, dump = got["text"], got["dump"]
    for need in ("1단계 · 프로젝트", "어느 고객사 프로젝트에서 일할까?", "최근에 쓴 폴더야. 처음이면 GitHub에서 받은 고객사 저장소 폴더를 골라.",
                 "ready2C:/p/ready2준비됨 · 세션 2", "needsC:/p/needs준비 필요", "다른 폴더 찾아보기", "뒤로", "이 프로젝트로"):
        assert need in text, need
    assert "환영해" not in text and not got["posts"]  # 아직 아무것도 기억시키지 않았다
    assert "data-pick-ok" in (STATIC / "app.js").read_text(encoding="utf-8") and "disabled: !sel || busy" in (STATIC / "app.js").read_text(encoding="utf-8")  # 고르기 전에는 [이 프로젝트로] 가 막혀 있다
    assert "REready2" in text and "NEneeds" in text  # 머리글자: 한 단어면 앞 두 글자(시안 G-02: 단어가 둘이면 단어 첫 글자 HC·PC)
    # 시안 G-02: 첫 줄(가장 최근 폴더)이 처음부터 골라져 있어 아무것도 안 눌러도 [이 프로젝트로] 를 누를 수 있다
    pre = _smoke(tmp_path, "", [], extra=extra, actions=start + [{"click": "[data-pick-ok]"}])
    assert any("/api/folders/last" in str(p_) for p_ in pre["posts"]), pre["posts"]
    # 카드를 눌러도 확정되지 않는다
    sel = _smoke(tmp_path, "", [], extra=extra, actions=start + [{"click": "[data-pick-folder]", "index": 0}])
    assert not sel["posts"]
    # [이 프로젝트로] -> 마지막 폴더 기억 + 첫 실행 표시, 준비된 폴더면 홈으로
    ok = _smoke(tmp_path, "", [], extra=extra, actions=start + [{"click": "[data-pick-folder]", "index": 0}, {"click": "[data-pick-ok]"}])
    posts = [(p[0], p[1]) for p in ok["posts"]]
    assert ("POST", "/api/folders/last") in posts and ("POST", "/api/start-checks/seen") in posts
    assert "C:/p/ready2" in [p[2] for p in ok["posts"] if p[1] == "/api/folders/last"][0] and ok["path"] == "/"
    assert "1단계 · 프로젝트" not in ok["text"]
    # 준비 안 됨 + 안내를 아직 안 봤으면 새 작업 화면의 프로젝트 준비(03)
    shown = dict(extra, **{"GET /api/folders/intro": {"ready": "no", "seen": False, "show": True}, "POST /api/folders/intro/seen": {"seen": True},
                           "POST /api/folders/last": {"path": "C:/p/needs", "name": "needs"}})
    prep = _smoke(tmp_path, "", [], extra=shown, actions=start + [{"click": "[data-pick-folder]", "index": 2}, {"click": "[data-pick-ok]"}])
    assert prep["path"] == "/new" and "needs 준비하기" in prep["text"] and "이 폴더엔 아직 하네스 구조가 없어" in prep["text"]
    # 안내를 이미 봤으면 홈
    seen = dict(shown, **{"GET /api/folders/intro": {"ready": "no", "seen": True, "show": False}})
    home = _smoke(tmp_path, "", [], extra=seen, actions=start + [{"click": "[data-pick-folder]", "index": 2}, {"click": "[data-pick-ok]"}])
    assert home["path"] == "/" and "준비하기" not in home["text"]
    # [뒤로] -> 01
    back = _smoke(tmp_path, "", [], extra=extra, actions=start + [{"click": "[data-pick-back]"}])
    assert "환영해" in back["text"] and "시작하기" in back["text"] and not back["posts"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_project_pick_without_recent_folders_and_settings_replay(tmp_path):
    empty = dict(_start(firstRun=True), **{"GET /api/folders/recent": {"folders": []}})
    got = _smoke(tmp_path, "", [], extra=empty, actions=[{"click": "[data-intro-start]"}])
    assert "다른 폴더 찾아보기" in got["text"] and "<div.inline-row>" not in got["dump"] and "사용" not in got["text"]  # 시안 G-02: 경로 입력칸 없이 찾아보기만(선택 창을 못 열 때만 입력칸) and "<button.folder-opt.proj>" not in got["dump"]
    # 설정의 "처음 화면 다시 보기" 도 01 부터 시작해 02 로 이어진다
    again = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_start(), **_folder_rows()), actions=[{"click": "[data-intro-again]"}, {"click": "[data-intro-start]"}])
    assert "어느 고객사 프로젝트에서 일할까?" in again["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_empty_home_subtitle_names_the_remembered_ready_project(tmp_path):
    ready = dict(_folder_rows(), **{"GET /api/folders/last": {"path": "C:/p/ready2", "name": "ready2"}})
    assert "프로젝트 준비 끝 · ready2" in _smoke(tmp_path, "", [], extra=ready)["text"]
    needs = dict(_folder_rows(), **{"GET /api/folders/last": {"path": "C:/p/needs", "name": "needs"}})
    assert "프로젝트 준비 끝" not in _smoke(tmp_path, "", [], extra=needs)["text"]
    assert "Claude Code 세션을 시작하면" in _smoke(tmp_path, "", [], extra=_folder_rows())["text"]  # 기억한 폴더가 없으면 지금 문구 그대로


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_question_and_permission_screens_show_chat_and_say_box(tmp_path):
    chat = [{"t": 1, "role": "me", "text": "구매오더 앱 써 줘"}, {"t": 2, "role": "ai", "text": "두 가지만 물어볼게."}]
    q = {"id": "q1", "sessionId": "s1", "kind": "question", "status": "pending",
         "questions": [{"question": "얼마나 급해?", "header": "우선순위", "options": [{"label": "반드시 필요"}]}]}
    got = _smoke(tmp_path, "r/q1", [_session("s1", pendingRequestIds=["q1"], chat=chat)], [q])
    dump, text = got["dump"], got["text"]
    assert "구매오더 앱 써 줘" in text and "두 가지만 물어볼게." in text and "AI에게 말하기" in text
    assert text.index("구매오더 앱 써 줘") < text.index("얼마나 급해?") < text.index("답 보내기") < text.index("AI에게 말하기")  # 대화 -> 질문 카드 -> 답 보내기 -> 말하기
    assert "<input.input.q-other>" in dump and "<label.sr-only>" in dump and "다른 답이 있으면 직접 적어 줘" in text  # 보이는 글 없이 입력칸 하나(label 은 sr-only)
    # 보낼 수 없는 세션은 입력창이 막히고 이유가 보인다
    no = _smoke(tmp_path, "r/q1", [_session("s1", pendingRequestIds=["q1"], chat=chat, canSend=False, cannotSendReason="터미널에서 연 세션이라 콘솔에서 말할 수 없어.")], [q])
    assert "터미널에서 연 세션이라 콘솔에서 말할 수 없어." in no["text"]


def _wn(*versions, current="0.10.186"):
    return {"GET /api/whats-new": {"current": current, "seen": "0.10.180", "items": [{"version": v, "lines": ls} for v, ls in versions]}}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_whats_new_card_text_and_ok_button_posts_seen(tmp_path):
    extra = dict(_start(), **_wn(("0.10.186", ["첫 줄이야"]), ("0.10.185", ["둘째 줄이야", "셋째 줄이야"])), **{"POST /api/whats-new/seen": {"seen": "0.10.186"}})
    got = _smoke(tmp_path, "", [_session("s1")], extra=extra)
    for need in ("하네스가 새로 바뀌었어 · 이번에 바뀐 것", "첫 줄이야", "둘째 줄이야", "알겠어"):
        assert need in got["text"], need
    assert "0.10.186" not in got["text"] and "0.10.185" not in got["text"]  # 판 번호는 글로 보이지 않는다(#794)
    assert "더 보기" not in got["text"]
    done = _smoke(tmp_path, "", [_session("s1")], extra=extra, actions=[{"click": "[data-wn-ok]"}])
    assert ["POST", "/api/whats-new/seen", "{}"] in [list(p) for p in done["posts"]]
    assert "이번에 바뀐 것" not in done["text"] and "첫 줄이야" not in done["text"]  # 누르면 카드가 닫힌다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_whats_new_card_hidden_when_empty_or_first_run_and_folds_long_lists(tmp_path):
    assert "이번에 바뀐 것" not in _smoke(tmp_path, "", [_session("s1")], extra=dict(_start(), **_wn()))["text"]  # 줄이 없으면 안 뜬다
    first = _smoke(tmp_path, "", [_session("s1")], extra=dict(_start(firstRun=True), **_wn(("0.10.186", ["첫 줄이야"]))))
    assert "첫 줄이야" not in first["text"] and "GET /api/whats-new" not in first["calls"]  # 첫 실행 화면이 뜨는 동안엔 묻지도 않는다
    long = dict(_start(), **_wn(("0.10.186", [f"가{i}줄" for i in range(5)]), ("0.10.185", [f"나{i}줄" for i in range(5)])))
    got = _smoke(tmp_path, "", [_session("s1")], extra=long)
    assert "가0줄" in got["text"] and "나0줄" not in got["text"] and "더 보기" in got["text"]
    more = _smoke(tmp_path, "", [_session("s1")], extra=long, actions=[{"click": "[data-wn-more]"}])
    assert "나0줄" in more["text"] and "더 보기" not in more["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_memory_banner_ring_and_unknown_cases(tmp_path):
    hot = {"tokens": 920000, "window": 1000000, "pct": 92}
    got = _smoke(tmp_path, "s/s1", [_session("s1", context=hot)])
    assert "이 세션 기억이 거의 찼어 (92%)" in got["text"] and "새 세션으로 넘기기" in got["text"] and "계속하기" in got["text"]
    assert "<span.ring.pct.hot>" in got["sideDump"] and "기억92%" not in got["text"]  # 링(사이드바)은 빨강, 숫자 띠에 기억 칸은 없다
    # 80% 초과 90% 미만은 노랑 링, 배너는 없다
    got = _smoke(tmp_path, "s/s1", [_session("s1", context={"tokens": 850000, "window": 1000000, "pct": 85})])
    assert "<span.ring.pct.warn>" in got["sideDump"] and "기억이 거의 찼어" not in got["text"]
    # 64% 는 기본 링
    got = _smoke(tmp_path, "s/s1", [_session("s1", context={"tokens": 640000, "window": 1000000, "pct": 64})])
    assert "<span.ring.pct>" in got["sideDump"] and "기억이 거의 찼어" not in got["text"]
    # 창 크기를 모르면 % 없이 토큰 수만, 배너 없음
    got = _smoke(tmp_path, "s/s1", [_session("s1", context={"tokens": 241482, "window": None, "pct": None})])
    assert "기억이 거의 찼어" not in got["text"] and "<span.ring.unk>" in got["sideDump"]
    # 읽지 못했으면 지금처럼 ? 와 확인 못 함
    got = _smoke(tmp_path, "s/s1", [_session("s1")])
    assert "<span.ring.unk>" in got["sideDump"] and "기억이 거의 찼어" not in got["text"]
    # 터미널 세션은 넘기기 버튼 없이 안내만
    got = _smoke(tmp_path, "s/s1", [_session("s1", managed=False, context=hot)])
    assert "기억이 거의 찼어" in got["text"] and "새 세션으로 넘기기" not in got["text"] and "/harness:handoff" in got["text"]
    # 홈 표의 기억 열
    got = _smoke(tmp_path, "", [_session("s1", context=hot)])
    assert "92%" in got["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_memory_banner_compact_button_states_and_chat_note(tmp_path):
    """#863: 콘솔 세션의 기억 배너와 자세히 > 기억 칸에 [요약해서 계속하기]. 일하는 중·요약 중에는 보내지 않고, 터미널 세션엔 없다."""
    hot = {"tokens": 920000, "window": 1000000, "pct": 92}
    url = "POST /api/sessions/s1/compact"
    idle = _smoke(tmp_path, "s/s1", [_session("s1", context=hot)], extra={url: {"ok": True}}, actions=[{"click": ".mem-compact"}])
    assert "요약해서 계속하기" in idle["text"] and "새 세션으로 넘기기" in idle["text"]
    assert [p[1] for p in idle["posts"] if p[1].endswith("/compact")] == ["/api/sessions/s1/compact"]
    assert "기억 요약92% 사용(92만 토큰)" in idle["text"]  # 자세히 안의 기억 칸
    panel = _smoke(tmp_path, "s/s1", [_session("s1", context=hot)], extra={url: {"ok": True}}, actions=[{"click": "[data-compact]", "index": 1}])  # 0 은 배너, 1 은 자세히 안의 기억 칸
    assert any(p[1].endswith("/compact") for p in panel["posts"])
    working = _smoke(tmp_path, "s/s1", [_session("s1", status="running", context=hot)], extra={url: {"ok": True}}, actions=[{"click": ".mem-compact"}])
    assert not any(p[1].endswith("/compact") for p in working["posts"])  # 일하는 중에는 보내지 않는다
    squeezing = _smoke(tmp_path, "s/s1", [_session("s1", status="running", currentAction="Compact", compact={"state": "running"}, context=hot)],
                       extra={url: {"ok": True}}, actions=[{"click": ".mem-compact"}])
    assert "기억을 요약하는 중이야" in squeezing["text"] and "요약하는 중…" in squeezing["text"]
    assert not any(p[1].endswith("/compact") for p in squeezing["posts"])
    failed = _smoke(tmp_path, "s/s1", [_session("s1", context=hot, compact={"state": "failed", "reason": "x"})])
    assert "지난번 요약은 실패했어" in failed["text"]
    term = _smoke(tmp_path, "s/s1", [_session("s1", managed=False, context=hot)])
    assert "요약해서 계속하기" not in term["text"] and "/harness:handoff" in term["text"]
    chat = [{"t": 1, "role": "me", "text": "요약해 줘"}, {"t": 2, "role": "note", "text": "기억을 요약했어 · 35,779 → 8,449 토큰", "tone": "ok"},
            {"t": 3, "role": "note", "text": "기억을 요약하지 못했어", "tone": "bad"}]
    noted = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)])
    assert "기억을 요약했어 · 35,779 → 8,449 토큰" in noted["text"] and "<div.reqnote.chat-note>" in noted["dump"] and "기억을 요약하지 못했어" in noted["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_first_run_start_survives_reload_and_memory_banner_stays_closed(tmp_path):
    """#796: 시작하기 뒤 새로고침하면 01 이 아니라 02, 계속하기는 새로고침해도 닫은 채."""
    extra = dict(_folder_rows(), **_start(firstRun=True))
    started = _smoke(tmp_path, "", [], extra=extra, actions=[{"click": "[data-intro-start]"}])
    assert started["ls"].get("bh-intro-page") == "project"
    reloaded = _smoke(tmp_path, "", [], extra=extra, ls=started["ls"])
    assert "어느 고객사 프로젝트에서 일할까?" in reloaded["text"] and "환영해" not in reloaded["text"]
    back = _smoke(tmp_path, "", [], extra=extra, ls=started["ls"], actions=[{"click": "[data-pick-back]"}])
    assert "환영해" in back["text"] and "bh-intro-page" not in back["ls"]
    done = _smoke(tmp_path, "", [], extra=dict(extra, **{"POST /api/folders/last": {"path": "C:/p/ready2", "name": "ready2"}, "POST /api/start-checks/seen": {"firstRun": False}}),
                  ls=started["ls"], actions=[{"click": "[data-pick-folder]", "index": 0}, {"click": "[data-pick-ok]"}])
    assert "bh-intro-page" not in done["ls"]
    # 기억 90% 배너: 계속하기 -> 새로고침해도 닫힘, 다른 세션은 그대로 뜬다
    hot = {"tokens": 920000, "window": 1000000, "pct": 92}
    first = _smoke(tmp_path, "s/s1", [_session("s1", context=hot)], actions=[{"click": ".mem-stay"}])
    assert "기억이 거의 찼어" not in first["text"] and first["ls"].get("bh-mem-ok:s1") == "1"
    again = _smoke(tmp_path, "s/s1", [_session("s1", context=hot)], ls=first["ls"])
    assert "기억이 거의 찼어" not in again["text"]
    other = _smoke(tmp_path, "s/s2", [_session("s2", context=hot)], ls=first["ls"])
    assert "기억이 거의 찼어" in other["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_chat_draws_hook_block_cards_two_kinds_and_fix_button(tmp_path):
    chat = [{"t": 1, "role": "me", "text": "문서 써 줘"},
            {"t": 2, "role": "block", "hook": "pre_write_guard", "kind": "blocked", "tool": "Write",
             "text": "문서가 템플릿을 따르지 않습니다. 개요 절이 없습니다.\n자세한 위반 목록입니다.\n\n다음: 개요 절을 추가하십시오.", "fix": "개요 절을 추가하십시오."},
            {"t": 3, "role": "block", "hook": "stop-deliver", "kind": "cannot_check", "text": "엔진을 받지 못해 검사 불능입니다.", "fix": ""}]
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)])
    text, dump = got["text"], got["dump"]
    assert "<div.bad.q.blocked>" in dump and "<div.bad.q.unsure>" in dump
    assert "✕ 막힘" in text and "하네스 검사가 막았어 · 파일 쓰기 검사" in text
    assert "? 확인 못 함" in text and "검사를 못 해서 멈췄어 · 마무리 확인" in text
    assert "문서가 템플릿을 따르지 않습니다." in text and "자세한 위반 목록입니다." not in text  # 첫 문장만 크게, 나머지는 접힘
    assert "고치는 법: 개요 절을 추가하십시오." in text
    # 시안 G-16 단추: 막힘 [그렇게 고쳐 줘] [내가 직접 볼게] [검사 원문] / 확인 못 함 [검사 다시 돌리기] [관리자에게 알리기]
    assert text.count("그렇게 고쳐 줘") == 1 and "내가 직접 볼게" in text and "검사 원문" in text
    assert "검사 다시 돌리기" in text and "관리자에게 알리기" in text
    assert "<button.pill.dark>" in dump and "<button.pill.dark.sm>" not in dump  # 보내는 단추는 시안의 진한 단추(보통 크기)
    unsent = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat, canSend=False)])
    assert "그렇게 고쳐 줘" not in unsent["text"] and "검사 다시 돌리기" not in unsent["text"] and "✕ 막힘" in unsent["text"]
    assert "내가 직접 볼게" in unsent["text"] and "관리자에게 알리기" in unsent["text"]  # 보내지 않는 단추는 남는다
    mine = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)], actions=[{"click": "[data-block-self]"}])
    assert "직접 보기로 했어." in mine["text"] and mine["text"].count("내가 직접 볼게") == 0
    unknown = _smoke(tmp_path, "s/s1", [_session("s1", chat=[dict(chat[1], hook="새_훅")])])
    assert "하네스 검사가 막았어 · 새_훅" in unknown["text"]  # 이름표에 없는 한글 이름은 원래 이름
    english = _smoke(tmp_path, "s/s1", [_session("s1", chat=[dict(chat[1], hook="activation_gate", text="비활성 오브젝트가 있습니다. inactiveObjects 로 확인하십시오.", fix="inactiveObjects 로 확인하십시오.")])])
    assert "하네스 검사가 막았어 · 활성화 확인" in english["text"] and "inactiveObjects" not in english["text"] and "activation_gate" not in english["text"]  # 영문 이름은 카드에 안 나온다(#794)
    opened = _smoke(tmp_path, "s/s1", [_session("s1", chat=[dict(chat[1], hook="activation_gate", text="비활성 오브젝트가 있습니다. inactiveObjects 로 확인하십시오.", fix="inactiveObjects 로 확인하십시오.")])], actions=[{"click": "[data-block-raw]"}])
    assert "inactiveObjects" in opened["text"]  # 원문은 [검사 원문] 안에만
    repo = _smoke(tmp_path, "s/s1", [_session("s1", chat=[dict(chat[1], hook="mcp_activation_tracker", text="계속되면 jaeheeMin/blueward-harness 저장소에 이슈로 알리십시오.", fix="")])])
    assert "jaeheeMin/blueward-harness" in repo["text"]  # 아는 이름만 바꾸고 저장소 이름은 그대로(#794)


_BLOCK = {"t": 2, "role": "block", "hook": "pre_write_guard", "kind": "blocked", "tool": "Write",
          "text": "문서가 템플릿을 따르지 않습니다. 개요 절이 없습니다.\n자세한 위반 목록입니다.\n\n다음: 개요 절을 추가하십시오.", "fix": "개요 절을 추가하십시오."}
_UNSURE = {"t": 3, "role": "block", "hook": "stop-deliver", "kind": "cannot_check", "text": "엔진을 받지 못해 검사 불능입니다.", "fix": ""}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_block_card_body_shows_first_two_sentences_and_folds_the_rest(tmp_path):
    """시안 G-23: 막힘 카드 본문은 앞 두 문장, 셋째부터는 [검사 원문] 안에 접힌다."""
    three = dict(_BLOCK, text="첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다.", fix="")
    closed = _smoke(tmp_path, "s/s1", [_session("s1", chat=[three])])
    assert "첫째 문장입니다. 둘째 문장입니다." in closed["text"] and "셋째 문장입니다." not in closed["text"]
    opened = _smoke(tmp_path, "s/s1", [_session("s1", chat=[three])], actions=[{"click": "[data-block-raw]"}])
    assert "셋째 문장입니다." in opened["text"]
    one = _smoke(tmp_path, "s/s1", [_session("s1", chat=[dict(three, text="한 문장입니다.")])])
    assert "한 문장입니다." in one["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_blocked_session_shows_apart_from_my_turn_in_home_side_and_banner(tmp_path):
    """#790: 막힘(✕)·확인 못 함(?)은 홈 표·사이드바·맨 위 띠에서 내 차례와 따로 보이고, 내 차례 숫자에 섞이지 않는다."""
    sessions = [_session("s1", title="막힌 일", status="idle", lastBlock={"t": 2, "kind": "blocked", "open": True}),
                _session("s2", title="못 한 일", status="idle", lastBlock={"t": 3, "kind": "cannot_check", "open": True}),
                _session("s3", title="풀린 일", status="idle", lastBlock={"t": 4, "kind": "blocked", "open": False}),
                _session("s4", title="질문 일", status="waiting", pendingRequestIds=["q1"], lastBlock={"t": 5, "kind": "blocked", "open": True})]
    q = {"id": "q1", "sessionId": "s4", "kind": "question", "status": "pending", "toolName": "AskUserQuestion", "toolInput": {"questions": [{"question": "어느 쪽?", "options": [{"label": "가"}]}]}}
    got = _smoke(tmp_path, "", sessions, [q])
    text, dump = got["text"], got["dump"]
    assert "<span.tagx.fail>" in dump and "<span.tagx.unk>" in dump and "✕ 막힘" in text and "? 확인 못 함" in text
    assert text.count("가서 보기") == 2 and "내 차례1" in text  # 막힘 둘은 내 차례 숫자에 안 들어가고, 묻는 요청이 있는 세션만 내 차례
    assert "✕ 막힘 · 고친 뒤 이어서" in got["side"] and "? 확인 못 함 · 검사를 못 했어" in got["side"]  # 사이드바
    assert "막힌 일 1건 · 확인 못 한 검사 1건" in got["ann"]  # 시안 G-16: 둘을 세되 초록 띠 한 줄
    assert "내 차례 1건 — “질문 일” 세션에서 답이 필요해" in got["ann"]  # 제목에 조사가 바로 붙지 않는다
    # 풀린 막힘(뒤에 말이 이어짐)과 목록이 열림 여부를 안 알려 주는 옛 서버는 막힘으로 치지 않는다
    calm = _smoke(tmp_path, "", [_session("s3", status="idle", lastBlock={"t": 4, "kind": "blocked", "open": False}), _session("s5", status="idle", lastBlock={"t": 4, "kind": "blocked"})])
    assert "<span.tagx.fail>" not in calm["dump"] and "✕ 막힘" not in calm["ann"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_open_block_card_comes_before_flow_picker_and_has_next_steps(tmp_path):
    """#791: 막힘이 열려 있으면 갈래 선택·다음 단계보다 "고친 뒤 이어서" 안내가 먼저, 직접 보기 뒤 다음 할 일과 되돌리기, 원문·고치는 법 중복 없음."""
    chat = [{"t": 1, "role": "me", "text": "문서 써 줘"}, _BLOCK]
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat, flowId=None, flowName=None, flowSteps=[], stepIndex=0)])
    assert "막힌 걸 고친 뒤 이어서 하자" in got["text"] and "어떤 일이야?" not in got["text"] and "그래도 먼저 일 고르기" in got["text"]
    skipped = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat, flowId=None, flowName=None, flowSteps=[], stepIndex=0)], actions=[{"click": "[data-hold-skip]"}])
    assert "어떤 일이야?" in skipped["text"] and "막힌 걸 고친 뒤 이어서 하자" not in skipped["text"]
    # 막힘이 풀리면(뒤에 AI 말) 안내가 사라진다
    solved = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat + [{"t": 4, "role": "ai", "text": "고쳤어."}], flowId=None, flowName=None, flowSteps=[], stepIndex=0)])
    assert "막힌 걸 고친 뒤 이어서 하자" not in solved["text"] and "어떤 일이야?" in solved["text"]
    # 직접 보기 뒤: 다음 할 일, [다 고쳤어, 이어서 해 줘], [다시 고르기]
    mine = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)], actions=[{"click": "[data-block-self]"}])
    assert "직접 보기로 했어." in mine["text"] and "다 고쳤어, 이어서 해 줘" in mine["text"] and "다시 고르기" in mine["text"]
    back = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)], actions=[{"click": "[data-block-self]"}, {"click": "[data-block-undo]"}])
    assert "직접 보기로 했어." not in back["text"] and "내가 직접 볼게" in back["text"]
    # 원문을 펼쳐도 "다음:" 줄과 "고치는 법" 이 같은 글로 두 번 나오지 않는다
    raw = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)], actions=[{"click": "[data-block-raw]"}])
    assert "자세한 위반 목록입니다." in raw["text"] and raw["text"].count("개요 절을 추가하십시오.") == 1 and "다음: 개요" not in raw["text"]
    # 보낼 수 없는(터미널) 세션: 보내는 단추 대신 터미널에서 하라는 안내
    term = _smoke(tmp_path, "s/s1", [_session("s1", chat=[_UNSURE], canSend=False, managed=False, cannotSendReason="쉬는 터미널 세션이라 여기서는 새로 시킬 수 없어. 터미널에서 이어서 말해 줘.")])
    assert "검사 다시 돌리기" not in term["text"] and "터미널에서 같은 일을 다시 시켜 줘" in term["text"]
    term2 = _smoke(tmp_path, "s/s1", [_session("s1", chat=[_BLOCK], canSend=False, managed=False, cannotSendReason="쉬는 터미널 세션입니다.")])
    assert "그렇게 고쳐 줘" not in term2["text"] and "터미널에서 고쳐 줘" in term2["text"] and "<p.note-attn>" in term2["dump"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_session_meets_trouble_records_g23(tmp_path):
    """시안 G-23: 막힘 카드 아래 비슷한 기록, 막힘이 풀리면 기록해 둘까? 카드, [기록하기] 는 눌러야 AI 초안."""
    block = {"t": 2, "role": "block", "hook": "pre-bash-git-guard", "kind": "blocked", "tool": "Bash", "text": "그냥 git push 는 쓸 수 없어.", "fix": "올리기 단계로 푸시하면 돼."}
    chat = [{"t": 1, "role": "ai", "text": "푸시하려다 막혔어."}, block, {"t": 3, "role": "me", "text": "그렇게 고쳐 줘"}, {"t": 4, "role": "ai", "text": "다시 푸시했고 통과했어."}]
    sim = {"ok": True, "slug": "o/p", "items": [{"number": 790, "repo": "o/p", "title": "deliver 가 git 명령 검사에 막힘", "solved": True}, {"number": 655, "repo": "o/p", "title": "맨손 git push 가 거절됨", "solved": False}]}
    extra = {"GET /api/trouble/similar": sim, "POST /api/trouble/ai-draft": {"id": "d-abc", "hidden": 0}}
    got = _smoke(tmp_path, "s/s1", [_session("s1", status="idle", chat=chat)], extra=extra)
    assert "비슷한 기록 2건 — #790 deliver 가 git 명령 검사에 막힘(해결됨) · #655 맨손 git push 가 거절됨(아직 안 풀림)" in got["text"]
    assert "기록해 둘까?" in got["text"] and "방금 푼 문제를 팀 기록으로 남길까?" in got["text"] and "기록하기" in got["text"] and "괜찮아" in got["text"]
    assert not [p for p in got["posts"] if "ai-draft" in p[1]]  # 보기만 해서는 초안을 만들지 않는다(자동 실행 없음)
    assert any("cwd=" in c and "similar" in c for c in got["calls"])
    pressed = _smoke(tmp_path, "s/s1", [_session("s1", status="idle", chat=chat)], extra=extra, actions=[{"click": "[data-trouble-write]"}])
    assert [p[1] for p in pressed["posts"] if "ai-draft" in p[1]] == ["/api/trouble/ai-draft"] and pressed["path"] == "/troubles/new"
    # 풀리기 전(막힘이 마지막)·일하는 중에는 제안 카드가 없다
    assert "기록해 둘까?" not in _smoke(tmp_path, "s/s1", [_session("s1", status="idle", chat=chat[:2])], extra=extra)["text"]
    assert "기록해 둘까?" not in _smoke(tmp_path, "s/s1", [_session("s1", status="running", chat=chat)], extra=extra)["text"]
    # 기록 목록을 못 읽으면 "없음" 이 아니라 확인 못 함
    unknown = _smoke(tmp_path, "s/s1", [_session("s1", status="idle", chat=chat)], extra={"GET /api/trouble/similar": {"ok": False, "reason": "GitHub 로그인이 필요해", "items": []}})
    assert "? 비슷한 기록 확인 못 함 · GitHub 로그인이 필요해" in unknown["text"]
    # 초안을 못 만들면 이유와 빈 칸 쓰기를 보인다(지어내지 않는다)
    failed = _smoke(tmp_path, "s/s1", [_session("s1", status="idle", chat=chat)], extra={"GET /api/trouble/similar": sim}, actions=[{"click": "[data-trouble-write]"}])
    assert "빈 칸으로 쓰기" in failed["text"] and failed["path"] != "/troubles/new"


# ---- 브라우저 알림 (#651) ----

_OFF = {"turn": False, "blocked": False, "done": False}
_ALL = {"turn": True, "blocked": True, "done": True}


def _notify_env(permission, cfg=None, **env):
    return {"__env": dict({"notification": permission}, **env), "GET /api/settings/notify": cfg or _OFF}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_settings_notify_group_shows_three_switches_and_permission_line(tmp_path):
    got = _smoke(tmp_path, "settings", [_session("s1")], extra=_notify_env("granted", {"turn": True, "blocked": False, "done": False}))
    text, dump = got["text"], got["dump"]
    for need in ("알림", "내 차례가 오면", "막히거나 확인 못 한 일이 생기면", "AI가 일을 끝낼 때마다", "브라우저 알림 · 허용됨", "콘솔 탭이 열려 있을 때만"):
        assert need in text, need
    assert dump.count("<button.swrow>") == 4 and "<input" not in dump  # 기본 checkbox 가 아니라 스위치 모양(알림 셋 + 한도 표시 하나(#1039))
    assert dump.count("<i.sw.on>") == 1  # 서버에 저장된 값(turn)만 켜져 있다
    assert "GET /api/settings/notify" in got["calls"]
    default = _smoke(tmp_path, "settings", [_session("s1")], extra=_notify_env("default"))
    assert "아직 안 물음" in default["text"] and "<i.sw.on>" not in default["dump"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_settings_notify_first_switch_asks_permission_and_saves_only_when_granted(tmp_path):
    saved = {"PUT /api/settings/notify": dict(_OFF, turn=True)}
    sw = [{"click": "button[data-notify-key=turn]"}]
    ok = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_notify_env("default", ask="granted"), **saved), actions=sw)
    assert ok["asked"] == 1 and any(p[0] == "PUT" and p[1] == "/api/settings/notify" and '"turn":true' in p[2].replace(" ", "") for p in ok["posts"])
    assert ok["dump"].count("<i.sw.on>") == 1
    no = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_notify_env("default", ask="denied"), **saved), actions=sw)
    assert no["asked"] == 1 and not [p for p in no["posts"] if p[0] == "PUT"] and "<i.sw.on>" not in no["dump"]  # 막히면 켠 채 두지 않는다
    assert "브라우저가 알림을 막았어 · 주소창 왼쪽 자물쇠에서 알림을 허용해 줘" in no["text"]
    denied = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_notify_env("denied"), **saved), actions=sw)
    assert denied["asked"] == 0 and not [p for p in denied["posts"] if p[0] == "PUT"] and "주소창 왼쪽 자물쇠" in denied["text"]
    gone = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_notify_env("absent"), **saved), actions=sw)
    assert "이 브라우저는 알림을 지원하지 않아" in gone["text"] and not [p for p in gone["posts"] if p[0] == "PUT"]
    off = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_notify_env("granted", dict(_OFF, turn=True)), **{"PUT /api/settings/notify": _OFF}), actions=sw)
    assert any(p[0] == "PUT" and '"turn":false' in p[2].replace(" ", "") for p in off["posts"]) and off["asked"] == 0  # 끄는 건 묻지 않는다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_settings_notify_state_line_tells_waiting_dismissed_denied_and_granted_apart(tmp_path):
    sw = [{"click": "button[data-notify-key=turn]"}]
    saved = {"PUT /api/settings/notify": dict(_OFF, turn=True)}
    # 허용창에 답 없이 닫으면(default 로 돌아옴) 켜진 걸로 보이지 않고 닫았다고 말한다
    shut = _smoke(tmp_path, "settings", [_session("s1")], extra=dict(_notify_env("default", ask="default"), **saved), actions=sw)
    assert "허용창을 답 없이 닫았어 (아직 안 켜졌어)" in shut["text"] and "<i.sw.on>" not in shut["dump"] and not [p for p in shut["posts"] if p[0] == "PUT"]
    # 막힘: 켜는 법 한 줄. 서버엔 켜 둔 값이 있어도 켜짐으로 그리지 않고 따로 경고한다
    denied = _smoke(tmp_path, "settings", [_session("s1")], extra=_notify_env("denied", dict(_OFF, turn=True)))
    assert "막힘 · 알림이 오지 않아" in denied["text"] and "브라우저 설정의 사이트 알림" in denied["text"]
    assert "<i.sw.on>" not in denied["dump"] and "data-notify-stale" not in denied["dump"] and "알림은 오지 않아" in denied["text"]
    # 허용됨: 스위치가 켜졌는지까지 구분
    on = _smoke(tmp_path, "settings", [_session("s1")], extra=_notify_env("granted", dict(_OFF, done=True)))
    assert "허용됨 · 켜져 있어" in on["text"] and "알림은 오지 않아" not in on["text"]
    off = _smoke(tmp_path, "settings", [_session("s1")], extra=_notify_env("granted"))
    assert "허용됨 · 스위치는 모두 꺼져 있어" in off["text"]
    ask = _smoke(tmp_path, "settings", [_session("s1")], extra=_notify_env("default"))
    assert "아직 안 물음" in ask["text"] and "알림은 오지 않아" not in ask["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_console_tells_when_requests_went_to_terminal_while_disconnected(tmp_path):
    import time
    later = time.time() + 60
    mark = {"time": later, "text": "콘솔이 연결돼 있지 않아 터미널로 넘김: Bash"}
    sessions = [_session("s1", log=[mark, mark])]
    def gone(logs):  # 끊김 -> (그 사이 서버가 남긴 기록) -> 다시 붙음
        return [{"es": "error"}, {"set": {"GET /api/sessions": {"sessions": [_session("s1", log=logs)]}}}, {"es": "open"}]
    got = _smoke(tmp_path, "", [_session("s1")], actions=gone([mark, mark]))
    assert "연결이 끊긴 사이 AI가 2번 허락이나 질문을 터미널에서 물었어" in got["head"] + got["text"] + got["dump"]
    # 끊긴 적 없으면, 또는 끊긴 사이가 아닌 옛 기록이면 알리지 않는다
    never = _smoke(tmp_path, "", sessions, actions=[{"es": "open"}])
    assert "터미널에서 물었어" not in never["dump"] + never["text"]
    old = _smoke(tmp_path, "", [_session("s1")], actions=gone([dict(mark, time=1700000000)]))
    assert "터미널에서 물었어" not in old["dump"] + old["text"]


def _live(tmp_path, sessions, actions, cfg=_ALL, requests=None, **env):
    extra = _notify_env("granted", cfg, **env)
    return _smoke(tmp_path, "", sessions, requests=requests, extra=extra, actions=actions)


def _change(sid, **fields):
    return [{"set": {"GET /api/sessions/" + sid: _session(sid, **fields)}}, {"emit": ["session", {"id": sid}]}]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notify_sends_once_per_event_and_skips_first_list_visible_tab_and_off_switches(tmp_path):
    # 첫 목록(이미 내 차례)은 기준만 잡고 보내지 않는다
    assert _live(tmp_path, [_session("s1", group="todo")], [])["notes"] == []
    # running -> idle: 끝남 한 번
    got = _live(tmp_path, [_session("s1", group="running")], _change("s1", group="idle"))
    assert [n["title"] for n in got["notes"]] == ["AI가 끝냈어 · 구매오더 조회 앱 요구사항"] and got["notes"][0]["tag"] == "bh-done-s1"
    # 같은 상태로 다시 와도 더 보내지 않는다
    again = _live(tmp_path, [_session("s1", group="running")], _change("s1", group="idle") + _change("s1", group="idle"))
    assert len(again["notes"]) == 1
    # 새 요청(질문): 내 차례 한 번, 본문은 질문, 누르면 창을 앞으로 하고 /r/<id> 로 간다
    q = {"id": "q9", "sessionId": "s1", "kind": "question", "status": "pending", "questions": [{"question": "무엇을?"}]}
    got = _live(tmp_path, [_session("s1", group="running")], _change("s1", group="todo", pendingRequestIds=["q9"]) + [{"clickNote": 0}],
                requests=[q])
    assert [n["title"] for n in got["notes"]] == ["내 차례야 · 구매오더 조회 앱 요구사항"] and got["notes"][0]["body"] == "질문"
    assert got["focused"] == 1 and got["path"] == "/r/q9"
    # 새 막힘 / 확인 못 함
    blk = _change("s1", lastBlock={"t": 50, "kind": "blocked"}) + _change("s1", lastBlock={"t": 60, "kind": "cannot_check"}) + _change("s1", lastBlock={"t": 60, "kind": "cannot_check"})
    got = _live(tmp_path, [_session("s1", lastBlock={"t": 40, "kind": "blocked"})], blk)
    assert [n["title"].split(" · ")[0] for n in got["notes"]] == ["막혔어", "확인 못 함"]
    # 끈 스위치 / 보이는 탭은 보내지 않는다
    assert _live(tmp_path, [_session("s1", group="running")], _change("s1", group="idle"), cfg=_OFF)["notes"] == []
    assert _live(tmp_path, [_session("s1", group="running")], _change("s1", group="idle"), visible=True)["notes"] == []
    # 권한이 없으면 보내지 않는다
    off = _smoke(tmp_path, "", [_session("s1", group="running")], extra=_notify_env("denied", _ALL), actions=_change("s1", group="idle"))
    assert off["notes"] == []


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_header_keeps_work_menu_and_project_name_without_sessions(tmp_path):
    """시안 G-04: 세션이 없어도 메뉴(내 일·작업·산출물·새 작업)와 프로젝트 이름(경로가 아니라 이름, 마지막 폴더)이 보이고, 홈 입력칸 단추는 "보내기" 다."""
    last = {"GET /api/folders/last": {"path": "C:/Work/harness-sandbox", "name": "harness-sandbox"}}
    got = _smoke(tmp_path, "", [], extra=last)
    assert got["head"].startswith("내 일작업산출물새 작업") and "harness-sandbox" in got["head"] and "Work/" not in got["head"]
    assert "보내기" in got["text"] and "새 작업으로" not in got["text"]
    new = _smoke(tmp_path, "new", [], extra=last)
    assert "harness-sandbox" in new["head"] and "Work/" not in new["head"]


_IDLE_TERMINAL = "쉬는 터미널 세션이라 여기서는 새로 시킬 수 없어. 터미널에서 이어서 말해 줘."


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_current_action_shows_plain_words_raw_only_in_tech_info(tmp_path):
    """#818: 목록·내 일·홈 표·세션 제목은 쉬운 말, 원문은 기술 정보에만."""
    running = [_session("s1", status="running", managed=True, currentAction="Skill: harness:srs", title="구매오더"),
               _session("s2", status="running", managed=True, currentAction="Bash: git push origin main", title="다른 일", cwd="C:/w/other")]
    for route in ("s/s1", ""):
        got = _smoke(tmp_path, route, running)
        shown = got["text"] + got["side"]
        assert "명령 실행 중" in got["side"] and "요구사항 문서 진행 중" in shown, route  # 왼쪽 목록 둘째 줄
        assert "git push" not in got["side"] and "Skill:" not in got["side"], route
    one = _smoke(tmp_path, "s/s1", running)
    assert "요구사항 문서 진행 중" in one["text"].split("현재 동작")[0]  # 세션 제목
    assert "현재 동작Skill: harness:srs" in one["text"]  # 기술 정보의 원문
    assert "<p.action-line" not in one["dump"]
    files = _smoke(tmp_path, "s/s1", [_session("s1", status="running", managed=True, currentAction="Write: docs/SRS.md")])
    assert "파일 고치는 중" in files["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_idle_terminal_notice_once_and_casual(tmp_path):
    for flow in ({}, {"turnSkill": "deliver"}):
        got = _smoke(tmp_path, "s/s1", [_session("s1", managed=False, canSend=False, cannotSendReason=_IDLE_TERMINAL, **flow)])
        # 아래 "콘솔에서 이어 가기" 칸과 어긋나지 않게 그 칸을 가리키는 말로 한 번만(#867)
        shown = "쉬는 터미널 세션이라 여기서는 새로 시킬 수 없어. 터미널에서 이어서 말하거나, 아래에서 콘솔로 이어 가."
        assert got["text"].count(shown) == 1 and _IDLE_TERMINAL not in got["text"], (flow, got["text"].count(shown))
    assert "입니다" not in _IDLE_TERMINAL and "십시오" not in _IDLE_TERMINAL


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_first_my_bubble_hides_skill_command_line(tmp_path):
    chat = [{"t": 1, "role": "me", "text": "/harness:spec\n구매오더 조회 앱 만들어 줘\n\n참고 파일: @docs/ssot/SRS.md"}, {"t": 2, "role": "ai", "text": "알겠어."}]
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)])
    assert "구매오더 조회 앱 만들어 줘" in got["text"] and "참고 파일: @docs/ssot/SRS.md" in got["text"]
    assert "/harness:spec" not in got["text"].replace("/harness:spec 실행", "")


_TERM = {"managed": False, "canSend": False, "cannotSendReason": _IDLE_TERMINAL}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_idle_terminal_resume_panel_follows_the_liveness_check(tmp_path):
    """#867: 터미널이 닫힌 걸 서버가 확인했을 때만 [콘솔에서 이어 가기]. 열려 있거나 모르면 이유와 갈라서 이어 가기만."""
    def live(state, why):
        return {"GET /api/sessions/s1/liveness": {"state": state, "why": why}}

    ended = _smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra=live("ended", "닫힘"))
    assert "터미널이 닫힌 걸 확인했어" in ended["text"] and "갈라서 이어 가기" in ended["text"]
    # 밝은 칸 위의 [다시 확인] 은 어두운 바탕용 ghost 가 아니라 line(그러면 글자가 묻힌다)
    assert "<button.pill.line>" in ended["dump"] and "<button.pill.ghost>" not in ended["dump"].split("<div.contbox>", 1)[-1].split("</div.contbox>", 1)[0]
    alive =_smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra=live("alive", "열림"))
    assert "아직 열려 있어" in alive["text"] and "두 갈래로 갈라져" in alive["text"] and "터미널이 닫힌 걸 확인했어" not in alive["text"]
    unknown = _smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra=live("unknown", "세션 목록을 못 읽어."))
    assert "세션 목록을 못 읽어." in unknown["text"] and "“갈라서 이어 가기” 를 써 줘" in unknown["text"]
    managed = _smoke(tmp_path, "s/s1", [_session("s1")])
    assert not [c for c in managed["calls"] if c.endswith("/liveness")] and "터미널이 닫힌 걸 확인했어" not in managed["text"]  # 콘솔 세션엔 확인도 없다(칸은 숨김)
    forked = _smoke(tmp_path, "s/s2", [_session("s2", forkedFrom="s1")])
    assert "터미널 세션에서 갈라서 이어 감" in forked["text"] and "원래 세션 보기" in forked["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_idle_terminal_resume_panel_sends_mode_and_text_and_opens_the_new_session(tmp_path):
    base = {"GET /api/sessions/s1/liveness": {"state": "ended", "why": "닫힘"}, "POST /api/sessions/s1/continue": {"id": "s9", "mode": "fork", "forked": True},
            "GET /api/sessions/s9": _session("s9", forkedFrom="s1")}
    fork = _smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra=base,
                  actions=[{"type": "[data-cont-text]", "value": "이어서 해 줘"}, {"click": "[data-cont-fork]"}])
    assert [p[:2] for p in fork["posts"]] == [["POST", "/api/sessions/s1/continue"]] and '"mode":"fork"' in fork["posts"][0][2] and "이어서 해 줘" in fork["posts"][0][2]
    assert fork["path"] == "/s/s9"  # 갈라진 새 세션 화면으로 간다
    resume = _smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra=dict(base, **{"POST /api/sessions/s1/continue": {"id": "s1", "mode": "resume", "forked": False}}),
                    actions=[{"type": "[data-cont-text]", "value": "이어서"}, {"click": "[data-cont-resume]"}])
    assert '"mode":"resume"' in resume["posts"][0][2] and resume["path"] == "/s/s1"  # 같은 세션이라 화면은 그대로
    alive = _smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra=dict(base, **{"GET /api/sessions/s1/liveness": {"state": "alive", "why": "열림"}}),
                   actions=[{"type": "[data-cont-text]", "value": "이어서"}, {"click": "[data-cont-resume]"}])
    assert alive["posts"] == []  # 열려 있으면 단추를 눌러도 보내지 않는다
    refused = _smoke(tmp_path, "s/s1", [_session("s1", **_TERM)], extra={k: v for k, v in base.items() if not k.startswith("POST")},  # 보내기가 404 로 거절된다
                     actions=[{"type": "[data-cont-text]", "value": "이어서"}, {"click": "[data-cont-fork]"}])
    assert "이어 가지 못했어" in refused["text"] and refused["path"] == "/s/s1"


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_secret_values_are_masked_in_chat_and_record_form(tmp_path):
    """#827: 화면에 보이는 비밀 값은 ••••••••. 대화는 보이기만 가리고, 기록 입력칸은 값 자체를 바꾼다."""
    chat = [{"t": 1, "role": "me", "text": "배포가 안 돼\nclient_secret=abcd1234efgh"},
            {"t": 2, "role": "ai", "text": "db_password: hunter2xyz 로 붙었어요."}]
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)])
    assert "abcd1234efgh" not in got["text"] and "hunter2xyz" not in got["text"]
    assert "client_secret=••••••••" in got["text"] and "db_password: ••••••••" in got["text"]
    form = _smoke(tmp_path, "troubles/new", [], extra={"GET /api/trouble": {"loading": False, "projects": [{"ok": True, "name": "r", "repo": "o/r"}], "stats": {"open": 0}},
                                                       "POST /api/trouble/check": {"hits": []}, "GET /api/trouble/similar": {"ok": True, "items": []}},
                  actions=[{"type": "[aria-label=symptom]", "value": "ATC 막힘\nclient_secret=abcd1234efgh"}])
    assert form["values"] == ["ATC 막힘\nclient_secret=••••••••"], form["errors"]  # 입력칸 값이 실제로 바뀐다
    # 시안 G-22 의 비밀 줄 카드는 "가렸어" 로 보인다. 가린 값은 비밀이 아니니 [GitHub 에 올리기] 는 잠그지 않고, 같은 말을 하는 아래 알림 줄은 비운다.
    assert "비밀번호·키처럼 보이는 글이 있어 · 가렸어" in form["text"] and "증상 2번째 줄의 값을 •••••••• 로 바꿨어." in form["text"], form["text"]
    assert "올리기 전에 지워 줘" not in form["text"] and "비밀처럼 보이는 값을 가렸어." not in form["text"]
    assert "비밀번호처럼 보이는 줄을 지워 줘" not in form["text"] and "비어 있는 칸: 프로젝트, 제목" in form["text"]  # 못 올리는 까닭은 빈 칸뿐이다(비밀 때문이 아니다)
    assert not [p for p in form["posts"] if "abcd1234efgh" in p[2]]  # 서버로 원래 값이 가지 않는다
    gone = _smoke(tmp_path, "troubles/new", [], extra={"GET /api/trouble": {"loading": False, "projects": [{"ok": True, "name": "r", "repo": "o/r"}], "stats": {"open": 0}},
                                                       "POST /api/trouble/check": {"hits": []}, "GET /api/trouble/similar": {"ok": True, "items": []}},
                  actions=[{"type": "[aria-label=symptom]", "value": "ATC 막힘\nclient_secret=abcd1234efgh"}, {"click": ".tb-masked button"}])
    assert not gone["errors"], gone["errors"]
    assert "client_secret" not in gone["text"] and "가렸어" not in gone["text"]  # [그 줄 지우기] 로 가린 줄이 빠지고 카드도 사라진다
    # 승인 화면: 명령 원문·도구 입력 전체도 보이기만 가린다(허락하면 원래 명령이 그대로 돈다)
    req = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "cwd": "C:/w/proj",
           "toolInput": {"command": "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwx' https://x", "description": "API 확인"}}
    appr = _smoke(tmp_path, "r/p1", [_session("s1", pendingRequestIds=["p1"])], [req])
    assert "abcdefghijklmnopqrstuvwx" not in appr["text"] and "도구에 넘기는 입력 전체" in appr["text"] and "••••••••" in appr["text"]


def _rewind_chat():
    return [{"t": 1, "role": "me", "text": "표 고쳐 줘", "uuid": "u-1"}, {"t": 2, "role": "ai", "text": "고쳤어"}]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_rewind_button_only_on_console_messages_and_blocked_while_running(tmp_path):
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat())])
    assert got["text"].count("이 요청 이전으로 되돌리기") == 1 and "<div.rewind>" in got["dump"]
    term = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat(), managed=False)])  # 터미널(훅만) 세션은 지점을 모른다
    assert "이 요청 이전으로 되돌리기" not in term["text"]
    old = _smoke(tmp_path, "s/s1", [_session("s1", chat=[{"t": 1, "role": "me", "text": "uuid 없는 옛 말"}])])
    assert "이 요청 이전으로 되돌리기" not in old["text"]
    run = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat(), status="running")])
    # 일하는 중·끝난 세션은 내 말마다 잠긴 단추·안내를 붙이지 않는다(시안 G-18)
    assert "이 요청 이전으로 되돌리기" not in run["text"] and "되돌릴 수 없어" not in run["text"] and "<div.rewind>" not in run["dump"]
    ended = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat(), status="ended")])
    assert "이 요청 이전으로 되돌리기" not in ended["text"] and "되돌릴 수 없어" not in ended["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_rewind_card_lists_files_and_limits_then_rewinds(tmp_path):
    api = {"POST /api/sessions/s1/rewind": {"canRewind": True, "error": "", "filesChanged": ["a.txt", "docs/b.md"], "insertions": 3, "deletions": 5, "dryRun": True}}
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat())], extra=api, actions=[{"click": "[data-rewind-open]"}])
    text = got["text"]
    for need in ("되돌리기 확인", "파일 2개", "a.txt", "docs/b.md", "추가했던 3줄", "지웠던 5줄", "대화 내용은 그대로", "커밋하거나 푸시한 것은 안 돌아가.", "되돌리기", "취소"):
        assert need in text, need
    first = [p for p in got["posts"] if p[1].endswith("/rewind")]
    assert len(first) == 1 and '"dryRun":true' in first[0][2].replace(" ", "")
    done = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat())], extra=api, actions=[{"click": "[data-rewind-open]"}, {"click": "[data-rewind-go]"}])
    posts = [p for p in done["posts"] if p[1].endswith("/rewind")]
    assert len(posts) == 2 and "dryRun" not in posts[1][2] and "u-1" in posts[1][2]
    assert "되돌렸어." in done["text"] and "대화는 그대로야" in done["text"]
    cancel = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat())], extra=api, actions=[{"click": "[data-rewind-open]"}, {"click": "[data-rewind-cancel]"}])
    assert "되돌리기 확인" not in cancel["text"] and len([p for p in cancel["posts"] if p[1].endswith("/rewind")]) == 1  # 취소는 서버에 아무것도 안 보낸다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_rewind_shows_claude_reason_and_does_not_pass_silently(tmp_path):
    no = {"POST /api/sessions/s1/rewind": {"canRewind": False, "error": "File rewinding is not enabled.", "filesChanged": [], "insertions": 0, "deletions": 0, "dryRun": True}}
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat())], extra=no, actions=[{"click": "[data-rewind-open]"}])
    assert "되돌릴 수 없어. 이유: File rewinding is not enabled." in got["text"] and "data-rewind-go" not in got["dump"]
    empty = {"POST /api/sessions/s1/rewind": {"canRewind": True, "error": "", "filesChanged": [], "insertions": 0, "deletions": 0, "dryRun": True}}
    e = _smoke(tmp_path, "s/s1", [_session("s1", chat=_rewind_chat())], extra=empty, actions=[{"click": "[data-rewind-open]"}])
    assert "되돌릴 게 없어" in e["text"] and "data-rewind-go" not in e["dump"]


_ELICIT_FIELDS = [
    {"key": "color", "title": "색", "description": "", "required": True, "type": "enum", "options": [{"value": "red", "label": "빨강"}, {"value": "blue", "label": "파랑"}]},
    {"key": "size", "title": "팀 인원", "description": "", "required": False, "type": "integer", "minimum": 1, "maximum": 50},
    {"key": "note", "title": "메모", "description": "", "required": False, "type": "string", "format": "email"},
    {"key": "ok", "title": "동의", "description": "", "required": False, "type": "boolean"},
]
_ELICIT_FORM = {"id": "e1", "sessionId": "s1", "kind": "elicitation", "status": "pending", "toolName": "elicitation:asksrv",
                "elicitation": {"server": "asksrv", "message": "좋아하는 색과 팀 인원을 알려 줘", "mode": "form", "fields": _ELICIT_FIELDS, "url": ""}}


def _elicit_url(url):
    return {"id": "e2", "sessionId": "s1", "kind": "elicitation", "status": "pending", "toolName": "elicitation:asksrv",
            "elicitation": {"server": "asksrv", "message": "이 주소에서 로그인해 줘", "mode": "url", "fields": [], "url": url}}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_elicitation_form_draws_fields_and_send_needs_required(tmp_path):
    """#885: MCP 질문 폼은 질문 카드 모양(.q·.qopt)으로 그려지고, 꼭 채워야 하는 칸이 비면 [보내기] 가 잠긴다."""
    sess = [_session("s1", pendingRequestIds=["e1"])]
    got = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM])
    text, dump = got["text"], got["dump"]
    for need in ("연결 도구(asksrv)가 묻는 것", "좋아하는 색과 팀 인원을 알려 줘", "꼭 채워야 해", "안 채워도 돼", "빨강", "파랑", "팀 인원", "메모", "동의", "예", "아니오", "보내기", "거절", "닫기",
                 "내 답을 기다리는 중", "아직 채우지 못한 항목이 1개 있어."):
        assert need in text, need
    assert dump.count("<button.qopt>") == 4 and "<div.qgroup>" in dump and "<div.q>" in dump and "<input.input.q-other>" in dump
    assert "보내기" in got["disabledButtons"] and "거절" not in got["disabledButtons"] and "닫기" not in got["disabledButtons"]
    picked = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM], actions=[{"click": ".qopt", "index": 1}])
    assert "보내기" not in picked["disabledButtons"] and "아직 채우지 못한 항목" not in picked["text"]
    # 숫자 칸에 정수가 아닌 값을 적으면 다시 잠긴다
    odd = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM], actions=[{"click": ".qopt", "index": 1}, {"type": ".q-other", "value": "2.5", "index": 0}])
    assert "보내기" in odd["disabledButtons"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_elicitation_defaults_prefill_only_matching_values(tmp_path):
    """#885 558 지적: schema 의 default 를 처음 값으로 채운다. 보기에 없거나 타입이 다른 default 는 버린다."""
    fields = [dict(_ELICIT_FIELDS[0], default="blue"), dict(_ELICIT_FIELDS[1], default=7), dict(_ELICIT_FIELDS[2], default="a@b.kr"),
              dict(_ELICIT_FIELDS[3], default=True)]
    form = dict(_ELICIT_FORM, elicitation=dict(_ELICIT_FORM["elicitation"], fields=fields))
    sess = [_session("s1", pendingRequestIds=["e1"])]
    sent = _smoke(tmp_path, "r/e1", sess, [form], extra={"POST /api/requests/e1/answer": {}}, actions=[{"click": "[data-elicit-send]"}])
    assert sent["posts"] == [["POST", "/api/requests/e1/answer", '{"action":"accept","content":{"color":"blue","size":7,"note":"a@b.kr","ok":true}}']]
    bad = [dict(_ELICIT_FIELDS[0], default="green"), dict(_ELICIT_FIELDS[1], default="7"), dict(_ELICIT_FIELDS[2], default=3), dict(_ELICIT_FIELDS[3], default="yes")]
    form2 = dict(_ELICIT_FORM, elicitation=dict(_ELICIT_FORM["elicitation"], fields=bad))
    got = _smoke(tmp_path, "r/e1", sess, [form2])
    assert "보내기" in got["disabledButtons"] and "아직 채우지 못한 항목이 1개 있어." in got["text"]  # 꼭 채울 색이 비어 있다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_elicitation_url_shows_open_button(tmp_path):
    """#885 558 지적: url 모드 주소는 글자로 보이고, 누를 곳은 [주소 열기] 단추(pill)다. 열 수 없는 주소엔 단추가 없다."""
    sess = [_session("s1", pendingRequestIds=["e2"])]
    shown = _smoke(tmp_path, "r/e2", sess, [_elicit_url("https://example.com/login")])
    assert "<a.pill.line>" in shown["dump"] and "주소 열기" in shown["text"] and "https://example.com/login" in shown["text"]
    bad = _smoke(tmp_path, "r/e2", sess, [_elicit_url("javascript:alert(1)")])
    assert "주소 열기" not in bad["text"] and bad["links"] == [l for l in bad["links"] if l[0] != "javascript:alert(1)"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_elicitation_form_posts_values_and_decline_cancel(tmp_path):
    sess = [_session("s1", pendingRequestIds=["e1"])]
    route = {"POST /api/requests/e1/answer": {}}
    sent = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM], extra=route,
                  actions=[{"click": ".qopt", "index": 1}, {"type": ".q-other", "value": "4", "index": 0}, {"type": ".q-other", "value": "a@b.kr", "index": 1},
                           {"click": ".qopt", "index": 2}, {"click": "[data-elicit-send]"}])
    assert sent["posts"] == [["POST", "/api/requests/e1/answer", '{"action":"accept","content":{"color":"blue","size":4,"note":"a@b.kr","ok":true}}']]
    assert "답을 보냈어." in sent["text"]
    no = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM], extra=route, actions=[{"click": "[data-elicit-decline]"}])
    assert no["posts"] == [["POST", "/api/requests/e1/answer", '{"action":"decline"}']] and "거절했어." in no["text"]
    cut = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM], extra=route, actions=[{"click": "[data-elicit-cancel]"}])
    assert cut["posts"] == [["POST", "/api/requests/e1/answer", '{"action":"cancel"}']] and "닫았어." in cut["text"]
    fail = _smoke(tmp_path, "r/e1", sess, [_ELICIT_FORM], actions=[{"click": "[data-elicit-decline]"}])  # 길이 없으면 404
    assert "이미 처리된 질문이야." in fail["text"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_elicitation_url_mode_links_only_http_and_sends_without_content(tmp_path):
    sess = [_session("s1", pendingRequestIds=["e2"])]
    shown = _smoke(tmp_path, "r/e2", sess, [_elicit_url("https://example.com/login")])
    assert ["https://example.com/login", "_blank", "noopener noreferrer"] in shown["links"] and "열 수 없는 주소야" not in shown["text"]
    assert "연결 도구(asksrv)가 묻는 것" in shown["text"] and "다 했어" in shown["text"]
    ok = _smoke(tmp_path, "r/e2", sess, [_elicit_url("https://example.com/login")], extra={"POST /api/requests/e2/answer": {}}, actions=[{"click": "[data-elicit-send]"}])
    assert ok["posts"] == [["POST", "/api/requests/e2/answer", '{"action":"accept"}']]
    for bad in ("javascript:alert(1)", "file:///C:/x", "data:text/html,x", "not a url"):
        got = _smoke(tmp_path, "r/e2", sess, [_elicit_url(bad)])
        assert all(l[0] != bad for l in got["links"]), bad  # 다른 스킴은 링크로 만들지 않는다
        assert "열 수 없는 주소야" in got["text"] and bad in got["text"] and "다 했어" in got["text"], bad


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_elicitation_waiting_in_chat_is_drawn_in_place_as_form(tmp_path):
    chat = [{"t": 1, "role": "me", "text": "해 줘"},
            {"t": 2, "role": "req", "id": "e1", "kind": "elicitation", "title": "연결 도구(asksrv)가 묻는 것: 좋아하는 색", "answer": None},
            {"t": 3, "role": "req", "id": "e0", "kind": "elicitation", "title": "연결 도구(asksrv)가 묻는 것: 지난 질문", "answer": "보냄: color=red"}]
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat, pendingRequestIds=["e1"], status="waiting")], [_ELICIT_FORM])
    text, dump = got["text"], got["dump"]
    assert dump.count("<div.qgroup>") == 1 and "연결 도구(asksrv)가 묻는 것" in text and dump.count("<button.qopt>") == 4
    assert "연결 도구(asksrv)가 묻는 것: 지난 질문 → 보냄: color=red" in text and "승인 요청:" not in text


# ---- 알림 말풍선 · 팝업 · 헤더 계정 한도(#1016) ----

def _q_session(sid="s1", rid="q1", title="구매오더 조회 앱 요구사항"):
    s = _session(sid, title=title, status="waiting", pendingRequestIds=[rid])
    q = {"id": rid, "sessionId": sid, "kind": "question", "status": "pending",
         "questions": [{"question": "요구사항을 올릴지 정해 주세요", "options": [{"label": "올려"}, {"label": "나중에"}]}]}
    return s, q


def _perm_session(sid="s2", rid="p1", title="권한 일"):
    s = _session(sid, title=title, status="waiting", pendingRequestIds=[rid])
    r = {"id": rid, "sessionId": sid, "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "touch a", "description": "파일 만들기"}}
    return s, r


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_bubble_shows_most_urgent_one_line_with_dot_on_every_screen(tmp_path):
    s, q = _q_session()
    for route in ("", "s/s1", "settings", "docs"):
        got = _smoke(tmp_path, route, [s], [q])
        assert got["bubble"].startswith("내 차례 1건: 요구사항을 올릴지 정해 주세요"), (route, got["bubble"])
        assert got["dot"] == 1, route  # 알림이 있으면 단추에 점
        assert "<div.nb-bubble>" not in got["dump"]  # (말풍선은 머리줄에 있다 — 본문에 겹쳐 그리지 않는다)
    got = _smoke(tmp_path, "", [s], [q])
    assert '<div class="nb-bubble"' not in got["head"] and "알림" not in got["limits"]
    # 알림이 없으면 말풍선도 점도 없다(단추는 늘 있다)
    calm = _smoke(tmp_path, "", [_session("s1")])
    assert calm["bubble"] == "" and calm["dot"] == 0


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_bubble_priority_follows_strip_order(tmp_path):
    """말풍선 우선순위는 띠 순서: 내 차례 → 막힘 → API 오류. 막힘·오류만 있으면 막힘이 먼저."""
    s, q = _q_session()
    blocked = _session("s3", title="막힌 일", status="idle", lastBlock={"t": 2, "kind": "blocked", "open": True})
    api = _session("s4", title="로그인 일", status="idle", apiIssue={"kind": "auth", "status": 401, "t": 5})
    got = _smoke(tmp_path, "", [api, blocked, s], [q])
    assert got["bubble"].startswith("내 차례 1건:")
    got = _smoke(tmp_path, "", [api, blocked])
    assert got["bubble"].startswith("막힌 일 1건: “막힌 일” 세션부터 보자")
    got = _smoke(tmp_path, "", [api])
    assert got["bubble"].startswith("⚠ 오류 1건: “로그인 일” 세션 — 로그인이 풀렸어")
    # 같은 알림이 홈 띠와 말풍선 두 군데 겹치지 않게 띠는 감춘다(DOM 에만 있다)
    assert got["annBubble"] == "1" and "로그인이 풀렸어" in got["ann"]  # 띠 데이터는 DOM 에 남기고(.ann-slot[data-bubble] 로 감춘다) 말풍선만 보인다
    assert got["dot"] == 1


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_bubble_close_remembers_by_id_and_new_notice_shows_again(tmp_path):
    s, q = _q_session()
    got = _smoke(tmp_path, "", [s], [q], actions=[{"click": ".nb-x"}])
    assert got["bubble"] == "" and got["dot"] == 1  # 말풍선은 닫혀도 점은 남는다(알림이 아직 있다)
    assert json.loads(got["ss"]["bh-nb-dismissed"]) == ["req:q1"]
    # 새로고침해도 같은 알림은 다시 안 뜬다
    again = _smoke(tmp_path, "", [s], [q], extra={"__ss": {"bh-nb-dismissed": '["req:q1"]'}})
    assert again["bubble"] == "" and again["dot"] == 1
    # 새 알림은 뜬다
    s2, p = _perm_session()
    new = _smoke(tmp_path, "", [s, s2], [q, p], extra={"__ss": {"bh-nb-dismissed": '["req:q1"]'}})
    assert new["bubble"].startswith("내 차례 2건: 권한 일 · ") and "내 차례 2건" in new["bubble"]
    # 풀린(더는 없는) 알림의 닫은 표시는 잊어서 같은 일이 다시 생기면 다시 뜬다
    gone = _smoke(tmp_path, "", [_session("s1")], extra={"__ss": {"bh-nb-dismissed": '["req:gone","ver:9"]'}})
    assert json.loads(gone["ss"]["bh-nb-dismissed"]) == ["ver:9"]
    # 닫은 뒤 초점은 알림 단추로
    assert got["activeK"] == "nb-btn"


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_popup_answers_permission_with_existing_answer_api(tmp_path):
    s, p = _perm_session()
    got = _smoke(tmp_path, "", [s], [p], actions=[{"click": ".nb-say"}])
    d = got["dialog"]
    assert "승인 요청 · 권한 일" in d and "touch a" in d and "이번만 허락" in d and "하지 마" in d
    assert "다시 묻지 않기" not in d  # 추가될 규칙(suggestionText)을 못 보여 주면 이 단추를 두지 않는다(#1016 검토)
    assert 'role="dialog"' not in d and "<div.nb-dialog>" in got["dialogDump"]
    assert "1/" not in d  # 한 건이면 n/m 은 없다
    done = _smoke(tmp_path, "", [s], [p], extra={"POST /api/requests/p1/answer": {"ok": True}}, actions=[{"click": ".nb-say"}, {"click": "[data-k=allow]"}])
    assert ["POST", "/api/requests/p1/answer", '{"decision":"allow"}'] in done["posts"]  # 새 경로 없이 기존 응답 API
    assert "허락했어." in done["dialog"] and "답할 알림이 더 없어" in done["dialog"]
    deny = _smoke(tmp_path, "", [s], [p], extra={"POST /api/requests/p1/answer": {"ok": True}}, actions=[{"click": ".nb-btn"}, {"click": "[data-k=deny]"}])
    assert ["POST", "/api/requests/p1/answer", '{"decision":"deny"}'] in deny["posts"]
    ps = dict(p, suggestionText=["Bash(touch a:*)"])  # 추가될 규칙을 먼저 보여 줄 수 있으면 "다시 묻지 않기" 를 둔다
    sess = _smoke(tmp_path, "", [s], [ps], extra={"POST /api/requests/p1/answer": {"ok": True}}, actions=[{"click": ".nb-btn"}, {"click": "[data-k=allow_session]"}])
    assert ["POST", "/api/requests/p1/answer", '{"decision":"allow_session"}'] in sess["posts"]
    shown = _smoke(tmp_path, "", [s], [ps], actions=[{"click": ".nb-btn"}])
    assert "Bash(touch a:*)" in shown["dialog"] and shown["dialog"].index("Bash(touch a:*)") < shown["dialog"].index("이번만 허락")  # 규칙을 먼저 보여 준 뒤 단추
    # 응답이 실패하면 오류를 보이고 닫지 않는다(여기선 서버가 없는 요청이라고 답한 경우)
    fail = _smoke(tmp_path, "", [s], [p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=allow]"}])
    assert "이미 처리됐거나 닫힌 요청이야" in fail["dialog"] and "이번만 허락" in fail["dialog"] and "답할 알림이 더 없어" not in fail["dialog"]
    assert all(p_[0] == "POST" and "/answer" in p_[1] for p_ in fail["posts"])


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_popup_question_options_send_answers_and_irreversible_verbs(tmp_path):
    s, q = _q_session()
    got = _smoke(tmp_path, "", [s], [q], extra={"POST /api/requests/q1/answer": {"ok": True}}, actions=[{"click": ".nb-say"}])
    assert "질문 · 구매오더 조회 앱 요구사항" in got["dialog"] and "올려" in got["dialog"] and "나중에" in got["dialog"] and "답 보내기" not in got["dialog"]
    sent = _smoke(tmp_path, "", [s], [q], extra={"POST /api/requests/q1/answer": {"ok": True}}, actions=[{"click": ".nb-say"}, {"click": "[data-k=opt-0-1]"}])
    assert ["POST", "/api/requests/q1/answer", '{"answers":{"요구사항을 올릴지 정해 주세요":"나중에"}}'] in sent["posts"]  # 보기 하나가 곧 답
    assert "세션에 답을 전달했어." in sent["dialog"]
    # 여러 가지를 묻거나 여러 개 고르는 질문은 골라 두고 [답 보내기]
    multi = dict(q, questions=[{"question": "색은?", "multiSelect": True, "options": [{"label": "빨강"}, {"label": "파랑"}]}])
    pick = _smoke(tmp_path, "", [s], [multi], actions=[{"click": ".nb-btn"}])
    assert "답 보내기" in pick["dialog"] and "답 보내기" in pick["dialogDisabled"]
    two = _smoke(tmp_path, "", [s], [multi], extra={"POST /api/requests/q1/answer": {"ok": True}}, actions=[{"click": ".nb-btn"}, {"click": "[data-k=opt-0-0]"}, {"click": "[data-k=opt-0-1]"}, {"click": "[data-k=send]"}])
    assert ["POST", "/api/requests/q1/answer", '{"answers":{"색은?":"빨강, 파랑"}}'] in two["posts"]
    # 되돌릴 수 없는 일은 승인 화면과 같은 말로 묻고 "다시 묻지 않기" 는 없다
    s2, p = _perm_session()
    irrev = dict(p, risk="irreversible", riskNote="파일을 지워", toolInput={"command": "rm -rf build"})
    got = _smoke(tmp_path, "", [s2], [irrev], actions=[{"click": ".nb-btn"}])
    assert "이번만 지워" in got["dialog"] and "지우지 마" in got["dialog"] and "다시 묻지 않기" not in got["dialog"] and "되돌릴 수 없는 일" in got["dialog"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_popup_pages_between_items_and_other_kinds_open_session(tmp_path):
    s, q = _q_session()
    s2, p = _perm_session()
    blocked = _session("s3", title="막힌 일", status="idle", lastBlock={"t": 2, "kind": "blocked", "open": True})
    api = _session("s4", title="로그인 일", status="idle", apiIssue={"kind": "auth", "status": 401, "t": 5})
    base = [s, s2, blocked, api]
    got = _smoke(tmp_path, "", base, [q, p], actions=[{"click": ".nb-btn"}])
    assert "1/4" in got["dialog"] and "질문" in got["dialog"]
    nxt = _smoke(tmp_path, "", base, [q, p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=next]"}])
    assert "2/4" in nxt["dialog"] and "승인 요청 · 권한 일" in nxt["dialog"]
    blk = _smoke(tmp_path, "", base, [q, p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=next]"}, {"click": "[data-k=next]"}])
    assert "3/4" in blk["dialog"] and "✕ 막힘" in blk["dialog"] and "세션 열기" in blk["dialog"]
    err = _smoke(tmp_path, "", base, [q, p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=prev]"}])  # 처음에서 이전은 끝으로
    assert "4/4" in err["dialog"] and "로그인이 풀렸어" in err["dialog"] and "/login" in err["dialog"] and "세션 열기" in err["dialog"]
    # 세션 열기는 팝업을 닫고 그 세션으로 간다
    opened = _smoke(tmp_path, "", base, [q, p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=prev]"}, {"click": "[data-k=open]"}])
    assert opened["dialog"] == "" and opened["path"] == "/s/s4"
    # 말풍선의 글자를 누르면 그 알림부터 연다
    api_only = _smoke(tmp_path, "", [blocked, api], actions=[{"click": ".nb-say"}])
    assert "1/2" in api_only["dialog"] and "✕ 막힘" in api_only["dialog"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_popup_closes_with_esc_and_keeps_focus_inside(tmp_path):
    s, p = _perm_session()
    s2, q = _q_session()
    got = _smoke(tmp_path, "", [s, s2], [p, q], actions=[{"click": ".nb-btn"}])
    assert got["dialog"] and got["activeK"] == "nb-h"  # 열면 제목으로 초점(키보드로 열고 Enter 한 번에 승인되지 않게)
    esc = _smoke(tmp_path, "", [s, s2], [p, q], actions=[{"click": ".nb-btn"}, {"key": "Escape"}])
    assert esc["dialog"] == "" and esc["activeK"] == "nb-btn"  # 닫으면 연 단추로 초점을 돌려준다
    close = _smoke(tmp_path, "", [s, s2], [p, q], actions=[{"click": ".nb-btn"}, {"click": "[data-k=close]"}])
    assert close["dialog"] == ""
    # Tab 이 끝 단추에서 처음으로, Shift+Tab 이 처음에서 끝으로 돈다(팝업 밖으로 초점이 나가지 않는다)
    assert _smoke(tmp_path, "", [s, s2], [p, q], actions=[{"click": ".nb-btn"}, {"focus": "[data-k=detail]"}, {"key": "Tab"}])["activeK"] == "prev"
    assert _smoke(tmp_path, "", [s, s2], [p, q], actions=[{"click": ".nb-btn"}, {"focus": "[data-k=prev]"}, {"key": "Tab", "shift": True}])["activeK"] == "detail"
    empty = _smoke(tmp_path, "", [_session("s1")], actions=[{"click": ".nb-btn"}])
    assert "지금 알릴 게 없어." in empty["dialog"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_header_shows_account_limits_or_says_unknown(tmp_path):
    import time
    now = time.time()
    far = 4102444800  # 2100년: 풀릴 시각이 지나지 않은 값
    unknown = _smoke(tmp_path, "", [_session("s1")], extra={"GET /api/account-limits": {"windows": [], "source": "rate_limit_event"}})
    assert unknown["limits"] == "한도 알 수 없어" and "%" not in unknown["limits"] and "0% 라는 뜻이 아니야" in unknown["limitsTitle"]
    failed = _smoke(tmp_path, "", [_session("s1")])  # 한도 API 를 못 읽어도 0% 로 꾸미지 않는다
    assert failed["limits"] == "한도 알 수 없어" and "읽지 못했어" in failed["limitsTitle"]
    wins = [{"type": "five_hour", "status": "allowed", "utilization": 0.42, "resetsAt": far, "t": now},
            {"type": "seven_day", "status": "allowed_warning", "utilization": 0.91, "resetsAt": far, "t": now - 7200}]
    got = _smoke(tmp_path, "", [_session("s1")], extra={"GET /api/account-limits": {"windows": wins}})
    assert "5시간 42%" in got["limits"] and "⚠ 주간 91%" in got["limits"] and "알 수 없음" not in got["limits"]
    assert "오래된 값" in got["limitsTitle"] and "에 받은 값" in got["limitsTitle"]
    rej = _smoke(tmp_path, "", [_session("s1")], extra={"GET /api/account-limits": {"windows": [dict(wins[0], status="rejected", utilization=1.0)]}})
    assert "✕ 5시간 100%" in rej["limits"]
    # 다른 화면에서도 늘 보인다
    assert "5시간 42%" in _smoke(tmp_path, "settings", [_session("s1")], extra={"GET /api/account-limits": {"windows": wins}})["limits"]


def test_notice_assets_wired_and_css_uses_variables_only():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/api-notice.js"') < html.index('src="/notice-logic.js"') < html.index('src="/app.js"')
    css = (STATIC / "app.css").read_text(encoding="utf-8").split("알림 말풍선 · 팝업 · 헤더 계정 한도(#1016)", 1)[1]
    assert "prefers-reduced-motion: no-preference" in css and "animation: nb-in" in css  # 움직임 줄이기면 등장 효과 없음
    assert ".nb-bubble[hidden]" in css and "max-width: min(460px, calc(100vw - 32px))" in css  # 좁은 화면에서 넘치지 않게
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"--nb-err:[^;]+;", "", re.sub(r"\.nb-warn[^}]*\}|rgba\([^)]*\)", "", body)))  # 색은 변수(단, 경고 글자 두 색·그림자는 예외)
    post = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    assert "--bub-bg" in post and "--bub-ink" in post and "--bub-dot" in post  # Post 도 변수만 덮는다
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    nb = app[app.index("알림 말풍선 · 팝업 · 계정 한도(#1016)"):app.index("첫 화면 · 자동 점검 (시안 01)")]
    assert "innerHTML" not in nb and 'role: \'dialog\'' in nb and "aria-modal" in nb and "'Escape'" in nb
    # 검토 반영: NodeList 에는 filter 가 없다(진짜 브라우저), 같은 알림이면 팝업을 통째로 다시 만들지 않는다, 답하는 동안은 넘기지 않는다
    assert "Array.prototype.slice.call(nb.dlg.querySelectorAll" in nb and not re.search(r"querySelectorAll\([^)]*\)\.(filter|map)", nb)
    assert "patchChildren(nb.dlg" in nb and "clear(nb.dlg)" not in nb
    assert re.search(r"function nbMove\(step\) \{[^}]*nb\.busy", nb)


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_popup_does_not_quick_allow_what_it_cannot_show_in_full(tmp_path):
    """#1016 검토: 팝업에서 내용을 다 못 보여 주는 승인(파일 쓰기·MCP·샌드박스 해제·백그라운드·긴 명령·계획)은 빠른 허락 단추 없이 [자세히 보기]·[거절] 만."""
    def pop(**kw):
        s, r = _perm_session()
        r = dict(r, **kw)
        return _smoke(tmp_path, "", [s], [r], actions=[{"click": ".nb-btn"}])
    cases = {
        "write": dict(toolName="Write", toolInput={"file_path": "docs/a.md", "content": "본문"}),
        "edit": dict(toolName="Edit", toolInput={"file_path": "docs/a.md", "old_string": "a", "new_string": "b"}),
        "mcp": dict(toolName="mcp__abap__write", toolInput={"x": 1}, mcp={"server": "abap", "tool": "write"}),
        "sandbox": dict(toolInput={"command": "ls", "dangerouslyDisableSandbox": True}),
        "background": dict(toolInput={"command": "sleep 9", "run_in_background": True}),
        "long": dict(toolInput={"command": "echo " + "x" * 700}),
    }
    for name, kw in cases.items():
        got = pop(**kw)["dialog"]
        assert "이번만 허락" not in got and "다시 묻지 않기" not in got, name
        assert "팝업에서 내용을 다 보여 줄 수 없어" in got and "자세히 보기" in got and "하지 마" in got, name
    # 계획은 [계획 보기 · 진행 정하기] 만(고쳐 달라고 하기는 이유가 필요해 전체 화면에서)
    plan = pop(toolName="ExitPlanMode", toolInput={"plan": "## 계획"})["dialog"]
    assert "계획 보기 · 진행 정하기" in plan and "이 계획대로 진행" not in plan and "하지 마" not in plan
    # 다 보이는 명령(600자 이하)은 자르지 않고 전체를 보인다. 되돌릴 수 없는 일은 승인 화면과 같은 말
    full = "echo " + "y" * 590
    ok = pop(toolInput={"command": full})["dialog"]
    assert full in ok and "이번만 허락" in ok
    assert "되돌릴 수 없는 일" in pop(risk="irreversible", toolInput={"command": "rm -rf build"})["dialog"]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_popup_locks_then_moves_on_when_item_is_handled_elsewhere(tmp_path):
    """#1016 검토: 보던 알림이 다른 곳에서 처리돼 사라지면 안내와 함께 잠깐 단추를 막은 뒤 다음 알림을 보인다(눈 깜짝할 새 다른 알림에 답하지 않게)."""
    s, q = _q_session()
    s2, p = _perm_session()
    handled = dict(s, status="idle", pendingRequestIds=[])
    got = _smoke(tmp_path, "", [s, s2], [q, p], actions=[{"click": ".nb-btn"}, {"set": {"GET /api/sessions/s1": handled}}, {"emit": ["session", {"id": "s1"}]}])
    assert "이 알림은 이미 처리됐어" in got["dialog"] and "이번만 허락" not in got["dialog"]  # 다음 알림을 바로 그리지 않는다
    assert "다음 알림을 불러올게" in got["dialog"] and "허락" not in got["dialog"].replace("이미 처리됐어", "")  # 잠긴 동안은 눌러 답할 단추가 없다
    after = _smoke(tmp_path, "", [s, s2], [q, p], actions=[{"click": ".nb-btn"}, {"set": {"GET /api/sessions/s1": handled}}, {"emit": ["session", {"id": "s1"}]}, {"wait": 1300}])
    assert "이 알림은 이미 처리됐어" not in after["dialog"] and "승인 요청 · 권한 일" in after["dialog"] and "이번만 허락" in after["dialog"]
    # 내가 답해서 사라진 알림은 안내 없이 바로 다음으로(결과 안내는 한 번)
    mine = _smoke(tmp_path, "", [s, s2], [q, p], extra={"POST /api/requests/q1/answer": {"ok": True}}, actions=[{"click": ".nb-btn"}, {"click": "[data-k=opt-0-0]"}])
    assert "이미 처리됐어" not in mine["dialog"] and "세션에 답을 전달했어." in mine["dialog"] and "승인 요청 · 권한 일" in mine["dialog"]
    # 다른 알림으로 넘기면 안내·고른 답은 비워진다
    multi = dict(q, questions=[{"question": "색은?", "multiSelect": True, "options": [{"label": "빨강"}, {"label": "파랑"}]}])
    moved = _smoke(tmp_path, "", [s, s2], [multi, p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=opt-0-0]"}, {"click": "[data-k=next]"}, {"click": "[data-k=prev]"}])
    assert "답 보내기" in moved["dialogDisabled"]  # 처음으로 돌아와도 고른 것이 없다
    kept = _smoke(tmp_path, "", [s, s2], [multi, p], actions=[{"click": ".nb-btn"}, {"click": "[data-k=opt-0-0]"}, {"emit": ["session", {"id": "s2"}]}])
    assert "답 보내기" not in kept["dialogDisabled"]  # 같은 알림이면 다른 세션 갱신에 고른 답이 지워지지 않는다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_notice_dismiss_id_for_api_error_without_time_uses_kind_and_status(tmp_path):
    api = _session("s4", title="로그인 일", status="idle", apiIssue={"kind": "auth", "status": 401})  # 받은 때(t)를 모른다
    got = _smoke(tmp_path, "", [api], actions=[{"click": ".nb-x"}])
    assert json.loads(got["ss"]["bh-nb-dismissed"]) == ["api:s4:auth:401"]
    other = _smoke(tmp_path, "", [_session("s4", title="로그인 일", status="idle", apiIssue={"kind": "other", "status": 500})], extra={"__ss": {"bh-nb-dismissed": '["api:s4:auth:401"]'}})
    assert other["bubble"].startswith("⚠ 오류 1건")  # 종류가 다른 새 오류는 다시 뜬다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_theme_switch_keeps_session_input_choices_and_focus(tmp_path):
    """테마를 바꿔 화면을 다시 만들어도 이어서 요청 글·질문 카드에서 고른 값이 남는다(Post 위쪽 줄 테마 단추가 부르는 경로)."""
    q1 = {"id": "q1", "sessionId": "s1", "kind": "question", "status": "pending", "questions": [{"question": "색은?", "multiSelect": True, "options": [{"label": "빨강"}, {"label": "파랑"}]}]}
    chat = [{"t": 5, "role": "req", "id": "q1", "kind": "question", "title": "색은?", "answer": None}]
    sess = [_session("s1", chat=chat, pendingRequestIds=["q1"], status="waiting")]
    acts = [{"type": "#follow", "value": "표 순서를 바꿔 줘"}, {"click": ".qopt", "index": 1}, {"focus": "#follow"}, {"theme": "post"}, {"theme": "sauce"}, {"read": "#follow"}]
    got = _smoke(tmp_path, "s/s1", sess, [q1], actions=acts)
    assert got["values"][-1] == "표 순서를 바꿔 줘"  # 글이 두 번 바뀐 뒤에도
    assert got["pressed"][:2] == ["false", "true"]  # 고른 보기가 그대로
    assert got["activeId"] == "follow"  # 포커스도 돌아온다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_theme_switch_keeps_request_screen_inputs(tmp_path):
    plan = {"id": "pl1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "ExitPlanMode", "toolInput": {"plan": "1. 문서 고치기"}}
    sess = [_session("s1", status="waiting", pendingRequestIds=["pl1"])]
    got = _smoke(tmp_path, "r/pl1", sess, [plan], actions=[{"click": "[data-plan-revise]"}, {"type": "#plan-why", "value": "문서만 먼저"}, {"type": "#say", "value": "잠깐만"},
                                                         {"theme": "post"}, {"read": "#plan-why"}, {"read": "#say"}])
    assert got["values"][-2:] == ["문서만 먼저", "잠깐만"]  # 이유 칸은 열린 채, 말하기 칸 글도 그대로


def test_theme_switch_rerenders_every_route_and_resets_post_sig():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    handler = app[app.index("document.addEventListener('bh-theme'"):]
    handler = handler[:handler.index("});")]
    assert "route.name ===" not in handler and "renderRoute()" in handler  # 홈·세션·요청·새 작업만이 아니라 모든 화면
    assert "snapFields()" in handler and "view.keep" in handler and "restoreFields(snap)" in handler
    build = app[app.index("function build() {"):]
    assert "postSig = ''" in build[:build.index("post = isPostTheme()")]  # 다시 만든 안내판 칸이 빈 채 남지 않게
    assert "keep: function () { return built" in app and "keep: function () { return { why: why" in app


def test_post_home_deck_restores_focus_after_redraw():
    js = (STATIC / "post-home.js").read_text(encoding="utf-8")
    paint = js[js.index("function paintDeck()"):js.index("/* 차분:")]
    assert "var mark = focusMark();" in paint and "focusBack(mark);" in paint  # 덱을 다시 그려도 포커스를 돌려놓는다
    assert "CSS.escape(id)" in js  # pickTop 의 선택자
    assert "stampKind" in js and "it.stampKind === 'plan'" in js  # 도장이 찍힌 카드의 종류 글


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1042_rule_raw_json_lives_in_details_tech_info_not_in_the_card(tmp_path):
    raw = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "touch:*"}], "behavior": "allow", "destination": "session"}]
    req = {"id": "p1", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "note": "touch 는 목록에 없어",
           "toolInput": {"command": "touch a", "description": "Create the file"}, "hasSuggestions": True,
           "suggestionText": ["이 세션: 허용 규칙 추가 - Bash(touch:*)"], "suggestions": raw}
    text = _smoke(tmp_path, "r/p1", [_session("s1", pendingRequestIds=["p1"])], [req])["text"]
    assert text.count('"addRules"') == 1 and "추가될 규칙 원문" in text
    assert text.index("기술 정보") < text.index("추가될 규칙 원문") < text.index('"addRules"')  # 원문은 기술 정보 안
    assert "이 세션: 허용 규칙 추가 - Bash(touch:*)" in text  # 쉬운 말 목록은 그대로
    none = _smoke(tmp_path, "r/p1", [_session("s1", pendingRequestIds=["p1"])], [dict(req, suggestions=None)])["text"]
    assert "추가될 규칙 원문" not in none and "이 세션: 허용 규칙 추가" in none


_MCP_CONN = {"state": "problem", "canReconnect": True, "servers": [
    {"name": "claude.ai Gmail", "status": "needs-auth", "label": "로그인이 필요해", "problem": True, "error": "", "canReconnect": False, "connectorAuth": True},
    {"name": "claude.ai Slack", "status": "needs-auth", "label": "로그인이 필요해", "problem": True, "error": "", "canReconnect": False, "connectorAuth": True}]}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_1042_claude_ai_connectors_fold_into_one_line_project_mcp_stays_loud(tmp_path):
    only = _smoke(tmp_path, "s/s1", [_session("s1", mcp=_MCP_CONN)])
    assert "claude.ai 커넥터 2개가 로그인 전이야" in only["text"] and "연결이 안 된 도구가 있어" not in only["text"]
    assert "<div.banner.mcp>" not in only["dump"] and "<details.mcp-conn>" in only["dump"]
    mixed_mcp = dict(_MCP_CONN, servers=_MCP_CONN["servers"] + [_MCP_BAD["servers"][0]])
    mixed = _smoke(tmp_path, "s/s1", [_session("s1", mcp=mixed_mcp)])
    assert "연결이 안 된 도구가 있어" in mixed["text"] and "abap-adt — 연결하지 못했어" in mixed["text"] and "claude.ai 커넥터 2개가 로그인 전이야" in mixed["text"]
    assert "<div.banner.mcp>" in mixed["dump"] and "<details.mcp-conn>" in mixed["dump"]
    assert "claude.ai Gmail — 로그인이 필요해" not in mixed["text"]  # 큰 목록에 커넥터가 따로 오르지 않는다


# ---- Post 테마 검증 갈래 C(2026-11-18): 상태·숫자 정합 ----

@pytest.mark.skipif(not NODE, reason="node 없음")
def test_post_verify_c_docs_gone_folder_is_not_failure_and_not_asked_again(tmp_path):
    """작업 폴더가 없어진 세션(서버 409)은 "읽기 실패" 와 따로 "폴더가 없어 읽지 못함" 으로 알리고, 다시 그려도 또 묻지 않는다."""
    extra = {"__status": {"GET /api/sessions/s2/files": 409}, "GET /api/sessions/s2/files": {"error": "세션의 작업 폴더가 없어."}}
    got = _smoke(tmp_path, "docs", [_session("s1"), _session("s2", cwd="C:/w/gone")], extra=extra)
    assert "1개 세션은 작업 폴더가 없어져서(지운 폴더 등) 문서를 읽지 못했어." in got["text"]
    assert "세션의 문서를 읽지 못했어" not in got["text"] and "git 상태를 읽지 못해서" not in got["text"]  # 서버 오류·git 못 읽음과 섞지 않는다
    assert "아직 양식으로 뽑은 산출물이 없어." in got["text"]
    flow = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    assert "GONE_RECHECK_MS" in flow and "goneDirs[key] = Date.now()" in flow  # 같은 세션·폴더는 잠깐 다시 묻지 않는다


_POST_C_NODE = r"""
const path = require('path');
const L = require(path.join(process.argv[1], 'flow-logic.js'));
const P = require(path.join(process.argv[1], 'post-logic.js'));
const out = {};
const s = { id: 'a', status: 'idle', group: 'todo', pendingRequestIds: ['r1'] };
const answered = sess => (sess.pendingRequestIds || []).filter(r => r !== 'r1');  // r1 은 이미 답한 요청
out.plain = P.stateOf(s, L);
out.passed = P.stateOf(s, L, answered);
P.useOpenIds(answered);
out.registered = P.stateOf(s, L);
P.useOpenIds(null);
out.reset = P.stateOf(s, L);
out.label = P.FILTERS.map(f => f.label).join(',');
// 같은 순간: 내 차례 세션 2(대기 요청 2건 세션 + 올릴 차례 세션), 확인 못 함 1, 일하는 중 1, 끝남 1
const list = [
  { id: 'q', status: 'idle', group: 'todo', pendingRequestIds: ['r2', 'r3'] },
  { id: 'd', status: 'idle', group: 'todo', turnSkill: 'deliver', pendingRequestIds: [] },
  { id: 'u', status: 'idle', group: 'idle', pendingRequestIds: [], lastBlock: { kind: 'cannot_check', open: true } },
  { id: 'r', status: 'running', group: 'running', pendingRequestIds: [] },
  { id: 'e', status: 'ended', group: 'idle', pendingRequestIds: [] }];
out.turnItems = L.turnItems(list).length;
out.counts = L.counts(list);
out.filter = P.filterCounts(list.map(x => P.stateOf(x, L)));
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_post_verify_c_state_uses_open_ids_and_filter_name_differs_from_turn():
    r = subprocess.run([NODE, "-e", _POST_C_NODE, str(STATIC)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # 이미 답한 요청만 남은 세션은 내 차례가 아니다 — 직접 넘기든 화면이 알려 두든(useOpenIds) 같고, 안 알리면 서버 값을 믿는다
    assert out["plain"] == "turn" and out["passed"] == "idle" and out["registered"] == "idle" and out["reset"] == "turn"
    # 목록 걸러보기는 내 차례 + 막힘 + 확인 못 함 묶음이라 "내 차례" 가 아니라 "할 일" 이다(홈·띠의 내 차례 N건과 이름이 겹치지 않게)
    assert out["label"] == "전체,할 일,일하는 중,끝남"
    # 내 차례 건수(요청·올릴 차례 하나하나) 3 = 홈 타일·띠·알림의 내 차례, 할 일(세션 수) 3 = 내 차례 세션 2 + 확인 못 함 1
    assert out["turnItems"] == 3 and out["counts"]["todo"] == 2 and out["counts"]["unsure"] == 1 and out["counts"]["running"] == 1
    assert out["filter"] == {"all": 5, "turn": 3, "run": 1, "done": 1}



# ---- Post 파이프라인 탭(post-pipeline.js) ----
_POST_PIPELINE_NODE = r"""
const path = require('path');
const dir = process.argv[1];
const L = require(path.join(dir, 'flow-logic.js'));
const PL = require(path.join(dir, 'post-logic.js'));
const P = require(path.join(dir, 'post-pipeline.js'));
const it = (n, o) => Object.assign({ number: n, req: 'REQ-00' + n, dev: 'DEV-00' + n, title: 't' + n, kind: '', spec: false, prs: [] }, o);
const items = [
  it(1, { spec: true }), it(2, { prs: [{ number: 9, kind: 'spec' }] }), it(3, { spec: true, prs: [{ number: 10, kind: 'work' }] }), it(4, { kind: '설정' }),
  it(5, { unsure: true, prs: [{ number: 11, kind: 'spec' }] }), it(6, { done: true, prs: [{ number: 12, kind: 'work' }] }), it(7), it(8, { spec: true }), it(9, { spec: true })
];
const sessions = [
  { id: 'a', title: 'Spec 쓰기 DEV-007', flowId: 'spec', status: 'running', group: 'running', updatedAt: 1 },
  { id: 'b', branch: 'feat/40-dev008-list', status: 'idle', group: 'todo', pendingRequestIds: ['r'], updatedAt: 1 },
  { id: 'c', flowPr: { number: 10, state: 'OPEN' }, status: 'idle', group: 'idle', updatedAt: 1 },
  { id: 'd', flowReason: '이전 세션에서 넘김 DEV-009', status: 'idle', group: 'idle', lastBlock: { kind: 'blocked', open: true }, updatedAt: 1 },
  { id: 'e', title: 'DEV-009 다시', status: 'running', group: 'running', updatedAt: 5 },
  { id: 'f', title: 'DEV-001 넘김', status: 'running', group: 'running', handedOffTo: 'g', updatedAt: 9 }
];
const out = {};
out.nums = P.numsIn('feat: DEV-013 (DEV-013) feat/881-dev013-x REQ-19 device12 DEV-1234567');
out.lanes = P.board(items, sessions, L, PL).map(l => l.map(c => c.item.number + ':' + c.state + (c.session ? '@' + c.session.id : '')));
out.lane = [P.laneOf(it(1, { done: true, kind: '설정' })), P.laneOf(it(2), [{ flowId: 'spec' }]), P.laneOf(it(3, { unsure: true }), [{ flowId: 'spec' }])];
out.sub = [P.summary({ items, hidden: 2 }), P.summary({ items: [it(1, { req: '' })] })];
out.groups = P.groups([{ cwd: '/a', data: { repo: { key: 'k', name: 'r' }, state: 'yes', loading: true } }, { cwd: '/b', data: { repo: { key: 'k', name: 'r' }, state: 'yes' } },
  { cwd: '/c', data: { repo: { key: 'z', name: 'z' }, state: 'no' } }, { cwd: '/d', error: { status: 403 } }]).map(g => g.key + ':' + g.cwds.join('+') + ':' + !!g.data.loading);
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_post_pipeline_attaches_sessions_and_places_lanes():
    r = subprocess.run([NODE, "-e", _POST_PIPELINE_NODE, str(STATIC)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["nums"] == [13, 19]  # 브랜치의 dev013 도 번호, device12·일곱 자리는 아니다
    # 칸: 1 요구사항(미정·아무것도 없음) · 2 Spec(Spec PR·Spec 세션) · 3 개발(Spec 있음·설정) · 4 검토(작업 PR) · 5 합쳐짐
    # 세션: 이름(a)·브랜치(b)·세션 PR 번호(c)·갈래 사유(d) 로 붙는다. 넘긴 세션(f)은 붙이지 않는다. 한 건에 여럿이면 막힘이 앞선다(d > e)
    # 칸 안: 막힘 > 내 차례 > 번호순
    assert out["lanes"] == [["5:idle"], ["2:idle", "7:run@a"], ["9:blocked@d", "8:turn@b", "1:idle", "4:idle"], ["3:wait@c"], ["6:idle"]]
    assert out["lane"] == [4, 1, 0]  # 완료가 먼저, 다음 단계 미정이면 Spec 세션이 있어도 요구사항 칸
    assert out["sub"] == ["SRS 9건 · Spec 있는 개발 건 4 · 설정 1 · 표준 0 · 보류·취소 2건 뺌", "원장 1건 · Spec 있는 개발 건 0 · 설정 0 · 표준 0"]
    assert out["groups"] == ["k:/a+/b:false", "z:/c:false"]  # 같은 저장소 worktree 는 한 판, 다 읽은 값이 읽는 중 값을 대신한다


def test_post_pipeline_wiring_route_rail_and_scoped_css():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = [html.index(f'src="/{n}"') for n in ("flow-logic.js", "post-logic.js", "post-home.js", "post-pipeline.js", "app.js")]
    assert order == sorted(order) and '<link rel="stylesheet" href="/post-pipeline.css">' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "if (p === '/pipeline') return { name: 'pipeline' };" in app and "pipeline: pipelineView" in app
    assert "item('/pipeline', '파이프라인', 'route', nm === 'pipeline', 0)" in app
    assert "!isPostTheme() || !window.BHPostPipeline" in app  # Sauce 로 주소를 치고 오면 안내만 한다
    js = (STATIC / "post-pipeline.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "'/api/pipeline'" in js and "하네스는 이 순서를 지키게 해." in js
    assert "요구사항을 확인하지 못했어." in js  # 못 읽은 저장소는 빈 판이 아니라 이유를 보인다
    css = (STATIC / "post-pipeline.css").read_text(encoding="utf-8")
    rules = [ln for ln in css.splitlines() if "{" in ln and not ln.lstrip().startswith(("@media", "/*"))]
    assert rules and all(ln.lstrip().startswith(':root[data-theme="post"] .po-pl') or ln.lstrip().startswith(':root[data-theme="post"] a.po-pl') or ln.lstrip().startswith(':root[data-theme="post"] button.po-pl') for ln in rules)
    assert "border-left" not in css and "--bg:" not in css  # 시안에 없는 강조선·토큰 복사 없음


def test_post_home_B_session_chips_whats_new_and_pr_poll_and_letter_avatar():
    # 2026-11-18 Post 홈 검증 B. post-*.js 는 가짜 DOM 시험이 안 불러와서 원문 확인에 더해 Aside 실화면으로 봤다(docs/status/2026-11-18-post-verify-B.md).
    home = (STATIC / "post-home.js").read_text(encoding="utf-8")
    # 세션 표: 번호·기억·API 오류·고쳐야 함 칩. 기억을 모르면 ? 를 지어내지 않고 뺀다
    assert "L.issueOf(s)" in home and "L.prBadge(s.flowPr)" in home and "L.memoryOf(s)" in home and "m.kind !== 'unknown'" in home
    assert "L.prNeedsFix(s)" in home and "'고쳐야 함'" in home and "BHApiNotice.notice(s)" in home
    # 새 소식 칸은 세션이 없을 때·불러오는 중에도 붙고, 세션이 생기면 foot 으로 되돌린다
    assert home.count("restSlot.appendChild(slots.whatsSlot)") == 2 and "foot.appendChild(slots.whatsSlot)" in home
    # 덱 머리 숫자는 타일·띠·문장과 같은 내 차례 건수(BHLogic.turnItems 길이)다: 검사가 실패한 PR 세션도 카드로 올리고, 한 세션의 요청 여럿은 "요청 +N"
    assert "fix: true" in home and "return '고쳐야 함'" in home and "turnN = Math.max(cardN, turnTotal)" in home and "turnTotal = turnCount;" in home
    assert "'요청 +' + it.more" in home and ".po-dc-wait + .po-dc-wait" in (STATIC / "theme-post.css").read_text(encoding="utf-8")
    # 열린 PR 상태를 홈이 열려 있는 동안 1분마다 다시 읽고, 홈을 떠나면 멈춘다(Sauce 홈과 같은 간격)
    assert "MY_PRS_POLL_MS = 20000" in home and "clearInterval(prTimer)" in home and "delete fixBox.dataset.ready" in home
    ui = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    assert "var CACHE_MS = 60000;" in ui  # 확인 주기(20초)는 이 캐시(60초)보다 짧아야 캐시가 풀린 뒤 곧 새로 읽는다
    # #1066: 작은 아바타는 잘린 직원 그림이 아니라 글자, 기억을 모르는 점선 ? 링은 Post 에서 뺀다
    js = (STATIC / "theme-post.js").read_text(encoding="utf-8")
    assert "if (size === 'sm') return letterAvatar(opts.name);" in js and "po-av-letter" in js
    assert "Intl.Segmenter" in js and "letterOf: letterOf" in js and "(PS.letterOf ? PS.letterOf(name)" in home  # 국기·가족 이모지·제로폭 시작 제목도 한 글자, 홈 표와 같은 함수
    assert "title: 'PR #' + s.flowPr.number + ' 의 자동 검사가 실패했어'" in home
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    logic = (STATIC / "flow-logic.js").read_text(encoding="utf-8")
    assert ".po-rest > .wn-slot:empty { display: none; }" in css and ".po-stc-err { width: 150px;" in css.replace(".po-mine .po-stc-err", ".po-stc-err")  # 빈 새 소식 칸 간격·오류 칩 줄바꿈
    m = re.search(r'\.po-si \.ring\.unk\[title="([^"]+)"\] \{ visibility: hidden; \}', css)  # 2회차: 자리는 남긴다(제목 줄 정렬)
    assert m and f"title: '{m.group(1)}'" in logic  # CSS 가 가리키는 문구가 memoryOf 의 unknown title 과 같아야 한다


def test_post_verify_B2_memo_count_teams_and_session_fixes():
    # 2026-11-18 Post 검증 B 2회차. post-*.js 는 가짜 DOM 시험이 안 불러와서 원문 확인이고, 본체는 Aside 실화면이다(docs/status/2026-11-18-post-verify-B.md).
    home = (STATIC / "post-home.js").read_text(encoding="utf-8")
    # 메모의 몇 번째는 덱 머리와 같은 묶음·단위: 내 차례는 건수(카드가 요청 여럿이면 범위), 막힘·확인 못 함은 따로. 카드 수로 세지 않는다
    assert "function memoCount(it)" in home and "n: mine.length" in home and "'내 차례 ' + (end > at ? at + '–' + end : at) + '/' + turnTotal" in home
    assert "'다음 ' + (i + 1) + '/' + items.length" not in home and "text: '다음', onClick: function () { step(1, true); }" in home
    # 메모의 "다음" 은 포커스를 덱 카드로 옮기지 않는다(화면이 덱까지 튀어 메모가 밀려 나간다). J·K 는 그대로 덱 카드로
    assert "function pickTop(id, stay)" in home and "if (stay) return;" in home
    # 팀 칸: 갈래가 없거나 팀이 없는 세션은 "팀 없음" 으로 세어 합이 장면 인원(= 머리 "N개")과 같다
    assert "'팀 없음'" in home and "!teamOf(s.flow)" in home and "sceneSub.textContent = kit.sceneList().length + '개';" in home
    # 닫힌·합쳐진 PR 칩은 남은 검사 결과 색이 아니라 상태로
    assert "prSt === 'CLOSED' ? 'none'" in home and "prSt === 'MERGED' ? 'pass'" in home
    # 차분 목록은 앞 12개 + 더 보기
    assert "CALM_MAX = 12" in home and "'나머지 ' + (all.length - shown.length) + '개 더 보기'" in home
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "m >= 1440 ? Math.floor(m / 1440) + '일째'" in app  # Post 홈 덱·메모의 오래 기다린 요청은 "N일째"
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    assert ':root[data-theme="post"] .po-eb .po-st-idle { display: none; }' in css and ".po-maplist .po-ml-more { grid-column: 1 / -1; }" in css
    # 틀: 상태줄 한도는 비율로 주의·막힘(서버가 status 를 allowed 로 고정), 급할 때만 풀리는 시각을 칩에
    assert "c.source === 'statusline' && c.pct != null ? (c.pct >= 100 ? 'err' : c.pct >= 80 ? 'warn' : '')" in app and "class: 'ptop-when'" in app
    notice = (STATIC / "notice-logic.js").read_text(encoding="utf-8")
    assert "when: when ? when.replace(/^오늘 /, '') : '', source: w.source || ''," in notice
    # 사이드 목록: 접기 단추 포커스 되돌림, 지금 세션 줄을 목록 창 안으로, 걸러보기 탭 방향키·roving tabindex, 글자 아바타에 이름을 넘김
    assert "function postSideAfter(cur)" in app and "sideMode = col; sideShownFor = '';" in app and "foldRefocus" in app and "function onPostFilterKey(e)" in app and "sideEl.addEventListener('keydown', onPostFilterKey);" in app
    assert "tabindex: postFilter === f.id ? '0' : '-1'" in app and "{ size: 'sm', name: sessionTitle(s) }" in app
    # 요청 화면: 도장 튕김이 다시 그리기로 끊기지 않게(STAMP_ANIM_MS 안에는 still 이 아니고, 지난 시간만큼 앞당겨 이어서), 여기서 답하지 않은 요청은 체크 없이
    assert "still: st.shown && Date.now() - st.at.getTime() >= STAMP_ANIM_MS" in app
    sess = (STATIC / "post-session.js").read_text(encoding="utf-8")
    assert "sp.style.animationDelay = -gone + 'ms'" in sess
    assert "function notMine()" in app and "'여기서 답하지 않은 질문'" in app and "if (away) line = resultOf().title;" in app
    assert ':root[data-theme="post"] .qopt { border-radius: 22px; }' in css
    # 새 작업: 막힌 까닭이 있는 칸으로 화면을 옮기고(좁은 폭에서 오류가 화면 밖), 고급 설정이 닫혀 있으면 연다. select 화살표는 반복·자리까지 함께
    assert "function showBlock(sel)" in app and "if (isPostTheme()) advOpen = true; draw(); showBlock('#model-custom');" in app and "showBlock('[data-folder-toggle]')" in app
    assert ':root[data-theme="post"] select.input, :root[data-theme="post"] .light select.input { background-repeat: no-repeat;' in css
    assert "background-color: var(--field); color: var(--text); border-radius: 10px; }" in css and ".folder-pick .folder-opt .pn small.mono { display: -webkit-box;" in css and "title: isPostTheme() ? f.path : null" in app
    assert "attrs['aria-label'] = '계정 사용 한도: ' + lv.chips.map" in app and "(상태줄의 쓴 비율로 판단)" in app  # 칩 풀이·묶음 이름도 같은 판정
    assert "var a = calmList.querySelectorAll('a')[CALM_MAX]; if (a) a.focus();" in home  # 더 보기를 누르면 새로 보인 첫 줄로 포커스


def test_post_new_task_extra_cases_X1():
    # 2026-11-18 Post 새 작업 못 본 케이스 점검 1회차. post-*.js 는 가짜 DOM 시험이 안 불러와서 원문 확인이고, 본체는 Aside 실화면이다(docs/status/2026-11-18-post-extra-newwork.md).
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    # 작업 폴더가 고른 뒤 지워져 시작이 400 으로 거절되면 "Claude Code 가 못 살펴봤어" 가 아니라 폴더 고르기로 돌려보낸다(Post 만)
    assert "if (e.status === 400 && isPostTheme()) { folderCheck(e, run); return; }" in app and "function folderCheck(e, run)" in app
    assert "customMsg = '고른 작업 폴더를 쓸 수 없어: ' + why + ' 다른 폴더를 골라 줘.'" in app and "showBlock('#custom')" in app
    # 서버에 닿지 못한 시작은 분석 실패와 다른 말을 한다
    assert "errNet = e.status === 0" in app and "post && errNet ? '콘솔 서버에 연결하지 못했어'" in app
    # 키보드: 단계가 바뀌면 초점이 문서 맨 위로 튀지 않게 제목으로, 시작 오류·글 비어 있음·폴더 창 취소 뒤에는 누른 칸으로
    assert "id: post ? 'new-title' : null, tabindex: post ? '-1' : null" in app and "document.getElementById('new-title')" in app and "drawnStep !== screen" in app  # 2회차: 프로젝트 준비 안내도 한 단계
    assert "if (startErr && isPostTheme() && document.activeElement === document.body) { var sb = document.getElementById('start-go'); if (sb) sb.focus(); }" in app
    assert "folderCheck(e, run)" in app and "run !== beginRun || step !== 'analyzing'" in app  # 늦게 온 폴더 확인이 다시 시작한 요청을 덮지 않게 and "id: 'start-go'" in app
    assert "textErr = true; draw(); showBlock('#brief'); return;" in app
    assert "backFocus('folder-browse')" in app and "backFocus('custom')" in app and "function backFocus(id)" in app
    # 첨부가 서버에서 거절되면 그 화면의 칩에는 빼기(×)가 없어 돌아가는 길을 알려 준다
    assert "files.length && attachRejected(e, files)" in app and '"다른 걸로 할래" 로 돌아가서 빼 줘.' in app  # 2회차: 첨부 탓인 400·413 에만
    # 아주 긴 폴더 이름: 제목·눈썹은 어디서든 줄을 바꾸고, 위쪽 줄은 알림·테마 단추 대신 이름만 줄어든다
    assert ':root[data-theme="post"] .ptitle .eb, :root[data-theme="post"] .ptitle h1 { overflow-wrap: anywhere; }' in css
    assert ':root[data-theme="post"] #app > .top > :not(.ptop-proj):not(.sp):not(.ptop-lim) { flex-shrink: 0; }' in css and ".ptop-proj b { flex: 0 1 auto; min-width: 0;" in css
    assert ':root[data-theme="post"] #new-title:focus { outline: none; }' in css


def test_post_new_task_extra_cases_X3():
    # 2026-11-18 Post 새 작업 못 본 케이스 2회차(1회차 수정분 독립 재확인). 본체는 Aside 실화면(docs/status/2026-11-18-post-extra-newwork.md 「2회차」).
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # 느린 분석 시작(윈도우 git) 중 요청 고치기·다시 시작을 누르면 늦게 온 시작·폴링 답은 버린다(쓰던 화면이 확인 화면으로 튀지 않게)
    assert "function late(run) { return isPostTheme() && (!alive || run !== beginRun || step !== 'analyzing'); }" in app
    assert "if (isPostTheme() && (!alive || aid !== resume)) { if (alive) loadRecent(); return; }" in app  # 주소 ?id= 로 이어 보는 첫 답도
    assert "if (late(run)) return;\n        aid = d && (d.id || d.analysisId);" in app and "if (!alive || late(run)) return; if (e.status === 400 && isPostTheme())" in app
    assert "function gone() { return !alive || (isPostTheme() && (id !== aid || step !== 'analyzing')); }" in app
    # 폴더 탓 400 안내·지난 시작 오류는 새 분석을 시작하면 지운다
    assert "if (isPostTheme()) { customMsg = ''; startErr = ''; }" in app
    # 분석 뒤 폴더가 지워진 채 시작하면 "claude 를 찾을 수 없어" 대신 폴더를 확인해 말하고, 첨부 안내는 첨부 탓일 때만
    assert "function attachRejected(e, files)" in app and "e.status === 400 || e.status === 502) return api('POST', '/api/folders/validate'" in app
    assert "'시작하지 못했어: 고른 작업 폴더를 쓸 수 없어: ' + String(v.error || '') + ' \"다른 걸로 할래\" 로 돌아가서 다른 폴더를 골라 줘.'" in app
    # 키보드: 폴더를 고르면 목록을 열었던 단추로, id 없는 칸(바꾸기·체크·답 단추)도 다시 그린 뒤 같은 자리로, 프로젝트 준비 안내는 그 제목으로
    assert "draw(); backFocus('folder-toggle'); checkIntro(p); }" in app and "id: isPostTheme() ? 'folder-toggle' : null" in app
    assert "var mark = isPostTheme() && !keepFocus ? focusMark() : null;" in app and "function focusMark()" in app and "return el.className === m.cls;" in app
    assert "if (isPostTheme()) placeFocus(stepMoved, keepFocus, selStart, mark);" in app and "screen = showIntro ? 'intro' : step" in app  # 안내 화면도 있던 칸을 먼저 되돌린다
    assert "h('h1', { id: isPostTheme() ? 'new-title' : null, tabindex: isPostTheme() ? '-1' : null, title: draft.cwd" in app


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_post_x2_docs_many_sessions_sauce_has_no_truncation_note(tmp_path):
    # 2026-11-18 Post 데이터 있는 화면 점검(X2). 산출물 탭은 최근 12개 세션만 읽는다 — Post 만 몇 개가 빠졌는지 알린다(Sauce 는 그대로).
    got = _smoke(tmp_path, "docs", [_session(f"s{i}", updatedAt=1700000100 + i) for i in range(14)])
    assert "더 오래된 세션" not in got["text"] and "data-docs-more" not in json.dumps(got, ensure_ascii=False)


def test_post_x2_data_screens_source_and_css():
    # post-*.js 와 Post 전용 분기는 가짜 DOM 시험이 안 불러와서 원문 확인이다. 본체는 Aside 실화면(docs/status/2026-11-18-post-extra-datascreens.md).
    ui = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    tb = (STATIC / "trouble.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "theme-post.css").read_text(encoding="utf-8")
    # 산출물: 같은 이름의 파일이 여러 세션에서 오면 둘째 줄에 세션 이름, 다시 그려도 키보드 포커스 유지, 좁은 화면에서 고르면 미리보기로, 미리보기 못 하는 문서의 안내가 버튼 위치와 맞게
    assert "multiSess ? entry.session.title || kit.baseName(entry.session.cwd) : ''" in ui and "multiSess = isPost() && all.reduce(" in ui
    assert "back.focus({ preventScroll: true })" in ui and "ae.classList.contains('drow')" in ui and "'data-dkey': post ? entry.key : null" in ui  # 같은 경로 파일이 다른 세션에 있어도 키(폴더|경로)로 되돌림
    assert "function pick(entry, byUser)" in ui and "pv.scrollIntoView({ block: 'start' })" in ui and "pick(entry, true)" in ui
    assert "(ctx.btnAt || '아래') + ' 버튼으로 열어 봐.'" in ui and ui.count("btnAt: isPost() ? '위' : ''") == 2
    assert "data-docs-more" in ui and "isPost() ? sessionList().filter(" in ui
    assert ":root[data-theme=\"post\"] .ext { display: inline-grid; place-items: center; flex: none; width: 44px;" in css and ".ext-docx { background: #2B579A;" in css
    assert ".docs-page .dprev { scroll-margin-top: 88px; }" in css and ".docs-page .drow .dn small { font-size: 11.5px; color: var(--muted); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2;" in css
    # 팀 기록: 거르기·찾기·종류 고르기로 화면을 다시 그려도(목록·한 건·새 기록 셋 다) Post 에서는 누르던 칸에 포커스가 남는다
    assert "function focusKey(page)" in tb and "function focusBack(page, key)" in tb and tb.count("focusBack(page, key);") == 3 and tb.count("var key = focusKey(page);") == 3 and "sameButtons(page, a.className, a.textContent).indexOf(a)" in tb
    assert "getTheme() === 'post'" in tb[tb.index("function focusKey(page)"):tb.index("function focusBack(page, key)")]
    # MCP url 모드: 열 수 없는 주소(javascript: 등)는 Post 에서 [다 했어] 도 막고, 긴 주소는 줄을 바꾼다
    assert "var cantOpen = isUrl && !href && isPostTheme();" in app and "sendBtn.disabled = st.busy || n > 0 || cantOpen;" in app
    assert ":root[data-theme=\"post\"] [data-elicit-url] { overflow-wrap: anywhere; word-break: break-all; }" in css
    # Tab 건너뛰기 링크: Post 만(Sauce 에서는 hidden), 레일보다도 앞, 목록 맨 앞에 하나 더, 포커스가 올 때만 보임
    assert "var on = isPostTheme(), r = document.getElementById('root');" in app and "document.addEventListener('bh-theme', syncSkip);" in app and "skipEl.parentNode.removeChild(skipEl)" in app  # Sauce 에는 붙이지 않는다
    assert "root.appendChild(appEl); syncSkip();" in app and "text: '세션 목록 건너뛰기' }), tabs, list," in app and "text: '본문으로 건너뛰기'" in app
    assert ":root[data-theme=\"post\"] .po-skip:not(:focus) { position: absolute; width: 1px; height: 1px;" in css and ":root[data-theme=\"post\"] #main:focus { outline: none; }" in css


def test_post_x2_docs_old_versions_stay_open_when_picked():
    # 이전 판을 고르면 목록이 다시 그려져 접힌 칸 안에 고른 줄이 숨던 것: Post 는 고른 이전 판이 든 칸을 열어 두고, 연 상태를 기억한다
    ui = (STATIC / "flow-ui.js").read_text(encoding="utf-8")
    assert "det.open = !!st.oldOpen[d.key] || oldKeys.indexOf(st.sel) >= 0;" in ui and "st.oldOpen[d.key] = det.open;" in ui and "oldOpen: {}" in ui


_POST_PROJECT_NODE = r"""
const path = require('path');
const P = require(path.join(process.argv[1], 'post-logic.js'));
const folders = {
  '/w/a': { state: 'yes', key: 'K1', name: 'a', top: '/w/a', folder: 'a' },
  '/w/a/sub': { state: 'yes', key: 'K1', name: 'a', top: '/w/a', folder: 'a' },
  '/w/a-wt': { state: 'yes', key: 'K1', name: 'a', top: '/w/a-wt', folder: 'a-wt' },
  '/w/b': { state: 'yes', key: 'K2', name: 'b', top: '/w/b', folder: 'b' },
  '/w/plain': { state: 'no', reason: 'x' },
  '/w/gone': { state: 'unknown', reason: 'y' }
};
const list = ['/w/a', '/w/a/sub', '/w/a-wt', '/w/b', '/w/plain', '/w/gone', '/w/new', ''].map((cwd, i) => ({ id: 's' + i, cwd }));
const v = P.projectView(list, folders, { key: 'K1', top: '/w/a' });
const all = P.projectView(list, folders, null), before = P.projectView(list, null, { key: 'K1', top: '/w/a' });
process.stdout.write(JSON.stringify({ ids: v.list.map(s => s.id), tag: v.tag, all: all.list.length, allTags: Object.keys(all.tag).length, before: before.list.length, copy: v.list !== list && all.list !== list }));
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_post_project_view_filters_by_repo_and_tags_other_folders():
    """#1070: 같은 저장소(worktree 포함)만 보이고 다른 폴더엔 폴더 이름, 다른 저장소는 뺀다. git 아님·판정 못 함은 감추지 않고 표를 붙이고,
    아직 판정을 못 받은 폴더는 그대로 보인다. 프로젝트가 없거나 판정 전이면 거르지 않는다."""
    r = subprocess.run([NODE, "-e", _POST_PROJECT_NODE, str(STATIC)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ids"] == ["s0", "s1", "s2", "s4", "s5", "s6", "s7"]  # s3(다른 저장소)만 빠진다
    assert out["tag"] == {"s2": {"kind": "folder", "text": "a-wt"}, "s4": {"kind": "nogit", "text": "git 저장소 아님"},
                          "s5": {"kind": "unknown", "text": "저장소 확인 못 함"}, "s7": {"kind": "unknown", "text": "저장소 확인 못 함"}}
    assert out["all"] == 8 and out["allTags"] == 0 and out["before"] == 8 and out["copy"] is True


def test_post_project_scope_only_in_post_and_feeds_every_count():
    """#1070: 거르기는 Post 에서만(Sauce 는 모든 세션 그대로), 그리고 사이드 목록·알림(sideData)·홈(flow-ui kit)·파이프라인이 같은 거른 목록을 쓴다."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "return isPostTheme() && window.BHPostLogic ? window.BHPostLogic.projectView(all, repos.folders, postProject()) : { list: all, tag: {} };" in app
    assert "var all = scopedSessions();" in app and "window.BHLogic.turnItems(all, openIds)" in app  # 띠·알림·레일·덱 숫자
    assert "var arr = scopedSessions();" in app  # 사이드 목록·장면(sceneList)·레일
    assert "sessions: { values: scopedSessions }, requests: requests," in app and "sessions: scopedSessions, loaded:" in app  # 홈·산출물, 파이프라인
    assert "if (loadedOnce && inProject(m)) notifyChange(prev, m);" in app
    assert "if (isPostTheme() && startCwd) setProject({ path: startCwd });" in app and "class: 'ptop-pick'" in app
    assert "kit.projectTag ? kit.projectTag(s) : null" in (STATIC / "post-home.js").read_text(encoding="utf-8")
    assert ':root[data-theme="post"] .po-ptag {' in (STATIC / "theme-post.css").read_text(encoding="utf-8")


def test_post_project_pipeline_follows_picked_project_and_rechecks_unsure_folders():
    """#1070 리뷰: 파이프라인은 마지막 폴더 대신 고른 프로젝트 폴더를, 저장소 판정 뒤에 읽는다. 판정 못 한 폴더가 있으면 다시 묻는다."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    pipe = (STATIC / "post-pipeline.js").read_text(encoding="utf-8")
    assert "var last = (kit.home && kit.home()) || st.last;" in pipe and "if (last && !seen[last]) out.push(last);" in pipe
    assert "loaded: function () { return loadedOnce && repos.tried; }" in app and "home: function () { var pj = postProject(); return pj ? pj.path : ''; } });" in app
    assert "if (unsure) repos.again = setTimeout(function () { repos.sig = null; scheduleSide(); }, 60000);" in app
