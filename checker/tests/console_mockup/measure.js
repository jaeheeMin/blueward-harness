// 선택자 맵 {키: CSS 선택자} 를 받아 키마다 첫 요소의 위치·크기·글자 크기·안쪽 여백·모서리를 CSS px 로 돌려준다.
// 보이지 않는 요소(크기 0)는 null. _layout 에는 가로 스크롤 판단용 너비가 든다.
(function (sels) {
  var num = function (v) { return Math.round(v * 10) / 10; };
  var out = {};
  Object.keys(sels).forEach(function (k) {
    var e = document.querySelector(sels[k]);
    if (!e) { out[k] = null; return; }
    var r = e.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) { out[k] = null; return; }
    var c = getComputedStyle(e);
    // 글자 줄의 세로 가운데: 같은 글이 시안에선 인라인 span(높이 13), 콘솔에선 블록(높이 21)이어도 같은 자리면 같게 나온다.
    var rg = document.createRange(); rg.selectNodeContents(e);
    var tr = rg.getClientRects(), tcy = tr.length ? tr[0].top + tr[0].height / 2 + scrollY : null;
    var px = function (v) { return v.indexOf('%') > 0 ? Math.min(r.width, r.height) * parseFloat(v) / 100 : parseFloat(v) || 0; };
    out[k] = {
      x: num(r.left + scrollX), y: num(r.top + scrollY), w: num(r.width), h: num(r.height),
      tcy: tcy === null ? null : num(tcy), fs: parseFloat(c.fontSize), bg: c.backgroundColor, color: c.color,
      nat: e.tagName === 'IMG' ? e.naturalWidth : null,
      pad: [c.paddingTop, c.paddingRight, c.paddingBottom, c.paddingLeft].map(parseFloat),
      rad: [c.borderTopLeftRadius, c.borderTopRightRadius, c.borderBottomRightRadius, c.borderBottomLeftRadius].map(function (v) { return num(Math.min(px(v), Math.min(r.width, r.height) / 2)); }),
      n: document.querySelectorAll(sels[k]).length
    };
  });
  var d = document.documentElement, b = document.body;
  var opaque = function (c) { return c && c !== 'transparent' && c !== 'rgba(0, 0, 0, 0)'; };
  var app = document.querySelector('#app, .app'), ar = app && app.getBoundingClientRect();
  // 배경이 창 높이 끝까지 덮는지: html·body 배경은 화면 전체(canvas)에 번지고, 아니면 맨 위 앱 상자의 배경이 창 아래끝까지 와야 한다.
  var canvas = opaque(getComputedStyle(d).backgroundColor) || opaque(getComputedStyle(b).backgroundColor);
  var appBottom = ar && opaque(getComputedStyle(app).backgroundColor) ? Math.round(ar.bottom + scrollY) : 0;
  out._layout = { clientW: d.clientWidth, scrollW: d.scrollWidth, docH: d.scrollHeight, innerH: innerHeight,
                  bg: { canvas: canvas, appBottom: appBottom, covers: canvas || appBottom >= innerHeight } };
  return out;
})
