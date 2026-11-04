/* 글자 크기와 저장소 도구. head 에서 동기로 불러 첫 페인트 전에 적용한다. 색은 app.css 의 :root 한 벌뿐이다. */
(function () {
  'use strict';
  var SCALES = [['보통', '1.15'], ['크게', '1.3'], ['아주 크게', '1.45']];
  var DEFAULT_SCALE = '1.15';

  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { console.debug('설정을 저장하지 못했습니다(이번 화면에만 적용)', e); }
  }

  function getScale() {
    var v = read('bh-scale');
    for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) return v;
    return DEFAULT_SCALE;
  }
  function applyScale(v) { document.documentElement.style.zoom = v; }

  window.BH = {
    SCALES: SCALES,
    getScale: getScale,
    setScale: function (v) {
      for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) { write('bh-scale', v); applyScale(v); return; }
    },
    read: read, write: write
  };
  applyScale(getScale());
})();
