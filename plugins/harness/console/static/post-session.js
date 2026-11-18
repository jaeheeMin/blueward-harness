/* Post(Cozy Office) 테마의 세션·요청 화면 부품(B단계). 데이터를 읽거나 고치지 않고, 받은 값으로 DOM 조각만 만든다.
   - here: 세션 머리 오른쪽 안내판(큰 사람 그림 + "{팀} · {단계}" + 상태별 한 줄)
   - clerk: 요청 카드 위의 리뷰 룸 검토 담당(승인·계획) 또는 그 세션 사람(질문)
   - seal: 요청 처리가 성공한 뒤에만 카드에 찍는 도장(role="status")
   글자·도장 판정은 post-logic.js 의 순수 함수가 정하고 여기서는 그리기만 한다. 보이는 것은 Post 일 때뿐이다(CSS). */
(function () {
  'use strict';

  var BASE = '/static/post/';
  var PL = window.BHPostLogic, PS = window.BHPostScene;

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function img(src, cls) { var im = new Image(); im.alt = ''; im.decoding = 'async'; im.src = src; if (cls) im.className = cls; return im; }

  /* 세션 머리 오른쪽 안내판. k = 단계 번호(0~4), state = 세션 상태, flow = 팀을 정한 갈래(post-logic.js teamFlowOf). */
  function here(sessionId, state, k, flow) {
    var f = el('figure', 'po-here');
    f.appendChild(PS.avatar(sessionId, state, { size: 'lg' }));
    var cap = el('figcaption');
    cap.appendChild(el('b', null, PL.hereTitle(k, flow)));
    cap.appendChild(el('small', null, PL.hereLine(state)));
    f.appendChild(cap);
    return f;
  }

  /* 요청 카드 바로 위 한 줄. kind: permission · plan · question · elicitation. 승인·계획은 리뷰 룸 검토 담당(가만히 서 있다가 1.2초 주기로 도장을 찍는다), 질문은 그 세션 사람이 손을 든다. */
  function clerk(kind, sessionId, k, flow) {
    var f = el('figure', 'po-clerk'), box = el('span'), anim = PS.animOn();  // 차분·움직임 줄이기면 한 장 그림
    f.setAttribute('aria-hidden', 'true');
    if (kind === 'question' || kind === 'elicitation') {
      var who = PL.personOf(sessionId);
      box.appendChild(img(BASE + 'people/' + who + '/ask-1.svg'));
      if (anim) box.appendChild(img(BASE + 'people/' + who + '/ask-2.svg', 'po-av-b'));
    } else {
      box.appendChild(img(BASE + 'clerk/idle.svg'));
      if (anim) { box.appendChild(img(BASE + 'clerk/stamp-1.svg', 'po-c1')); box.appendChild(img(BASE + 'clerk/stamp-2.svg', 'po-c2')); }
    }
    f.appendChild(box);
    f.appendChild(el('figcaption', null, PL.clerkLine(kind, k, flow)));
    return f;
  }

  /* 도장 한 개. info = { decision, kind, k, flow, still }. still 이면 이미 한 번 보여 준 도장이라 튕기는 동작 없이 바로 보인다(다시 그릴 때 또 찍히지 않게). */
  function seal(info) {
    var s = PL.sealOf(info.decision), sp = el('span', 'po-seal po-seal-' + s.tone + (info.still || !PS.animOn() ? ' still' : ''));  // 차분·움직임 줄이기 = 튕김 없이 바로 보임
    var gone = !info.still && info.at instanceof Date ? Date.now() - info.at.getTime() : 0;
    if (gone > 0) sp.style.animationDelay = -gone + 'ms';  // 튕기는 중에 다시 그려졌으면 처음부터가 아니라 이어서 튕긴다
    sp.setAttribute('role', 'status');
    sp.appendChild(el('b', null, s.text));
    sp.appendChild(el('small', null, PL.sealSub(info.at || new Date(), PL.sealDesk(info.kind, info.k, info.flow))));
    return sp;
  }

  /* 카드에 도장을 붙인다(카드마다 한 번만). */
  function stamp(card, info) {
    if (!card || card.querySelector(':scope > .po-seal')) return null;
    var s = PL.sealOf(info.decision);
    card.classList.add('po-done', 'po-' + s.tone);
    var sp = seal(info);
    card.appendChild(sp);
    return sp;
  }

  window.BHPostSession = { here: here, clerk: clerk, seal: seal, stamp: stamp };
})();
