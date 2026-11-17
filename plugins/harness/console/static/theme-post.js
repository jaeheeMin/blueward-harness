/* Post(우체국) 테마의 장면. 홈 위쪽 띠에 라인아트 부품(static/post/)을 manifest 좌표대로 쌓는다.
   창구 다섯 개가 순서의 다섯 단계이고, 세션은 그 앞에 선 손님이다. 장식이 아니라 세션 상태를 그대로 옮긴다
   (내 차례 = 손을 흔든다 · 막힘/확인 못 함 = 머뭇거린다 · 일하는 중 = 걷는다 · 승인 기다림 = 선다 · 끝 = 손을 든다).
   Post 일 때만 그린다. 테마가 바뀌면 bh-theme 이벤트로 새로 고침 없이 붙고 떨어진다. prefers-reduced-motion 이면 멈춘 한 장면이다. */
(function () {
  'use strict';
  var BASE = '/static/post/';
  var VW = 1600, VH = 240, PLAQ = 50;
  var STEP = [
    { name: '요구사항', hint: '무엇을 만들지 쓰기' }, { name: '개발 Spec', hint: '어떻게 만들지 설계' },
    { name: '개발', hint: 'AI가 만드는 중' }, { name: '검토', hint: '팀 승인 받기' }, { name: '합쳐짐', hint: '끝, 반영됨' }
  ];
  var MAX_PEOPLE = 14;
  var PL = window.BHPostLogic;  // 손님 고정 배정·상태·창구 규칙(post-logic.js). 장면과 모든 화면의 아바타가 같은 함수를 쓴다
  var LABEL = PL.LABEL, GLYPH = PL.GLYPH;

  var manifest = null, loading = null;
  function loadManifest(cb) {
    if (window.BWPOST) { manifest = window.BWPOST; return cb(true); }
    if (loading) return loading.push(cb);
    loading = [cb];
    var sc = document.createElement('script');
    sc.src = BASE + 'manifest.js';
    function done(ok) { manifest = ok ? window.BWPOST : null; var l = loading; loading = null; l.forEach(function (f) { f(!!manifest); }); }
    sc.onload = function () { done(!!window.BWPOST); };
    sc.onerror = function () { console.debug('우체국 장면 부품 목록을 읽지 못했습니다'); done(false); };
    document.head.appendChild(sc);
  }

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function reducedMotion() { return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches; }
  function isPost() { return !!(window.BH && window.BH.getTheme && window.BH.getTheme() === 'post'); }
  /* 효과 강도(theme.js): '0' 차분 · '1' 보통 · '2' 화려. 움직이는지는 anim = fx !== '0' && !reduced(가이드 2.7) */
  function fxLevel() { return window.BH && window.BH.getFx ? window.BH.getFx() : '1'; }
  function calm() { return fxLevel() === '0'; }
  function animOn() { return !calm() && !reducedMotion(); }

  /* 장면 하나(띠 + 창구 이름표). list 는 [{ id, title, state, station, tag }]. */
  function Scene(host, opts) {
    var M = manifest, L = M.layout, F = M.files, P = {};
    L.people.forEach(function (q) { P[q.name] = q; });
    var anim = !reducedMotion(), rich = anim && fxLevel() === '2';  // 차분(0)은 장면 자체를 그리지 않는다(attach). 움직임 줄이기는 멈춘 한 장면
    var anims = [], peopleSig = null, raf = 0, alive = true, ro = null;
    var wrap = el('div', 'po'), band = el('div', 'po-band'), plaq = el('div', 'po-plaq');
    var peopleLayer = el('div', 'po-people');
    wrap.setAttribute('role', 'img');
    wrap.appendChild(band); wrap.appendChild(plaq);
    host.appendChild(wrap);

    function put(file, x, y, op, parent) {
      var e = F[file]; if (!e) return el('i');
      var img = new Image(e[0], e[1]); img.src = BASE + file; img.alt = ''; img.decoding = 'async';
      img.style.cssText = 'left:' + (x - e[2]) + 'px;top:' + (y - e[3]) + 'px;width:' + e[0] + 'px;height:' + e[1] + 'px;opacity:' + (op == null ? 1 : op);
      (parent || band).appendChild(img); return img;
    }
    function flip(list, per, ph) { anims.push(function (t) { var k = Math.floor(t / per + (ph || 0)) % list.length; list.forEach(function (im, i) { im.style.opacity = i === k ? 1 : 0; }); }); }

    /* 바뀌지 않는 배경·창구·소품 */
    put('bg/wall.svg', 800, 120);
    // 화려(fx=2)에서만 창문마다 구름이 4초 주기로 바뀐다(창문 사이 0.37 위상차)
    L.windows.forEach(function (w, i) {
      var wa = put('bg/window-a.svg', w.x, w.y);
      if (rich) flip([wa, put('bg/window-b.svg', w.x, w.y, 0)], (L.poseTiming && L.poseTiming.window) || 4, i * .37);
    });
    var ck = L.clock; put(ck.face, ck.x, ck.y);
    var hh = put(ck.hour, ck.x, ck.y), mm = put(ck.minute, ck.x, ck.y);
    [hh, mm].forEach(function (im, i) { var e = F[i ? ck.minute : ck.hour]; im.style.transformOrigin = e[2] + 'px ' + e[3] + 'px'; });
    hh.style.transform = 'rotate(105deg)'; mm.style.transform = 'rotate(252deg)';
    if (anim) anims.push(function (t) { mm.style.transform = 'rotate(' + (252 + t * 6) + 'deg)'; hh.style.transform = 'rotate(' + (105 + t * .5) + 'deg)'; });
    var cv = L.conveyor; put(cv.rail, cv.x, cv.y);
    var cf = cv.frames.map(function (f, i) { return put(f, cv.x, cv.y, i ? 0 : 1); }); if (anim) flip(cf, cv.framePeriod);
    var lt = [put(cv.letters, cv.x, cv.y), put(cv.letters, cv.x + cv.lettersTile, cv.y)];
    if (anim) anims.push(function (t) { var off = (t * cv.lettersSpeed) % cv.lettersTile, e = F[cv.letters]; lt[0].style.left = (cv.x - e[2] - off) + 'px'; lt[1].style.left = (cv.x - e[2] + cv.lettersTile - off) + 'px'; });
    L.lights.forEach(function (l) { put(l.off, l.x, l.y); put(l.on, l.x, l.y); });
    put('bg/floor.svg', 800, 120);
    L.signs.forEach(function (s, i) {
      put(s.file, s.x, s.y);
      var d = el('span', 'po-sign', (i + 1) + '  ' + STEP[i].name);
      d.style.cssText = 'left:' + s.face.x + 'px;top:' + s.face.y + 'px;width:' + s.face.w + 'px;height:' + s.face.h + 'px';
      band.appendChild(d);
    });
    L.stations.forEach(function (st) {
      put(st.base, st.x, st.y);
      if (st.id === 'review') {
        var cl = L.clerk, cp = cl.poses.map(function (f, i) { return put(f, cl.x, cl.y, i ? 0 : 1); });
        if (anim) anims.push(function (t) { var k = Math.floor(t / cl.stampPeriod) % 4; cp[0].style.opacity = k === 0 || k === 3 ? 1 : 0; cp[1].style.opacity = k === 1 ? 1 : 0; cp[2].style.opacity = k === 2 ? 1 : 0; });
        put(st.overlays[0], st.x, st.y);
      } else if (st.overlays.length === 2) {
        var ov = st.overlays.map(function (f, i) { return put(f, st.x, st.y, i ? 0 : 1); });
        if (anim) flip(ov, st.id === 'workshop' ? (L.poseTiming.gears || .3) : (L.poseTiming.mailIn || .4));
      }
    });
    L.props.forEach(function (q) { put(q.file, q.x, q.y); });
    band.appendChild(peopleLayer);

    /* 세션 손님. 바뀐 것이 있을 때만 이 층을 다시 만든다. */
    var peopleAnims = [];
    function drawPeople(list) {
      while (peopleLayer.firstChild) peopleLayer.removeChild(peopleLayer.firstChild);
      peopleAnims = [];
      var per = [0, 0, 0, 0, 0], ln = L.lanes.front;
      list.slice(0, MAX_PEOPLE).forEach(function (s, i) {
        var k = Math.max(0, Math.min(4, s.station | 0)), j = per[k]++, sta = L.stations[k], info = P[PL.personOf(s.id)] || P[PL.WHO[0]];
        var x0 = sta.standX + (j % 2 ? -1 : 1) * 112 * Math.ceil(j / 2), w = info.w, h = info.h;  // 0, -112, 112, -224, 224 … 겹치지 않게 번갈아 선다
        var a = el('a', 'po-s b-' + s.state);
        a.href = '/s/' + encodeURIComponent(s.id); a.tabIndex = -1;
        a.addEventListener('click', function (ev) {
          if (ev.defaultPrevented || ev.button || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
          if (opts.onNavigate) { ev.preventDefault(); opts.onNavigate(a.getAttribute('href')); }
        });
        a.style.cssText = 'left:' + x0 + 'px;top:' + (ln.y - h) + 'px;width:' + w + 'px;height:' + h + 'px';
        var dir = info.name + '/';
        function img(n, op) { var im = new Image(w, h); im.alt = ''; im.src = BASE + 'people/' + dir + n + '.svg'; im.style.opacity = op; a.appendChild(im); return im; }
        function pf(list2, per2, ph) { if (anim) peopleAnims.push(function (t) { var q = Math.floor(t / per2 + ph) % list2.length; list2.forEach(function (im, n) { im.style.opacity = n === q ? 1 : 0; }); }); }
        var st = s.state;
        if (st === 'turn') pf([img('ask-1', 1), img('ask-2', 0)], L.poseTiming.ask || .35, i * .3);
        else if (st === 'blocked' || st === 'unk') pf([img('stuck-1', 1), img('stuck-2', 0)], L.poseTiming.stuck || .5, i * .3);
        else if (st === 'wait') img('wait', 1);
        else if (st === 'done') img('done', 1);
        else if (st === 'run') {
          var rf = [1, 2, 3, 4].map(function (n) { return img('walk-' + n, n === 1 ? 1 : 0); }), lf = [1, 2, 3, 4].map(function (n) { return img('walk-' + n + '-left', 0); });
          var span = 46, cyc = 4 * span / info.speed;
          if (anim) peopleAnims.push(function (t) {
            var u = ((t + i) % cyc) / cyc, right = u < .5, d = right ? u * 2 : 2 - u * 2, f = Math.floor((t / info.period) * 4) % 4;
            a.style.left = (x0 - span + d * 2 * span) + 'px';
            rf.forEach(function (im, q) { im.style.opacity = right && q === f ? 1 : 0; }); lf.forEach(function (im, q) { im.style.opacity = !right && q === f ? 1 : 0; });
          });
        } else img('walk-1', 1);
        var tag = el('span', 'po-tag');
        if (GLYPH[st]) tag.appendChild(el('i', null, GLYPH[st]));
        tag.appendChild(el('b', null, st === 'turn' ? '내 차례!' : s.tag));
        tag.appendChild(el('small', null, st === 'turn' ? s.tag : LABEL[st]));
        a.appendChild(tag);
        peopleLayer.appendChild(a);
      });
    }
    function drawPlaque(list) {
      while (plaq.firstChild) plaq.removeChild(plaq.firstChild);
      var cnt = [0, 0, 0, 0, 0];
      list.forEach(function (s) { cnt[Math.max(0, Math.min(4, s.station | 0))]++; });
      L.stations.forEach(function (st, i) {
        var sp = el('span'); sp.style.setProperty('--x', st.x);
        sp.appendChild(el('b', null, (i + 1) + ' ' + STEP[i].name + ' · ' + cnt[i]));
        sp.appendChild(el('small', null, STEP[i].hint));
        plaq.appendChild(sp);
      });
    }
    function describe(list) {
      var shown = list.length, cut = shown > MAX_PEOPLE ? '(그림에는 ' + MAX_PEOPLE + '개만 그렸어)' : '';
      var turn = list.filter(function (s) { return s.state === 'turn'; }).length;
      wrap.setAttribute('aria-label', '우체국 장면. 세션 ' + shown + '개가 다섯 창구(요구사항 · 개발 Spec · 개발 · 검토 · 합쳐짐) 앞에 서 있어' + cut + (turn ? ' · 내 차례 ' + turn + '개' : '') + '. 같은 내용이 왼쪽 세션 목록에 있어.');
    }

    function fit() {
      var W = host.clientWidth || VW, s = Math.max(W / VW, W < 700 ? .55 : 0);
      wrap.style.setProperty('--s', s);
      band.style.transform = 'scale(' + s + ')';
      wrap.style.height = (VH * s + PLAQ) + 'px'; host.style.height = (VH * s + PLAQ) + 'px';
      wrap.style.width = Math.max(W, VW * s) + 'px';
      host.style.overflowX = W < VW * s - 1 ? 'auto' : 'hidden';
    }
    fit();
    if (typeof ResizeObserver === 'function') { ro = new ResizeObserver(fit); ro.observe(host); }

    var t0 = performance.now();
    function frame(now) {
      if (!alive) return;
      var t = (now - t0) / 1000;
      for (var q = 0; q < anims.length; q++) anims[q](t);
      for (q = 0; q < peopleAnims.length; q++) peopleAnims[q](t);
      raf = requestAnimationFrame(frame);
    }
    function onVis() { cancelAnimationFrame(raf); if (!document.hidden && alive && anim) raf = requestAnimationFrame(frame); }
    document.addEventListener('visibilitychange', onVis);

    return {
      update: function (list) {
        var sig = list.map(function (s) { return s.id + '|' + s.state + '|' + s.station + '|' + s.tag; }).join(';');
        if (sig !== peopleSig) { peopleSig = sig; drawPeople(list); drawPlaque(list); }
        describe(list);
        if (!anim) { anims.forEach(function (f) { f(.2); }); peopleAnims.forEach(function (f) { f(.2); }); }
      },
      start: function () { if (anim) raf = requestAnimationFrame(frame); },
      destroy: function () {
        alive = false; cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVis);
        if (ro) ro.disconnect();
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
        host.style.height = ''; host.style.overflowX = '';
      }
    };
  }

  /* 홈이 부른다. host 는 빈 div. 테마가 post 일 때만 장면이 있고, 테마가 바뀌면 붙거나 떨어진다.
     opts: { list(): 장면에 올릴 세션 목록, onNavigate(href), onFocus(f) — 사무실 장면이 메모 자리를 알린다 }. office(window.BHOfficeScene)를 주면 우체국 장면 대신 사무실 장면을 붙인다. */
  // 사무실 번들의 작은 창(Document PiP)은 번들 안에 닫기 API 가 없어 브라우저 API 로 닫는다(PiP 는 이 장면만 쓴다)
  function closePip() {
    try { var w = window.documentPictureInPicture && window.documentPictureInPicture.window; if (w) w.close(); } catch (e) { console.warn('작은 창(PiP)을 닫지 못함', e); }
  }

  function attach(host, opts, office) {
    var scene = null, dead = false, reduce = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
    var waitRo = null, wantFocus = null;  // wantFocus: 메모가 보여 달라고 한 세션(장면이 아직 안 붙었거나 다시 붙을 때 붙은 뒤에 준다)
    function drop() { if (waitRo) { waitRo.disconnect(); waitRo = null; } if (scene) { scene.destroy(); scene = null; } host.classList.remove('is-office'); host.hidden = true; }
    function sync() {
      if (dead) return;
      if (!isPost() || calm()) { closePip(); return drop(); }  // 차분 = 장면을 그리지 않고 세션 목록(post-home.js)이 대신한다. 작은 창(PiP)도 함께 닫는다(홈을 떠날 때의 destroy 는 PiP 를 살려 둔다)
      if (scene || waitRo) return;
      host.hidden = false;
      if (office) {  // AI 오피스 장면(post/office/office-post.js): 부품 목록을 안 받고 바로 붙는다. 팀 요약 줄은 post-home.js 가 그린다
        host.classList.add('is-office');
        // 칸이 숨겨져 폭이 0 일 때 붙이면 장면이 scale(Infinity) 로 그려져 콘솔 오류가 난다 — 폭이 생길 때까지 기다렸다 붙인다
        var mount = function () {
          if (dead || scene || !host.clientWidth) return;
          if (waitRo) { waitRo.disconnect(); waitRo = null; }
          var o = office.attach(host, opts);
          scene = { update: function () { o.update(); }, destroy: function () { o.destroy(); }, focus: function (id) { if (typeof o.focus === 'function') o.focus(id); } };  // 옛 번들은 focus 가 없다
          if (wantFocus) scene.focus(wantFocus);
        };
        if (!host.clientWidth && typeof ResizeObserver === 'function') { if (!waitRo) { waitRo = new ResizeObserver(mount); waitRo.observe(host); } } else mount();
        return;
      }
      loadManifest(function (ok) {
        if (dead || scene || !isPost() || calm()) return;
        if (!ok) { host.hidden = true; return; }
        scene = Scene(host, opts);
        scene.update(opts.list()); scene.start();
      });
    }
    function onTheme() { sync(); }
    function onMotion() { drop(); sync(); }  // 움직임·효과 강도 설정이 바뀌면 다시 만든다
    function onPref(ev) { if (ev && ev.detail === 'fx') onMotion(); }
    document.addEventListener('bh-theme', onTheme);
    document.addEventListener('bh-pref', onPref);
    if (reduce && reduce.addEventListener) reduce.addEventListener('change', onMotion);
    host.hidden = true;
    sync();
    return {
      update: function () { if (scene) scene.update(opts.list()); },
      focus: function (id) { wantFocus = id || null; if (scene && scene.focus) scene.focus(wantFocus); },  // 사무실 장면이 그 세션의 주인공을 보여 준다(우체국 장면은 아무것도 안 한다)
      destroy: function () {
        dead = true; document.removeEventListener('bh-theme', onTheme); document.removeEventListener('bh-pref', onPref);
        if (reduce && reduce.removeEventListener) reduce.removeEventListener('change', onMotion);
        drop();
      }
    };
  }

  /* 세션 목록(사이드·접힌 레일·차분 목록)의 작은 아바타(#1066): 우체국 직원 그림을 30×36 칸에 잘라 넣으면 손 흔드는 팔·소품이 겹쳐 팔이 여러 개처럼 보인다.
     그래서 'sm' 는 그림 대신 제목 첫 글자를 둥근 칸에 쓴다(홈 "내 세션" 목록의 글자 아바타와 같은 모양). 이름은 opts.name 으로 받고,
     app.js 의 사이드 목록은 이름을 안 넘기므로(아바타만 부른다) 같은 줄의 제목에서 읽어 채운다(fillLetters). 큰 그림(카드 머리·세션 머리)은 잘리지 않으니 그대로다. */
  function letterOf(name) { return Array.from(String(name || '').trim())[0] || ''; }
  function nameAround(av) {
    var row = av.closest('.po-si'), n = row && row.querySelector('.sinfo .n');
    if (n) return n.textContent;
    var rail = av.closest('.rail-ring');  // 접힌 레일 링크의 title 은 "이름 · 상태"
    return rail ? rail.getAttribute('title') || '' : '';
  }
  function fillLetters() {
    var list = document.querySelectorAll('.po-av-letter:not([data-fixed])');
    for (var i = 0; i < list.length; i++) { var c = letterOf(nameAround(list[i])); if (list[i].textContent !== c) list[i].textContent = c; }
  }
  var letterWatch = null;
  function watchLetters() {
    if (letterWatch || typeof MutationObserver !== 'function' || !document.body) return;
    letterWatch = new MutationObserver(fillLetters);  // 글자를 쓰는 것도 변경이지만 같은 값이면 다시 쓰지 않아 한 번에 멈춘다
    letterWatch.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['title'] });
  }
  function letterAvatar(name) {
    var span = el('span', 'po-av po-av-letter sm', letterOf(name));
    span.setAttribute('aria-hidden', 'true');
    if (name) span.setAttribute('data-fixed', '1'); else watchLetters();
    return span;
  }

  /* 세션 손님 아바타(span.po-av). 장면의 손님과 같은 사람이다(personOf). 자세는 상태로 정한다(내 차례 = 편지를 흔듦 · 막힘/확인 못 함 = 머리를 긁음 · 승인 기다림 = 앉음 · 끝 = 엄지 척 · 그 밖 = 서 있음).
     opts.size: 'sm'(글자 아바타, opts.name 의 첫 글자 — 아래 letterAvatar) · 'lg'(88×104, 세션 머리) · 생략(34×40, 카드 머리). Post 가 아니어도 만들 수 있지만 보이는 것은 Post 일 때뿐이다(CSS). */
  function avatar(sessionId, state, opts) {
    var size = opts && opts.size;
    if (size === 'sm') return letterAvatar(opts.name);
    var who = PL.personOf(sessionId), pose = PL.poseOf(state), tone = PL.toneOf(state);
    var span = el('span', 'po-av' + (tone ? ' po-av-' + tone : '') + (size ? ' ' + size : ''));
    span.setAttribute('aria-hidden', 'true');
    function img(n, cls) { var im = new Image(); im.alt = ''; im.decoding = 'async'; im.src = BASE + 'people/' + who + '/' + n + '.svg'; if (cls) im.className = cls; span.appendChild(im); }
    img(pose === 'ask' ? 'ask-1' : pose === 'stuck' ? 'stuck-1' : pose === 'walk' ? 'walk-1' : pose);
    if (pose === 'ask' && animOn()) img('ask-2', 'po-av-b');  // 두 장을 번갈아 편지를 흔든다. 움직임 줄이기·차분이면 한 장
    return span;
  }

  /* 다른 화면이 쓰는 것: personOf·stateOf·stationOf(post-logic.js 와 같은 함수), avatar, isPost, STEP(창구 이름·풀이) */
  window.BHPostScene = { attach: attach, STEP: STEP, avatar: avatar, isPost: isPost, calm: calm, animOn: animOn, personOf: PL.personOf, stateOf: PL.stateOf, stationOf: PL.stationOf, poseOf: PL.poseOf, LABEL: PL.LABEL, GLYPH: PL.GLYPH };
})();
