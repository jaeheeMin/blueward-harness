/* 갈래·도구·문서 칸 화면 조각. app.js 가 쓰는 도구(kit)를 받아 조각을 만든다. 세션에서 온 글은 모두 textContent 로만 넣는다. */
(function () {
  'use strict';

  var CACHE_MS = 30000;
  var LOADING_POLL_MS = 2000;  // 서버가 gh 를 읽는 중(loading)이라고 할 때 다시 묻는 간격
  var LOADING_POLL_MAX = 15;
  var JOB_POLL_MS = 1000;
  var JOB_POLL_MAX = 180;
  var DOCS_REFETCH_MS = 4000;
  var MAX_APPROVAL_FOLDERS = 3;
  var NOT_READY = '아직 준비 안 됨';
  var NOT_READY_STATUS = [404, 501, 503];
  var HARNESS_PREFIX = '/harness:';

  window.BHFlowUI = { create: create };

  function create(kit) {
    var L = window.BHLogic;
    var h = kit.h, clear = kit.clear, api = kit.api;
    var cache = { flows: {}, approvals: {}, devReady: {} };
    var updatePressed = false;
    var stripWatchers = [];

    /* ---------- 공통 ---------- */
    function failText(e, what) {
      if (e && NOT_READY_STATUS.indexOf(e.status) >= 0) return (what ? what + ': ' : '') + NOT_READY;
      return (what ? what + ': ' : '') + (e && e.message ? e.message : '요청을 처리하지 못했어요.');
    }
    /* 같은 주소는 CACHE_MS 안에 한 번만 부른다(진행 중인 요청도 같이 쓴다). 서버가 loading 을 주면 gh 가 아직 읽는 중이다:
       wait 면 그동안 가벼운 재요청으로 끝나기를 기다리고, 아니면 받은 값을 바로 쓰고 캐시만 짧게 둔다. */
    function cached(store, key, url, wait) {
      var hit = store[key], now = Date.now();
      if (hit && now - hit.at < CACHE_MS) return hit.promise;
      function once(n) {
        return api('GET', url).then(function (d) {
          if (d && d.loading) {
            if (wait && n < LOADING_POLL_MAX) return new Promise(function (ok) { setTimeout(ok, LOADING_POLL_MS); }).then(function () { return once(n + 1); });
            if (store[key] && store[key].promise === p) store[key].at = now - CACHE_MS + LOADING_POLL_MS;
          }
          return { ok: true, data: d };
        }, function (e) { return { ok: false, error: e }; });
      }
      var p = once(0);
      store[key] = { at: now, promise: p };
      return p;
    }
    function flowsFor(cwd) { return cached(cache.flows, cwd || '', '/api/flows' + kit.qs({ cwd: cwd }), false); }
    function approvalsFor(cwd) {
      if (!cwd) return Promise.resolve({ ok: false, error: null });
      return cached(cache.approvals, cwd, '/api/approvals' + kit.qs({ cwd: cwd }), true);
    }
    // 이 폴더의 개발 건별 Spec 유무(#668). 읽는 중이면 끝나기를 기다린다. 결과는 L.devReadyView 로 거른다.
    function devReadyFor(cwd) {
      if (!cwd) return Promise.resolve({ ok: false, error: null });
      return cached(cache.devReady, cwd, '/api/dev-ready' + kit.qs({ cwd: cwd }), true);
    }
    // 묻는 카드: 문장 + (선택) 막힌 이유 + 두 버튼(추천 / 그래도). 새 작업 화면의 두 곳이 같이 쓴다.
    function askCard(o) {
      return h('div', { class: 'askcard', role: 'group', 'aria-label': o.label || '확인', 'data-ask': o.id || 'flow' },
        h('p', { class: 'ask-q' }, o.lead),
        o.block ? h('p', { class: 'note-attn', role: 'alert', 'data-ask-block': '1', text: o.block }) : null,
        h('div', { class: 'chips' },
          h('button', { type: 'button', class: 'btn primary', 'data-ask-switch': '1', text: o.switchText, onClick: o.onSwitch }),
          h('button', { type: 'button', class: 'btn', 'data-ask-keep': '1', text: o.keepText, onClick: o.onKeep })));
    }
    function sid(s) { return encodeURIComponent(s.id); }
    function sessionList() { return Array.from(kit.sessions.values()); }
    function folderName(s) { return kit.baseName(s.cwd) || '폴더 모름'; }

    /* 대화상자: 확인·취소. body 는 노드 목록, validate 는 오류 글을 돌려준다. */
    var openModal = null;
    function closeModal() {
      if (!openModal) return;
      document.removeEventListener('keydown', openModal.onKey);
      if (openModal.el.parentNode) openModal.el.parentNode.removeChild(openModal.el);
      openModal = null;
    }
    function modal(o) {
      closeModal();
      var err = h('p', { class: 'note-attn', role: 'alert', hidden: true });
      var ok = h('button', { type: 'button', class: 'btn primary', text: o.confirmText || '확인', onClick: function () {
        var bad = o.validate ? o.validate() : '';
        if (bad) { err.textContent = bad; err.hidden = false; return; }
        var run = o.onConfirm;
        closeModal();
        if (run) run();
      } });
      function dismiss() { closeModal(); if (o.onCancel) o.onCancel(); }  // 취소 버튼·Esc·바깥 클릭
      var extras = o.extra ? o.extra(ok) : [];
      var box = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'modal-h' },
        h('h2', { id: 'modal-h', class: 'sect-h', text: o.title }), o.body, err,
        h('div', { class: 'btn-row mt-24' }, h('button', { type: 'button', class: 'btn', text: '취소', onClick: dismiss }), extras, ok));
      var el = h('div', { class: 'modal-back', onMousedown: function (e) { if (e.target === el) dismiss(); } }, box);
      var onKey = function (e) { if (e.key === 'Escape') dismiss(); };
      document.addEventListener('keydown', onKey);
      document.body.appendChild(el);
      openModal = { el: el, onKey: onKey };
      var focus = box.querySelector('textarea, input, .btn.primary');
      if (focus) focus.focus();
    }

    /* ---------- 순서 막대 ---------- */
    function stepBar(s, big) {
      var steps = L.barSteps(s);
      return h('ol', { class: 'stepbar' + (big ? ' big' : ''), 'aria-label': '진행 순서' }, steps.map(function (st) {
        // 큰 순서 알약(세션 제목 아래, 시안 G-09·12)은 짧은 이름. 전체 이름은 title 로(이유가 있으면 이유와 함께).
        var full = big && L.stepShort(st) !== st.name ? st.name : '';
        return h('li', { class: 'step ' + st.state, 'aria-current': st.state === 'now' ? 'step' : null, title: [full, st.reason].filter(Boolean).join(' · ') || null },
          big ? null : h('span', { class: 'dot', 'aria-hidden': 'true' }),
          h('span', { class: 'snm', text: (big && st.state === 'done' ? '✓ ' : '') + (big ? L.stepShort(st) : st.name) }),
          h('span', { class: 'slb sr-only', text: st.label }));
      }));
    }
    function prChip(s) {
      var pr = L.prBadge(s.flowPr);
      if (!pr) return null;
      var url = kit.safeHttp(pr.url);
      var label = 'PR #' + pr.number + ' · ' + pr.text;
      return h('span', { class: 'prchip ' + pr.checks }, url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: label }) : label);
    }

    /* 올림·승인 기다림·합쳐짐: 검토 요청(PR) 카드. 줄은 데이터에 있는 것만(검사는 합친 한 값, 승인은 PR 상태에서 읽는다). */
    function prCard(s) {
      var pr = s && s.flowPr, lines = L.prLines(pr, s && s.flowId);
      if (!lines.length) return null;
      var url = kit.safeHttp(pr.url);
      var label = 'PR #' + pr.number + (pr.title ? ' · ' + pr.title : '');
      // 검사가 실패했으면 ✕ 막힘(빨간 테두리), 결과를 못 읽었으면 ? 확인 못 함(보라 점선). 통과·실패 어느 쪽으로도 치지 않는다.
      var failed = lines.some(function (ln) { return ln.state === 'fail'; }), unsure = !failed && lines.some(function (ln) { return ln.state === 'unk'; });
      return h('div', { class: 'q prcard' + (failed ? ' blocked' : unsure ? ' unsure' : ''), 'data-pr-card': '1' },
        failed ? h('span', { class: 'tagx fail', text: '✕ 막힘' }) : unsure ? h('span', { class: 'tagx unk', text: '? 확인 못 함' }) : null,
        failed ? h('span', { class: 'sub', text: '자동 검사가 잘못을 찾았어. 고쳐서 다시 올려야 넘어가.' }) : unsure ? h('span', { class: 'sub', text: '검사 결과를 못 읽었어. 통과도 실패도 아니야.' }) : null,
        h('div', { class: 'qh' }, h('b', { text: label }), url ? h('a', { class: 'pill line sm', href: url, target: '_blank', rel: 'noopener noreferrer', text: 'GitHub에서 보기' }) : null),
        lines.map(function (ln) {
          return h('div', { class: 'crow ' + ln.state, 'data-line': ln.id }, h('i', { class: 'mk', 'aria-hidden': 'true' }), h('span', { class: 'cn', text: ln.name }), h('span', { class: 'ct', text: ln.text }));
        }));
    }

    /* ---------- 도구 실행 ---------- */
    function runSkill(s, skill) {
      return api('POST', '/api/sessions/' + sid(s) + '/skills/' + encodeURIComponent(skill) + '/run', {});
    }
    // 도구 하나를 실행하고 사람이 읽을 결과 글을 돌려준다.
    function runTool(s, toolId, name) {
      if (toolId === 'reload') {
        return api('POST', '/api/sessions/' + sid(s) + '/reload', {}).then(function (d) { return L.reloadResult(d); }, function (e) { return failText(e, '다시 불러오기'); });
      }
      return runSkill(s, toolId).then(function () {
        if (toolId === 'update') { updatePressed = true; notifyStrip(); }
        return name + ' 실행을 요청했어요.';
      }, function (e) { return failText(e, name); });
    }
    function notifyStrip() { stripWatchers.forEach(function (f) { f(); }); }

    /* ---------- 항상 열린 도구 줄 ---------- */
    // getCtx() -> { session, cwd, onInsert(skill) }. 세션이 없으면(새 작업) 누른 도구를 입력칸에 넣어 준다.
    function toolsRow(getCtx) {
      var el = h('section', { class: 'toolsrow', 'aria-label': '도구' });
      var strip = h('div', { class: 'reload-strip', role: 'status', hidden: true });
      var project = h('p', { class: 'note-attn project-notice', role: 'status', hidden: true, 'data-project-notice': '1' });
      var list = h('div', { class: 'tools-list' });
      var note = h('p', { class: 'note-muted tools-note', role: 'status', hidden: true });
      el.appendChild(strip); el.appendChild(project); el.appendChild(list); el.appendChild(note);
      var data = { flows: null, approvals: null, key: null }, alive = true;

      function say(text) { note.textContent = text; note.hidden = !text; }
      function paintStrip() {
        var info = L.reloadStrip(updatePressed, sessionList());
        strip.hidden = !info;
        clear(strip);
        if (!info) return;
        strip.appendChild(h('span', { text: info.text + ' · ' }));
        strip.appendChild(h('button', { type: 'button', class: 'btn sm', text: '모두 다시 불러오기', onClick: reloadAll }));
      }
      function reloadAll() {
        say('모두 다시 불러오는 중이에요.');
        api('POST', '/api/reload-all', {}).then(function (d) {
          updatePressed = false; notifyStrip();
          say(d && d.queued ? '지금 하는 일이 끝나면 다시 불러올게요.' : '돌고 있는 세션을 다시 불러왔어요.');
        }, function (e) { say(failText(e, '모두 다시 불러오기')); });
      }
      function paint() {
        var ctx = getCtx(), s = ctx.session;
        var tools = L.visibleTools(data.flows, data.approvals, { hasSession: !!s, managed: !!(s && s.managed) });
        var blocked = s && s.canSend === false ? (s.cannotSendReason || '이 세션에는 지금 요청을 보낼 수 없어요.') : '';
        var pn = L.projectNotice(data.flows) || L.formsNotice(data.flows);
        project.hidden = !pn;
        project.textContent = pn ? pn.text : '';
        clear(list);
        tools.forEach(function (t) {
          var isConsole = t.kind === 'console';
          list.appendChild(h('button', { type: 'button', class: 'tool', 'data-tool': t.id, disabled: !!blocked, title: blocked || (isConsole ? t.name : HARNESS_PREFIX + t.skill),
            onClick: function () {
              if (!s) { if (ctx.onInsert && t.skill) ctx.onInsert(t.skill); return; }
              say(t.name + ' 요청을 보내는 중이에요.');
              runTool(s, t.id, t.name).then(function (msg) { if (alive) say(msg); });
            } }, t.name));
        });
        paintStrip();
      }
      function load() {
        var ctx = getCtx(), key = ctx.cwd || '';
        Promise.all([flowsFor(key), approvalsFor(key)]).then(function (r) {
          if (!alive) return;
          data.flows = r[0].ok ? r[0].data : null;
          data.approvals = r[1].ok ? r[1].data : null;
          data.key = key;
          paint();
        });
      }
      stripWatchers.push(paintStrip);
      function update() {
        var key = getCtx().cwd || '';
        paint();
        if (data.key !== key) load();
      }
      load();
      return { el: el, update: update, say: say, destroy: function () { alive = false; stripWatchers = stripWatchers.filter(function (f) { return f !== paintStrip; }); } };
    }

    /* ---------- 새 세션 점검 ---------- */
    function startChecksPanel() {
      // 시안 13: 대화 판 맨 위의 "시작 점검" 카드. 한 줄에 ✓ 동그라미 · 이름 · 상태 · (다시) 하기 버튼.
      var el = h('div', { class: 'q startchecks', 'aria-label': '새 세션 점검', hidden: true });
      var note = h('p', { class: 'note-muted', role: 'status', hidden: true });
      var last = null, alive = true;
      var CROW = { done: 'ok', run: 'run', fail: 'fail', todo: 'todo' };
      function draw() {
        var s = last, checks = s ? L.startChecks(s) : [];
        el.hidden = !checks.length;
        clear(el);
        if (!checks.length) return;
        el.appendChild(h('span', { class: 'eb', text: '새 세션 점검' }));
        checks.forEach(function (c) {
          el.appendChild(h('div', { class: 'crow ' + CROW[c.state], 'data-check': c.id },
            h('i', { class: 'mk', 'aria-hidden': 'true' }), h('span', { class: 'cn', text: c.name }), h('span', { class: 'ct', text: c.label }),
            h('button', { type: 'button', class: 'pill line sm', disabled: s.canSend === false, text: c.state === 'done' ? '다시 하기' : '하기',
              onClick: function () {
                note.hidden = false; note.textContent = c.name + ' 요청을 보내는 중이에요.';
                runTool(s, c.id, c.name).then(function (msg) { if (alive) { note.textContent = msg; kit.refreshSession(s.id); } });
              } })));
        });
        el.appendChild(note);
      }
      return { el: el, update: function (s) { last = s; draw(); }, destroy: function () { alive = false; } };
    }

    /* ---------- 갈래 칸(세션 화면) ---------- */
    // opts.compact: 세션 화면처럼 제목 아래에 순서 알약을 따로 두는 쪽에서 쓴다(갈래 이름·순서 막대를 이 칸에서 뺀다).
    function flowPanel(opts) {
      var compact = !!(opts && opts.compact);
      var el = h('section', { class: 'flowpanel' + (compact ? ' compact' : ''), 'aria-label': '진행 순서' });
      var st = { busy: false, msg: '', picker: null, pickerCwd: null, job: '' };
      var last = null, alive = true, pollTimer = null;

      function ensurePicker(s) {
        if (st.pickerCwd === s.cwd) return;
        st.pickerCwd = s.cwd; st.picker = null;
        flowsFor(s.cwd).then(function (r) { if (!alive) return; st.picker = r; draw(); });
      }
      function act(promise, okMsg) {
        st.busy = true; st.msg = ''; draw();
        return promise.then(function (d) {
          if (d && d.id && d.id === last.id) kit.mergeSession(d);
          st.msg = okMsg || '';
        }, function (e) { st.msg = failText(e); }).then(function () {
          st.busy = false; if (alive) draw(); kit.refreshSession(last.id);
        });
      }
      function post(path, body, okMsg) { return act(api('POST', '/api/sessions/' + sid(last) + path, body), okMsg); }

      function askSkip(step) {
        var reason = h('textarea', { class: 'textarea', rows: '3', placeholder: '예: 이번에는 양식이 필요 없어서', 'aria-label': '건너뛰는 이유' });
        modal({
          title: '"' + (step.name || step.id) + '" 단계를 건너뛸까요?',
          body: [h('p', { class: 'note-muted', text: '순서를 건너뛰면 기록에 이유가 남아요. 이유를 꼭 적어 주세요.' }), reason],
          confirmText: '건너뛰기', validate: function () { return L.skipReasonError(reason.value); },
          onConfirm: function () { post('/flow/skip', { reason: reason.value.trim() }, '단계를 건너뛰었어요.'); }
        });
      }
      function choose(flowId) { act(api('PUT', '/api/sessions/' + sid(last) + '/flow', { flowId: flowId })); }

      function askNext(opt) {
        modal({
          title: '"' + opt.label + '" 로 넘어갈까요?',
          body: [h('p', { text: '인계하고 새 세션으로 넘어갑니다. 지금 세션에서 한 일을 정리해 새 세션에 넘겨요.' })],
          confirmText: '넘어가기', onConfirm: function () { startNext(opt); }
        });
      }
      function startNext(opt) {
        st.busy = true; st.job = '새 세션을 준비하고 있어요.'; st.msg = ''; draw();
        api('POST', '/api/sessions/' + sid(last) + '/flow/next', { flowId: opt.flow, ids: (opt.ids || []).filter(function (i) { return /^REQ-\d{1,6}$/.test(i); }) }).then(function (d) {
          var jobId = d && (d.jobId || d.id);
          if (!jobId) throw new Error('작업 번호를 받지 못했어요.');
          pollJob(jobId, 0);
        }, function (e) { st.busy = false; st.job = ''; st.msg = failText(e, '새 세션으로 넘기기'); if (alive) draw(); });
      }
      // 인계 결과를 사람이 보고 새 세션을 시작한다: [이대로 새 세션 시작] [고쳐서 시작] [취소]
      function askStart(jobId, prompt, warning) {
        var box = h('textarea', { class: 'textarea', rows: '10', readOnly: true, 'aria-label': '새 세션에 보낼 인계 글', maxlength: '4000' });
        box.value = prompt;
        function begin(path, body, label) {
          st.busy = true; st.job = label; st.msg = ''; draw();
          api('POST', '/api/jobs/' + encodeURIComponent(jobId) + path, body).then(function () { if (path === '/confirm') pollJob(jobId, 0); else { st.busy = false; st.job = ''; if (alive) draw(); } },
            function (e) { st.busy = false; st.job = ''; st.msg = failText(e, path === '/confirm' ? '새 세션 시작' : '취소'); if (alive) draw(); });
        }
        modal({
          title: '새 세션에 이 글을 보낼까요?',
          body: [h('p', { class: 'note-muted', text: '지금 세션이 정리한 인계 글이에요. 읽어 보고 그대로 시작하거나, 고쳐서 시작하세요.' }),
                 warning ? h('p', { class: 'note-attn', role: 'status', text: warning }) : null, box],
          confirmText: '이대로 새 세션 시작',
          validate: function () { return box.value.trim() ? '' : '보낼 글이 비어 있어요.'; },
          onConfirm: function () { begin('/confirm', { prompt: box.value }, '새 세션을 시작하고 있어요.'); },
          onCancel: function () { begin('/cancel', {}, '취소하고 있어요.'); },
          extra: function (ok) {
            return [h('button', { type: 'button', class: 'btn', text: '고쳐서 시작', onClick: function () {
              box.readOnly = false; box.focus(); ok.textContent = '고친 내용으로 새 세션 시작';
            } })];
          }
        });
      }
      function pollJob(jobId, n) {
        if (!alive) return;
        api('GET', '/api/jobs/' + encodeURIComponent(jobId)).then(function (job) {
          var out = L.jobOutcome(job);
          if (out.confirm) { st.busy = false; st.job = ''; if (alive) { draw(); askStart(jobId, out.prompt, out.warning); } return; }
          if (!out.done && n < JOB_POLL_MAX) { pollTimer = setTimeout(function () { pollJob(jobId, n + 1); }, JOB_POLL_MS); return; }
          st.busy = false; st.job = '';
          if (out.done && out.ok) { kit.go('/s/' + encodeURIComponent(out.sessionId)); return; }
          st.msg = out.done ? '새 세션으로 넘기지 못했어요: ' + out.error : '새 세션이 아직 준비되지 않았어요. 잠시 뒤 다시 확인해 주세요.';
          if (alive) draw();
        }, function (e) { st.busy = false; st.job = ''; st.msg = failText(e, '진행 상태 확인'); if (alive) draw(); });
      }

      function drawPicker(s) {
        var box = h('div', { class: 'flowpick' });
        box.appendChild(h('h2', { class: 'sect-h', text: '어떤 일인가요?' }));
        box.appendChild(h('p', { class: 'note-muted', text: '일을 고르면 그 순서대로만 진행해요.' }));
        var r = st.picker;
        if (!r) box.appendChild(h('p', { class: 'note-muted', role: 'status', text: '불러오는 중이에요.' }));
        else if (!r.ok) box.appendChild(h('p', { class: 'note-attn', role: 'alert', text: failText(r.error, '일 목록') }));
        else {
          var flows = kit.listOf(r.data, 'flows').filter(function (f) { return !(f.exposure && f.exposure.visible === false); });
          var grid = h('div', { class: 'flowpick-grid' });
          flows.forEach(function (f) {
            grid.appendChild(h('button', { type: 'button', class: 'opt', disabled: st.busy, 'data-flow': f.id, onClick: function () { choose(f.id); } },
              h('span', { class: 't', text: f.name }), f.description ? h('span', { class: 'd', text: f.description }) : null,
              f.steps ? h('span', { class: 'd order', text: '순서: ' + L.orderText(f) }) : null));
          });
          box.appendChild(grid);
        }
        el.appendChild(box);
      }

      function drawAction(s) {
        var a = L.nextAction(s), box = h('div', { class: 'nextstep ask' });
        if (a.type === 'none') { box.appendChild(h('p', { class: 'sub', text: a.note })); el.appendChild(box); return; }
        var busyNow = s.status === 'running' || s.status === 'starting';
        box.appendChild(h('span', { class: 'eb', text: busyNow ? '다음 단계 · AI 가 끝나면' : '네 차례' }));
        box.appendChild(h('b', { text: '지금 할 일 · ' + a.stepName }));
        if (a.hint) box.appendChild(h('p', { class: 'sub', text: a.hint }));
        var row = h('div', { class: 'acts' });
        if (a.type === 'skill') {
          row.appendChild(h('button', { type: 'button', class: 'pill acc', disabled: st.busy || a.disabled, title: a.disabledReason || null, text: a.label,
            onClick: function () { act(runSkill(last, a.skill), HARNESS_PREFIX + a.skill + ' 실행을 요청했어요.'); } }));
        } else if (a.type === 'done' || a.type === 'human') {
          row.appendChild(h('button', { type: 'button', class: 'pill acc', disabled: st.busy, text: a.label,
            onClick: function () { post('/flow/done', {}, '이 단계를 끝냈어요.'); } }));
          if (a.type === 'human') row.appendChild(h('button', { type: 'button', class: 'pill line', disabled: st.busy, text: a.refreshLabel, onClick: function () { post('/flow/refresh', {}, '다시 확인했어요.'); } }));
        } else {
          box.appendChild(h('p', { class: 'sub', text: a.step.state === 'active' ? '밖에서 일이 끝나길 기다리는 중이에요.' : '아직 시작 전이에요.' }));
          row.appendChild(h('button', { type: 'button', class: 'pill acc', disabled: st.busy, text: a.label, onClick: function () { post('/flow/refresh', {}, '다시 확인했어요.'); } }));
          if (a.helper) row.appendChild(h('button', { type: 'button', class: 'pill line', disabled: st.busy || a.helperDisabled, text: HARNESS_PREFIX + a.helper + ' 보기',
            onClick: function () { act(runSkill(last, a.helper), HARNESS_PREFIX + a.helper + ' 실행을 요청했어요.'); } }));
        }
        box.appendChild(row);
        if (a.disabledReason && a.type === 'skill') box.appendChild(h('p', { class: 'sub', text: a.disabledReason }));
        box.appendChild(h('button', { type: 'button', class: 'skiplink', disabled: st.busy, text: '이 단계 건너뛰기', onClick: function () { askSkip(a.step); } }));
        el.appendChild(box);
      }

      function drawFinished(s) {
        var nx = L.nextOptions(s), box = h('div', { class: 'nextflow handoff' });
        box.appendChild(h('span', { class: 'eb', text: '다음 일' }));
        box.appendChild(h('b', { text: '이 일은 끝났어요' }));
        if (nx.unknown) box.appendChild(h('p', { class: 'sub attn', role: 'alert', text: '판정 불능 · ' + nx.unknown }));
        if (nx.hint && !nx.options.length) box.appendChild(h('p', { class: 'sub', text: nx.hint }));
        if (nx.options.length) {
          var mem = L.memoryOf(s);
          box.appendChild(h('p', { class: 'sub', 'data-memory': mem.kind, text: (mem.kind === 'pct' ? '이 세션이 기억을 ' + mem.pct + '% 썼어요. ' : mem.kind === 'tokens' ? '이 세션이 기억을 ' + mem.words + ' 썼어요(%는 확인 못 함). ' : '')
            + '다음에 이어서 할 일을 고르세요. 새 세션에서 시작하면 앞 대화를 다시 읽지 않아 더 빠르고 정확해요.' }));
          var row = h('div', { class: 'acts' });
          nx.options.forEach(function (o) {
            if (o.disabled) row.appendChild(h('button', { type: 'button', class: 'pill off', disabled: true }, o.label, h('small', { text: '준비 중' })));
            else if (o.clickable) row.appendChild(h('button', { type: 'button', class: 'pill dark', disabled: st.busy, text: o.label, onClick: function () { askNext(o); } }));
            else row.appendChild(h('span', { class: 'sub', text: o.label }));
          });
          box.appendChild(row);
        } else if (!nx.unknown && !nx.hint) box.appendChild(h('p', { class: 'sub', text: '이어서 할 일이 없어요.' }));
        el.appendChild(box);
      }

      function draw() {
        var s = last;
        if (!s) return;
        clear(el);
        if (!s.flowId) {
          ensurePicker(s); drawPicker(s);
        } else {
          if (!compact) {
            el.appendChild(h('div', { class: 'flow-head' },
              h('h2', { class: 'flow-name', text: s.flowName || s.flowId }),
              s.flowReason ? h('span', { class: 'flow-reason', text: s.flowReason }) : null,
              prChip(s)));
            el.appendChild(stepBar(s, true));
          }
          (s.flowUnknown || []).forEach(function (u) { el.appendChild(h('p', { class: 'note-attn', role: 'status', text: '판정 불능 · ' + (typeof u === 'string' ? u : u.reason || JSON.stringify(u)) })); });
          if (s.flowFinished) drawFinished(s); else drawAction(s);
        }
        if (st.job) el.appendChild(h('p', { class: 'note-accent', role: 'status', text: st.job }));
        if (st.msg) el.appendChild(h('p', { class: 'note-accent', role: 'status', text: st.msg }));
      }
      return {
        el: el,
        update: function (s) { last = s; draw(); },
        // 기억 배너의 [새 세션으로 넘기기]: 지금 갈래를 새 세션에서 이어 간다(다음 갈래 카드와 같은 인계 절차)
        handoffSame: function (s) { last = s; askNext({ flow: s.flowId, label: (s.flowName || s.flowId) + ' 이어서', ids: [] }); },
        destroy: function () { alive = false; clearTimeout(pollTimer); closeModal(); }
      };
    }

    /* ---------- 같은 폴더 알림 ---------- */
    // update(cwd, busy, onSwitch(path))
    function folderNotice() {
      var el = h('div', { class: 'folder-notice', role: 'status', hidden: true });
      var state = { busy: false, msg: '' }, alive = true;
      var last = null;
      function draw() {
        clear(el);
        if (!last) { el.hidden = true; return; }
        el.hidden = !(last.busy || state.msg);
        if (el.hidden) return;
        if (last.busy) {
          el.appendChild(h('p', { text: '이 폴더에서 다른 세션이 일하고 있어요. 같은 파일을 고치면 서로 덮어쓸 수 있어요.' }));
          el.appendChild(h('button', { type: 'button', class: 'btn sm', disabled: state.busy, text: state.busy ? '만드는 중' : '이 작업용 폴더 따로 만들기', onClick: make }));
        }
        if (state.msg) el.appendChild(h('p', { class: 'note-accent', text: state.msg }));
      }
      function make() {
        state.busy = true; state.msg = ''; draw();
        api('POST', '/api/folders/worktree', { cwd: last.cwd }).then(function (d) {
          if (!d || !d.path) throw new Error('새 폴더 경로를 받지 못했어요.');
          state.msg = '작업용 폴더를 만들었어요: ' + d.path;
          if (last.onSwitch) last.onSwitch(d.path);
        }, function (e) { state.msg = failText(e, '작업용 폴더 만들기'); }).then(function () { state.busy = false; if (alive) draw(); });
      }
      return { el: el, update: function (cwd, busy, onSwitch) { last = { cwd: cwd, busy: busy, onSwitch: onSwitch }; draw(); }, destroy: function () { alive = false; } };
    }

    /* ---------- 만든 문서 칸 ---------- */
    /* 미리보기 한 장: 세션 화면의 문서 칸과 산출물 화면이 같이 쓴다. ctx = { sheet, name, setSheet(i) } */
    function renderPreview(p, ctx) {
      var box = h('div', { class: 'preview' });
      if (p.kind === 'md') {
        box.appendChild(h('div', { class: 'report-body' }, window.BHMarkdown.render(p.text)));
      } else if (p.kind === 'table') {
        if (!p.sheets.length) box.appendChild(h('p', { class: 'note-muted', text: '표가 비어 있어요.' }));
        else {
          var idx = Math.min(ctx.sheet, p.sheets.length - 1);
          if (!ctx.header || p.sheets.length > 1) box.appendChild(h('div', { class: 'sheet-tabs', role: 'tablist' }, p.sheets.map(function (sh, i) {
            return h('button', { type: 'button', role: 'tab', class: 'chip', 'aria-selected': String(i === idx), 'aria-pressed': String(i === idx), text: sh.name || ('시트 ' + (i + 1)),
              onClick: function () { ctx.setSheet(i); } });
          })));
          var rows = kit.listOf(p.sheets[idx], 'rows');
          var table = h('table', { class: 'sheet' }, h('tbody', null, rows.map(function (r) {
            return h('tr', null, (Array.isArray(r) ? r : [r]).map(function (c) { return h(ctx.header && r === rows[0] ? 'th' : 'td', { text: c == null ? '' : String(c) }); }));
          })));
          box.appendChild(h('div', { class: 'md-table sheet-wrap' }, table));
          if (!rows.length) box.appendChild(h('p', { class: 'note-muted', text: '이 시트는 비어 있어요.' }));
        }
      } else if (p.kind === 'slides') {
        if (!p.slides.length) box.appendChild(h('p', { class: 'note-muted', text: '슬라이드에서 읽은 글이 없어요.' }));
        p.slides.forEach(function (sl, i) {
          box.appendChild(h('section', { class: 'slide' }, h('h3', { class: 'label', text: '슬라이드 ' + (sl.index != null ? sl.index : i + 1) }),
            kit.listOf(sl, 'texts').map(function (t) { return h('p', { text: String(t) }); })));
        });
      } else if (p.kind === 'image') {
        var okUrl = p.url.charAt(0) === '/' && p.url.charAt(1) !== '/' ? p.url : kit.safeHttp(p.url);
        box.appendChild(okUrl ? h('img', { class: 'preview-img', src: okUrl, alt: ctx.name }) : h('p', { class: 'note-muted', text: '그림 주소를 받지 못했어요.' }));
      } else box.appendChild(h('p', { class: 'note-muted', text: p.reason || '이 종류는 미리 볼 수 없어요. 아래 버튼으로 열어 보세요.' }));
      return box;
    }

    /* ---------- 산출물 화면 (/docs): 모든 세션이 만든 문서를 한 곳에서 ---------- */
    // 새 서버 API 는 없다. 세션마다 /files 를 불러 모은다(최근에 바뀐 세션 DOCS_PAGE_MAX 개까지).
    var DOCS_PAGE_MAX = 12;
    function docsPage(root) {
      var st = { parts: null, sel: null, preview: null, previewError: null, sheet: 0, note: '', say: '' };
      var alive = true, loading = false, loadedAt = 0, timer = null, askVal = '';
      var page = h('div', { class: 'page docs-page' });
      root.appendChild(page);

      function pool() {
        return sessionList().filter(function (s) { return !s.handedOffTo; }).sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); }).slice(0, DOCS_PAGE_MAX);
      }
      function sig() { return pool().map(function (s) { return s.id; }).join('|'); }
      function load() {
        if (loading) return;
        loading = true; loadedAt = Date.now(); st.sig = sig();
        Promise.all(pool().map(function (s) {
          return api('GET', '/api/sessions/' + sid(s) + '/files').then(function (d) { return { session: s, files: kit.listOf(d, 'files'), unknown: !!(d && d.unknown), note: d && d.note ? String(d.note) : '' }; },
            function (e) { return { session: s, files: [], unknown: true, failed: e }; });
        })).then(function (parts) { st.parts = parts; }).then(function () {
          loading = false;
          if (alive && sig() !== st.sig) { load(); return; }  // 읽는 동안 세션이 늘거나 줄었으면 다시 모은다
          if (alive && !(document.activeElement && document.activeElement.id === 'doc-ask')) draw();  // 고쳐 달라고 쓰는 중이면 입력칸을 다시 그리지 않는다
        });
      }
      function later() {
        if (timer || !alive) return;
        timer = setTimeout(function () { timer = null; if (alive && Date.now() - loadedAt > 5000) load(); }, 1500);
      }
      // 세션 데이터가 바뀔 때: 세션 구성이 달라졌으면 바로 다시 모으고, 아니면 가끔만 다시 읽는다.
      function refresh() {
        if (!alive) return;
        if (!kit.loaded()) { draw(); return; }
        if (sig() !== st.sig) load(); else later();
      }
      function docs() { return st.parts ? L.mergeDocs(st.parts) : []; }
      function selected() {
        if (!st.sel) return null;
        var hit = docs().filter(function (d) { return d.key === st.sel; })[0];
        if (hit) return hit;
        return st.picked || null;
      }
      function pick(entry) {
        st.sel = entry.key; st.picked = entry; st.preview = null; st.previewError = null; st.sheet = 0; st.note = ''; st.say = '';
        draw();
        api('GET', '/api/sessions/' + sid(entry.session) + '/files/preview' + kit.qs({ path: entry.file.path })).then(function (d) { st.preview = L.normPreview(d); },
          function (e) { st.previewError = e; }).then(function () { if (alive && st.sel === entry.key) draw(); });
      }
      function openFile(entry, mode) {
        st.note = mode === 'reveal' ? '탐색기를 여는 중이야.' : '기본 프로그램으로 여는 중이야.'; draw();
        api('POST', '/api/sessions/' + sid(entry.session) + '/files/open', { path: entry.file.path, mode: mode }).then(function () {
          st.note = mode === 'reveal' ? '탐색기에서 위치를 열었어.' : '열었어.';
        }, function (e) { st.note = failText(e, '열기'); }).then(function () { if (alive) draw(); });
      }
      // 고쳐 달라고 하기·양식으로 뽑기는 이 문서를 만든 세션에 말을 보내는 일이다(콘솔이 직접 고치거나 뽑지 않는다).
      function ask(entry, text) {
        st.say = '세션에 보내는 중이야.'; draw();
        api('POST', '/api/sessions/' + sid(entry.session) + '/messages', { text: text }).then(function () {
          st.say = '"' + (entry.session.title || kit.baseName(entry.session.cwd) || '세션') + '" 세션에 보냈어. 끝나면 이 목록이 바뀌어.'; askVal = '';
          setTimeout(function () { if (alive) load(); }, 4000);
        }, function (e) { st.say = failText(e, '보내기'); }).then(function () { if (alive) draw(); });
      }

      // 시안 G-14: 한 줄에 이름 · 판 · 확장자 + 올림 칩. 크기·세션은 줄에 올려 두면 보이는 설명으로 둔다.
      function rowTitle(entry) {
        var f = entry.file;
        return [f.path, f.size != null ? kit.fmtSize(f.size) : '', entry.session.title || ''].filter(Boolean).join(' · ');
      }
      function row(entry, sub) {
        var f = entry.file, on = st.sel === entry.key, c = entry.chip, lb = L.docLabel(f.path);
        var tail = lb.ver ? ' v' + lb.ver + ' · ' + lb.ext : '';
        return h('button', { type: 'button', class: 'drow' + (on ? ' on' : '') + (sub ? ' sub' : ''), 'aria-pressed': String(on), 'data-path': f.path, title: rowTitle(entry), onClick: function () { pick(entry); } },
          h('span', { class: 'dn' }, h('span', { class: 'dl' }, h('b', { text: lb.name }), tail ? h('span', { class: 'dv', text: tail }) : null)),
          c ? h('span', { class: 'chip2 ' + c.tone, title: c.title, text: c.text }) : null);
      }
      function listBox(all) {
        var box = h('div', { class: 'lt dlist' }), unsure = false;
        L.DOC_GROUPS.forEach(function (g) {
          var items = all.filter(function (d) { return d.group === g[0]; });
          if (!items.length) return;
          box.appendChild(h('span', { class: 'eb', text: g[1] }));
          items.forEach(function (d) {
            if (d.chip && d.chip.text === '확인 못 함') unsure = true;
            box.appendChild(row(d, false));
            var olds = L.versionPaths(d.file);
            if (olds.length) {
              var det = h('details', { class: 'more docs-old' }, h('summary', { text: '이전 판 ' + olds.length + '개' }));
              olds.forEach(function (v) { det.appendChild(row({ key: d.key.split('|')[0] + '|' + v.path.toLowerCase(), file: v, session: d.session, chip: null }, true)); });
              box.appendChild(det);
            }
          });
        });
        box.appendChild(h('span', { class: 'dnote', text: '안 올림 = 내 PC에만 · 검토 중 = 승인 기다림 · 합쳐짐 = 팀 공용본' + (unsure ? ' · 확인 못 함 = 알 수 없음' : '') }));
        return box;
      }

      // ---- 고객 양식 결과(시안 G-15) ----
      function cellsText(cells) {
        if (!cells.known) return cells.pending ? '양식 칸 세는 중' : '양식 칸 수 확인 못 함';
        return cells.empty ? '양식 칸 ' + cells.total + '개 중 ' + cells.filled + '개 채움' : '양식 칸 ' + cells.total + '개 모두 채움';
      }
      function resultCard(entry, cells) {
        var f = entry.file, ext = (/\.([a-z0-9]+)$/i.exec(f.path) || [])[1] || '';
        var fresh = f.mtime && Date.now() - (f.mtime > 1e12 ? f.mtime : f.mtime * 1000) < 120000;
        var info = [f.size != null ? kit.fmtSize(f.size) : '', f.mtime ? (fresh ? '방금' : kit.clock(f.mtime)) : '', cells ? cellsText(cells) : ''].filter(Boolean).join(' · ');
        return h('div', { class: 'q dresult', 'data-form-card': '1' },
          h('span', { class: 'pi', text: ext.toUpperCase() }),
          h('span', { class: 'dn' }, h('b', { text: kit.baseName(f.path) }), h('small', { text: info })),
          h('button', { type: 'button', class: 'pill line', text: '폴더에서 보기', onClick: function () { openFile(entry, 'reveal'); } }),
          h('a', { class: 'pill dark', href: '/api/sessions/' + sid(entry.session) + '/files/download' + kit.qs({ path: f.path }), download: kit.baseName(f.path), text: '내려받기' }));
      }
      // 카드 · 미리보기 · (빈 칸 안내) · AI 에게 말하기. 결과 화면과 목록 화면(양식 파일을 고른 때)이 같이 쓴다.
      function resultBody(entry, can) {
        var f = entry.file, isX = /\.xlsx$/i.test(f.path);
        var cells = !isX ? null : st.preview ? L.formCells(st.preview) : st.previewError ? { known: false } : { known: false, pending: true };
        var out = [resultCard(entry, cells)], sheetName = '';
        if (isX && st.preview && st.preview.kind === 'table' && st.preview.sheets.length) {
          var si = Math.min(st.sheet, st.preview.sheets.length - 1);
          sheetName = st.preview.sheets[si].name || ('시트 ' + (si + 1));
        }
        if (isX) out.push(h('span', { class: 'eb', text: '미리보기' + (sheetName ? ' · ' + sheetName + ' 시트' : '') }));
        if (st.note) out.push(h('p', { class: 'note-accent', role: 'status', text: st.note }));
        if (st.previewError) out.push(h('p', { class: 'note-muted', role: 'status', text: failText(st.previewError, '미리보기') }));
        else if (!st.preview) out.push(h('p', { class: 'note-muted', role: 'status', text: '불러오는 중이에요.' }));
        else out.push(h('div', { class: 'dsheet' }, renderPreview(st.preview, { sheet: st.sheet, name: kit.baseName(f.path), header: true, setSheet: function (i) { st.sheet = i; draw(); } })));
        if (cells && cells.known && cells.empty) {
          var names = cells.blankNames.slice(0, 3).join(', ') + (cells.blankNames.length > 3 ? ' 외 ' + (cells.blankNames.length - 3) + '곳' : '');
          out.push(h('div', { class: 'banner', role: 'status' }, h('b', { text: '비어 있는 칸 ' + cells.empty + '개' }),
            h('span', { class: 'bt', text: names + ' 칸이 비어 있어. 알게 되면 말해 줘, 다시 뽑아 줄게.' })));
        }
        out.push(composer(entry, can, '"' + f.path + '" 의 비어 있는 칸을 채워서 다시 뽑아 줘: ', '예: 출처는 구매팀 김OO, 10/28 회의야'));
        if (!can) out.push(h('p', { class: 'note-muted', text: entry.session.cannotSendReason || '이 세션에는 지금 말을 보낼 수 없어.' }));
        if (st.say) out.push(h('p', { class: 'note-accent', role: 'status', text: st.say }));
        return out;
      }
      function composer(entry, can, prefix, placeholder) {
        var input = h('input', { id: 'doc-ask', class: 'comp-in', type: 'text', value: askVal, disabled: !can, autocomplete: 'off', placeholder: placeholder,
          onInput: function (e) { askVal = e.target.value; } });
        function send() { var t = askVal.trim(); if (t) ask(entry, prefix + t); }
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); send(); } });
        return h('div', { class: 'dask' }, h('label', { for: 'doc-ask', class: 'sr-only', text: 'AI에게 말하기' }),
          h('div', { class: 'comp' }, input, h('button', { type: 'button', class: 'pill dark', disabled: !can, text: '보내기', onClick: send })));
      }
      function exportBtn(entry, can, cls) {
        var f = entry.file, kind = /매뉴얼|manual/i.test(f.path) ? 'pptx' : 'xlsx';
        return h('button', { type: 'button', class: cls, disabled: !can, text: kind + '로 뽑기',
          onClick: function () { ask(entry, '"' + f.path + '" 을(를) 고객 양식 ' + kind + ' 파일로 뽑아 줘.'); } });
      }
      function previewBox(entry) {
        var f = entry.file, c = entry.chip, s = entry.session, can = s.canSend !== false;
        var form = L.isFormOutput(f), canExport = L.docGroup(f) === 'spec', lb = L.docLabel(f.path);
        var ver = lb.ver || (st.preview && st.preview.kind === 'md' ? (/^\s*버전:\s*v?(\d+(?:\.\d+)*)/m.exec(st.preview.text) || [])[1] || '' : '');
        var box = h('div', { class: 'dprev' });
        var chipText = c ? (ver ? 'v' + ver + ' · ' : '') + c.text : (ver ? 'v' + ver : '');
        box.appendChild(h('div', { class: 'dhead' }, h('h2', { class: 'wrap-any', text: form ? kit.baseName(f.path) : lb.name }), chipText ? h('span', { class: 'chip2 ' + (c ? c.tone : ''), title: c ? c.title : '', text: chipText }) : null,
          h('span', { class: 'sp' }),
          form ? null : h('button', { type: 'button', class: 'pill line sm', text: '열기', onClick: function () { openFile(entry, 'open'); } }),
          form ? null : h('button', { type: 'button', class: 'pill line sm', text: '폴더에서 보기', onClick: function () { openFile(entry, 'reveal'); } }),
          canExport ? exportBtn(entry, can, 'pill dark sm') : null));
        if (form) { resultBody(entry, can).forEach(function (n) { box.appendChild(n); }); return box; }
        if (st.note) box.appendChild(h('p', { class: 'note-accent', role: 'status', text: st.note }));
        var pane = h('div', { class: 'docs-pane' });
        pane.appendChild(h('div', { class: 'ptool' }, h('span', { text: lb.base + (ver ? ' · v' + ver : '') }),
          c ? h('span', { class: 'chip2 ' + c.tone, title: c.title, text: c.text === '안 올림' ? '아직 안 올림' : c.text }) : null,
          h('span', { class: 'sp' }), h('span', { class: 'pt-m', text: '세션 ' + (s.title || kit.baseName(s.cwd) || '이름 없는 세션') }),
          canExport ? exportBtn(entry, can, 'pill line xs') : null));
        if (st.previewError) pane.appendChild(h('p', { class: 'note-muted', role: 'status', text: failText(st.previewError, '미리보기') }));
        else if (!st.preview) pane.appendChild(h('p', { class: 'note-muted', role: 'status', text: '불러오는 중이에요.' }));
        else pane.appendChild(renderPreview(st.preview, { sheet: st.sheet, name: kit.baseName(f.path), setSheet: function (i) { st.sheet = i; draw(); } }));
        box.appendChild(pane);
        box.appendChild(composer(entry, can, '"' + f.path + '" 을(를) 고쳐 줘: ', '이 문서 고쳐 달라고 하기 — 예: 표시 항목에 납품일 추가'));
        if (!can) box.appendChild(h('p', { class: 'note-muted', text: s.cannotSendReason || '이 세션에는 지금 말을 보낼 수 없어.' }));
        if (st.say) box.appendChild(h('p', { class: 'note-accent', role: 'status', text: st.say }));
        return box;
      }

      function title(eb, h1, line) {
        return h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: eb }), h('h1', { text: h1 }), line ? h('span', { class: 'line', text: line }) : null);
      }
      function draw() {
        clear(page);
        if (!kit.loaded()) { page.appendChild(title('산출물', '내가 만든 문서')); page.appendChild(kit.loadingBox('세션을 불러오는 중입니다.')); return; }
        if (!pool().length) { page.appendChild(title('산출물', '내가 만든 문서')); page.appendChild(kit.stateBox('folder', '아직 만든 문서가 없어', '작업을 시작하면 세션이 만든 문서가 여기에 모여.', kit.link('/new', { class: 'btn', text: '새 작업 시작' }))); return; }
        if (!st.parts) { page.appendChild(title('산출물', '내가 만든 문서')); page.appendChild(kit.loadingBox('문서를 모으는 중이에요.')); return; }
        var all = docs(), failed = st.parts.filter(function (p) { return p.failed; }), unsure = st.parts.filter(function (p) { return p.unknown && !p.failed; });
        var notes = [];
        if (failed.length) notes.push(h('p', { class: 'note-attn', role: 'status', text: failed.length + '개 세션의 문서를 읽지 못했어. 목록에 빠진 문서가 있을 수 있어.' }));
        else if (unsure.length) notes.push(h('p', { class: 'note-attn', role: 'status', text: unsure.length + '개 세션은 git 상태를 읽지 못해서 올림 여부를 "확인 못 함"으로 보여.' }));
        st.parts.forEach(function (p) { if (p.note && !p.unknown) notes.push(h('p', { class: 'note-muted', role: 'status', text: p.note })); });  // 칩은 그대로 두고 안내만 한 줄 더한다
        if (!all.length) { page.appendChild(title('산출물', '내가 만든 문서')); page.appendChild(h('section', { class: 'light dsec' }, notes, h('p', { class: 'note-muted', text: '아직 만든 문서가 없어.' }))); return; }
        // 시안 G-15: 방금 고객 양식 xlsx 를 뽑았으면(가장 최근 산출물이 그 파일) 목록 없이 결과 화면을 먼저 보인다. '문서 목록 보기' 로 나가면 시안 G-14 목록 화면.
        var fresh = st.view === 'list' ? null : L.latestFormXlsx(all);
        if (fresh && (!st.sel || st.sel === fresh.key || st.inResult)) {
          st.inResult = true;
          if (st.sel !== fresh.key) setTimeout(function () { if (alive && st.sel !== fresh.key) pick(fresh); }, 0);
          page.appendChild(h('div', { class: 'ptitle-row' }, title('산출물 · 고객 양식', '고객 양식으로 뽑았어', L.formSubtitle(fresh.file.path)),
            h('button', { type: 'button', class: 'pill line sm', text: '문서 목록 보기', onClick: function () { st.view = 'list'; st.inResult = false; st.sel = null; st.picked = null; st.auto = false; draw(); } })));
          page.appendChild(h('section', { class: 'light dres' }, notes, resultBody(fresh, fresh.session.canSend !== false)));
          return;
        }
        page.appendChild(title('산출물', '내가 만든 문서'));
        var sec = h('section', { class: 'light dsec' }, notes);
        // 시안 G-14: 처음 들어오면 가장 최근 글 문서(md)를, 없으면 가장 최근 문서를 골라 미리보기까지 보인다. 한 번만(사람이 고른 뒤엔 건드리지 않는다).
        if (!st.sel && !st.auto) {
          st.auto = true;
          var first = all.filter(function (d) { return /\.(md|markdown|txt)$/i.test(d.file.path); })[0] || all[0];
          setTimeout(function () { if (alive && !st.sel) pick(first); }, 0);
        }
        var cur = selected();
        sec.appendChild(h('div', { class: 'dgrid' }, listBox(all),
          cur ? previewBox(cur) : h('div', { class: 'dprev' }, h('p', { class: 'empty-line', text: '왼쪽에서 문서를 골라 줘. 미리보기와 고치기 입력칸이 여기에 나와.' }))));
        page.appendChild(sec);
      }
      draw(); refresh();
      return {
        title: function () { return '산출물'; },
        onData: refresh, onSession: refresh, onRequest: function () {}, onRemoved: refresh,
        destroy: function () { alive = false; clearTimeout(timer); }
      };
    }

    function docsPanel() {
      var el = h('section', { class: 'docs', 'aria-label': '만든 문서' });
      var listBox = h('div', { class: 'docs-list' });
      var pane = h('div', { class: 'docs-pane paper', hidden: true });
      var wrap = h('div', { class: 'docs-wrap' }, pane, listBox);  // 시안 G-09: 위에 흰 문서 미리보기, 아래에 문서 줄
      el.appendChild(h('h2', { class: 'eb', title: '이 세션에서 쓴 파일과 시작 뒤 새로 바뀐 파일이에요. 같은 폴더의 다른 세션이 바꾼 파일이 섞일 수 있어요.', text: '만든 산출물' }));
      el.appendChild(wrap);
      var st = { files: null, error: null, selected: null, preview: null, previewError: null, sheet: 0, note: '', at: 0, stamp: null };
      var last = null, alive = true, loading = false;

      function fetchFiles(s) {
        if (loading) return;
        loading = true; st.at = Date.now();
        api('GET', '/api/sessions/' + sid(s) + '/files').then(function (d) { st.files = L.docList(kit.listOf(d, 'files')); st.error = null; st.unknown = d && d.unknown ? String(d.reason || '') : null; st.note = d && d.note ? String(d.note) : ''; st.truncated = !!(d && d.truncated); },
          function (e) { st.error = e; }).then(function () { loading = false; if (alive) { drawList(); autoPick(); } });
      }
      function selectFile(f) {
        st.selected = f.path; st.preview = null; st.previewError = null; st.sheet = 0; st.note = '';
        drawList(); drawPane();
        api('GET', '/api/sessions/' + sid(last) + '/files/preview' + kit.qs({ path: f.path })).then(function (d) { st.preview = L.normPreview(d); },
          function (e) { st.previewError = e; }).then(function () { if (alive && st.selected === f.path) drawPane(); });
      }
      function openFile(mode) {
        st.note = mode === 'reveal' ? '탐색기를 여는 중이에요.' : '기본 프로그램으로 여는 중이에요.'; drawPane();
        api('POST', '/api/sessions/' + sid(last) + '/files/open', { path: st.selected, mode: mode }).then(function () {
          st.note = mode === 'reveal' ? '탐색기에서 위치를 열었어요.' : '열었어요.';
        }, function (e) { st.note = failText(e, '열기'); }).then(function () { if (alive) drawPane(); });
      }

      function item(f, sub) {
        var picked = st.selected === f.path, c = sub ? null : L.docChip(f, last, st.unknown != null);
        return h('button', { type: 'button', class: 'drow' + (picked ? ' on' : '') + (sub ? ' sub' : ''), 'aria-pressed': String(picked), 'data-path': f.path, onClick: function () { selectFile(f); } },
          h('span', { class: 'dn' }, h('b', { class: 'wrap-any', text: kit.baseName(f.path) }),
            h('small', { text: [L.kindBadge(f), f.size != null ? kit.fmtSize(f.size) : '', f.mtime ? kit.clock(f.mtime) : ''].filter(Boolean).join(' · ') })),
          c ? h('span', { class: 'chip2 ' + c.tone, title: c.title, text: c.text }) : null);
      }
      // 시안 G-09: 처음엔 가장 최근 글 문서(md)를 흰 종이로 미리 보여 준다. 사람이 닫을 방법은 없다(다른 문서를 고르면 바뀐다).
      function autoPick() {
        if (st.selected || st.auto || !st.files || !st.files.length) return;
        var md = st.files.filter(function (f) { return /\.(md|markdown|txt)$/i.test(f.path); })[0];
        st.auto = true;
        if (md) selectFile(md);
      }
      function drawList() {
        clear(listBox);
        if (st.error && !st.files) { listBox.appendChild(h('p', { class: 'note-muted', role: 'status', text: failText(st.error, '문서 목록') })); return; }
        if (!st.files) { listBox.appendChild(h('p', { class: 'note-muted', role: 'status', text: '불러오는 중이에요.' })); return; }
        if (st.unknown != null) listBox.appendChild(h('p', { class: 'note-attn', role: 'status', text: '바뀐 문서를 확인하지 못했어요.' + (st.unknown ? ' (' + st.unknown + ')' : '') + ' 아래 목록에 빠진 문서가 있을 수 있어요.' }));
        if (st.note) listBox.appendChild(h('p', { class: 'note-muted', role: 'status', text: st.note }));
        if (st.truncated) listBox.appendChild(h('p', { class: 'note-attn', role: 'status', text: '문서가 너무 많아 목록이 잘렸어요. 더 있을 수 있어요.' }));
        if (!st.files.length) { listBox.appendChild(h('p', { class: 'note-muted', text: st.unknown != null ? '확인된 문서가 없어요.' : '아직 만든 문서가 없어요.' })); return; }
        // 시안 G-08(일하는 중): 오른쪽은 문서 미리보기 한 장 — 다른 문서 목록은 눌렀을 때만 펼친다(고를 수 있게 남겨 둔다).
        // G-09(일을 마치고 내 차례): 미리보기 아래에 문서 줄 목록을 보인다.
        if (st.selected && !st.showList && last && last.status === 'running') {
          var others = st.files.length - 1;
          if (others > 0) listBox.appendChild(h('button', { type: 'button', class: 'disclose', 'data-docs-more': '1', 'aria-expanded': 'false',
            onClick: function () { st.showList = true; drawList(); } }, '다른 문서 ' + others + '개 보기'));
          return;
        }
        st.files.forEach(function (f) {
          listBox.appendChild(item(f, false));
          var olds = L.versionPaths(f);
          if (olds.length) {
            var det = h('details', { class: 'tech flat docs-old' }, h('summary', { text: '이전 판 ' + olds.length + '개' }));
            olds.forEach(function (v) { det.appendChild(item(v, true)); });
            listBox.appendChild(det);
          }
        });
      }
      function drawPreview(p) { return renderPreview(p, { sheet: st.sheet, name: kit.baseName(st.selected), setSheet: function (i) { st.sheet = i; drawPane(); } }); }
      function drawPane() {
        clear(pane);
        pane.hidden = !st.selected;
        if (!st.selected) return;
        var sel = (st.files || []).filter(function (f) { return f.path === st.selected; })[0], c = sel ? L.docChip(sel, last, st.unknown != null) : null;
        pane.appendChild(h('div', { class: 'pane-head' },
          h('span', { class: 'wrap-any', text: kit.baseName(st.selected) }),
          c ? h('span', { class: 'chip2 ' + c.tone, title: c.title, text: c.text }) : null,
          h('span', { class: 'sp' }),
          h('button', { type: 'button', class: 'pill line sm', text: '열기', onClick: function () { openFile('open'); } }),
          h('button', { type: 'button', class: 'pill line sm', text: '탐색기에서 위치 보기', onClick: function () { openFile('reveal'); } })));
        if (st.note) pane.appendChild(h('p', { class: 'note-accent', role: 'status', text: st.note }));
        if (st.previewError) pane.appendChild(h('p', { class: 'note-muted', role: 'status', text: failText(st.previewError, '미리보기') }));
        else if (!st.preview) pane.appendChild(h('p', { class: 'note-muted', role: 'status', text: '불러오는 중이에요.' }));
        else pane.appendChild(drawPreview(st.preview));
      }
      function update(s) {
        last = s;
        var stamp = [s.updatedAt, (s.changedFiles || []).length].join('|');
        if (!st.files || (stamp !== st.stamp && Date.now() - st.at > DOCS_REFETCH_MS)) { st.stamp = stamp; fetchFiles(s); }
        drawList();
      }
      drawList();
      return { el: el, update: update, destroy: function () { alive = false; } };
    }

    /* ---------- 새 작업: 순서 칸("이렇게 진행돼")과 분석한 갈래 보여 주고 바꾸기 ---------- */
    var STEP_NOTE = { skill: function (st) { return st.skill ? HARNESS_PREFIX + st.skill : ''; }, work: function () { return '직접 하는 일'; }, human: function () { return '사람이 확인'; }, wait: function () { return '밖에서 일이 끝나길 기다려'; } };
    function flowCells(flow) {
      return h('div', { class: 'flow', 'data-flow-cells': flow.id }, kit.listOf(flow, 'steps').map(function (st, i) {
        var note = STEP_NOTE[st.kind] ? STEP_NOTE[st.kind](st) : '';
        return h('div', { class: 'fs' }, h('b', { text: (i + 1) + ' ' + (st.name || st.id) }), note ? h('small', { text: note }) : null);
      }));
    }
    // update({cwd, flowId, note}): 갈래 id 가 있으면 그 갈래의 순서를, 없으면 note 를 보인다.
    function flowPreview() {
      var el = h('div', { class: 'flowpreview', 'data-flow-preview': '1' }), alive = true, last = null;
      function draw(r) {
        clear(el);
        if (!last || !last.flowId) { el.appendChild(h('p', { class: 'quiet', text: last ? last.note || '' : '' })); return; }
        if (!r) { el.appendChild(h('p', { class: 'quiet', role: 'status', text: '불러오는 중이야.' })); return; }
        if (!r.ok) { el.appendChild(h('p', { class: 'quiet', role: 'status', text: failText(r.error, '진행 순서') })); return; }
        var flow = kit.listOf(r.data, 'flows').filter(function (f) { return f.id === last.flowId; })[0];
        el.appendChild(flow ? flowCells(flow) : h('p', { class: 'quiet', text: '이 프로젝트에는 이 일의 순서가 없어.' }));
      }
      function update(o) {
        last = o;
        draw(null);
        if (o.flowId) flowsFor(o.cwd).then(function (r) { if (alive && last === o) draw(r); });
      }
      return { el: el, update: update, destroy: function () { alive = false; } };
    }

    /* ---------- 새 작업: 분석한 갈래 보여 주고 바꾸기 ---------- */
    // update({cwd, found, selected, onPick(id)})
    function flowChooser() {
      var el = h('section', { class: 'flowchoose', hidden: true });
      var open = false, alive = true, last = null;
      function nameOf(flows, id) { var f = flows.filter(function (x) { return x.id === id; })[0]; return f ? f.name : id; }
      function draw(r) {
        clear(el);
        el.hidden = true;
        if (!last || !r) return;
        if (!r.ok) { el.hidden = false; el.appendChild(h('p', { class: 'note-muted', text: failText(r.error, '일 갈래') })); return; }
        var flows = kit.listOf(r.data, 'flows').filter(function (f) { return !(f.exposure && f.exposure.visible === false); });
        if (!flows.length) return;
        // 도구 스킬만 쓰는 일(scaffold, cts, role, manual …)은 어느 갈래에도 억지로 넣지 않는다. 서버가 같은 id(none)로 알아듣는다.
        flows.push({ id: L.NO_FLOW_ID, name: '순서 없이 이 도구만', steps: [] });
        el.hidden = false;
        var found = last.found, picked = last.selected;
        var cur = flows.filter(function (f) { return f.id === picked; })[0];
        el.appendChild(h('h2', { class: 'sect-h', text: '어떤 일인가요?' }));
        // 종류 버튼으로 고른 갈래를 AI 가 다르게 보면 조용히 덮어쓰지 않고 먼저 묻는다(#668).
        var conflict = !last.userPicked && L.kindConflict(found, last.kindFlowId);
        if (conflict) {
          var aiName = nameOf(flows, conflict.id);
          el.appendChild(askCard({
            id: 'flow', label: 'AI 추천 확인',
            lead: ['AI 는 ', h('b', { text: aiName }), ' 부터 하자고 해' + (conflict.reason ? ' — ' + conflict.reason : '')],
            block: last.insist ? L.devBlock(last.kindFlowId, last.ready) : '',
            switchText: aiName + ' 쪽으로 바꾸기 (추천)', keepText: last.kindName || '그래도 ' + nameOf(flows, last.kindFlowId),
            onSwitch: function () { last.onPick(conflict.id); }, onKeep: function () { last.onKeep(); }
          }));
          return;
        }
        if (found && found.confident === false && found.alternativeId && !last.userPicked) {
          el.appendChild(h('p', { class: 'note-muted', text: '어느 쪽에 더 가까운지 골라 주세요. ' + (found.reason || '') }));
          var two = h('div', { class: 'chips' });
          [found.id, found.alternativeId].forEach(function (id) {
            two.appendChild(h('button', { type: 'button', class: 'btn', 'aria-pressed': String(picked === id), 'data-flow': id, text: nameOf(flows, id), onClick: function () { last.onPick(id); } }));
          });
          el.appendChild(two);
        } else if (cur && cur.id === L.NO_FLOW_ID) {
          el.appendChild(h('p', { class: 'flow-line', text: '도구만 쓰는 일이에요 · 정해진 순서 없이 그 도구 스킬로 바로 시작해요.' }));
          if (found && found.id === cur.id && found.reason) el.appendChild(h('p', { class: 'note-muted', text: found.reason }));
        } else if (cur) {
          el.appendChild(h('p', { class: 'flow-line', text: '이 일은 \'' + cur.name + '\' 갈래야.' }));
          el.appendChild(flowCells(cur));
          if (found && found.id === cur.id && found.reason) el.appendChild(h('p', { class: 'note-muted', text: found.reason }));
        } else el.appendChild(h('p', { class: 'note-muted', text: '고르지 않으면 정해진 순서 없이 시작해요.' }));
        var blocked = last.kindFlowId === 'dev' && picked === 'dev' ? L.devBlock('dev', last.ready) : '';  // 종류 버튼으로 개발을 골랐는데 Spec 이 없다고 확실할 때
        if (blocked) el.appendChild(h('p', { class: 'note-attn', role: 'alert', 'data-ask-block': '1', text: blocked }));
        el.appendChild(h('button', { type: 'button', class: 'disclose', 'aria-expanded': String(open), onClick: function () { open = !open; draw(r); } }, kit.icon('chev', 14), '다른 갈래로 바꾸기'));
        if (open) {
          var grid = h('div', { class: 'chips' });
          flows.forEach(function (f) {
            grid.appendChild(h('button', { type: 'button', class: 'chip', 'aria-pressed': String(f.id === picked), 'data-flow': f.id, text: f.name, onClick: function () { last.onPick(f.id); } }));
          });
          el.appendChild(grid);
        }
      }
      function update(o) {
        last = o;
        flowsFor(o.cwd).then(function (r) { if (alive) draw(r); });
      }
      return { el: el, update: update, destroy: function () { alive = false; } };
    }

    /* ---------- 홈 ---------- */
    function approvalCard(box, onMerged) {
      var cwds = [], seenRepo = {};
      sessionList().forEach(function (s) {
        var key = s.repo || L.normPath(s.cwd);
        if (s.cwd && !seenRepo[key] && cwds.length < MAX_APPROVAL_FOLDERS) { seenRepo[key] = 1; cwds.push(s.cwd); }
      });
      var sig = cwds.join('|');
      if (box.dataset.sig === sig && box.dataset.ready) return;
      box.dataset.sig = sig;
      Promise.all(cwds.map(approvalsFor)).then(function (rs) {
        if (box.dataset.sig !== sig || !box.isConnected) return;
        box.dataset.ready = '1';
        var merged = L.mergeApprovals(rs.map(function (r) { return r.ok ? r.data : null; }));
        clear(box);
        if (onMerged) onMerged(merged);
        var compact = !!box.dataset.compact;  // 홈 "검토 요청(PR)" 칸 안(시안 G-11): 머리 없이 줄만
        if (merged.state === 'yes') {
          var items = merged.items;
          if (!compact) {
            // 세션이 없을 때의 따로 선 칸: eb 머리 + 줄(이름 · 오른쪽 짧은 글). 머리와 문장은 각자 한 줄(.blk)
            box.appendChild(h('span', { class: 'eb blk', text: '내가 승인할 PR ' + items.length + '건' }));
            if (!items.length) box.appendChild(h('span', { class: 'quiet blk', text: '지금 기다리는 PR 이 없어요.' }));
          }
          items.forEach(function (it) {
            var url = kit.safeHttp(it.url);
            var label = (compact ? '내가 승인할 PR ' : '') + '#' + it.number + ' ' + (it.title || '');
            box.appendChild(h('div', { class: 'srow2', 'data-approval': String(it.number) }, url ? h('a', { class: 'lm', href: url, target: '_blank', rel: 'noopener noreferrer', text: label }) : h('span', { class: 'lm', text: label }),
              h('span', { text: (it.author ? it.author + (compact ? ' 가 올림' : '') : '') + (it.staleApproval ? ' · 새 변경 뒤 다시 확인' : '') })));
          });
        } else if (merged.state === 'unknown') {
          if (!compact) box.appendChild(h('span', { class: 'eb blk', text: '내가 승인할 PR' }));
          box.appendChild(h('span', { class: 'note-attn blk', role: 'status', text: '승인할 PR 판정 불능 · ' + (merged.reason || '이유를 읽지 못했어요.') }));
        }
      });
    }

    // 프로젝트 준비 안내: 세션이 있는 폴더 중 templates/·rules/ 가 없는 곳을 알린다. 읽지 못한 폴더는 숨기지 않고 '확인 못 함' 으로 적는다.
    function projectCard(box) {
      var cwds = [], seen = {};
      sessionList().forEach(function (s) {
        var key = s.repo || L.normPath(s.cwd);
        if (s.cwd && !seen[key] && cwds.length < MAX_APPROVAL_FOLDERS) { seen[key] = 1; cwds.push(s.cwd); }
      });
      var sig = cwds.join('|');
      if (box.dataset.sig === sig && box.dataset.ready) return;
      box.dataset.sig = sig;
      Promise.all(cwds.map(flowsFor)).then(function (rs) {
        if (box.dataset.sig !== sig || !box.isConnected) return;
        box.dataset.ready = '1';
        clear(box);
        var lines = [], unk = [];
        rs.forEach(function (r, i) {
          var name = kit.baseName(cwds[i]) || cwds[i];
          if (!r.ok) { unk.push(name + ': 프로젝트 준비 여부를 확인하지 못했어요 - ' + failText(r.error)); return; }
          var pn = L.projectNotice(r.data);
          if (pn) lines.push(name + ': ' + pn.text);
          else { var fn = L.formsNotice(r.data); if (fn) lines.push(name + ': ' + fn.text); }
        });
        // 할 일 안내는 시안의 흰 칸(.lt). 정말 못 읽은 폴더만 "? 확인 못 함" 모양(보라 점선)을 쓴다.
        if (lines.length) {
          box.appendChild(h('section', { class: 'lt', 'data-project-card': '1' },
            h('span', { class: 'eb', text: '프로젝트 준비' }),
            lines.map(function (t) { return h('div', { class: 'srow2' }, h('span', null, h('b', { class: 'lw', text: '! ' }), t)); })));
        }
        if (unk.length) {
          box.appendChild(h('section', { class: 'approval-card unknown', 'data-project-card': 'unknown' },
            h('h2', { class: 'sect-h', text: '프로젝트 준비' }),
            h('ul', { class: 'plain-list' }, unk.map(function (t) { return h('li', null, h('span', { class: 'note-attn', text: t })); }))));
        }
      });
    }

    // 홈 아래 오른쪽 칸 "최근 산출물"(시안 G-11): 최근에 움직인 세션 몇 개의 문서 목록을 모아 가장 최근 몇 개를 칩과 함께 보인다.
    // 읽지 못하면 있는 것처럼 두지 않고 "확인 못 함" 이라고 쓴다.
    // 같은 목록으로 홈 숫자 칸 "이번 주 산출물" 도 센다(onWeek(n), 읽지 못하면 onWeek(null)). 이번 주에 움직인 세션은 WEEK_POOL 개까지 본다.
    var RECENT_POOL = 6, RECENT_ROWS = 4, WEEK_POOL = 20;
    function recentCard(box, onWeek) {
      var nowSec = Date.now() / 1000, all = sessionList();
      var recentFirst = all.filter(function (s) { return !s.handedOffTo; }).sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); }).slice(0, RECENT_POOL);
      var pool = recentFirst.slice();
      L.weekPool(all, nowSec, WEEK_POOL).forEach(function (s) { if (pool.indexOf(s) < 0) pool.push(s); });
      // 순서만 바뀐 것(일하는 세션의 updatedAt 갱신)으로는 다시 읽지 않는다. 세션 묶음이 바뀔 때만 6개 파일 목록을 다시 묻는다.
      var sig = pool.map(function (s) { return s.id; }).sort().join('|');
      if (box.dataset.sig === sig && box.dataset.ready) return;
      box.dataset.sig = sig;
      if (!box.dataset.ready) { clear(box); box.appendChild(h('span', { class: 'eb', text: '최근 산출물' })); box.appendChild(h('span', { class: 'quiet', role: 'status', text: '불러오는 중이야.' })); }
      Promise.all(pool.map(function (s) {
        return api('GET', '/api/sessions/' + sid(s) + '/files').then(function (d) { return { session: s, files: kit.listOf(d, 'files'), unknown: !!(d && d.unknown) }; },
          function (e) { return { session: s, files: [], unknown: true, failed: e }; });
      })).then(function (parts) {
        if (box.dataset.sig !== sig || !box.isConnected) return;
        box.dataset.ready = '1';
        clear(box);
        box.appendChild(h('span', { class: 'eb', text: '최근 산출물' }));
        var failed = parts.filter(function (p) { return p.failed; }).length;
        var allDocs = L.mergeDocs(parts);
        if (onWeek) onWeek(failed === parts.length && parts.length ? null : L.weekDocCount(allDocs, Date.now() / 1000));
        var docs = allDocs.slice(0, RECENT_ROWS);
        if (failed === parts.length && parts.length) { box.appendChild(h('span', { class: 'note-attn', role: 'status', text: '확인 못 함 · 문서 목록을 읽지 못했어.' })); return; }
        if (!docs.length) box.appendChild(h('span', { class: 'quiet', text: '아직 만든 산출물이 없어.' }));
        docs.forEach(function (d) {
          box.appendChild(h('div', { class: 'srow2', 'data-doc': d.file.path }, h('span', { class: 'lm', title: d.session.title || null, text: kit.baseName(d.file.path) }),
            h('span', { class: 'chip2 ' + d.chip.tone, title: d.chip.title, text: d.chip.text })));
        });
        if (failed) box.appendChild(h('span', { class: 'quiet', role: 'status', text: '일부 세션의 문서를 읽지 못했어. 목록에 빠진 문서가 있을 수 있어.' }));
      });
    }

    var GROUP_ORDER = { todo: 0, running: 1, idle: 2 };
    // 자주 하는 일: 누르면 새 작업 화면의 입력칸에 이 문장을 미리 넣어 간다(새 작업 화면은 종류를 미리 고르는 인자를 받지 않는다).
    var KINDS = [
      ['요구사항정의서', '고객 요구를 SRS 로', '요구사항정의서(SRS)를 만들고 싶어. '],
      ['개발 Spec', '요구사항으로 설계서', '개발 Spec 을 만들고 싶어. '],
      ['사용자 매뉴얼', '화면 캡처 · pptx', '사용자 매뉴얼을 만들고 싶어. '],
      ['CTS 관리대장', '요청 건 · xlsx', 'CTS 관리대장에 요청 건을 더하고 싶어. '],
      ['Role 정리', '메뉴 배정 · xlsx', 'Role(사용자 권한) 메뉴 배정을 정리하고 싶어. '],
      ['개발하기', 'Spec 승인된 건', '새 기능을 개발하고 싶어. ']
    ];
    function startNew(text) { if (kit.startNew) kit.startNew(text); else kit.go('/new'); }
    function pad2(n) { return n < 10 ? '0' + n : '' + n; }
    function today() { var d = new Date(); return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
    function issueOf(s) { var m = /^[\w.-]+\/(\d+)-/.exec(s.branch || ''); return m ? m[1] : ''; }
    function tile(label, value, cls) {
      return h('div', { class: 'tile2' + (cls ? ' ' + cls : '') }, h('span', { class: 'eb', text: label }), h('span', { class: 'v', text: value }));
    }
    function tbar(s) {
      var steps = s.flowId ? L.barSteps(s) : [];
      if (!steps.length) return h('span', { class: 'none', text: '–' });
      return h('ol', { class: 'tbar', 'aria-label': '진행 순서' }, steps.map(function (st) {
        return h('li', { class: st.state, 'aria-current': st.state === 'now' ? 'step' : null, title: st.name + ' · ' + st.label },
          h('span', { class: 'sr-only', text: st.name + ' ' + st.label }));
      }));
    }
    function pendingOf(s) {
      return (s.pendingRequestIds || []).map(function (rid) { return { rid: rid, r: kit.requests.get(rid) }; })
        .filter(function (x) { return !(x.r && x.r.status && x.r.status !== 'pending'); })[0] || null;
    }
    function emptyHome(root, approvals, projects) {
      var page = h('div', { class: 'page home' });
      var sub = h('p', { class: 'line', text: 'Claude Code 세션을 시작하면 왼쪽 목록에 생겨. 지금 바로 맡길 일이 있으면 아래에서 시작해.' });
      page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb accent', text: '내 일' }), h('h1', { text: '아직 시작한 작업이 없어' }), sub));
      // 시안 G-04: 서버가 기억한 마지막 폴더가 준비됐으면 "프로젝트 준비 끝 · 이름". 못 읽거나 준비됨이 아니면 위 문구 그대로.
      api('GET', '/api/folders/last').then(function (d) {
        if (!d || !d.path) return null;
        return api('GET', '/api/folders/recent').then(function (r) {
          var hit = kit.listOf(r, 'folders').filter(function (f) { return f && f.path === d.path && f.ready === 'yes'; })[0];
          if (hit && sub.isConnected) sub.textContent = '프로젝트 준비 끝 · ' + (d.name || kit.baseName(d.path));
        });
      }).then(null, function (e) { console.debug('마지막 폴더를 읽지 못했습니다', e); });
      var grid = h('div', { class: 'kinds' }, KINDS.map(function (k) {
        return h('button', { type: 'button', class: 'kind', 'data-kind': k[0], onClick: function () { startNew(k[2]); } }, h('b', { text: k[0] }), h('small', { text: k[1] }));
      }));
      var input = h('input', { id: 'home-brief', class: 'comp-in', type: 'text', placeholder: '하고 싶은 일을 적어 — 예: 구매오더 조회 앱 요구사항 써 줘', autocomplete: 'off' });
      var form = h('form', { class: 'comp', onSubmit: function (e) { e.preventDefault(); startNew(input.value); } },
        h('label', { class: 'sr-only', for: 'home-brief', text: '하고 싶은 일' }), input,
        h('button', { type: 'submit', class: 'pill dark', text: '새 작업으로' }));
      page.appendChild(h('section', { class: 'light' }, h('h2', { text: '첫 작업을 시작해 볼까?' }),
        h('p', { class: 'lm', text: '자주 하는 일이야. 눌러도 되고, 아래에 하고 싶은 일을 그냥 적어도 돼.' }), grid, form));
      page.appendChild(h('div', { class: 'tiles2' }, tile('내 차례', '0', ''), tile('일하는 중', '0', ''), tile('만든 산출물', '0', '')));
      approvals.className = 'approvals lt';  // 세션이 없을 땐 표 아래 칸이 없으니 따로 선 흰 칸. 비면 숨는다(.lt:empty)
      page.appendChild(approvals);
      page.appendChild(projects);
      root.appendChild(page);
    }
    // 표시 약속(시안 16): 화면 어디서나 같은 뜻으로 쓰는 세 가지 표시
    function legend() {
      // 시안 G-16: 막힘·확인 못 함 카드가 있는 세션 화면 아래, 전체 폭 흰 칸(.lt) 안에 줄(표시 | 뜻). 홈에는 없다(G-04·G-11).
      return h('div', { class: 'lt legend', role: 'group', 'aria-label': '표시 약속' },
        h('span', { class: 'eb', text: '표시 약속' }),
        h('div', { class: 'srow2' }, h('b', { class: 'lf', text: '✕ 막힘' }), h('span', { text: '잘못을 찾음, 고쳐야 넘어가' })),
        h('div', { class: 'srow2' }, h('b', { class: 'lu', text: '? 확인 못 함' }), h('span', { text: '검사 못 함, 통과로도 실패로도 안 침' })),
        h('div', { class: 'srow2' }, h('b', { class: 'lw', text: '! 내 차례' }), h('span', { text: '네 답이나 확인이 필요' })));
    }
    function homeView(root) {
      var approvals = h('div', { class: 'approvals' });
      var recent = h('div', { class: 'lt', 'data-recent': '1' });
      var projects = h('div', { class: 'projects' });
      var prVal = h('span', { class: 'v', text: '…' });
      var prTile = h('div', { class: 'tile2', 'data-pr-tile': '1' }, h('span', { class: 'eb', text: '승인 기다리는 PR' }), prVal);
      prTile.hidden = true;
      // 시안 G-11 의 넷째 칸 "이번 주 산출물". 값은 최근 산출물 칸이 읽은 문서 목록으로 센다(새로 묻지 않는다).
      var weekVal = h('span', { class: 'v', text: '…' });
      var weekTile = h('div', { class: 'tile2', 'data-week-tile': '1' }, h('span', { class: 'eb', text: '이번 주 산출물' }), weekVal);
      function showWeek(n) {
        weekVal.textContent = n == null ? '확인 못 함' : String(n);
        weekTile.className = 'tile2' + (n == null ? ' unk' : '');
      }
      var homeOpen = false;  // "외 n건" 펼침. 이 화면에서만 기억한다
      function showPr(merged) {
        if (merged.state === 'yes') { prVal.textContent = String(merged.items.length); prTile.className = 'tile2'; prTile.hidden = false; }
        else if (merged.state === 'unknown') { prVal.textContent = '확인 못 함'; prTile.className = 'tile2 unk'; prTile.hidden = false; }
        else prTile.hidden = true;
      }
      function draw() {
        clear(root);
        if (!kit.loaded()) {
          root.appendChild(kit.conn() === 'down' ? kit.stateBox('warn', '서버에 연결할 수 없습니다', '서버가 꺼졌을 수 있습니다. 다시 연결을 시도하고 있습니다.') : kit.loadingBox('세션을 불러오는 중입니다.'));
          return;
        }
        var list = sessionList();
        if (!list.length) { emptyHome(root, approvals, projects); approvalCard(approvals, showPr); projectCard(projects); return; }
        list.sort(function (a, b) { return (GROUP_ORDER[L.groupOf(a)] - GROUP_ORDER[L.groupOf(b)]) || ((b.updatedAt || 0) - (a.updatedAt || 0)); });
        var c = L.counts(list), page = h('div', { class: 'page home' });
        var proj = folderName(list[0]);
        page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: today() + ' · ' + proj }), h('h1', { text: '오늘 내 일' })));  // "세션 n개 · …" 줄은 시안에 없다(타일이 같은 숫자를 보인다)
        page.appendChild(h('div', { class: 'tiles2' }, tile('내 차례', String(c.todo), c.todo ? 'warn' : ''), tile('AI가 일하는 중', String(c.running), ''), prTile, weekTile));  // 시안 G-11 순서

        var todo = list.filter(function (s) { return L.groupOf(s) === 'todo'; });
        // 내 차례는 가장 오래 기다린 한 건만 카드로 두고, 나머지는 "외 n건" 을 눌러 펼친다(펼침 상태는 이 화면에서만 기억).
        var waiting = todo.slice().sort(function (a, b) { return (a.updatedAt || 0) - (b.updatedAt || 0); });
        function callCard(s) {
          var pend = pendingOf(s), name = s.title || folderName(s) || '이름 없는 세션';
          var href = pend ? '/r/' + encodeURIComponent(pend.rid) : '/s/' + encodeURIComponent(s.id);
          var verb = pend && pend.r && kit.kindOf(pend.r) === 'question' ? '가서 답하기' : pend ? '가서 승인하기' : '가서 확인하기';
          var what = pend ? (kit.requestTitle ? kit.requestTitle(pend.r) : (pend.r && pend.r.title) || '요청을 확인하세요') : s.askedInText ? '답을 기다리는 듯해요(추정)' : s.turnSkill ? kit.skillLabel(s.turnSkill) + ' 끝남 — 다음을 정해 줘' : '내 차례예요';
          return h('div', { class: 'call', 'data-call': s.id },
            h('div', { class: 'ct' }, h('span', { class: 'eb', text: '네 차례 · ' + name }), h('b', { text: what })),
            kit.link(href, { class: 'pill dark', text: verb }));
        }
        if (waiting.length) {
          page.appendChild(callCard(waiting[0]));
          if (waiting.length > 1) {
            var rest = waiting.slice(1), more = h('div', { class: 'calls-more', 'data-calls-more': '1' }), moreBtn = h('button', { type: 'button', class: 'pill line sm', 'data-calls-toggle': '1', onClick: function () { homeOpen = !homeOpen; paintMore(); } });
            var paintMore = function () {
              moreBtn.setAttribute('aria-expanded', String(homeOpen));
              moreBtn.textContent = homeOpen ? '접기' : '외 ' + rest.length + '건';
              clear(more);
              if (homeOpen) rest.forEach(function (s) { more.appendChild(callCard(s)); });
            };
            paintMore();
            page.appendChild(h('div', { class: 'calls-rest' }, moreBtn, more));
          }
        }

        var head = h('tr', null, ['작업', '단계', '번호', '기억', '상태'].map(function (t) { return h('th', { scope: 'col', text: t }); }));
        var rows = list.map(function (s) {
          var g = L.groupOf(s), todoRow = g === 'todo', ended = s.status === 'ended';
          var title = s.title || folderName(s) || '이름 없는 세션';
          var subs = L.runningSubCount(s);
          var doing = ended ? '끝난 세션' : s.currentAction || (s.currentSkill ? kit.skillLabel(s.currentSkill) + ' 진행 중' : todoRow ? (s.askedInText ? '답을 기다리는 듯해요(추정)' : '내 차례예요') : g === 'running' ? '작업하는 중' : '쉬는 중');
          var tip = doing + (subs ? ' · 서브에이전트 ' + subs + '개 실행 중' : '');  // 둘째 줄 대신 칩 title 로(시안: 상태 칸은 칩 하나)
          var chip = todoRow ? h('span', { class: 'tag', title: tip, text: '내 차례' }) : h('span', { class: 'tag ok', title: tip, text: ended ? '끝남' : g === 'running' ? '일하는 중' : '쉬는 중' });
          var issue = issueOf(s), pr = prChip(s);
          var nums = h('td', { 'data-l': '번호' }, issue ? h('span', { class: 'mono', text: '이슈 #' + issue }) : null, pr, !issue && !pr ? h('span', { class: 'none', text: '–' }) : null);
          return h('tr', { class: todoRow ? 'attn' : '', 'data-session': s.id },
            h('td', { 'data-l': '작업' }, kit.link('/s/' + encodeURIComponent(s.id), { class: 'rt', text: title }),
              h('span', { class: 'rs', text: s.flowId ? (s.flowName || s.flowId) : '정해진 갈래 없음', title: s.cwd || null })),
            h('td', { 'data-l': '단계' }, tbar(s)),
            nums,
            h('td', { 'data-l': '기억' }, (function () {
              var m = L.memoryOf(s);
              return h('span', { class: 'mono' + (m.kind === 'unknown' ? ' unk' : '') + (m.level ? ' ' + m.level : ''), title: m.title, text: m.text });
            })()),
            h('td', { 'data-l': '상태' }, chip));
        });
        page.appendChild(h('section', { class: 'light tablebox' }, h('h2', { text: '내 세션' }),
          h('table', { class: 'list' }, h('thead', null, head), h('tbody', null, rows))));
        // 시안 G-11 표 아래 두 칸: 왼쪽 검토 요청(PR) 줄, 오른쪽 최근 산출물 줄
        approvals.className = 'approvals';
        approvals.dataset.compact = '1';  // 검토 요청 칸 안에서는 줄로 그린다(시안 G-11)
        var own = list.filter(function (s) { return s.flowPr && s.flowPr.number; }).slice(0, 4);
        var prBox = h('div', { class: 'lt', 'data-pr-box': '1' }, h('span', { class: 'eb', text: '검토 요청(PR)' }),
          own.length ? own.map(function (s) {
            var pr = L.prBadge(s.flowPr);
            return h('div', { class: 'srow2' }, h('span', { class: 'lm', text: 'PR #' + pr.number + (pr.title ? ' ' + pr.title : '') }), h('span', { text: pr.text }));
          }) : h('span', { class: 'quiet', text: '이 콘솔의 세션에 연결된 검토 요청이 없어.' }),
          approvals);
        page.appendChild(h('div', { class: 'grid3' }, prBox, recent));
        page.appendChild(projects);
        root.appendChild(page);
        recentCard(recent, showWeek);
        approvalCard(approvals, showPr);
        projectCard(projects);
      }
      draw();
      return { onData: draw, onSession: draw, onRequest: draw, onRemoved: draw, title: function () { return ''; } };
    }

    return {
      stepBar: stepBar, prCard: prCard, flowPreview: flowPreview, toolsRow: toolsRow, startChecksPanel: startChecksPanel, flowPanel: flowPanel, folderNotice: folderNotice,
      docsPanel: docsPanel, docsPage: docsPage, flowsFor: flowsFor, approvalsFor: approvalsFor, flowChooser: flowChooser, devReadyFor: devReadyFor, askCard: askCard, homeView: homeView, legend: legend, closeModal: closeModal
    };
  }
})();
