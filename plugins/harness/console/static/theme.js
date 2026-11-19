/* 글자 크기·테마와 저장소 도구. head 에서 동기로 불러 첫 페인트 전에 적용한다. 기본 색(Sauce)은 app.css 의 :root, 다른 테마는 html[data-theme] 아래 파일이 덮는다. */
(function () {
  'use strict';
  // 시안(가 G-19)대로 작게/보통/크게, 보통 = 배율 없음(#721). 옛 키 bh-scale(보통이 1.15 였다)은 읽지 않아
  // 그대로 두면 모두 새 보통으로 시작한다.
  var KEY = 'bh-zoom';
  var SCALES = [['작게', '0.9'], ['보통', '1'], ['크게', '1.15']];
  var DEFAULT_SCALE = '1';

  // 테마(#1013): sauce 가 기본이고 모르는 값은 sauce 로 본다. html[data-theme] 으로 걸고, 바뀌면 bh-theme 이벤트를 쏜다(장면이 새로 고침 없이 붙고 떨어진다).
  var THEME_KEY = 'bh-theme';
  var THEMES = [
    { id: 'sauce', name: 'Sauce', tagline: '기본 · 어두운 바탕에 초록 강조' },
    { id: 'post', name: 'Cozy Office', tagline: '사무실 · 세션이 팀 자리에 앉아 일해요', mode: 'light' }
  ];
  var DEFAULT_THEME = 'sauce';

  // Post 전용 설정(D단계): 효과 강도(bh-fx: 0 차분 · 1 보통 · 2 화려)와 밝기(bh-mode: auto = 테마 기본 · light · dark).
  // 테마 기본 = 시안 applyPrefs 대로 그 테마의 기본 밝기(Post 는 밝게)이고 운영체제 설정은 따르지 않는다.
  // html[data-fx]·html[data-mode] 는 Post 일 때만 걸고 Sauce 에서는 뗀다. 바뀌면 bh-pref 이벤트를 쏜다.
  var FX_KEY = 'bh-fx', MODE_KEY = 'bh-mode';
  var FX = [['0', '차분'], ['1', '보통'], ['2', '화려']];
  var MODES = [['auto', '테마 기본'], ['light', '밝게'], ['dark', '어둡게']];
  var DEFAULT_FX = '1', DEFAULT_MODE = 'auto';

  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { console.debug('설정을 저장하지 못했습니다(이번 화면에만 적용)', e); }
  }
  function pick(list, v, dflt) {
    for (var i = 0; i < list.length; i++) if (list[i][0] === v) return v;
    return dflt;
  }
  var fxNow = pick(FX, read(FX_KEY), DEFAULT_FX), modeNow = pick(MODES, read(MODE_KEY), DEFAULT_MODE);

  function getScale() {
    var v = read(KEY);
    for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) return v;
    return DEFAULT_SCALE;
  }
  function applyScale(v) { document.documentElement.style.zoom = v; }

  function getTheme() {
    // 이미 화면에 건 테마가 먼저다. 저장이 막힌 창에서 고르면 저장소엔 옛 값이 남아 있다.
    var on = document.documentElement.dataset && document.documentElement.dataset.theme;
    for (var j = 0; j < THEMES.length; j++) if (THEMES[j].id === on) return on;
    var v = read(THEME_KEY);
    for (var i = 0; i < THEMES.length; i++) if (THEMES[i].id === v) return v;
    return DEFAULT_THEME;
  }
  function modeOf() {
    if (modeNow !== 'auto') return modeNow;
    for (var i = 0; i < THEMES.length; i++) if (THEMES[i].id === getTheme()) return THEMES[i].mode || 'light';
    return 'light';
  }
  function applyPrefs() {
    var root = document.documentElement;
    if (getTheme() === 'post') { root.setAttribute('data-fx', fxNow); root.setAttribute('data-mode', modeOf()); }
    else { root.removeAttribute('data-fx'); root.removeAttribute('data-mode'); }
  }
  function emit(name, detail) {
    try { if (typeof document.dispatchEvent === 'function' && typeof CustomEvent === 'function') document.dispatchEvent(new CustomEvent(name, { detail: detail })); }
    catch (e) { console.debug('설정 바뀜 알림을 보내지 못했습니다', e); }
  }
  function applyTheme(v) {
    var root = document.documentElement;
    if (root.dataset) root.dataset.theme = v;
    applyPrefs();
    emit('bh-theme', v);
  }

  window.BH = {
    SCALES: SCALES,
    THEMES: THEMES,
    getTheme: getTheme,
    setTheme: function (v) {
      for (var i = 0; i < THEMES.length; i++) if (THEMES[i].id === v) { write(THEME_KEY, v); applyTheme(v); return; }
    },
    FX: FX, MODES: MODES,
    getFx: function () { return fxNow; },
    setFx: function (v) { if (pick(FX, v, null) === null) return; fxNow = v; write(FX_KEY, v); applyPrefs(); emit('bh-pref', 'fx'); },
    getMode: function () { return modeNow; },
    modeOf: modeOf,  // 지금 실제로 걸린 밝기: 'light' | 'dark'
    setMode: function (v) { if (pick(MODES, v, null) === null) return; modeNow = v; write(MODE_KEY, v); applyPrefs(); emit('bh-pref', 'mode'); },
    getScale: getScale,
    setScale: function (v) {
      for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) { write(KEY, v); applyScale(v); return; }
    },
    read: read, write: write
  };
  applyScale(getScale());
  applyTheme(getTheme());
})();
