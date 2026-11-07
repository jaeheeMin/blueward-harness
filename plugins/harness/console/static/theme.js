/* 글자 크기와 저장소 도구. head 에서 동기로 불러 첫 페인트 전에 적용한다. 색은 app.css 의 :root 한 벌뿐이다. */
(function () {
  'use strict';
  // 시안(가 G-19)대로 작게/보통/크게, 보통 = 배율 없음(#721). 옛 키 bh-scale(보통이 1.15 였다)은 읽지 않아
  // 그대로 두면 모두 새 보통으로 시작한다.
  var KEY = 'bh-zoom';
  var SCALES = [['작게', '0.9'], ['보통', '1'], ['크게', '1.15']];
  var DEFAULT_SCALE = '1';

  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { console.debug('설정을 저장하지 못했습니다(이번 화면에만 적용)', e); }
  }

  function getScale() {
    var v = read(KEY);
    for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) return v;
    return DEFAULT_SCALE;
  }
  function applyScale(v) { document.documentElement.style.zoom = v; }

  window.BH = {
    SCALES: SCALES,
    getScale: getScale,
    setScale: function (v) {
      for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) { write(KEY, v); applyScale(v); return; }
    },
    read: read, write: write
  };
  applyScale(getScale());
})();
