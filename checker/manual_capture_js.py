"""화면 캡처(`checker.manual_capture`)가 페이지에 주입하는 JavaScript(#533).

요소 위치는 **화면에 보이는 이름**으로 찾는다(#348 시험의 방식). 찾기만 하고 판정(0개·1개·여러 개)은 파이썬이 한다.
필터는 라벨과 입력 칸을 묶은 영역, 열은 머리글부터 표 아래 끝(보이는 만큼)까지다.
후보는 화면 밖이거나 조상의 overflow 로 잘려 일부만 보이는 것까지 **모두** 읽는 순서로 내고 `visible` 로 구분한다(그래서 같은 이름이 화면 밖에 더 있으면
파이썬이 ambiguous 로 판정하고, `index` 도 화면 밖을 포함한 전체 순서로 센다). 가로 스크롤 밖 열은 `scrollColumn`(하나)·`scrollColumns`(같은 표의 여럿을 한 번에)가 같은 목록·순서로 골라 먼저 보이게 한다.
`팝업` 단계 뒤에는 `setScope` 가 찾는 범위를 그 대화상자 안으로 좁히고(`clearScope` 로 되돌린다), 후보 찾기는 모두 그 범위 안에서만 한다.
"""
from __future__ import annotations

# 준비 대기(UI5): 문서가 다 불러와졌고, UI5 코어가 초기화돼 있고 화면을 다시 그릴 일이 없고, 막는 층(busy)이 없다.
# 값: true 준비됨 / false 아직 / "no-ui5" UI5 가 없는 페이지(문서만 다 불러옴)
READY_JS = """(() => {
  if (document.readyState !== 'complete') return false;
  if (!(window.sap && sap.ui && sap.ui.getCore)) return 'no-ui5';
  const core = sap.ui.getCore();
  if (core.isInitialized && !core.isInitialized()) return false;
  if (core.getUIDirty && core.getUIDirty()) return false;
  if (document.querySelector('.sapMBusyDialog, .sapUiLocalBusy, .sapUiBlockLayer:not(.sapUiBlockLayerHidden)')) return false;
  return true;
})()"""

LIB_JS = r"""(() => {
  const trimLabel = s => (s || '').replace(/\s+/g, ' ').replace(/[\s:：*]+$/, '').trim();
  const clip = el => {
    const r = el.getBoundingClientRect();
    let L = r.left, T = r.top, R = r.right, B = r.bottom;
    // 고정 위치(position: fixed) 요소 위의 조상은 그 요소를 자르지 않는다. UI5 팝업은 크기 0·overflow hidden 인
    // 정적 영역(sap-ui-static) 안에 고정 위치로 그려져, 그 조상까지 보면 팝업 안 요소가 모두 잘린 것으로 나왔다(#653 실제 테넌트 100).
    for (let p = el.parentElement, prev = el; p; prev = p, p = p.parentElement) {
      if (getComputedStyle(prev).position === 'fixed') break;
      const cs = getComputedStyle(p);
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
        const pr = p.getBoundingClientRect();
        if (cs.overflowX !== 'visible') { L = Math.max(L, pr.left); R = Math.min(R, pr.right); }
        if (cs.overflowY !== 'visible') { T = Math.max(T, pr.top); B = Math.min(B, pr.bottom); }
      }
    }
    L = Math.max(L, 0); T = Math.max(T, 0); R = Math.min(R, innerWidth); B = Math.min(B, innerHeight);
    return { full: { x: r.left, y: r.top, w: r.width, h: r.height }, x: L, y: T, w: R - L, h: B - T };
  };
  const shown = el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    return true;
  };
  // 전부 보이면 잘린 사각형, 아니면 null
  const fully = (el, ratio) => {
    if (!shown(el)) return null;
    const c = clip(el);
    if (c.full.w <= 0 || c.full.h <= 0 || c.w <= 0 || c.h <= 0) return null;
    return (c.w * c.h) / (c.full.w * c.full.h) >= (ratio || 0.98) ? c : null;
  };
  const rectOf = c => ({ x: c.x, y: c.y, w: c.w, h: c.h });
  const union = list => {
    const x = Math.min(...list.map(c => c.x)), y = Math.min(...list.map(c => c.y));
    const x2 = Math.max(...list.map(c => c.x + c.w)), y2 = Math.max(...list.map(c => c.y + c.h));
    return { x, y, w: x2 - x, h: y2 - y };
  };
  const uniq = els => [...new Set(els)];

  // 찾는 범위. 기본은 문서 전체, `팝업` 단계 뒤에는 그 대화상자 안(setScope). 범위 뿌리가 사라지면(팝업이 닫힘) 아무것도 못 찾는다.
  let scopeEl = null;
  const R = () => (scopeEl ? (scopeEl.isConnected ? scopeEl : document.createDocumentFragment()) : document);

  const labelsNamed = name => uniq([...R().querySelectorAll('label, .sapMLabel, .sapUiCompFilterLabel')])
    .filter(l => trimLabel(l.textContent) === name);

  const inputOf = lab => {
    let t = null;
    const f = lab.getAttribute('for');
    if (f) t = document.getElementById(f);
    if (!t && lab.id && window.sap && sap.ui && sap.ui.getCore) {
      try {
        const c = sap.ui.getCore().byId(lab.id), lf = c && c.getLabelFor && c.getLabelFor();
        const tc = lf && sap.ui.getCore().byId(lf);
        t = tc && tc.getDomRef();
      } catch (e) { /* UI5 컨트롤이 아니다 */ }
    }
    if (!t) {
      const n = lab.nextElementSibling;
      if (n && (n.matches('input, select, textarea') || n.querySelector('input, select, textarea'))) t = n;
    }
    if (!t) return null;
    return t.closest('[data-sap-ui]') || t;
  };

  // 요소의 사각형. 전부 보이면 {r: 보이는 사각형, v: true}, 화면 밖·잘림이면 {r: 원래 사각형, v: false}, 화면에 없으면(크기 0) null.
  const rectFor = el => {
    if (!shown(el)) return null;
    const c = clip(el);
    if (c.full.w <= 0 || c.full.h <= 0) return null;
    const f = fully(el);
    return f ? { r: rectOf(f), v: true } : { r: { x: c.full.x, y: c.full.y, w: c.full.w, h: c.full.h }, v: false };
  };
  const iou = (a, b) => {
    const ix = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
    const iy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
    const i = ix * iy, u = a.w * a.h + b.w * b.h - i;
    return u > 0 ? i / u : 0;
  };

  // 후보 전부(화면 밖 포함)를 읽는 순서로 낸다. 판정은 파이썬(judge)이 하고, scrollColumn 도 같은 목록·순서를 쓴다.
  const cands = (kind, name) => {
    const items = [];
    let noInput = 0;
    const add = (el, g) => { if (g) items.push({ el, x: g.r.x, y: g.r.y, w: g.r.w, h: g.r.h, visible: g.v }); };
    if (kind === '필터') {
      for (const lab of labelsNamed(name)) {
        const a = rectFor(lab);
        if (!a) continue;
        const inp = inputOf(lab);
        const b = inp && rectFor(inp);
        if (!inp) { noInput += 1; continue; }
        if (b) add(lab, { r: union([a.r, b.r]), v: a.v && b.v });
      }
    } else if (kind === '버튼') {
      const els = uniq([...R().querySelectorAll('button, [role=button], .sapMBtn, input[type=button], input[type=submit]')])
        .filter(e => [e.innerText, e.getAttribute('aria-label'), e.title, e.value].some(v => trimLabel(v) === name));
      for (const e of els) add(e, rectFor(e));
    } else if (kind === '열') {
      for (const h of colHeaders(name)) {
        const g = rectFor(h);
        if (!g) continue;
        if (g.v) g.r = columnBox(h, g.r);
        add(h, g);
      }
    } else {
      const els = [...(scopeEl ? R() : document.body).querySelectorAll('*')].filter(e => !['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(e.tagName) &&
        trimLabel(e.textContent) === name && ![...e.children].some(k => trimLabel(k.textContent) === name));
      for (const e of els) add(e, rectFor(e));
    }
    items.sort((p, q) => (Math.floor(p.y / 10) - Math.floor(q.y / 10)) || (p.x - q.x));
    const kept = [];
    for (const it of items) if (!kept.some(k => iou(k, it) >= 0.9)) kept.push(it);
    return { items: kept, noInput };
  };
  const find = (kind, name) => {
    const { items, noInput } = cands(kind, name);
    return { items: items.map(({ el, ...r }) => r), noInput };
  };

  // 열 네모: 머리글부터 같은 열의 보이는 본문 칸 아래 끝까지. UI5 표(sap.ui.table)는 머리글과 본문이 다른 <table> 이라
  // 가장 가까운 <table> 은 머리글 표뿐이다(#637 실제 테넌트 100). 그래서 바깥 격자(role=grid 등)에서 같은 aria-colindex 칸을 모은다.
  // 칸을 못 모으면 바깥 격자의 보이는 아래 끝, 그것도 없으면 가장 가까운 표의 아래 끝까지.
  const columnBox = (h, hr) => {
    const grid = h.closest('[role=grid], [role=treegrid], [role=table], .sapUiTable, .sapMList') || h.closest('table');
    let bottom = hr.y + hr.h;
    const ci = h.getAttribute('aria-colindex');
    const cells = grid && ci ? [...grid.querySelectorAll('[aria-colindex="' + ci + '"]')].filter(c => c !== h && shown(c)) : [];
    const vis = cells.map(c => fully(c)).filter(Boolean).map(rectOf).filter(r => r.y >= hr.y);
    if (vis.length) bottom = Math.max(bottom, ...vis.map(r => r.y + r.h));
    else {
      // 머리글과 본문이 한 <table> 이면(sap.m.Table·HTML 표) 그 표가 머리글보다 아래로 내려간다. 머리글뿐이면 바깥 격자를 쓴다.
      const t = h.closest('table'), tc = t && clip(t);
      const box = tc && tc.y + tc.h > hr.y + hr.h + 2 ? tc : (grid && clip(grid));
      if (box) bottom = Math.max(bottom, box.y + box.h);
    }
    return { x: hr.x, y: hr.y, w: hr.w, h: bottom - hr.y };
  };

  const colHeaders = name => uniq([...R().querySelectorAll('th, [role=columnheader], .sapMListTblHeaderCell, .sapUiTableCol')])
    .filter(h => trimLabel(h.textContent) === name);

  // 가로 스크롤 밖 열을 보이게 한다. 같은 이름이 여럿이면 index(1부터, 읽는 순서)가 가리키는 것만.
  const scrollColumn = (name, index) => {
    const { items } = cands('열', name);  // find 와 같은 후보 목록(화면 밖 포함)·같은 순서
    if (items.length === 0) return 0;
    let pick = items[0];
    if (items.length > 1) {
      if (!index) return items.length;  // 여럿인데 index 가 없으면 고르지 않는다(judge 가 ambiguous 로 판정)
      pick = items[index - 1];
      if (!pick) return 0;
    }
    if (!pick.visible) pick.el.scrollIntoView({ block: 'nearest', inline: 'center' });
    return 1;
  };

  // `팝업` 단계의 `행`(#673): 이름이 유일한 열 머리글과 같은 aria-colindex 의 보이는 본문 칸(role=gridcell)을 위에서부터 센다.
  // 칸 안에 보이는 아이콘(.sapUiIcon)이 있으면 그 가운데를, 없으면 칸 가운데를 누를 자리로 돌려준다. 칸 글자·아이콘 유무도 함께 돌려준다.
  const cellOf = (name, row) => {
    const { items } = cands('열', name);
    if (items.length !== 1) return { ok: false, count: items.length };
    const h = items[0].el;
    const grid = h.closest('[role=grid], [role=treegrid], [role=table], .sapUiTable, .sapMList') || h.closest('table');
    const ci = h.getAttribute('aria-colindex');
    if (!grid || !ci) return { ok: false, count: 1, noGrid: true };
    const vis = [...grid.querySelectorAll('[role=gridcell][aria-colindex="' + ci + '"]')]
      .map(c => ({ c, f: fully(c) })).filter(o => o.f).map(o => ({ c: o.c, r: rectOf(o.f) }))
      .sort((p, q) => p.r.y - q.r.y);
    const o = vis[row - 1];
    if (!o) return { ok: false, count: 1, rows: vis.length };
    const icon = o.c.querySelector('.sapUiIcon');
    const ig = icon && fully(icon);
    return { ok: true, rect: ig ? rectOf(ig) : o.r, text: trimLabel(o.c.textContent), icon: !!icon, rows: vis.length };
  };

  // 같은 표의 열 여럿을 한 번에 보이게 한다(#657). 열마다 따로 가운데로 넘기면 먼저 보이던 왼쪽 열이 밀려난다.
  // 열들의 가로 범위(가장 왼쪽 열 시작 ~ 가장 오른쪽 열 끝)가 표의 보이는 폭 안이면 그 범위가 다 보이는 위치 하나로 넘긴다.
  // 가로 스크롤 요소는 sap.ui.table 이면 `.sapUiTableHSb`(scrollLeft), 아니면 overflow-x 가 auto·scroll 인 가장 가까운 조상이다.
  // 못 찾으면 ok:false(파이썬이 열마다 scrollColumn 으로 되돌아간다). 범위가 안 들어가면 넘기지 않고 fits:false 로 알린다.
  const scrollColumns = list => {
    const picks = [];
    for (const { name, index } of list) {
      const { items } = cands('열', name);  // scrollColumn 과 같은 후보·같은 index 기준
      if (items.length === 0) continue;
      let pick = items[0];
      if (items.length > 1) {
        if (!index) continue;
        pick = items[index - 1];
        if (!pick) continue;
      }
      picks.push({ name, el: pick.el });
    }
    if (picks.length === 0) return { ok: false, cols: [] };
    const scrollerOf = el => {
      const t = el.closest('.sapUiTable'), sb = t && t.querySelector('.sapUiTableHSb');
      if (sb && sb.scrollWidth > sb.clientWidth) return sb;
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (/(auto|scroll|overlay)/.test(getComputedStyle(p).overflowX) && p.scrollWidth > p.clientWidth + 1) return p;
      }
      return null;
    };
    const groups = new Map();
    for (const p of picks) {
      const sc = scrollerOf(p.el);
      if (!sc) return { ok: false, cols: [] };
      if (!groups.has(sc)) groups.set(sc, []);
      groups.get(sc).push(p);
    }
    const out = [];
    for (const [sc, ps] of groups) {
      const base = sc.getBoundingClientRect().left - sc.scrollLeft;  // 표 안 좌표의 0 (지금 스크롤과 무관)
      const cols = ps.map(p => { const r = p.el.getBoundingClientRect(); return { name: p.name, left: Math.round(r.left - base), width: Math.round(r.width) }; });
      const minL = Math.min(...cols.map(c => c.left)), maxR = Math.max(...cols.map(c => c.left + c.width));
      const view = sc.clientWidth, span = maxR - minL, fits = span <= view;
      if (fits) sc.scrollLeft = Math.max(0, Math.min(minL - (view - span) / 2, sc.scrollWidth - view));
      out.push({ ok: true, fits, span, view, cols });
    }
    return out.find(o => !o.fits) || out[0];
  };

  // 입력 값 넣기 준비: 라벨이 가리키는 입력 칸에 포커스를 주고 글자를 모두 선택한다. 유일할 때만.
  const focusInput = name => {
    // find('필터') 와 같은 후보(입력 칸이 딸린 라벨)만 센다 — 같은 이름의 표 열 머리글 라벨은 세지 않는다(#533 실제 테넌트 시험)
    const labs = cands('필터', name).items.map(it => it.el);
    if (labs.length !== 1) return { ok: false, count: labs.length };
    const root = inputOf(labs[0]);
    if (!root) return { ok: false, count: 1, noInput: true };
    const el = root.matches('input, textarea, select') ? root : root.querySelector('input, textarea, select');
    if (!el) return { ok: false, count: 1, noInput: true };
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    el.focus();
    if (el.select) el.select();
    return { ok: true };
  };

  // 라벨이 가리키는 입력 칸의 DOM 뿌리와 UI5 컨트롤(없으면 null). find('필터') 와 같은 후보가 유일할 때만 ok.
  const fieldOf = name => {
    const labs = cands('필터', name).items.map(it => it.el);
    if (labs.length !== 1) return { ok: false, count: labs.length };
    const root = inputOf(labs[0]);
    if (!root) return { ok: false, count: 1, noInput: true };
    let ctl = null;
    // 입력 칸 DOM 은 보통 컨트롤 안쪽 요소(`…-inner`)라 id 로 바로 못 찾는다. 가장 가까운 UI5 컨트롤로 올라간다.
    try {
      const E = window.sap && sap.ui && sap.ui.core && sap.ui.core.Element;
      if (E && typeof E.closestTo === 'function') ctl = E.closestTo(root);
      if (!ctl && window.sap && sap.ui && sap.ui.getCore) {
        for (let n = root; n && !ctl; n = n.parentElement) {
          if (n.id && n.hasAttribute('data-sap-ui')) ctl = sap.ui.getCore().byId(n.id) || null;
        }
      }
    } catch (e) { ctl = null; }
    return { ok: true, root, ctl: ctl || null };
  };
  const tokenTexts = ctl => ctl.getTokens().map(t => trimLabel(t.getText()));

  // 입력 칸의 지금 값: MultiInput 이면 토큰 글자들, 그 밖의 입력 칸이면 value. 판단 못 하면 ok:false(파이썬이 검사 불능으로 낸다).
  const readInput = name => {
    const f = fieldOf(name);
    if (!f.ok) return f;
    const { root, ctl } = f;
    if (ctl && typeof ctl.getTokens === 'function') return { ok: true, kind: 'multi', tokens: tokenTexts(ctl), keys: ctl.getTokens().map(t => trimLabel(String(t.getKey ? t.getKey() || '' : ''))), value: trimLabel(ctl.getValue ? ctl.getValue() : '') };
    if (ctl && typeof ctl.getValue === 'function') return { ok: true, kind: 'input', tokens: [], value: trimLabel(ctl.getValue()) };
    const el = root.matches('input, textarea') ? root : root.querySelector('input, textarea');
    if (el) return { ok: true, kind: 'input', tokens: [], value: trimLabel(el.value) };
    return { ok: false, count: 1, unknown: true };
  };

  // 지금 값을 UI5 컨트롤 API 로 지운다(토큰·value). UI5 컨트롤이 아니면 DOM 값을 비운다.
  const clearInput = name => {
    const f = fieldOf(name);
    if (!f.ok) return f;
    const { root, ctl } = f;
    if (ctl && typeof ctl.getTokens === 'function') {
      const removed = ctl.getTokens();
      ctl.removeAllTokens();
      if (typeof ctl.fireTokenUpdate === 'function') ctl.fireTokenUpdate({ type: 'removed', addedTokens: [], removedTokens: removed });
      if (ctl.setValue) ctl.setValue('');
      return { ok: true };
    }
    if (ctl && typeof ctl.setValue === 'function') {
      ctl.setValue('');
      if (typeof ctl.fireChange === 'function') ctl.fireChange({ value: '' });
      return { ok: true };
    }
    const el = root.matches('input, textarea') ? root : root.querySelector('input, textarea');
    if (!el) return { ok: false, count: 1, unknown: true };
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true };
  };

  // 드롭다운(Select·ComboBox)에서 보이는 항목 글자가 value 와 같은 항목을 고른다. 항목 목록(items)은 실패 사유로 쓴다.
  const selectOption = (name, value) => {
    const f = fieldOf(name);
    if (!f.ok) return f;
    const ctl = f.ctl;
    if (!ctl || typeof ctl.getItems !== 'function' || typeof ctl.setSelectedItem !== 'function') return { ok: false, count: 1, notSelect: true };
    const items = ctl.getItems();
    const texts = items.map(i => trimLabel(i.getText ? i.getText() : ''));
    const hits = items.filter((_, k) => texts[k] === value);
    if (hits.length !== 1) return { ok: false, count: hits.length, items: texts };
    const item = hits[0];
    ctl.setSelectedItem(item);
    if (typeof ctl.fireSelectionChange === 'function') ctl.fireSelectionChange({ selectedItem: item });
    if (typeof ctl.fireChange === 'function') ctl.fireChange({ selectedItem: item, value: value, itemPressed: true });
    const now = ctl.getSelectedItem && ctl.getSelectedItem();
    return { ok: !!now && trimLabel(now.getText()) === value, items: texts, selected: now ? trimLabel(now.getText()) : null };
  };

  const clearOverlay = () => { const o = document.getElementById('__mc_overlay'); if (o) o.remove(); };
  // plan: [{n, box:{x,y,w,h}, badge:{cx,cy,r}}]
  const drawOverlay = (plan, color, border) => {
    clearOverlay();
    const o = document.createElement('div');
    o.id = '__mc_overlay';
    o.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:2147483647;pointer-events:none;margin:0;padding:0';
    for (const p of plan) {
      const b = document.createElement('div');
      b.style.cssText = `position:absolute;box-sizing:border-box;left:${p.box.x}px;top:${p.box.y}px;width:${p.box.w}px;height:${p.box.h}px;border:${border}px solid ${color}`;
      o.appendChild(b);
      const d = document.createElement('div');
      const r = p.badge.r;
      d.textContent = String(p.n);
      d.style.cssText = `position:absolute;box-sizing:border-box;left:${p.badge.cx - r}px;top:${p.badge.cy - r}px;width:${2 * r}px;height:${2 * r}px;` +
        `border-radius:50%;background:${color};color:#fff;font:bold ${Math.round(r * 1.1)}px/${2 * r}px Arial,sans-serif;text-align:center`;
      o.appendChild(d);
    }
    document.documentElement.appendChild(o);
  };

  // 보이는 대화상자(오류·경고 창 등)의 글자. 준비 단계 뒤에 떠 있으면 그 상태를 찍지 않는다(#533 실제 테넌트 시험)
  // 보이는 대화상자 요소. 대화상자 안에 role 이 겹쳐 붙은 것은 바깥 하나로 센다.
  const dialogEls = () => {
    const all = uniq([...document.querySelectorAll('[role=alertdialog], [role=dialog], .sapMMessageBox, .sapMDialog')])
      .filter(d => {  // 대화상자는 잘림 판정(rectFor)을 쓰지 않는다 — UI5 는 고정 위치 영역에 그려 조상의 overflow 와 무관하다
        if (d.closest('#__mc_overlay') || !shown(d)) return false;
        const r = d.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
      });
    return all.filter(d => !all.some(o => o !== d && o.contains(d)));
  };
  const dialogs = () => dialogEls().map(d => trimLabel(d.innerText).slice(0, 200));

  // 오류·경고 창인가: alertdialog·MessageBox 이거나 UI5 Dialog 의 상태가 Error/Warning.
  const isAlert = d => {
    if (d.matches('[role=alertdialog], .sapMMessageBox') || d.querySelector('[role=alertdialog], .sapMMessageBox')) return true;
    try {
      const c = window.sap && sap.ui && sap.ui.getCore && sap.ui.getCore().byId(d.id);
      const st = c && c.getState && c.getState();
      return st === 'Error' || st === 'Warning';
    } catch (e) { return false; }
  };
  const dialogInfo = () => dialogEls().map(d => ({ text: trimLabel(d.innerText).slice(0, 200), alert: isAlert(d) }));

  // `팝업` 단계 뒤: 떠 있는 대화상자가 정확히 하나일 때만 그 안으로 찾는 범위를 좁힌다.
  const setScope = () => {
    const els = dialogEls();
    if (els.length !== 1) return { ok: false, count: els.length };
    scopeEl = els[0];
    return { ok: true };
  };
  const clearScope = () => { scopeEl = null; };

  window.__mc = { find, scrollColumn, scrollColumns, cellOf,focusInput, readInput, clearInput, selectOption, dialogs, dialogInfo, setScope, clearScope, drawOverlay, clearOverlay, size: () => ({ w: innerWidth, h: innerHeight }) };
  return true;
})()"""
