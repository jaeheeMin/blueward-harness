/* 이어서 요청 입력칸(여러 줄 + 첨부) (#860). 한도는 서버 attachments.py 와 같다. 서버가 한 번 더 검사한다.
   붙여 넣기·끌어 놓기·파일 고르기로 이미지(png·jpg·gif·webp)·PDF 를 붙이고, 칩으로 보여 주고, 빼기(×)를 둔다.
   미리보기용 그림(data:)은 이 탭 메모리에만 두고, 서버 대화 기록에는 이름·형식·크기만 간다. */
(function (root) {
  'use strict';

  var MB = 1 << 20;
  var MAX_COUNT = 5, MAX_IMAGE = 5 * MB, MAX_PDF = 20 * MB, MAX_TOTAL = 20 * MB, MAX_FIELD_PX = 132;
  var BY_EXT = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', pdf: 'application/pdf' };
  var TYPES = { 'image/png': 1, 'image/jpeg': 1, 'image/gif': 1, 'image/webp': 1, 'application/pdf': 1 };
  var PLACEHOLDER = '(첨부만 보냄)';  // 글 없이 첨부만 보낸 내 말을 서버가 대화에 남기는 글
  var thumbs = {};  // 이름|크기 → 미리보기 data URL (이 탭 메모리만)

  function typeOf(file) {
    var t = String(file.type || '').toLowerCase();
    if (TYPES[t]) return t;
    var m = /\.([a-z0-9]+)$/i.exec(String(file.name || ''));
    return (m && BY_EXT[m[1].toLowerCase()]) || '';
  }
  function sizeText(n) { return n >= MB ? (Math.round(n / MB * 10) / 10) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB'; }
  function isPdf(type) { return type === 'application/pdf'; }

  // 후보 파일 하나를 지금 목록(cur: [{size}])에 더해도 되는지. 안 되면 한 줄 이유를 돌려준다. 되면 ''.
  function whyNot(file, cur) {
    var type = typeOf(file), name = file.name || '첨부';
    if (!type) return name + ': 이미지(png·jpg·gif·webp)와 PDF 만 붙일 수 있어.';
    if (cur.length >= MAX_COUNT) return '첨부는 한 번에 ' + MAX_COUNT + '개까지야.';
    var limit = isPdf(type) ? MAX_PDF : MAX_IMAGE;
    if (file.size > limit) return name + ': 너무 커(' + sizeText(file.size) + '). ' + (isPdf(type) ? 'PDF 는 20MB' : '이미지는 한 장에 5MB') + '까지야.';
    if (!file.size) return name + ': 빈 파일이야.';
    var total = file.size;
    cur.forEach(function (c) { total += c.size; });
    if (total > MAX_TOTAL) return '첨부 합계가 너무 커. 합쳐서 20MB 까지야.';
    return '';
  }

  // Enter 만 보내기. Shift+Enter 는 줄바꿈, 한글 조합 중(isComposing·229) Enter 는 조합을 끝내는 키라서 보내지 않는다.
  function enterSends(e) { return e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229; }

  function fileList(dt) {
    var out = [];
    if (!dt) return out;
    if (dt.files && dt.files.length) { for (var i = 0; i < dt.files.length; i++) out.push(dt.files[i]); return out; }
    if (dt.items) {  // 붙여 넣은 그림은 files 가 비고 items 에만 있는 브라우저가 있다
      for (var j = 0; j < dt.items.length; j++) {
        if (dt.items[j].kind === 'file' && dt.items[j].getAsFile) { var f = dt.items[j].getAsFile(); if (f) out.push(f); }
      }
    }
    return out;
  }

  function chipFor(h, a, onRemove) {
    var thumb = thumbs[a.name + '|' + a.size];
    var isImg = String(a.type || a.media_type || '').indexOf('image/') === 0;
    return h('span', { class: 'attach-chip', 'data-attach': a.name },
      isImg && thumb ? h('img', { class: 'attach-thumb', src: thumb, alt: a.name }) : h('span', { class: 'attach-kind', text: isImg ? '그림' : 'PDF' }),
      h('span', { class: 'attach-name', text: a.name }),
      a.size ? h('span', { class: 'attach-size', text: sizeText(a.size) }) : null,
      onRemove ? h('button', { type: 'button', class: 'attach-x', 'aria-label': '빼기: ' + a.name, text: '×', onClick: onRemove }) : null);
  }

  // 대화 판에 내 말과 함께 보이는 첨부(빼기 없음). attachments: 서버 기록 [{name, type, size}]
  function chatChips(h, attachments) {
    var list = (Array.isArray(attachments) ? attachments : []).filter(function (a) { return a && typeof a === 'object' && a.name; });
    if (!list.length) return null;
    return h('div', { class: 'attach-row', 'data-chat-attach': '1' }, list.map(function (a) { return chipFor(h, a, null); }));
  }

  function composer(h, opts) {
    var items = [], enabled = true, pendingReads = 0, noteText = '';
    var field = h('textarea', { id: opts.id, class: 'comp-in', rows: '1', placeholder: opts.placeholder, autocomplete: 'off',
      onInput: function (e) { grow(); noteText = ''; paint(); if (opts.onInput) opts.onInput(e.target.value); },
      onKeydown: function (e) {
        if (!enterSends(e) || (opts.isBlocked && opts.isBlocked())) return;
        e.preventDefault();
        opts.onSend();
      },
      onPaste: function (e) {
        var files = fileList(e.clipboardData);
        if (!files.length) return;  // 글 붙여 넣기는 그대로 둔다
        e.preventDefault();
        add(files);
      } });
    var chips = h('div', { class: 'attach-box', 'data-attach-box': '1', hidden: true });
    var input = h('input', { type: 'file', class: 'sr-only', multiple: true, accept: 'image/png,image/jpeg,image/gif,image/webp,application/pdf', tabindex: '-1', 'aria-hidden': 'true',
      onChange: function (e) { add(fileList(e.target)); e.target.value = ''; } });
    var btn = h('button', { type: 'button', class: 'attach-btn', 'aria-label': '이미지나 PDF 붙이기', title: '이미지·PDF 붙이기 (붙여 넣기·끌어 놓기도 돼)', text: '첨부', onClick: function () { input.click(); } });
    var pick = h('span', { class: 'attach-pick' }, btn, input);

    function grow() {
      if (!field.style) return;
      field.style.height = 'auto';
      var need = field.scrollHeight || 0;
      field.style.height = (need ? Math.min(need, MAX_FIELD_PX) : 20) + 'px';
      field.style.overflowY = need > MAX_FIELD_PX ? 'auto' : 'hidden';
    }
    function paint() {
      var kids = items.map(function (a) { return chipFor(h, a, function () { items = items.filter(function (x) { return x !== a; }); noteText = ''; paint(); }); });
      if (noteText) kids.push(h('p', { class: 'attach-note', role: 'status', 'data-attach-note': '1', text: noteText }));
      while (chips.firstChild) chips.removeChild(chips.firstChild);
      kids.forEach(function (k) { chips.appendChild(k); });
      chips.hidden = !kids.length;
    }
    function add(files) {
      if (!enabled) { noteText = '터미널에서 연 세션에는 첨부를 보낼 수 없어.'; paint(); return; }
      var bad = [], tooMany = 0;
      files.forEach(function (file) {
        var why = whyNot(file, items);
        if (why) { bad.push(why); return; }
        var a = { name: file.name || (typeOf(file).indexOf('image/') === 0 ? '붙여 넣은 그림' : '첨부'), type: typeOf(file), size: file.size, data: '' };
        items.push(a);
        pendingReads++;
        var rd = new root.FileReader();
        rd.onload = function () {
          var url = String(rd.result || ''), at = url.indexOf(',');
          a.data = at >= 0 ? url.slice(at + 1) : '';
          if (a.type.indexOf('image/') === 0 && a.data) thumbs[a.name + '|' + a.size] = url;
          pendingReads--; paint();
        };
        rd.onerror = function () {
          items = items.filter(function (x) { return x !== a; });
          pendingReads--; noteText = (a.name) + ': 파일을 읽지 못했어.'; paint();
        };
        rd.readAsDataURL(file);
      });
      if (bad.length) noteText = bad[0] + (bad.length > 1 ? ' (외 ' + (bad.length - 1) + '개도 못 붙였어)' : '');
      paint();
    }
    function bindDrop(el) {
      el.addEventListener('dragover', function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0) e.preventDefault(); });
      el.addEventListener('drop', function (e) {
        var files = fileList(e.dataTransfer);
        if (!files.length) return;
        e.preventDefault();
        add(files);
      });
    }
    grow(); paint();
    return {
      field: field, chips: chips, pick: pick, add: add, bindDrop: bindDrop, grow: grow,
      count: function () { return items.length; },
      busy: function () { return pendingReads > 0; },
      // 서버로 보낼 첨부. base64 를 다 읽은 것만.
      payload: function () { return items.filter(function (a) { return a.data; }).map(function (a) { return { name: a.name, media_type: a.type, data: a.data }; }); },
      meta: function () { return items.map(function (a) { return { name: a.name, type: a.type, size: a.size }; }); },
      reset: function () { items = []; noteText = ''; field.value = ''; grow(); paint(); },
      note: function (t) { noteText = t || ''; paint(); },
      // 터미널에서 연 세션은 첨부를 보낼 수 없다: 단추를 감추고 붙여 넣기·끌어 놓기는 안내만 한다
      setEnabled: function (on) { enabled = !!on; pick.hidden = !enabled; if (!enabled && items.length) { items = []; paint(); } }
    };
  }

  var api = { MAX_COUNT: MAX_COUNT, MAX_IMAGE: MAX_IMAGE, MAX_PDF: MAX_PDF, MAX_TOTAL: MAX_TOTAL, PLACEHOLDER: PLACEHOLDER, typeOf: typeOf, whyNot: whyNot, enterSends: enterSends, sizeText: sizeText, composer: composer, chatChips: chatChips };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHAttach = api;
})(typeof window !== 'undefined' ? window : this);
