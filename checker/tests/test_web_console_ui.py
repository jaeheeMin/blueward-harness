"""웹 콘솔 화면 파일(static/*.js) 시험 (#558). node 가 있으면 순서 막대·버튼 노출 규칙을 가짜 DOM 위에서 확인한다.

서버(*.py)와는 상관없다. 화면이 믿는 API 모양은 flow-logic.js 의 순수 함수로 모아 두었다.
"""
from __future__ import annotations

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
    assert.strictEqual(work.type, 'done'); assert.strictEqual(work.label, '끝났어요'); assert.ok(!('skill' in work));
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
    assert.strictEqual(unk.state, 'unknown'); assert.ok(unk.text.includes('확인하지 못했어요') && !unk.text.includes('준비 안 됨'));
  },
  reload_strip_and_result() {
    const live = [{ id: 'a', status: 'idle' }, { id: 'b', status: 'ended' }, { id: 'c', status: 'running' }];
    assert.strictEqual(L.reloadStrip(false, live), null);
    assert.strictEqual(L.reloadStrip(true, [{ id: 'b', status: 'ended' }]), null);
    assert.deepStrictEqual(L.reloadStrip(true, live), { count: 2, text: '돌고 있는 세션 2개 다시 불러오기 필요' });
    assert.strictEqual(L.reloadResult({ ok: true, harnessVersion: '0.10.140', plugins: [], errorCount: 0 }), 'harness 0.10.140 로 다시 불러왔어요.');
    assert.strictEqual(L.reloadResult({ ok: true, plugins: [{ name: 'harness', version: '0.10.9' }], errorCount: 2 }), 'harness 0.10.9 로 다시 불러왔어요. (오류 2개)');
    assert.ok(L.reloadResult({ queued: true }).includes('끝나면'));
  },
  summary_counts() {
    const list = [{ id: 1, group: 'todo' }, { id: 2, group: 'running' }, { id: 3, status: 'running' }, { id: 4 }, { id: 5, pendingRequestIds: ['r'] }];
    assert.strictEqual(L.summaryText(L.counts(list)), '세션 5개 · 일하는 중 2 · 내 차례 2 · 쉬는 중 1');
    assert.strictEqual(L.summaryText(L.counts([])), '세션 0개 · 일하는 중 0 · 내 차례 0 · 쉬는 중 0');
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
    assert.deepStrictEqual(got.map(c => c.id), ['sync', 'version', 'update', 'reload']);
    assert.deepStrictEqual(got.map(c => c.state), ['done', 'fail', 'run', 'todo']);
    assert.strictEqual(got[3].kind, 'console');
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
    panel.update(sess('work')); assert.deepStrictEqual(buttons(), ['끝났어요', '이 단계 건너뛰기']);
    panel.update(sess('wait')); assert.deepStrictEqual(buttons(), ['다시 확인', '이 단계 건너뛰기']);
    panel.update(sess('human')); assert.deepStrictEqual(buttons(), ['끝났어요', '다시 확인', '이 단계 건너뛰기']);
    // 순서 막대: 지금 단계 하나만 강조
    assert.strictEqual(find(panel.el, e => e.tag === 'li' && e.attrs['aria-current'] === 'step').length, 1);
    assert.strictEqual(find(panel.el, e => e.tag === 'li' && (e.attrs['class'] || '').includes('step')).length, 2);
    // 끝난 갈래: 다음 갈래 버튼, 준비 중은 비활성
    panel.update(sess('skill', { flowFinished: true, nextFlow: { options: [{ flow: 'spec', label: '개발 Spec 만들기' }, { flow: null, disabled: true, label: '권한 양식' }] } }));
    const fin = find(panel.el, e => e.tag === 'button');
    assert.deepStrictEqual(fin.map(b => b.textContent), ['개발 Spec 만들기', '권한 양식준비 중']);
    assert.ok(!fin[0].disabled && fin[1].disabled === true);
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
    assert.ok(panel.el.textContent.includes('어떤 일인가요?'));
    panel.destroy();
    // 갈래 데이터를 못 쓰면(503) 준비 안 됨으로 알린다
    const err = Object.assign(new Error('x'), { status: 503 });
    const { kit: kit2 } = makeKit({ 'GET /api/flows': err });
    const p2 = loadUI(kit2).flowPanel();
    p2.update({ id: 's1', cwd: '/w2', status: 'idle' }); await tick(); await tick();
    assert.ok(p2.el.textContent.includes('아직 준비 안 됨'));
    p2.destroy();
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
    assert.ok(text.includes('세션 2개 · 일하는 중 1 · 내 차례 1 · 쉬는 중 0'));
    assert.ok(text.includes('proj-a') && text.includes('proj-b'));
    assert.ok(text.includes('서브에이전트 1개 실행 중') && text.includes('PR #4 · 검사 통과') && text.includes('이슈 #636'));
    assert.ok(text.includes('내가 승인할 PR 1건'));
    // 숫자 타일: 내 차례 / 일하는 중 / 쉬는 중, 승인 기다리는 PR 은 데이터를 받은 뒤에만 보인다
    const tiles = find(root, e => (e.attrs['class'] || '').split(' ').includes('tile2'));
    assert.deepStrictEqual(tiles.slice(0, 3).map(t => t.textContent), ['내 차례1', 'AI가 일하는 중1', '쉬는 중0']);
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
    assert.deepStrictEqual(tiles.map(t => t.textContent), ['내 차례0', '일하는 중0', '만든 산출물확인 못 함']);
    kinds[0].click();
    assert.ok(went[0].includes('요구사항정의서'));
    // 입력창에 적은 글은 새 작업으로 넘어간다
    const input = find(root, e => e.tag === 'input')[0];
    input.value = '구매오더 조회 앱 요구사항 써 줘';
    find(root, e => e.tag === 'form')[0].listeners.submit[0]({ preventDefault() {} });
    assert.strictEqual(went[1], '구매오더 조회 앱 요구사항 써 줘');
    assert.strictEqual(find(root, e => (e.attrs['class'] || '').includes('call')).length, 0);
  }
};

(async () => {
  const name = process.argv[3];
  assert.ok(cases[name], '없는 시험 ' + name);
  await cases[name]();
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
global.document = { documentElement: { style } };
require(file);
const BH = window.BH;
const out = { first: BH.getScale(), zoom: style.zoom, keys: Object.keys(BH).sort().join(',') };
BH.setScale('1.3');
out.afterSet = [BH.getScale(), store['bh-scale'], style.zoom];
BH.setScale('nonsense');
out.afterBad = [BH.getScale(), style.zoom];
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
    assert r["first"] == "1.15" and r["zoom"] == "1.15"
    assert r["keys"] == "SCALES,getScale,read,setScale,write"  # 옛 테마 표·디자인 전환은 없다
    assert r["afterSet"] == ["1.3", "1.3", "1.3"]
    assert r["afterBad"] == ["1.3", "1.3"]  # 모르는 값은 저장도 적용도 하지 않는다(바로 앞 값 유지)
    assert _theme_run({"bh-scale": "1.45"})["zoom"] == "1.45"
    assert _theme_run({"bh-scale": "zzz"})["first"] == "1.15"


def test_no_theme_or_design_switch_left():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    theme = (STATIC / "theme.js").read_text(encoding="utf-8")
    for needle in ("data-design", "data-tone", "design-quick", "getTheme", "getDesign", "setDesign", "BH.THEMES", "BH.DESIGNS"):
        assert needle not in app and needle not in css and needle not in theme, needle
    # 설정 화면에는 글자 크기만 남는다
    settings = app[app.index("function settingsView"):app.index("/* ---------- 시작 ---------- */")]
    assert "글자 크기" in settings and "테마" not in settings and "디자인" not in settings


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
    assert v["bg"] == "#132322" and v["surface"] == "#0e1a19" and v["accent"] == "#3ddc91" and v["light"] == "#edf7f5" and v["attn"] == "#ffcd48"


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
    # 맨 위 띠는 내 차례가 없으면 만들지 않는다
    ann = app[app.index("function renderAnn"):app.index("function projectOf")]
    assert re.search(r"clear\(annEl\);\s*if \(!d\.todo\.length\) return;", ann) and "내 차례 ' + d.todo.length + '건 — '" in ann
    # 메뉴: 내 일 → /, 작업 → 가장 위 세션, 새 작업 → /new, 설정 → /settings. 길이 없는 산출물은 두지 않는다.
    head = app[app.index("function renderHead"):app.index("function renderSide")]
    assert "link('/', { text: '내 일'" in head and "link('/new', { text: '새 작업'" in head and "link('/settings'" in head
    assert "'/s/' + encodeURIComponent(rows[0].id)" in head and "text: '산출물'" not in head
    # 세션 목록: 기억은 데이터가 없어 ? 와 툴팁만, 세션이 없으면 점선 상자와 새 세션 버튼
    side = app[app.index("function renderSide"):app.index("function renderRail")]
    assert "'기억 사용량 확인 못 함'" in side and "text: '?'" in side
    assert "아직 세션이 없어. 새 작업을 시작하면 여기에 생겨." in side and "+ 새 세션" in side
    assert "logo-sauce.png" in head and (STATIC / "logo-sauce.png").is_file() and not (STATIC / "blueward-logo.png").exists()


def test_design_states_have_shape_cues_not_only_color():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for needle in ("\\2713", "\\2715", "content: '!", "content: '?'", "dashed", "\\25CF"):
        assert needle in css, needle


def test_new_ui_copy_says_claude_code_not_claude():
    for name in ("flow-ui.js", "flow-logic.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"Claude(?! Code)", text), name
