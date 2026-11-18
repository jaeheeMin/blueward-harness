/* 헤더 알림 말풍선·팝업과 계정 한도 표시의 순수 함수(#1016). DOM 을 만지지 않는다(node 로 시험한다).
   알림 목록(items)은 app.js 가 급한 순서로 만들어 넘기고, 여기서는 말풍선에 띄울 한 건 고르기·닫은 알림 정리·팝업 선택지·한도 글자를 정한다. */
(function (root) {
  'use strict';

  var A = typeof module !== 'undefined' && module.exports ? require('./api-notice.js') : root.BHApiNotice;
  var LIMIT_NAME = { five_hour: '5시간', seven_day: '주간', seven_day_opus: '주간(Opus)', seven_day_sonnet: '주간(Sonnet)', overage: '추가 사용' };
  var STALE_SEC = 30 * 60;  // 이보다 오래된 한도 값은 흐리게 보이고 언제 값인지 title 에 적는다

  /* 말풍선에 띄울 한 건: 급한 순서로 정렬된 목록에서 닫지 않은 첫 번째. dismissed 는 {알림 id: true}. */
  function pickBubble(items, dismissed) {
    var d = dismissed || {};
    for (var i = 0; i < (items || []).length; i++) if (!d[items[i].id]) return items[i];
    return null;
  }
  /* 닫은 알림 표시 정리: 더는 없는 알림(풀린 막힘·끝난 차례 등)은 잊어서 같은 일이 다시 생기면 다시 뜨게 한다.
     화면에 따라 있다 없다 하는 알림(merged·ver)은 지우지 않는다. 항목 수는 100개까지만 둔다. */
  var KEEP = /^(merged|ver):/;
  function pruneDismissed(dismissed, items) {
    var live = {}, out = {};
    (items || []).forEach(function (it) { live[it.id] = true; });
    Object.keys(dismissed || {}).filter(function (id) { return live[id] || KEEP.test(id); }).slice(-100).forEach(function (id) { out[id] = true; });  // 넘치면 최근 것을 남긴다(저장도 같다)
    return out;
  }

  /* ---------- 팝업 선택지: 승인 요청 화면(requestView)과 같은 규칙 ---------- */
  /* 되돌릴 수 없는 일이면 지우기·올리기를 가려 단추에 그대로 쓴다. */
  function permVerbs(req) {
    var verbs = ['이번만 허락', '하지 마'];
    if (req && req.risk === 'irreversible') {
      var input = req.toolInput || req.tool_input || req.input || {};
      var text = String((input && (input.command || input.file_path)) || '') + ' ' + String(req.riskNote || req.title || '');
      if (/(^|[\s;&|])(rm|rmdir|del|erase|unlink)\s|Remove-Item|지우|삭제/i.test(text)) verbs = ['이번만 지워', '지우지 마'];
      else if (/git\s+push|gh\s+pr\s+(create|merge)|올리|푸시/i.test(text)) verbs = ['이번만 올려', '올리지 마'];
    }
    return verbs;
  }
  /* "허용하고 이 세션에서 다시 묻지 않기" 를 줄 수 있나. 되돌릴 수 없는 일·제안이 없는 요청은 줄 수 없다. */
  function canAllowSession(req) {
    if (!req) return false;
    return !(req.risk === 'irreversible' || req.canAllowSession === false || req.hasSuggestions === false ||
      (Array.isArray(req.permissionSuggestions) && !req.permissionSuggestions.length) ||
      (Array.isArray(req.permission_suggestions) && !req.permission_suggestions.length));
  }
  /* 팝업에서 무엇을 허락하는지 다 보여 줄 수 있는 승인인가. 계획·MCP·파일 쓰기/고치기·샌드박스 해제·백그라운드 실행·긴 명령은 아니다
     (그런 요청은 팝업에 빠른 허락 단추를 두지 않고 전체 화면 /r/<id> 로 보낸다). */
  var POPUP_TOOLS = ['Bash', 'Read', 'Glob', 'Grep', 'WebFetch', 'WebSearch'], POPUP_MAX = 600;
  function fitsPopup(req) {
    if (!req) return false;
    var tool = req.toolName || req.tool_name || '', input = req.toolInput || req.tool_input || req.input || {};
    if (req.mcp || POPUP_TOOLS.indexOf(tool) < 0 || !input || typeof input !== 'object') return false;
    if (input.dangerouslyDisableSandbox || input.run_in_background) return false;
    var what = String(input.command || input.file_path || input.pattern || input.url || input.query || '');
    return what.length > 0 && what.length <= POPUP_MAX;
  }
  /* 보기 하나를 누르면 바로 보낼 수 있는 질문인가(질문 하나 · 하나만 고름 · 보기가 있음). 아니면 골라 두고 [답 보내기]. */
  function isInstantQuestion(questions) {
    var q = Array.isArray(questions) ? questions : [];
    return q.length === 1 && !q[0].multiSelect && Array.isArray(q[0].options) && q[0].options.length > 0;
  }

  /* ---------- 계정 한도 ---------- */
  /* 쓴 비율: 0~1 이면 비율(×100), 1 초과 100 이하면 이미 퍼센트, 그 밖(음수·100 초과·숫자 아님)은 모름 — 서버(managed.py)와 같은 규칙 */
  function pctText(u) {
    if (typeof u !== 'number' || !isFinite(u) || u < 0 || u > 100) return '';
    return Math.round(u <= 1 ? u * 100 : u) + '%';
  }
  function clockOf(sec, now) { return A ? A.clockText(sec, now) : ''; }
  var STATUS_WORD = { allowed: '여유 있어', allowed_warning: '곧 한도에 닿아', rejected: '한도가 찼어' };

  /* 서버 /api/account-limits 의 windows 를 헤더 글자로. failed 는 읽기 실패.
     { unknown, text, title, chips: [{ type, name, pct(숫자 또는 모름 null), tone: ''|'warn'|'err'|'unk', stale, text, title }] }
     받은 값이 없거나 풀릴 시각이 이미 지난 값뿐이면 unknown — 0% 로 꾸미지 않는다. */
  function limitView(windows, nowMs, failed) {
    var now = nowMs == null ? Date.now() : nowMs, chips = [];
    (Array.isArray(windows) ? windows : []).forEach(function (w) {
      if (!w || typeof w !== 'object' || typeof w.type !== 'string') return;
      var resetMs = typeof w.resetsAt === 'number' && w.resetsAt > 0 ? w.resetsAt * 1000 : 0;
      if (resetMs && resetMs <= now) return;  // 풀린 뒤의 값은 지금 쓴 비율이 아니다
      var status = w.status || 'allowed';  // 빈 status 는 기존 처리(managed.py)처럼 allowed
      var name = LIMIT_NAME[w.type] || w.type, p = pctText(w.utilization), when = clockOf(w.resetsAt, now);
      var tone = status === 'rejected' ? 'err' : status === 'allowed_warning' ? 'warn' : status === 'allowed' ? '' : 'unk';
      var age = typeof w.t === 'number' && w.t > 0 ? Math.max(0, now / 1000 - w.t) : null, stale = age == null || age > STALE_SEC;
      var title = [name + ' 한도 · ' + (STATUS_WORD[status] || '상태를 몰라(' + status + ')'),
        p ? '쓴 비율 ' + p : '쓴 비율은 Claude Code 가 알려 주지 않았어',
        when ? when + ' 에 풀려' : '풀리는 시각은 몰라',
        age == null ? '언제 받은 값인지 몰라' : clockOf(w.t, now).replace(/^오늘 /, '') + ' 에 받은 값' + (w.source === 'statusline' ? '(상태줄에서)' : '') + (stale ? '(오래된 값이야)' : '')].join('\n');
      chips.push({ type: w.type, name: name, pct: p ? parseInt(p, 10) : null, tone: tone, stale: stale, title: title, when: when ? when.replace(/^오늘 /, '') : '', source: w.source || '',
        text: (tone === 'err' ? '✕ ' : tone === 'warn' ? '⚠ ' : tone === 'unk' ? '? ' : '') + name + ' ' + (p || '?') + (when ? ' · ' + when.replace(/^오늘 /, '') : '') });
    });
    if (!chips.length) {
      return { unknown: true, chips: [], text: '한도 알 수 없어',
        title: failed ? '계정 한도를 읽지 못했어. 0% 라는 뜻이 아니야.' : '아직 Claude Code 가 계정 한도를 알려 주지 않았어. 콘솔에서 연 작업이 한 번 돌거나, 설정의 "계정 한도 표시" 를 켠 뒤 Orca·터미널 세션이 한 번 응답하면 보여. 0% 라는 뜻이 아니야.' };
    }
    return { unknown: false, chips: chips, text: chips.map(function (c) { return c.text; }).join(' · '), title: chips.map(function (c) { return c.title; }).join('\n\n') };
  }

  /* 위쪽 줄 칩의 풀리는 시각(Post): limitView 의 "M월 D일 HH:MM"(오늘이면 "HH:MM")을 도장 밑줄과 같은 "MM.DD HH:MM" 으로. 달이 바뀌어도 헷갈리지 않는다(전에는 월을 떼 "21일 09:00") */
  function whenShort(w) { return String(w || '').replace(/^(\d+)월 (\d+)일 /, function (_, m, d) { return (m < 10 ? '0' : '') + m + '.' + (d < 10 ? '0' : '') + d + ' '; }); }

  var api = { whenShort: whenShort, pickBubble: pickBubble, pruneDismissed: pruneDismissed, permVerbs: permVerbs, canAllowSession: canAllowSession,
    isInstantQuestion: isInstantQuestion, fitsPopup: fitsPopup, limitView: limitView, STALE_SEC: STALE_SEC };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHNotice = api;
})(typeof window !== 'undefined' ? window : this);
