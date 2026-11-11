/* Claude Code 가 낸 API 오류·재시도·사용 한도를 쉬운 말로 바꾸는 순수 함수(#865). DOM 을 만지지 않는다(node 로 시험한다).
   서버가 세션에 싣는 apiIssue({kind: auth|limit|model|other|unknown|retry, ...})와 rateLimit({status, type, resetsAt, utilization})를 읽는다.
   하네스 훅 막힘(lastBlock)과는 원인이 달라 따로 다루고, 모르는 모양은 성공으로 뭉개지 않고 "알 수 없는 오류" 로 원문과 함께 보인다. */
(function (root) {
  'use strict';

  var LIMIT_NAME = { five_hour: '5시간', seven_day: '7일', seven_day_opus: '7일(Opus)', seven_day_sonnet: '7일(Sonnet)' };

  function pad(n) { return n < 10 ? '0' + n : String(n); }
  /* 풀리는 시각을 이 PC 의 시각으로. 오늘이면 시:분, 아니면 월·일을 붙인다. 초 단위(epoch seconds)를 받는다. */
  function clockText(sec, nowMs) {
    if (typeof sec !== 'number' || !isFinite(sec) || sec <= 0) return '';
    var d = new Date(sec * 1000), n = new Date(nowMs == null ? Date.now() : nowMs);
    var hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
    return d.toDateString() === n.toDateString() ? '오늘 ' + hm : (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + hm;
  }
  function pct(u) { return typeof u === 'number' && isFinite(u) ? Math.round(u * 100) + '%' : ''; }

  function rawText(issue) {
    var parts = [];
    if (issue.raw) parts.push(issue.raw);
    var meta = [];
    if (issue.status != null) meta.push('상태 ' + issue.status);
    if (issue.error) meta.push('error ' + issue.error);
    if (issue.reason) meta.push('terminal_reason ' + issue.reason);
    if (meta.length) parts.push('(' + meta.join(', ') + ')');
    return parts.join('\n');
  }

  /* 세션 화면에 그릴 카드 하나. { kind, tone: 'err'|'warn'|'info', tag, title, body, raw, side } 또는 null.
     side 는 사이드·홈 목록에 한 줄로 쓰는 말이고, 오류가 아닌 안내(재시도·한도 경고)는 sideTone 이 '' 이다. */
  function notice(s, nowMs) {
    if (!s || typeof s !== 'object') return null;
    var now = nowMs == null ? Date.now() : nowMs;
    var issue = s.apiIssue && typeof s.apiIssue === 'object' ? s.apiIssue : null;
    var rl = s.rateLimit && typeof s.rateLimit === 'object' ? s.rateLimit : null;
    var rlReset = rl && typeof rl.resetsAt === 'number' ? rl.resetsAt * 1000 : 0;
    var rlLive = !!rl && (!rlReset || rlReset > now);  // 풀린 시각이 지난 안내는 두지 않는다
    if (issue && issue.kind === 'retry') {
      if (s.status !== 'running') issue = null;  // 일이 끝났는데 남은 "다시 시도 중" 은 거짓이라 버린다
    }
    if (issue && issue.kind === 'retry') {
      var sec = typeof issue.delayMs === 'number' ? Math.max(1, Math.ceil(issue.delayMs / 1000)) : null;
      var n = issue.attempt != null ? issue.attempt + (issue.max ? '/' + issue.max : '') : '';
      return { kind: 'retry', tone: 'info', sideTone: '', tag: '다시 시도 중', title: '서버 연결을 다시 시도하는 중' + (n ? ' ' + n : ''),
        body: (sec ? '다음 시도는 ' + sec + '초 뒤야. ' : '') + '잠깐 기다리면 돼. 계속 안 되면 인터넷 연결을 확인해 줘.',
        raw: rawText(issue), side: '서버 연결 다시 시도 중' + (n ? ' ' + n : '') };
    }
    var limitHit = (issue && issue.kind === 'limit') || (rl && rl.status === 'rejected' && rlLive);
    if (limitHit) {
      var at = clockText(rl && rl.status === 'rejected' ? rl.resetsAt : null, now);
      return { kind: 'limit', tone: 'err', sideTone: 'err', tag: '⚠ 사용 한도', title: '사용 한도에 걸렸어',
        body: at ? at + ' 에 다시 쓸 수 있어. 그때까지는 기다려 줘.' : '언제 풀리는지는 확인 못 했어. 잠시 뒤 다시 해 봐.',
        raw: issue ? rawText(issue) : '', side: '⚠ 사용 한도' + (at ? ' · ' + at + ' 에 풀려' : '') };
    }
    if (issue) {
      if (issue.kind === 'auth') {
        return { kind: 'auth', tone: 'err', sideTone: 'err', tag: '⚠ 로그인', title: '로그인이 풀렸어',
          body: '터미널에서 claude 를 열어 /login 으로 다시 로그인해 줘. 그다음 여기서 이어서 말하면 돼.', raw: rawText(issue), side: '⚠ 오류 · 로그인이 풀렸어' };
      }
      if (issue.kind === 'model') {
        return { kind: 'model', tone: 'err', sideTone: 'err', tag: '⚠ 모델', title: '고른 모델을 쓸 수 없어',
          body: '모델 이름이 없거나 이 계정에서 쓸 수 없는 것 같아. 새 작업 화면 아래 "고급 설정" 에서 다른 모델을 골라 새로 시작해 줘.', raw: rawText(issue), side: '⚠ 오류 · 모델을 쓸 수 없어' };
      }
      if (issue.kind === 'other') {
        return { kind: 'other', tone: 'err', sideTone: 'err', tag: '⚠ 서버 오류', title: 'Claude Code 서버가 오류를 돌려줬어',
          body: '잠시 뒤 다시 시켜 봐. 같은 오류가 계속되면 아래 원문을 관리자에게 보여 줘.', raw: rawText(issue), side: '⚠ 오류 · 서버가 오류를 돌려줬어' };
      }
      // 모르는 종류·모양: 성공으로 보지 않고 모른다고 말한다
      return { kind: 'unknown', tone: 'err', sideTone: 'err', tag: '⚠ 알 수 없는 오류', title: '알 수 없는 오류로 끝났어',
        body: '무슨 오류인지 확인 못 했어. 일이 잘 끝난 게 아니니 아래 원문을 보고 다시 시켜 줘.', raw: rawText(issue) || '(원문 없음)', side: '⚠ 오류 · 알 수 없는 오류' };
    }
    if (rl && rlLive && rl.status !== 'allowed') {
      var name = LIMIT_NAME[rl.type] || '', p = pct(rl.utilization), when = clockText(rl.resetsAt, now);
      var warn = rl.status === 'allowed_warning';
      return { kind: warn ? 'limit_warn' : 'limit_unknown', tone: 'warn', sideTone: '', tag: warn ? '곧 한도' : '한도 상태 모름', title: warn ? '사용 한도가 가까워졌어' : '사용 한도 상태를 알 수 없어',
        body: warn ? (name ? name + ' ' : '') + '사용량이 ' + (p || '높은 수준') + ' 야.' + (when ? ' ' + when + ' 에 풀려.' : '') + ' 한도에 닿으면 일이 멈춰.'
          : 'Claude Code 가 알려 준 상태(' + rl.status + ')를 몰라서 한도 여부는 확인 못 했어.',
        raw: '', side: '' };
    }
    return null;
  }

  var api = { notice: notice, clockText: clockText };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BHApiNotice = api;
})(typeof window !== 'undefined' ? window : this);
