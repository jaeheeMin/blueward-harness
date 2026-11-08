/* 문제·해결 기록 화면 셋(시안 G-20 목록 · G-21 한 건 · G-22 새 기록, #733). 서버 API 는 trouble.py. 글은 모두 textContent 로만 넣는다. */
(function () {
  'use strict';

  var STAGES = ['개발', '문서 검사', 'SAP 운송', '배포', '기타'];
  var KIND = {
    open: { tag: null, dot: 'tb-d-open' },
    try: { tag: '시도 · 안 됨', cls: 'fail', dot: 'tb-d-fail' },
    candidate: { tag: '해결 후보', cls: 'warn', dot: 'tb-d-warn' },
    solved: { tag: '해결', cls: 'ok', dot: 'tb-d-ok' },
    note: { tag: null, dot: 'tb-d-open' }
  };
  var DRAFT_KEY = 'bh-trouble-draft';

  function dateText(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var m = d.getMonth() + 1, day = d.getDate();
    return (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
  }
  function itemHref(repo, number) { return '/troubles/' + repo.split('/').map(encodeURIComponent).join('/') + '/' + number; }
  function counts(it) {
    var parts = [];
    if (it.tries) parts.push('시도 ' + it.tries);
    if (it.candidates) parts.push('후보 ' + it.candidates);
    if (it.solvedNotes) parts.push('해결 ' + it.solvedNotes);
    return parts.join(' · ');
  }
  function stored(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function store(key, value) {
    try { if (value == null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch (e) { return false; }
    return true;
  }

  function create(kit) {
    var h = kit.h, clear = kit.clear, api = kit.api, qs = kit.qs, link = kit.link, go = kit.go;
    var filter = { status: 'all', q: '', project: '', author: '' };
    var carry = { warnings: [] };  /* 방금 올린 기록의 경고를 한 건 화면이 한 번 보여 준다 */

    function chip(done) { return h('span', { class: done ? 'tag ok' : 'tag', text: done ? '해결됨' : '아직 안 풀림' }); }
    function waitFor(fetch, draw, state) {
      var tries = 0;
      function once() {
        if (state.dead) return;
        fetch().then(function (data) {
          if (state.dead) return;
          draw(data);
          if (data && data.loading && tries++ < 30) state.timer = setTimeout(once, 1500);
        }, function (e) { if (!state.dead) draw(null, e); });
      }
      once();
    }
    function errBox(e, title) {
      var msg = e && e.status === 404 ? e.message : (e && e.message) || '읽지 못했어';
      return h('div', { class: 'tb-empty tb-unk' }, h('span', { class: 'tb-unk-t', text: '? 확인 못 함' }), ' · ' + (title || '') + msg);
    }
    function selectPill(label, value, options, onPick) {
      var sel = h('select', { class: 'tb-selnat', 'aria-label': label }, h('option', { value: '', text: '전체' }),
        options.map(function (o) { return h('option', { value: o.value, text: o.text }); }));
      sel.value = value;
      sel.addEventListener('change', function () { onPick(sel.value); });
      var cur = options.filter(function (o) { return o.value === value; })[0];
      return h('label', { class: 'qopt tb-sel' }, h('span', { text: label + ' · ' + (cur ? cur.text : '전체') + ' ▾' }), sel);
    }

    /* ---------- G-20 목록 ---------- */
    function listView(root) {
      var state = { dead: false, timer: null }, page = h('div', { class: 'tb-page' });
      root.appendChild(page);
      function reload(refresh) {
        clearTimeout(state.timer);
        var query = { status: filter.status, q: filter.q, project: filter.project, author: filter.author, refresh: refresh ? '1' : '' };
        waitFor(function () { return api('GET', '/api/trouble' + qs(query)).then(function (d) { query.refresh = ''; return d; }); }, draw, state);
      }
      function search() { filter.q = input.value.trim(); reload(false); }
      var input = h('input', { class: 'comp-in', id: 'tb-q', placeholder: '오류 문구나 낱말로 찾기', value: filter.q });
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); search(); } });

      function draw(d, e) {
        clear(page);
        if (!d) {
          page.appendChild(h('section', { class: 'light' }, errBox(e, '기록 목록을 ')));
          return;
        }
        var ok = d.projects.filter(function (p) { return p.ok; }), bad = d.projects.filter(function (p) { return !p.ok; });
        var st = d.stats;
        page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '문제·해결 기록' }), h('h1', { text: '팀이 겪은 문제와 푼 방법' }),
          h('span', { class: 'line', text: d.loading && !d.projects.length ? '읽는 중이야' : '프로젝트 ' + ok.length + '곳 · 기록 ' + st.total + '건 · 아직 안 풀린 것 ' + st.open +
            (st.truncated && st.truncated.length ? ' (최근 ' + st.limit + '건만 읽은 곳 있음)' : '') })));
        page.appendChild(h('div', { class: 'strip' },
          h('div', null, h('span', { class: 'eb', text: '이번 달 기록' }), h('span', { class: 'x', text: String(st.month) })),
          h('div', null, h('span', { class: 'eb', text: '아직 안 풀림' }), h('span', { class: 'x' + (st.open ? ' w' : ''), text: String(st.open) })),
          h('div', null, h('span', { class: 'eb', text: '해결됨' }), h('span', { class: 'x', text: String(st.solved) })),
          h('div', null, h('span', { class: 'eb', text: '많이 겪은 단계' }), h('span', { class: 'x', text: st.topStage || '-' }))));
        var light = h('section', { class: 'light tb-light' });
        var seg = h('span', { class: 'seg', role: 'radiogroup', 'aria-label': '상태' }, [['all', '전체'], ['open', '아직'], ['solved', '해결됨']].map(function (o) {
          return h('button', { type: 'button', role: 'radio', 'aria-checked': String(filter.status === o[0]), text: o[1], onClick: function () { filter.status = o[0]; reload(false); } });
        }));
        light.appendChild(h('div', { class: 'tb-bar' },
          h('div', { class: 'comp tb-find' }, h('label', { for: 'tb-q', class: 'sr-only', text: '기록 찾기' }), input,
            h('button', { type: 'button', class: 'pill dark', text: '찾기', onClick: search })),
          seg,
          h('div', { class: 'qo' },
            selectPill('프로젝트', filter.project, ok.map(function (p) { return { value: p.slug, text: p.name }; }), function (v) { filter.project = v; reload(false); }),
            selectPill('쓴 사람', filter.author, d.authors.map(function (a) { return { value: a, text: a }; }), function (v) { filter.author = v; reload(false); })),
          h('span', { class: 'tb-sp' }),
          link('/troubles/new', { class: 'pill acc', text: '+ 새 기록' })));
        var rows = h('div');
        d.items.forEach(function (it) {
          rows.appendChild(link(itemHref(it.repo, it.number), { class: 'rec' },
            chip(it.solved),
            h('div', null, h('b', { text: it.title }), h('small', { text: [it.project, it.pr ? 'PR #' + it.pr + (it.prTitle ? ' ' + it.prTitle : '') : 'PR 없음',
              '단계 ' + (it.stage || '-'), it.author, dateText(it.createdAt)].join(' · ') })),
            h('span', { class: 'cnt', text: counts(it) })));
        });
        if (!d.items.length && !d.loading) {
          var msg = !d.roots ? '아직 열어 본 프로젝트 폴더가 없어. 새 작업을 시작하면 그 폴더의 기록이 여기 모여.'
            : !st.total && !bad.length ? '아직 기록이 없어. 문제를 겪으면 [+ 새 기록] 으로 남겨 줘.'
            : st.total ? '조건에 맞는 기록이 없어.' : '';
          if (msg) rows.appendChild(h('div', { class: 'tb-empty', text: msg }));
        }
        if (d.loading && !d.items.length) rows.appendChild(h('div', { class: 'tb-empty', role: 'status', text: 'GitHub 에서 읽는 중이야…' }));
        light.appendChild(rows);
        bad.forEach(function (p) {
          light.appendChild(h('div', { class: 'tb-empty' }, h('span', { class: 'tb-unk-t', text: '? 확인 못 함' }), ' · ' + p.name + ' · 확인 못 함 — ' + p.reason + ' ',
            h('button', { type: 'button', class: 'tb-again', text: '다시 확인', onClick: function () { reload(true); } })));
        });
        if (d.items.length || ok.length) {
          light.appendChild(h('span', { class: 'tb-foot', text: '최근 순 ' + d.items.length + '건을 보는 중' + (d.matched > d.items.length ? ' (맞는 ' + d.matched + '건 중)' : '') +
            (bad.length && ok.length ? ' · ' + ok.map(function (p) { return p.name; }).join(', ') + ' 기록만 읽었어' : '') +
            (st.truncated && st.truncated.length ? ' · ' + st.truncated.join(', ') + ' 은 최근 ' + st.limit + '건만 읽었어' : '') }));
        }
        page.appendChild(light);
      }
      reload(false);
      return { title: function () { return '문제·해결 기록'; }, destroy: function () { state.dead = true; clearTimeout(state.timer); } };
    }

    /* ---------- G-21 한 건 ---------- */
    function itemView(root, repo, number) {
      var state = { dead: false }, page = h('div', { class: 'tb-page' }), title = '문제·해결 기록';
      var compose = { kind: 'candidate', text: '', busy: false, note: '' };
      root.appendChild(page);
      page.appendChild(kit.loadingBox('기록을 읽는 중이야'));

      function post(path, body) { return api('POST', path, body); }
      function afterWrite(res) {
        compose.busy = false;
        compose.note = res.warnings && res.warnings.length ? res.warnings.join(' · ') : '';
        if (!compose.note) compose.text = '';
        fetchItem();
      }
      function failed(e) { compose.busy = false; compose.note = e.message; fetchItem(); }
      function fetchItem() {
        api('GET', '/api/trouble/item' + qs({ repo: repo, number: number })).then(function (d) { if (!state.dead) draw(d); }, function (e) {
          if (state.dead) return;
          clear(page);
          page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '기록 #' + number }), h('h1', { text: e.status === 404 ? '이 기록을 찾지 못했어' : '기록을 읽지 못했어' })));
          page.appendChild(h('section', { class: 'light' }, errBox(e, ''), link('/troubles', { class: 'linkbtn', text: '목록으로' })));
        });
      }
      function summaryRow(label, content) {
        return h('div', { class: 'set tb-set96' }, h('span', { class: 'tb-lm', text: label }), content || h('span', { class: 'tb-lm', text: '' }));
      }
      function draw(d) {
        title = '기록 #' + d.number + ' ' + d.title;
        clear(page);
        var meta = h('div', { class: 'tb-meta' }, chip(d.solved));
        if (d.prNumber) meta.appendChild(h('span', { class: 'tag tb-dk', text: 'PR #' + d.prNumber + (d.prTitle ? ' ' + d.prTitle : '') }));
        meta.appendChild(h('span', { class: 'tag tb-dk', text: '단계 ' + (d.stage || '-') }));
        meta.appendChild(h('span', { class: 'tb-by', text: d.author + ' · ' + dateText(d.createdAt) }));
        page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '기록 #' + d.number + ' · ' + d.project }), h('h1', { text: d.title }), meta));

        var left = h('div', { class: 'tb-left' }), right = h('div', { class: 'tb-right' });
        if (carry.warnings.length) {
          left.appendChild(h('div', { class: 'tb-bad', role: 'status' }, h('span', { class: 'tagx fail', text: '! 일부만 됐어' }), h('span', { text: carry.warnings.join(' · ') })));
          carry.warnings = [];
        }
        left.appendChild(h('div', { class: 'lt' }, h('span', { class: 'eb', text: '요약' }),
          summaryRow('증상', h('span', { class: 'mono tb-sym', text: d.symptom || '(적지 않았어)' })),
          summaryRow('원인', h('span', { text: d.cause || '아직 몰라' })),
          summaryRow('해결 방법', d.solution ? h('span', { text: d.solution }) :
            h('span', { class: 'tb-lm', text: "아직 없어 — 아래 후보 중 하나를 '이걸로 해결' 하면 여기 채워져" }))));
        var hist = h('div', { class: 'lt' }, h('span', { class: 'eb', text: '이력' }));
        d.history.forEach(function (c) {
          var k = KIND[c.kind] || KIND.note, text = h('span');
          if (k.tag) { text.appendChild(h('span', { class: 'tagx ' + k.cls, text: k.tag })); text.appendChild(h('br')); }
          text.appendChild(document.createTextNode(c.text));
          if (c.kind === 'candidate' && !d.solved) {
            text.appendChild(h('div', { class: 'acts' }, h('button', { type: 'button', class: 'pill dark tb-small', text: '이걸로 해결', disabled: compose.busy, onClick: function () {
              compose.busy = true; compose.note = '';
              post('/api/trouble/resolve', { repo: repo, number: Number(number), commentId: c.id }).then(afterWrite, failed);
            } })));
          }
          hist.appendChild(h('div', { class: 'tl' }, h('span', null, h('b', { text: dateText(c.createdAt) }), h('small', { text: c.author })), h('i', { class: 'tb-dot ' + k.dot }), text));
        });
        left.appendChild(hist);

        var kinds = [['try', '시도해 봤어'], ['candidate', '해결 후보'], ['solved', '해결됐어']];
        var ta = h('textarea', { class: 'tb-fld', rows: 3, placeholder: '무엇을 해 봤는지, 어떻게 됐는지 적어 줘. 비밀번호·키는 빼고.', value: compose.text, 'aria-label': '내 이야기' });
        var send = h('button', { type: 'button', class: 'pill dark', text: '올리기' });
        var hint = h('span', { class: 'tb-lm tb-hint', role: 'status', text: compose.note });
        var opts = h('span', { class: 'qo' }, kinds.map(function (o) {
          return h('button', { type: 'button', class: 'qopt', 'aria-pressed': String(compose.kind === o[0]), text: o[1], onClick: function () { compose.text = ta.value; compose.kind = o[0]; draw(d); } });
        }));
        function sync() { compose.text = ta.value; send.disabled = compose.busy || !ta.value.trim(); }
        ta.addEventListener('input', sync);
        send.addEventListener('click', function () {
          sync(); if (send.disabled) return;
          compose.busy = true; compose.note = '';
          post('/api/trouble/comment', { repo: repo, number: Number(number), kind: compose.kind, text: ta.value }).then(afterWrite, failed);
          send.disabled = true;
        });
        sync();
        left.appendChild(h('div', { class: 'lt' }, h('span', { class: 'eb', text: '내 이야기 더하기' }), opts, ta,
          h('div', { class: 'tb-end' }, hint, send)));

        var pr = d.pr;
        var prCard = h('div', { class: 'lt' }, h('span', { class: 'eb', text: '관련 PR' }));
        if (!d.prNumber) prCard.appendChild(h('span', { class: 'tb-lm', text: '이 기록에는 PR 이 없어' }));
        else if (pr && pr.state === 'ok') {
          prCard.appendChild(h('b', { class: 'tb-b6', text: '#' + pr.number + ' ' + pr.title }));
          prCard.appendChild(h('div', { class: 'tb-row' }, h('span', { text: '상태' }), h('span', { class: pr.label === '합쳐짐' ? 'tag ok' : 'tag', text: pr.label })));
          var cx = h('span', { text: pr.checks === 'pass' ? '모두 통과' : pr.checks === 'pending' ? '진행 중' : pr.checks === 'none' ? '없음' : (pr.failed || 1) + '개 실패' });
          if (pr.checks === 'fail') cx.className = 'tb-bad-t';
          prCard.appendChild(h('div', { class: 'tb-row' }, h('span', { text: '검사' }), cx));
          var u = kit.safeHttp(pr.url);
          if (u) prCard.appendChild(h('div', { class: 'acts' }, h('a', { class: 'pill line', href: u, target: '_blank', rel: 'noopener noreferrer', text: 'PR 열기' })));
        } else if (pr && pr.state === 'missing') {
          prCard.appendChild(h('b', { class: 'tb-b6', text: '#' + d.prNumber }));
          prCard.appendChild(h('span', { class: 'tb-lm', text: pr.reason }));
        } else {
          prCard.appendChild(h('b', { class: 'tb-b6', text: '#' + d.prNumber + (d.prTitle ? ' ' + d.prTitle : '') }));
          prCard.appendChild(h('span', { class: 'tb-unk-t', text: '? 확인 못 함' }));
          prCard.appendChild(h('span', { class: 'tb-lm', text: pr ? pr.reason : '' }));
        }
        right.appendChild(prCard);
        var sim = h('div', { class: 'lt' }, h('span', { class: 'eb', text: '비슷한 기록' }));
        if (d.similarOk === false) sim.appendChild(h('span', null, h('span', { class: 'tb-unk-t', text: '? ' }), h('span', { class: 'tb-lm', text: '비슷한 기록을 확인 못 함 — 목록을 읽지 못했어' })));
        else if (!d.similar.length) sim.appendChild(h('span', { class: 'tb-lm', text: '비슷한 기록이 아직 없어' }));
        d.similar.forEach(function (s) {
          sim.appendChild(link(itemHref(s.repo, s.number), { class: 'tb-row tb-simrow' }, h('span', { text: '#' + s.number + ' ' + s.title }), chip(s.solved)));
        });
        right.appendChild(sim);
        var gh = kit.safeHttp(d.url);
        if (gh) right.appendChild(h('a', { class: 'tb-gh', href: gh, target: '_blank', rel: 'noopener noreferrer', text: 'GitHub 에서 보기 ↗' }));
        right.appendChild(h('span', { class: 'tb-note', text: '이 기록은 ' + d.project + ' 이슈 #' + d.number + ' 로 남아 있어. 팀원 모두 볼 수 있어.' }));
        page.appendChild(h('section', { class: 'light' }, h('div', { class: 'tb-split' }, left, right)));
      }
      fetchItem();
      return { title: function () { return title; }, destroy: function () { state.dead = true; } };
    }

    /* ---------- G-22 새 기록 ---------- */
    function newView(root, opts) {
      opts = opts || {};
      var state = { dead: false }, page = h('div', { class: 'tb-page' }), seed = {}, aiSource = '', savedNote = '';
      var f = { repo: '', pr: '', stage: '', title: '', symptom: '', cause: '', solved: false, solution: '' };
      var prInfo = null, prTimer = null, hits = [], checkTimer = null, similarList = [], simTimer = null, busy = false, err = null, simFail = false, draftNote = '';
      var projects = [];
      root.appendChild(page);
      page.appendChild(kit.loadingBox('프로젝트를 읽는 중이야'));

      function applySeed(d) {
        ['repo', 'pr', 'stage', 'title', 'symptom', 'cause', 'solution'].forEach(function (k) { if (d[k]) f[k] = String(d[k]); });
        f.solved = d.solved === true;
      }
      function boot() {
        var saved = null;
        var pend = opts.draft ? api('GET', '/api/trouble/draft' + qs({ id: opts.draft })).then(function (d) { aiSource = (d.source && d.source.title) || ''; applySeed(d); }, function (e) { draftNote = '초안을 읽지 못했어 · ' + (e && e.message || '') + ' (빈 칸에서 시작해)'; }) : Promise.resolve();
        pend.then(function () {
          if (!opts.draft) {
            try { saved = JSON.parse(stored(DRAFT_KEY) || 'null'); } catch (e) { saved = null; }
            if (saved && typeof saved === 'object') { applySeed(saved); savedNote = '나중에 쓰려고 저장해 둔 글을 불러왔어.'; }
          }
          return api('GET', '/api/trouble');
        }).then(function wait(d) {
          if (state.dead) return null;
          if (d.loading && !d.projects.some(function (p) { return p.ok; })) { setTimeout(function () { api('GET', '/api/trouble').then(wait, fail); }, 1200); return null; }
          projects = d.projects.filter(function (p) { return p.ok; });
          if (!projects.some(function (p) { return p.slug === f.repo; })) f.repo = projects[0] ? projects[0].slug : '';
          draw();
          if (f.pr) checkPr();
          recheck(); findSimilar();
          return null;
        }).then(null, fail);
      }
      function fail(e) { if (state.dead) return; clear(page); page.appendChild(h('section', { class: 'light' }, errBox(e, '프로젝트를 '))); }

      function checkPr() {
        clearTimeout(prTimer);
        var n = f.pr.replace('#', '').trim();
        if (!/^\d+$/.test(n) || !f.repo) { prInfo = null; drawPrChip(); return; }
        prInfo = { state: 'loading' }; drawPrChip();
        prTimer = setTimeout(function () {
          api('GET', '/api/trouble/pr' + qs({ repo: f.repo, number: n })).then(function (r) { if (!state.dead && n === f.pr.replace('#', '').trim()) { prInfo = r; drawPrChip(); } },
            function (e) { prInfo = { state: 'unknown', reason: e.message }; drawPrChip(); });
        }, 400);
      }
      function recheck() {
        clearTimeout(checkTimer);
        checkTimer = setTimeout(function () {
          api('POST', '/api/trouble/check', { fields: { title: f.title, symptom: f.symptom, cause: f.cause, solution: f.solution } }).then(function (r) {
            if (state.dead) return;
            hits = r.hits || []; drawBad(); drawMirror(); drawSubmit(); drawPreview();
          }, function (e) { hits = [{ field: '', line: 0, label: '비밀 검사를 못 했어 · ' + e.message, unknown: true }]; drawBad(); drawSubmit(); });
        }, 300);
      }
      function findSimilar() {
        clearTimeout(simTimer);
        simTimer = setTimeout(function () {
          var text = f.title + ' ' + (f.symptom.split('\n')[0] || '');
          if (text.trim().length < 4) { similarList = []; drawSimilar(); return; }
          api('GET', '/api/trouble/similar' + qs({ repo: f.repo, q: text })).then(function (r) { if (!state.dead) { similarList = r.items || []; simFail = r.ok === false; drawSimilar(); } }, function () { similarList = []; simFail = true; drawSimilar(); });
        }, 500);
      }

      var slots = {};
      function slot(name, cls) { return (slots[name] = h('div', { class: cls || '' })); }
      function setField(k, v) { f[k] = v; recheck(); drawPreview(); drawSubmit(); if (k === 'title' || k === 'symptom') findSimilar(); }
      function textarea(k, rows, extra) {
        var ta = h('textarea', { class: 'tb-fld' + (extra ? ' ' + extra : ''), rows: rows, value: f[k], 'aria-label': k });
        function grow() { ta.style.height = ''; if (ta.scrollHeight > ta.clientHeight + 1) ta.style.height = ta.scrollHeight + 2 + 'px'; }
        ta.addEventListener('input', function () { setField(k, ta.value); grow(); });
        setTimeout(grow, 0);
        return ta;
      }
      function setRow(label, hint, content) {
        return h('div', { class: 'set tb-set110' }, h('span', null, label, hint ? [h('br'), h('small', { class: 'tb-lm', text: hint })] : null), content);
      }
      function radios(list, current, onPick) {
        return h('span', { class: 'qo' }, list.map(function (o) {
          return h('button', { type: 'button', class: 'qopt', 'aria-pressed': String(current === o.value), text: o.text, onClick: function () { onPick(o.value); } });
        }));
      }
      function drawPrChip() {
        var s = slots.prchip; if (!s) return; clear(s);
        if (!f.pr.trim() || !prInfo) return;
        if (prInfo.state === 'loading') s.appendChild(h('span', { class: 'tb-lm', text: '확인하는 중…' }));
        else if (prInfo.state === 'ok') s.appendChild(h('span', { class: 'tag ok', text: '✓ #' + prInfo.number + ' ' + prInfo.title + ' · ' + (prInfo.checks === 'fail' ? '검사 실패' : prInfo.label) }));
        else if (prInfo.state === 'missing') s.appendChild(h('span', { class: 'tag', text: '✕ ' + prInfo.reason }));
        else s.appendChild(h('span', { class: 'tag', text: '? 확인 못 함 · ' + prInfo.reason }));
      }
      function lines(k) { return (f[k] || '').split('\n'); }
      function drawMirror() {
        var m = slots.mirror; if (!m) return; clear(m);
        var bad = {};
        hits.filter(function (x) { return x.field === 'symptom'; }).forEach(function (x) { bad[x.line] = 1; });
        lines('symptom').forEach(function (ln, i) {
          if (i) m.appendChild(document.createTextNode('\n'));
          m.appendChild(bad[i + 1] ? h('mark', { text: ln }) : document.createTextNode(ln));
        });
        m.appendChild(document.createTextNode('\n'));
      }
      function drawBad() {
        var s = slots.bad; if (!s) return; clear(s);
        var real = hits.filter(function (x) { return !x.unknown; });
        if (hits.some(function (x) { return x.unknown; })) {
          s.appendChild(h('div', { class: 'tb-empty tb-unk' }, h('span', { class: 'tb-unk-t', text: '? 확인 못 함' }), ' · ' + hits[0].label));
        }
        if (!real.length) return;
        var first = real[0], names = { title: '제목', symptom: '증상', cause: '원인', solution: '해결 방법' };
        s.appendChild(h('div', { class: 'tb-bad' }, h('span', { class: 'tagx fail', text: '✕ 올리기 전에 지워 줘' }),
          h('b', { class: 'tb-b15', text: '비밀번호·키처럼 보이는 글이 있어' }),
          h('span', { class: 'tb-s135', text: (names[first.field] || first.field) + ' ' + first.line + "번째 줄 '" + first.label + "'." + (real.length > 1 ? ' 외 ' + (real.length - 1) + '곳.' : '') + ' 지우고 올려 줘.' }),
          h('div', { class: 'acts' }, h('button', { type: 'button', class: 'pill line', text: real.length > 1 ? '그 줄들 지우기' : '그 줄 지우기', onClick: function () {
            if (real.some(function (x) { return x.field === 'title'; })) f.title = '';
            ['symptom', 'cause', 'solution'].forEach(function (k) {
              var drop = {}; real.filter(function (x) { return x.field === k; }).forEach(function (x) { drop[x.line] = 1; });
              if (Object.keys(drop).length) f[k] = lines(k).filter(function (_, i) { return !drop[i + 1]; }).join('\n');
            });
            hits = []; draw(); recheck();
          } }))));
      }
      function drawSimilar() {
        var s = slots.similar; if (!s) return; clear(s);
        var it = similarList[0];
        if (!it) {
          if (simFail) s.appendChild(h('span', { class: 'tb-s125' }, h('span', { class: 'tb-unk-t', text: '? ' }), '비슷한 기록을 확인 못 함 — 목록을 읽지 못했어'));
          return;
        }
        s.appendChild(h('div', { class: 'lt' }, h('span', { class: 'eb', text: '이미 비슷한 기록이 있어' }), h('b', { class: 'tb-b6', text: '#' + it.number + ' ' + it.title }),
          h('span', { class: 'tb-s125', text: it.author + ' · ' + dateText(it.createdAt) + ' · ' + (it.solved ? '해결됨' : '아직 안 풀림') }),
          h('div', { class: 'acts' }, link(itemHref(it.repo, it.number), { class: 'pill line', text: '거기에 더하기' }))));
      }
      function canSubmit() { return !busy && f.repo && f.stage && f.title.trim() && f.symptom.trim() && !hits.length && (!f.solved || f.solution.trim()); }
      function drawSubmit() {
        var b = slots.submit; if (b) b.disabled = !canSubmit();
        var n = slots.note; if (!n) return;
        var proj = projects.filter(function (p) { return p.slug === f.repo; })[0];
        n.textContent = '올리면 ' + (proj ? proj.name : '') + ' 이슈로 남고 팀원 모두 볼 수 있어.' +
          (hits.some(function (x) { return !x.unknown; }) ? ' 비밀번호 줄을 지우면 올릴 수 있어.' : '');
      }
      function drawPreview() {
        var s = slots.preview; if (!s) return; clear(s);
        var firstLine = lines('symptom')[0] || '', more = lines('symptom').length > 1 || firstLine.length > 60;
        var parts = [h('h3', { text: PREFIX + (f.title || '(제목)') }),
          h('span', { text: [f.pr.trim() ? 'PR #' + f.pr.replace('#', '').trim() : 'PR 없음', '단계 ' + (f.stage || '-'), '상태 ' + (f.solved ? '해결됨' : '아직 안 풀림')].join(' · ') }),
          h('h3', { text: '증상' }), h('span', { class: 'mono', text: (firstLine.slice(0, 60) || '(비어 있음)') + (more ? '…' : '') })];
        if (f.cause.trim()) parts.push(h('h3', { text: '원인' }), h('span', { text: f.cause.trim() }));
        if (f.solution.trim()) parts.push(h('h3', { text: f.solved ? '해결 방법' : '해결 후보' }), h('span', { text: f.solution.trim() }));
        s.appendChild(h('div', { class: 'tb-paper' }, h('div', { class: 'tb-ptool' }, h('span', { text: 'GitHub 에 이렇게 올라가' }), h('span', { class: 'tb-sp' }),
          h('span', { class: 'tag ok', text: 'type:trouble' })), h('div', { class: 'tb-pbody' }, parts)));
      }
      function submit() {
        if (!canSubmit()) return;
        busy = true; err = null; drawSubmit(); drawErr();
        api('POST', '/api/trouble', { repo: f.repo, pr: f.pr.replace('#', '').trim(), stage: f.stage, title: f.title, symptom: f.symptom, cause: f.cause,
          solution: f.solution, solved: f.solved }).then(function (r) {
          store(DRAFT_KEY, null);
          carry.warnings = r.warnings || [];
          go(itemHref(r.repo, r.number));
        }, function (e) {
          busy = false; err = { kind: e.status === 409 ? 'label' : e.status === 504 ? 'unsure' : 'fail', text: e.message }; drawSubmit(); drawErr();
        });
      }
      function drawErr() {
        var s = slots.err; if (!s) return; clear(s);
        if (!err) return;
        if (err.kind === 'unsure') s.appendChild(h('div', { class: 'tb-empty tb-unk', role: 'alert' }, h('span', { class: 'tb-unk-t', text: '? 올렸는지 확인 못 함' }), ' · ' + err.text + ' ',
          h('button', { type: 'button', class: 'tb-again', text: '목록 보기', onClick: function () { go('/troubles'); } })));
        else s.appendChild(h('div', { class: 'tb-bad', role: 'alert' }, h('span', { class: 'tagx fail', text: err.kind === 'label' ? '✕ 라벨이 없어' : err.kind === 'save' ? '✕ 저장하지 않았어' : '✕ 올리지 못했어' }),
          h('span', { class: 'tb-s135', text: err.text }),
          err.kind === 'label' ? h('div', { class: 'acts' }, h('button', { type: 'button', class: 'pill line', text: '다시 시도', onClick: submit })) : null));
      }

      function draw() {
        clear(page);
        if (!projects.length) {
          page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '새 기록' }), h('h1', { text: '기록을 남길 프로젝트가 없어' })));
          page.appendChild(h('section', { class: 'light' }, h('div', { class: 'tb-empty', text: 'GitHub 저장소를 읽은 프로젝트가 없어서 지금은 올릴 수 없어. 목록에서 확인 못 한 이유를 봐 줘.' }), link('/troubles', { class: 'linkbtn', text: '목록으로' })));
          return;
        }
        page.appendChild(h('div', { class: 'ptitle' }, h('span', { class: 'eb', text: '새 기록' }), h('h1', { text: '어떤 문제였어?' })));
        var light = h('section', { class: 'light tb-light' });
        if (aiSource) light.appendChild(h('div', { class: 'ask tb-ai' }, h('span', { class: 'eb', text: 'AI 초안' }), h('span', { class: 'tb-grow', text: "세션 '" + aiSource + "' 대화로 AI 가 미리 채웠어. 틀린 곳만 고쳐 줘." })));
        var prIn = h('input', { class: 'tb-fld tb-pr', value: f.pr, 'aria-label': '관련 PR 번호', inputmode: 'numeric' });
        prIn.addEventListener('input', function () { f.pr = prIn.value; checkPr(); drawPreview(); drawSubmit(); });
        var titleIn = h('input', { class: 'tb-fld', value: f.title, 'aria-label': '제목' });
        titleIn.addEventListener('input', function () { setField('title', titleIn.value); });
        var mirror = slot('mirror', 'tb-mirror'), symTa = textarea('symptom', 3, 'mono tb-symta');
        symTa.addEventListener('input', drawMirror);
        var form = h('div', { class: 'lt' },
          setRow('프로젝트', '', radios(projects.map(function (p) { return { value: p.slug, text: p.name }; }), f.repo, function (v) { f.repo = v; draw(); checkPr(); findSimilar(); })),
          setRow('관련 PR', '', h('span', { class: 'tb-prline' }, prIn, slot('prchip'))),
          setRow('단계', '', radios(STAGES.map(function (s) { return { value: s, text: s }; }), f.stage, function (v) { f.stage = v; draw(); })),
          setRow('제목', '', titleIn),
          setRow('증상', '오류 문구를 붙여 넣어', h('div', { class: 'tb-symwrap' }, mirror, symTa)),
          setRow('원인', '모르면 비워 둬', textarea('cause', 2)),
          setRow('상태', '', radios([{ value: 'yes', text: '해결됐어' }, { value: 'no', text: '아직이야 — 후보만 있어' }], f.solved ? 'yes' : 'no', function (v) { f.solved = v === 'yes'; draw(); })),
          setRow('해결 방법', '또는 후보', textarea('solution', 2)));
        var left = h('div', { class: 'tb-left' }, form, slot('bad'));
        var right = h('div', { class: 'tb-right tb-right280' }, slot('similar'), slot('preview'));
        light.appendChild(h('div', { class: 'tb-split' }, left, right));
        var submitBtn = h('button', { type: 'button', class: 'pill acc tb-submit', text: 'GitHub 에 올리기', onClick: submit });
        slots.submit = submitBtn;
        light.appendChild(slot('err'));
        light.appendChild(h('div', { class: 'tb-actions' }, submitBtn,
          h('button', { type: 'button', class: 'pill line', text: '나중에 쓰기', onClick: function () {
            if (hits.some(function (x) { return !x.unknown; })) { err = { kind: 'save', text: '비밀번호·키처럼 보이는 글이 있어 저장하지 않았어. 그 줄을 지우고 저장해 줘.' }; drawErr(); return; }
            var ok = store(DRAFT_KEY, JSON.stringify(f));
            if (ok) go('/troubles'); else { err = { kind: 'save', text: '이 브라우저에서는 저장할 수 없어서 나중에 쓰기를 못 했어.' }; drawErr(); }
          } }),
          h('button', { type: 'button', class: 'pill line tb-quiet', text: '취소', onClick: function () { go('/troubles'); } })));
        slots.note = h('span', { class: 'tb-note125' });
        light.appendChild(slots.note);
        if (savedNote) light.appendChild(h('span', { class: 'tb-note125', text: savedNote }));
        if (draftNote) light.appendChild(h('span', { class: 'tb-note125', text: draftNote }));
        page.appendChild(light);
        drawPrChip(); drawMirror(); drawBad(); drawSimilar(); drawPreview(); drawSubmit(); drawErr();
      }
      var PREFIX = '[기록] ';
      boot();
      return { title: function () { return '새 기록'; }, destroy: function () { state.dead = true; clearTimeout(prTimer); clearTimeout(checkTimer); clearTimeout(simTimer); } };
    }

    return { listView: listView, itemView: itemView, newView: newView };
  }

  window.BHTrouble = { create: create, dateText: dateText, itemHref: itemHref, counts: counts, STAGES: STAGES };
})();
