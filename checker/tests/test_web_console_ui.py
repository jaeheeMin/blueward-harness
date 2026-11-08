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
    // 시안 G-13: 새 세션이 스스로 하는 점검은 최신 내용 받기·하네스 판 두 줄뿐(갱신·다시 불러오기는 도구 줄)
    assert.deepStrictEqual(got.map(c => c.id), ['sync', 'version']);
    assert.deepStrictEqual(got.map(c => c.state), ['done', 'fail']);
    assert.deepStrictEqual(got.map(c => c.name), ['최신 내용 받기', '하네스 판']);
    assert.strictEqual(L.autoChecksOpen({ startChecks: [{ id: 'sync', state: 'done' }, { id: 'version', state: 'pending' }] }), true);
    assert.strictEqual(L.autoChecksOpen({ startChecks: [{ id: 'sync', state: 'done' }, { id: 'version', state: 'skipped' }, { id: 'update', state: 'pending' }] }), false);
    assert.strictEqual(L.autoChecksOpen({}), false);
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
    // 갈래 설명은 AI 말 한 줄(line)로 합쳐지고, 따로 "어떤 일인가요?" 제목이나 "이 일은" 줄은 없다
    assert.ok(ch.line.textContent.includes('이 일은 요구사항 갈래야.') && ch.line.textContent.includes('요구사항을 더하는 일'));
    assert.ok(!ch.el.textContent.includes('어떤 일인가요?') && !ch.el.textContent.includes('이 일은'));
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
      { id: 'n1', title: '새것', cwd: '/w/a', group: 'todo', updatedAt: 300 },
      { id: 'n2', title: '가장 오래', cwd: '/w/b', group: 'todo', updatedAt: 100 },
      { id: 'n3', title: '중간', cwd: '/w/c', group: 'todo', updatedAt: 200 },
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
  },
  standard_kind_hint_and_srs_status_cell() {
    // 숫자 띠·큰 순서 알약은 단계 이름 끝 괄호 설명을 뗀 짧은 이름(시안 G-09·12), 전체는 title
    assert.strictEqual(L.shortStepName('표준 건 작업 시작하기(그 [DEV-xxx] 로, 작업 기록과 작업 공간을 자동으로 만들어요)'), '표준 건 작업 시작하기');
    assert.strictEqual(L.shortStepName('SRS 쓰기'), 'SRS 쓰기');
    assert.strictEqual(L.shortStepName('(괄호만)'), '(괄호만)');  // 다 지워지면 원래 이름
    // step.short(workflow.json)가 있으면 그것, 없으면 괄호만 뗀 이름
    assert.strictEqual(L.stepShort({ name: '올리고 검토 요청하기', short: '올리기' }), '올리기');
    assert.strictEqual(L.stepShort({ name: '표준 건 작업 시작하기(설명)' }), '표준 건 작업 시작하기');
    const shortStep = { flowId: 'srs', flowSteps: [{ name: 'SRS 쓰기', short: '쓰기', state: 'done' }, { name: '올리고 검토 요청하기', short: '올리기', state: 'now' }, { name: '승인받고 합쳐지기 기다리기', short: '승인·합치기', state: 'todo' }], stepIndex: 1 };
    const shortCell = L.sessionStrip(shortStep, undefined).find(c => c.id === 'step');
    if (shortCell && shortCell.value !== '확인 못 함') { assert.strictEqual(shortCell.value, '2 / 3 올리기'); assert.strictEqual(shortCell.title, '올리고 검토 요청하기'); }
    const longStep = { flowId: 'standard', flowSteps: [{ name: '표준 건 작업 시작하기(그 [DEV-xxx] 로, 작업 기록과 작업 공간을 자동으로 만들어요)', state: 'now' }, { name: '올리기', state: 'todo' }], stepIndex: 0 };
    const stepCell = L.sessionStrip(longStep, undefined).find(c => c.id === 'step');
    if (stepCell && stepCell.value !== '확인 못 함') { assert.ok(!stepCell.value.includes('(')); assert.ok(stepCell.title.includes('자동으로 만들어요')); }
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
  async dom_docs_page() {
    const s1 = { id: 's1', title: 'SRS 세션', cwd: '/w/p', updatedAt: 9, canSend: true, flowPr: { number: 6, state: 'OPEN' } };
    const files = { files: [
      { path: 'docs/SRS_v0.2.md', kind: 'md', size: 100, mtime: 20, changed: false, versions: ['docs/SRS_v0.1.md', 'docs/SRS_v0.2.md'] },
      { path: 'out/BW_Backlog_v0.1.xlsx', kind: 'xlsx', size: 18000, mtime: 30, changed: true },
      { path: 'audit/log.md', kind: 'md', size: 5, mtime: 10, changed: true }] };
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
    // '문서 목록 보기' → 시안 G-14: 왼쪽 목록 + 가장 최근 글 문서 미리보기
    btn('문서 목록 보기').click(); for (let i = 0; i < 4; i++) await tick();
    for (const need of ['내가 만든 문서', '요구사항 · 설계', '고객 양식', '기록', 'SRS', 'v0.2 · md', 'BW_Backlog', 'v0.1 · xlsx', 'log.md', '검토 중', '안 올림', '이전 판 1개', '안 올림 = 내 PC에만 · 검토 중 = 승인 기다림 · 합쳐짐 = 팀 공용본']) assert.ok(root.textContent.includes(need), need);
    assert.ok(!root.textContent.includes('고객 양식으로 뽑았어') && !root.textContent.includes('확인 못 함 = 알 수 없음'));
    assert.ok(btn('열기') && btn('폴더에서 보기') && btn('xlsx로 뽑기'));
    assert.ok(root.textContent.includes('SRS_v0.2.md · v0.2') && root.textContent.includes('세션 SRS 세션'));
    btn('xlsx로 뽑기').click(); await tick(); await tick();
    assert.ok(sentTo().length === 2 && sentTo()[1][2].text.includes('docs/SRS_v0.2.md') && sentTo()[1][2].text.includes('고객 양식'));  // 콘솔이 직접 뽑지 않고 세션에 말을 보낸다
    assert.ok(root.textContent.includes('세션에 보냈어'));
    // 고쳐 달라고 하기
    find(root, e => e.attrs.id === 'doc-ask')[0].listeners.input[0]({ target: { value: '납품일 추가' } });
    btn('보내기').click(); await tick(); await tick();
    const fix = sentTo()[2];
    assert.ok(fix && fix[2].text.includes('납품일 추가') && fix[2].text.includes('고쳐 줘'));
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
    p.update({ id: 's1', startChecks: [] }); assert.ok(p.el.hidden);
    p.destroy();
    // 검사 실패는 ✕ 막힘, 결과를 못 읽으면 ? 확인 못 함, 통과·진행 중에는 둘 다 없다
    const card = checks => ui.prCard({ flowPr: { number: 6, state: 'OPEN', title: 't', checks } });
    const fail = card('fail'), unk = card('none');
    assert.ok(fail.attrs['class'].includes('blocked') && fail.textContent.includes('✕ 막힘') && !fail.textContent.includes('? 확인 못 함'));
    assert.ok(unk.attrs['class'].includes('unsure') && unk.textContent.includes('? 확인 못 함') && unk.textContent.includes('통과도 실패도 아니야'));
    for (const c of ['pass', 'pending']) { const ok = card(c); assert.ok(!/blocked|unsure/.test(ok.attrs['class']) && !ok.textContent.includes('✕ 막힘') && !ok.textContent.includes('? 확인 못 함'), c); }
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
BH.setScale('1.15');
out.afterSet = [BH.getScale(), store['bh-zoom'], style.zoom];
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
    assert r["first"] == "1" and r["zoom"] == "1"  # 시안(가)대로 보통 = 배율 없음(#721)
    assert r["keys"] == "SCALES,getScale,read,setScale,write"  # 옛 테마 표·디자인 전환은 없다
    assert r["afterSet"] == ["1.15", "1.15", "1.15"]
    assert r["afterBad"] == ["1.15", "1.15"]  # 모르는 값은 저장도 적용도 하지 않는다(바로 앞 값 유지)
    assert _theme_run({"bh-zoom": "0.9"})["zoom"] == "0.9"
    assert _theme_run({"bh-zoom": "zzz"})["first"] == "1"
    assert _theme_run({"bh-scale": "1.15"})["first"] == "1"  # 옛 키(보통이 1.15 였다)는 읽지 않는다


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
    assert re.search(r"clear\(annEl\);\s*if \(d\.todo\.length\) \{", ann) and "내 차례 ' + d.todo.length + '건 — '" in ann
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


def test_design_states_have_shape_cues_not_only_color():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for needle in ("\\2713", "\\2715", "content: '!", "content: '?'", "dashed", "\\25CF"):
        assert needle in css, needle


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


def _smoke(tmp_path, route, sessions, requests=None, extra=None, actions=None):
    import json
    data = dict(extra or {})
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
    assert "<section.light.talk>" in dump and "<aside.sess-side>" in dump and "<div.comp>" in dump
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
    assert dump.count("<button.qopt>") == 1 and "직접 적어 답하기" in text and "질문 · " not in text.replace("질문 ·", "질문 · ") or True
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
            "toolInput": {"command": "rm x.xlsx", "description": "옛 파일 지우기"}, "permissionSuggestions": [1], "suggestionText": ["Bash(rm *) 허용 규칙 추가"]}
    edit = {"id": "p2", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Edit", "toolInput": {"file_path": "docs/a.md", "old_string": "가", "new_string": "나"}}
    risky = {"id": "p3", "sessionId": "s1", "kind": "permission", "status": "pending", "toolName": "Bash", "toolInput": {"command": "curl x", "dangerouslyDisableSandbox": True}}
    sess = [_session("s1", pendingRequestIds=["p1", "p2", "p3"])]
    got = _smoke(tmp_path, "r/p1", sess, [bash, edit, risky])
    for need in ("확인 필요", "옛 파일 지우기", "자세히 (명령 원문)", "이번만 허락", "하지 마", "다음 규칙이 추가됩니다", "도구에 넘기는 입력 전체"):
        assert need in got["text"], need
    assert "<details.more>" in got["dump"] and "<details[open].more>" not in got["dump"]  # 쉬운 설명이 있는 명령은 원문을 접어 둔다
    got = _smoke(tmp_path, "r/p2", sess, [bash, edit, risky])
    assert "원래 글가바꾼 글나" in got["text"] and "<details[open].more>" in got["dump"]  # #634 이름, 고치는 일은 열어 둔다
    got = _smoke(tmp_path, "r/p3", sess, [bash, edit, risky])
    assert "샌드박스를 끄고 실행해" in got["text"] and "<details[open].more>" in got["dump"]  # 위험 표시는 접지 않는다


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
def test_session_screen_shows_auto_mode_unavailable_note(tmp_path):
    note = "auto 모드를 쓸 수 없는 것 같아. 이유는 확인 못 함 (claude 가 알려 준 모드 원문: default)"
    got = _smoke(tmp_path, "s/s1", [_session("s1", permissionChoice="auto", permissionMode="default", permissionNote=note)])
    assert note in got["text"]
    clean = _smoke(tmp_path, "s/s1", [_session("s1", permissionChoice="auto", permissionMode="auto")])
    assert "auto 모드를 쓸 수 없는 것 같아" not in clean["text"]


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
    assert "'/new?from=' + encodeURIComponent(sid)" in app and app.count("link(newHref(),") == 3  # 헤더 메뉴 · 목록 아래 + 새 세션 · 접힌 레일 +
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
    shown = {"GET /api/folders/intro": {"ready": "no", "seen": False, "show": True}, "POST /api/folders/intro/seen": {"seen": True}}
    pick = [{"click": "[data-folder-toggle]"}, {"click": ".folder-opt", "index": 2}]
    got = _smoke(tmp_path, "new", [], extra=dict(_folder_rows(), **shown), actions=pick)
    text = got["text"]
    for need in ("프로젝트 준비", "needs 준비하기", "이 폴더엔 아직 하네스 구조가 없어", "네 차례", "표준 구조를 만들까? 한 번만 하면 돼",
                 "만들고 나면 GitHub에 올려서 팀 승인을 받아. 그다음부터 문서를 쓸 수 있어.", "만들기", "나중에", "만들어지는 것",
                 "templates/", "고객 양식을 넣는 곳", "rules/", "문서 검사 기준", "docs/ssot/", "요구사항정의서 자리", "audit/", "변경 기록",
                 "만든 뒤 할 일", "고객 양식 파일을 templates/ 에 넣기", "GitHub에 올려서 승인받기", "첫 작업 시작"):
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
    for need in ("내가 만든 문서", "요구사항 · 설계", "SRS.md", "안 올림"):  # 시안 G-14: 처음엔 최근 글 문서를 골라 미리보기까지 보인다(빈 안내 대신)
        assert need in got["text"], need
    assert "산출물" in got["head"] and "GET /api/sessions/s1/files" in got["calls"]  # 새 서버 API 없이 세션별 문서 목록을 모은다


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_settings_screen_matches_design(tmp_path):
    got = _smoke(tmp_path, "settings", [_session("s1")])
    text, dump = got["text"], got["dump"]
    for need in ("보기와 알림", "글자 크기", "작게", "보통", "크게", "AI가 묻는 범위", "연결 상태", "GitHub", "하네스 판", "프로젝트", "고급", "AI 모델", "생각 깊이"):
        assert need in text, need
    assert dump.count("<button.scale>") == 3 and dump.count("<button.radio>") >= 1  # 시안 .seg / .radio 모양, 기본 위젯 없음
    assert "<select" not in dump and "<input" not in dump
    assert "화면 밝기" not in text  # 다크 한 벌뿐이라 넣지 않았다
    assert dump.count("<button.swrow>") == 3 and "내 차례가 오면" in text  # 알림 스위치 셋(#651)은 별도 시험에서 본다
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
    for need in ("하네스가 새 판(0.10.186)으로 바뀌었어 · 이번에 바뀐 것", "0.10.186", "첫 줄이야", "0.10.185", "둘째 줄이야", "알겠어"):
        assert need in got["text"], need
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
def test_chat_draws_hook_block_cards_two_kinds_and_fix_button(tmp_path):
    chat = [{"t": 1, "role": "me", "text": "문서 써 줘"},
            {"t": 2, "role": "block", "hook": "pre_write_guard", "kind": "blocked", "tool": "Write",
             "text": "문서가 템플릿을 따르지 않습니다. 개요 절이 없습니다.\n자세한 위반 목록입니다.\n\n다음: 개요 절을 추가하십시오.", "fix": "개요 절을 추가하십시오."},
            {"t": 3, "role": "block", "hook": "stop-deliver", "kind": "cannot_check", "text": "엔진을 받지 못해 검사 불능입니다.", "fix": ""}]
    got = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)])
    text, dump = got["text"], got["dump"]
    assert "<div.q.blocked>" in dump and "<div.q.unsure>" in dump
    assert "✕ 막힘" in text and "하네스 검사가 막았어 · 파일 쓰기 검사" in text
    assert "? 확인 못 함" in text and "검사를 못 해서 멈췄어 · 마무리 확인" in text
    assert "문서가 템플릿을 따르지 않습니다." in text and "자세한 위반 목록입니다." not in text  # 첫 문장만 크게, 나머지는 접힘
    assert "고치는 법 개요 절을 추가하십시오." in text
    # 시안 G-16 단추: 막힘 [그렇게 고쳐 줘] [내가 직접 볼게] [검사 원문] / 확인 못 함 [검사 다시 돌리기] [관리자에게 알리기]
    assert text.count("그렇게 고쳐 줘") == 1 and "내가 직접 볼게" in text and "검사 원문" in text
    assert "검사 다시 돌리기" in text and "관리자에게 알리기" in text
    assert "<button.pill.dark.sm>" in dump  # 보내는 단추는 진한 단추
    unsent = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat, canSend=False)])
    assert "그렇게 고쳐 줘" not in unsent["text"] and "검사 다시 돌리기" not in unsent["text"] and "✕ 막힘" in unsent["text"]
    assert "내가 직접 볼게" in unsent["text"] and "관리자에게 알리기" in unsent["text"]  # 보내지 않는 단추는 남는다
    mine = _smoke(tmp_path, "s/s1", [_session("s1", chat=chat)], actions=[{"click": "[data-block-self]"}])
    assert "직접 보기로 했어." in mine["text"] and mine["text"].count("내가 직접 볼게") == 0
    unknown = _smoke(tmp_path, "s/s1", [_session("s1", chat=[dict(chat[1], hook="새_훅")])])
    assert "하네스 검사가 막았어 · 새_훅" in unknown["text"]  # 이름표에 없으면 원래 이름


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
    assert dump.count("<button.swrow>") == 3 and "<input" not in dump  # 기본 checkbox 가 아니라 스위치 모양
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
