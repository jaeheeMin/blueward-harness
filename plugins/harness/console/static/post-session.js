/* Post(Cozy Office) 테마의 세션·요청 화면 부품(B단계). 데이터를 읽거나 고치지 않고, 받은 값으로 DOM 조각만 만든다.
   - here: 세션 머리 오른쪽 안내판(큰 사람 그림(사무실 장면의 그 사람) + "{팀} · {단계}")
   - clerk: 요청 카드 위에서 손을 든 그 세션 사람(승인·계획·질문 모두)
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
    cap.appendChild(el('b', null, PL.hereTitle(k, flow, state)));  // 곳은 장면이 세운 곳(판정 D1). 안내판은 앉은 곳만 말한다. 상태 한 줄(옛 hereLine)은 뺐다(문구 6회차에 함수도 지움): 같은 화면의 머리 상태 표시와 그 아래 문장이 이미 말한다(요약 정리, 2026-11-19)
    f.appendChild(cap);
    return f;
  }

  /* 요청 카드 바로 위 한 줄. kind: permission · plan · question · elicitation. 어느 요청이든 그 세션 사람이 손을 든다 — 사무실 장면에서 손 든 바로 그 사람이다(PS.portraitOf, 허리까지).
     옛 라인아트 장면의 「리뷰 룸 검토 담당」 그림은 새 장면에 없는 사람이라 여기서 뺐다. 번들이 없으면 옛 라인아트 직원이 손을 든다. */
  function clerk(kind, sessionId, k, flow) {
    var anim = PS.animOn();  // 차분·움직임 줄이기면 멈춘 그림(프로필 그림은 portraitOf 가 스스로 본다)
    var pic = PS.portraitOf ? PS.portraitOf(sessionId, 'turn', 'half', true) : null;
    var who = pic ? '' : PL.personOf(sessionId);
    var f = el('figure', 'po-clerk is-ask' + (who === 'kid' ? ' is-kid' : '')), box = el('span', pic ? 'po-av-pic po-av-turn' : '');
    f.setAttribute('aria-hidden', 'true');
    if (pic) box.appendChild(pic);
    else {
      box.appendChild(img(BASE + 'people/' + who + '/ask-1.svg'));
      if (anim) box.appendChild(img(BASE + 'people/' + who + '/ask-2.svg', 'po-av-b'));
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
