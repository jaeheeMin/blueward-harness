/* 테마와 글자 크기. head 에서 동기로 불러 첫 페인트 전에 적용한다. 테마 표는 이 파일에만 있다. */
(function () {
  'use strict';
  // [bg, surface, text, sec, muted, accent, attn, btn, btnink, light]
  var THEMES = {
    obsidian: ['#0d0d0e', '#131314', '#eeeeec', '#a3a3a0', '#8f8f8c', '#8ab4ff', '#e3b778', '#f4f4f2', '#0d0d0e', 0],
    dracula: ['#282a36', '#21222c', '#f8f8f2', '#c4c7d8', '#a9adc1', '#8be9fd', '#ffb86c', '#bd93f9', '#21222c', 0],
    nord: ['#2e3440', '#3b4252', '#eceff4', '#d8dee9', '#b3bccb', '#88c0d0', '#ebcb8b', '#88c0d0', '#2e3440', 0],
    'tokyo-night': ['#1a1b26', '#24283b', '#c0caf5', '#a9b1d6', '#9199c0', '#7dcfff', '#e0af68', '#7aa2f7', '#1a1b26', 0],
    catppuccin: ['#1e1e2e', '#181825', '#cdd6f4', '#bac2de', '#a6adc8', '#89b4fa', '#f9e2af', '#cba6f7', '#1e1e2e', 0],
    'rose-pine': ['#191724', '#1f1d2e', '#e0def4', '#bcb9d3', '#908caa', '#c4a7e7', '#f6c177', '#ebbcba', '#191724', 0],
    gruvbox: ['#282828', '#1d2021', '#ebdbb2', '#d5c4a1', '#a89984', '#83a598', '#fabd2f', '#ebdbb2', '#282828', 0],
    'one-dark': ['#282c34', '#21252b', '#d7dae0', '#abb2bf', '#9299a7', '#61afef', '#e5c07b', '#61afef', '#21252b', 0],
    'solarized-light': ['#fdf6e3', '#eee8d5', '#073642', '#4f6369', '#566b72', '#1a6fab', '#8a6800', '#073642', '#fdf6e3', 1],
    'github-light': ['#ffffff', '#f6f8fa', '#1f2328', '#59636e', '#59636e', '#0969da', '#9a6700', '#1f883d', '#ffffff', 1]
  };
  var NAMES = {
    obsidian: 'Obsidian', dracula: 'Dracula', nord: 'Nord', 'tokyo-night': 'Tokyo Night',
    catppuccin: 'Catppuccin Mocha', 'rose-pine': 'Rosé Pine', gruvbox: 'Gruvbox Dark',
    'one-dark': 'One Dark', 'solarized-light': 'Solarized Light', 'github-light': 'GitHub Light'
  };
  var KEYS = ['bg', 'surface', 'text', 'sec', 'muted', 'accent', 'attn', 'btn', 'btnink'];
  var SCALES = [['보통', '1.15'], ['크게', '1.3'], ['아주 크게', '1.45']];
  var DEFAULT_SCALE = '1.15';

  function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* 저장이 막혀도 동작한다 */ } }

  function getTheme() { var id = read('bh-theme'); return THEMES[id] ? id : 'obsidian'; }
  function getScale() {
    var v = read('bh-scale');
    for (var i = 0; i < SCALES.length; i++) if (SCALES[i][1] === v) return v;
    return DEFAULT_SCALE;
  }
  function apply(id) {
    var t = THEMES[id] || THEMES.obsidian, r = document.documentElement.style, c = t[9] ? '0,0,0' : '255,255,255';
    for (var i = 0; i < KEYS.length; i++) r.setProperty('--' + KEYS[i], t[i]);
    r.setProperty('--line', 'rgba(' + c + ',.1)');
    r.setProperty('--line2', 'rgba(' + c + ',.18)');
    r.setProperty('--soft', 'rgba(' + c + ',.07)');
    r.colorScheme = t[9] ? 'light' : 'dark';
  }
  function applyScale(v) { document.documentElement.style.zoom = v; }

  window.BH = {
    THEMES: THEMES, NAMES: NAMES, SCALES: SCALES,
    getTheme: getTheme, getScale: getScale,
    setTheme: function (id) { write('bh-theme', id); apply(id); },
    setScale: function (v) { write('bh-scale', v); applyScale(v); },
    read: read, write: write
  };
  apply(getTheme());
  applyScale(getScale());
})();
