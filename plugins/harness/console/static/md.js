/* 결과 보고용 작은 마크다운 렌더러. 모든 글자는 textContent 로만 넣고, 링크는 http(s) 만 허용한다. */
(function () {
  'use strict';

  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function text(s) { return document.createTextNode(s); }

  function safeUrl(u) {
    try {
      var p = new URL(u);
      return (p.protocol === 'http:' || p.protocol === 'https:') ? p.href : null;
    } catch (e) { return null; }
  }

  // 인라인: `코드`, **굵게**, [글](주소)
  var INLINE_SRC = /`([^`\n]+)`|\*\*([^*\n]+?)\*\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g;
  function inline(parent, src) {
    var last = 0, m, INLINE = new RegExp(INLINE_SRC.source, 'g');
    while ((m = INLINE.exec(src))) {
      if (m.index > last) parent.appendChild(text(src.slice(last, m.index)));
      if (m[1] !== undefined) {
        var c = el('code'); c.textContent = m[1]; parent.appendChild(c);
      } else if (m[2] !== undefined) {
        var b = el('strong'); inline(b, m[2]); parent.appendChild(b);
      } else {
        var href = safeUrl(m[4]);
        if (href) {
          var a = el('a'); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
          a.textContent = m[3]; parent.appendChild(a);
        } else {
          parent.appendChild(text(m[3] + ' (' + m[4] + ')'));
        }
      }
      last = INLINE.lastIndex;
    }
    if (last < src.length) parent.appendChild(text(src.slice(last)));
  }

  function render(src) {
    var root = el('div', 'md');
    var lines = String(src == null ? '' : src).replace(/\r\n?/g, '\n').split('\n');
    var i = 0, para = [];
    function flush() {
      if (!para.length) return;
      var p = el('p');
      para.forEach(function (ln, k) { if (k) p.appendChild(el('br')); inline(p, ln); });
      root.appendChild(p); para = [];
    }
    while (i < lines.length) {
      var line = lines[i], m;
      if ((m = /^\s*```/.exec(line))) {
        flush();
        var buf = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++;
        var pre = el('pre'), code = el('code');
        code.textContent = buf.join('\n'); pre.appendChild(code);
        pre.tabIndex = 0; root.appendChild(pre);
        continue;
      }
      if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
        flush();
        var hd = el('h' + Math.min(6, m[1].length + 2), 'md-h');
        inline(hd, m[2].trim()); root.appendChild(hd); i++;
        continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        flush();
        var ordered = /^\s*\d+[.)]\s+/.test(line);
        var list = el(ordered ? 'ol' : 'ul');
        while (i < lines.length && (m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]))) {
          var li = el('li');
          var depth = Math.min(3, Math.floor(m[1].replace(/\t/g, '  ').length / 2));
          if (depth) li.style.marginLeft = (depth * 1.25) + 'em';
          inline(li, m[3]); list.appendChild(li); i++;
        }
        root.appendChild(list);
        continue;
      }
      if ((m = /^>\s?(.*)$/.exec(line))) {
        flush();
        var q = el('blockquote'), qb = [];
        while (i < lines.length && (m = /^>\s?(.*)$/.exec(lines[i]))) { qb.push(m[1]); i++; }
        inline(q, qb.join(' ')); root.appendChild(q);
        continue;
      }
      if (/^\s*$/.test(line)) { flush(); i++; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); root.appendChild(el('hr')); i++; continue; }
      para.push(line.trim()); i++;
    }
    flush();
    return root;
  }

  window.BHMarkdown = { render: render };
})();
