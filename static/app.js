/* Plain browser JS. Authoritative state, prices and checks live on Django. */
(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const body = document.body;
  const screen = body.dataset.screen;
  const attemptId = body.dataset.attempt;
  const showId = body.dataset.show || null;
  const pageViewId = window.ticketGuardCapture?.pageViewId || crypto.randomUUID();
  const previousPage = sessionStorage.getItem('tg-last-page');
  const pageNames = ['login','signup','shows','detail','queue','captcha','select','complete','history'];
  const previousPageName = pageNames.includes(previousPage) ? previousPage : null;
  sessionStorage.setItem('tg-last-page',screen);
  const price = Number(body.dataset.price);
  const reserved = body.dataset.kind === 'reserved';
  let pageId = sessionStorage.getItem('tg-page') || crypto.randomUUID();
  sessionStorage.setItem('tg-page', pageId);
  let sequence = Math.max(Number(body.dataset.sequence), Number(sessionStorage.getItem('tg-seq-' + attemptId) || 0));
  let latestSequence = sequence;
  let quantity = 1;
  let remaining = Number($('#remaining')?.textContent || 28);
  let chosen = new Set();
  let paused = false;
  let busy = false;
  let moving = false;
  let verificationOutage = false;
  let blocked = false;
  const startedAt = Date.now();
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]').value;

  // Duplicating a tab may copy sessionStorage. Keep the older tab's identifier.
  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('ticket-guard-tabs') : null;
  if (channel) {
    channel.onmessage = ({data}) => {
      if (data.id !== pageId || data.startedAt === startedAt) return;
      if (data.type === 'probe' && data.startedAt > startedAt) channel.postMessage({type: 'occupied', id: pageId, startedAt});
      if (data.type === 'occupied' && data.startedAt < startedAt) {
        pageId = crypto.randomUUID();
        sessionStorage.setItem('tg-page', pageId);
      }
    };
    channel.postMessage({type: 'probe', id: pageId, startedAt});
  }

  function notify(message, redirect) {
    $('#notification-text').textContent = message;
    $('#notification-link').hidden = !redirect;
    if (redirect) $('#notification-link').href = redirect;
    $('#notification').hidden = false;
  }
  $('.dismiss').addEventListener('click', () => { $('#notification').hidden = true; });
  const fieldError = (selector, message) => {
    const element = $(selector);
    if (!element) return notify(message);
    element.textContent = message;
    element.hidden = false;
  };

  async function api(action, extra = {}) {
    let response;
    try {
      response = await fetch('/api/action/', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
        body: JSON.stringify({action, pageId, pageViewId, attemptId, ...extra})});
    } catch (_) { throw {error: '연결이 원활하지 않아요. 네트워크를 확인한 뒤 다시 시도해 주세요.', code: 'NETWORK'}; }
    let result;
    try { result = await response.json(); }
    catch (_) { throw {error: '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.', code: 'NETWORK'}; }
    if (!response.ok) throw result;
    return result;
  }

  function go(url) { moving = true; window.location.assign(url); }
  function failure(error) {
    notify(error.error || '처리 중 오류가 발생했어요. 다시 시도해 주세요.', error.redirect);
    if (['DUPLICATE_PAGE', 'EXPIRED', 'STALE_ATTEMPT', 'CAPTCHA_LIMIT'].includes(error.code)) {
      blocked = true;
      if ($('#confirm-booking')) $('#confirm-booking').disabled = true;
      if (error.code !== 'DUPLICATE_PAGE') sessionStorage.removeItem('tg-active');
    }
  }

  function event(type, details = {}, overrides = {}, keepalive = false) {
    window.ticketGuardCapture?.record(type, details, {
      pageInstanceId:pageId,pageViewId,bookingAttemptId:attemptId || null,showId,
      scheduleId:showId ? showId+'-evening' : null,...overrides
    });
  }
  window.addEventListener('pagehide', () => event('page_exit',{pageName:screen,previousPageName}));
  window.addEventListener('pageshow', (e) => { if (e.persisted) window.location.reload(); });
  document.querySelectorAll('.money').forEach(el => {
    const value = Number(el.textContent.replace(/[^0-9]/g, ''));
    el.textContent = value.toLocaleString('ko-KR') + '원';
  });
  document.querySelectorAll('.card-bottom strong, .selection-meta strong, .queue-show strong').forEach(el => {
    el.innerHTML = el.innerHTML.replace(/\b(\d{4,})\b/g, value => Number(value).toLocaleString('ko-KR'));
  });

  $('#toggle-password')?.addEventListener('click', (e) => {
    const visible = $('#password').type === 'password';
    $('#password').type = visible ? 'text' : 'password';
    e.currentTarget.textContent = visible ? '숨기기' : '보기';
    e.currentTarget.setAttribute('aria-pressed', String(visible));
  });
  $('#login-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const button = e.currentTarget.querySelector('[type=submit]');
    button.disabled = true;
    $('#login-error').hidden = true;
    try { const result = await api('login', {username: $('#username').value.trim(), password: $('#password').value}); sessionStorage.removeItem('tg-active'); sessionStorage.removeItem('tg-events'); go(result.redirect); }
    catch (error) { fieldError('#login-error', error.error); $('#password').setAttribute('aria-invalid', 'true'); $('#password').setAttribute('aria-describedby', 'login-error'); $('#password').focus(); }
    finally { button.disabled = false; }
  });
  $('#logout')?.addEventListener('click', async () => {
    try { const result = await api('logout'); sessionStorage.removeItem('tg-active'); sessionStorage.removeItem('tg-events'); go(result.redirect); }
    catch (error) { failure(error); }
  });
  $('#search')?.closest('form').addEventListener('submit', () => sessionStorage.setItem('tg-search-length',String($('#search').value.length)));
  document.querySelectorAll('[data-genre]').forEach(el => el.addEventListener('click', () => event('genre_change',{genre:el.dataset.genre},{},true)));
  document.querySelectorAll('[data-show-link]').forEach(el => el.addEventListener('click', () => event('show_select',{clickTarget:el.dataset.clickTarget || 'poster'},{showId:el.dataset.showLink,scheduleId:null},true)));
  ['#date-select', '#time-select'].forEach(id => $(id)?.addEventListener('change', () => event('schedule_select',{trigger:id==='#date-select'?'date_change':'time_change',selectedDate:$('#date-select').value})));
  document.querySelectorAll('.featured-show-card').forEach(card => card.addEventListener('mouseenter', () => {
    const hero = $('#featured-hero');
    hero.style.setProperty('--hero-image', `url('${card.dataset.heroImage}')`);
    $('#hero-title').innerHTML = card.dataset.heroTitle;
    $('#hero-tagline').textContent = card.dataset.heroTagline;
    $('#hero-show-meta').textContent = card.dataset.heroMeta;
    $('#hero-show-description').textContent = card.dataset.heroDescription;
    $('#hero-show-detail').hidden = false;
    document.querySelectorAll('.featured-show-card').forEach(item => item.classList.toggle('is-active', item === card));
  }));

  function countdown() {
    const el = $('#countdown');
    if (!el) return;
    const seconds = Math.max(0, Math.ceil((Number(el.dataset.opensAt) - Date.now()) / 1000));
    el.hidden = seconds === 0;
    el.textContent = '예매 시작까지 ' + String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
    $('#start-booking').disabled = seconds > 0;
    $('#start-booking').textContent = seconds > 0 ? '예매 오픈 예정' : '예매하기 →';
  }
  countdown();
  if ($('#countdown')) setInterval(countdown, 1000);
  $('#start-booking')?.addEventListener('click', async e => {
    e.currentTarget.disabled = true;
    try {
      const result = await api('start', {showId});
      sessionStorage.setItem('tg-active', JSON.stringify({id: result.id, pageId}));
      event('schedule_select',{trigger:'booking_start',selectedDate:$('#date-select').value},{},true);
      go(result.redirect);
    } catch (error) { failure(error); e.currentTarget.disabled = false; }
  });

  async function cancel() {
    const result = await api('cancel',{reason:'user_cancel'});
    sessionStorage.removeItem('tg-active');
    sessionStorage.removeItem('tg-selection-' + attemptId);
    go(result.redirect);
  }
  $('#cancel-booking')?.addEventListener('click', () => {
    if (window.confirm('진행 중인 예매를 취소할까요? 다시 입장하면 마지막 순번으로 등록돼요.')) cancel().catch(failure);
  });
  if (attemptId) {
    document.querySelectorAll('.site-header a').forEach(link => link.addEventListener('click', async e => {
      e.preventDefault();
      if (!window.confirm('페이지를 나가면 현재 입장 권한이 해제돼요. 이동할까요?')) return;
      try { await api('cancel',{reason:'menu_navigation'}); sessionStorage.removeItem('tg-active'); go(link.href); }
      catch (error) { failure(error); }
    }));
  }

  async function heartbeat() {
    if (paused || blocked || moving) return;
    try {
      const result = await api('heartbeat');
      if ($('#connection-state')) $('#connection-state').innerHTML = '● 정상 연결 중 <span>순서가 되면 자동으로 이동해요.</span>';
      if ($('#reconnect')) $('#reconnect').hidden = true;
      if (screen === 'queue') {
        $('#queue-rank').textContent = result.rank;
        $('#queue-wait').textContent = result.wait > 0 ? '약 ' + result.wait + '초' : '곧 입장해요';
        $('#queue-bar').style.width = Math.max(5, (12-result.wait) / 12 * 100) + '%';
      }
      if (result.stage !== screen) go(result.redirect);
    } catch (error) {
      if (error.code === 'NETWORK' && screen === 'queue') {
        $('#connection-state').textContent = '연결이 끊겼어요. 다시 연결해 주세요.';
        $('#reconnect').hidden = false;
      } else failure(error);
    }
  }
  $('#reconnect')?.addEventListener('click', async e => {
    paused = false;
    $('#connection-state').textContent = '다시 연결하고 있어요…';
    e.currentTarget.disabled = true;
    await heartbeat();
    e.currentTarget.disabled = false;
  });
  $('#disconnect')?.addEventListener('click', async () => {
    try { await api('scenario',{name:'disconnect',showId}); } catch(error) { return failure(error); }
    paused = true;
    $('#connection-state').textContent = '연결이 끊겼어요. 다시 연결해 주세요.';
    $('#reconnect').hidden = false;
  });
  $('#verification-outage')?.addEventListener('click', async () => {
    try { await api('scenario',{name:'verification_outage',showId}); } catch(error) { return failure(error); }
    verificationOutage = true;
    notify('다음 보안문자 제출에서 통신 오류를 재현합니다. 오답 횟수는 증가하지 않아요.');
  });
  function refreshCaptcha(reason='initial') {
    if ($('#captcha-image')) $('#captcha-image').src = '/captcha.png?pageId=' + encodeURIComponent(pageId) + '&pageViewId='+encodeURIComponent(pageViewId)+'&attemptId=' + encodeURIComponent(attemptId) + '&reason='+reason+'&v=' + Date.now();
  }
  $('#captcha-image')?.addEventListener('error', () => notify('보안문자 이미지를 불러오지 못했어요. 문제 바꾸기를 눌러 주세요.'));
  $('#refresh-captcha')?.addEventListener('click', () => refreshCaptcha('user_refresh'));
  $('#captcha-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    if (verificationOutage) { verificationOutage = false; return fieldError('#captcha-error', '통신 오류가 발생했어요. 오답 횟수는 그대로예요. 다시 확인해 주세요.'); }
    const button = e.currentTarget.querySelector('[type=submit]');
    button.disabled = true;
    try { const result = await api('verify', {answer: $('#captcha-answer').value}); go(result.redirect); }
    catch (error) {
      fieldError('#captcha-error', error.error);
      $('#captcha-answer').setAttribute('aria-invalid', 'true');
      $('#captcha-answer').focus();
      if (error.redirect || error.code !== 'CAPTCHA_WRONG') failure(error);
    } finally { button.disabled = blocked; }
  });

  function renderSelection() {
    if (screen !== 'select') return;
    document.querySelectorAll('[data-seat]').forEach(el => {
      const selected = chosen.has(el.dataset.seat);
      el.setAttribute('aria-pressed', String(selected));
      el.textContent = el.disabled ? '×' : selected ? '✓' : '';
      el.setAttribute('aria-label', el.dataset.seat[0] + '열 ' + el.dataset.seat.slice(1) + '번' + (el.disabled ? ' 판매 완료' : selected ? ' 선택됨' : ' 선택 가능'));
    });
    const count = reserved ? chosen.size : quantity;
    $('#selected-count').textContent = count;
    $('#selected-label').textContent = reserved ? ([...chosen].map(s => s[0] + '열 ' + s.slice(1) + '번').join(' · ') || '좌석을 선택해 주세요') : '자유석 ' + quantity + '명';
    $('#total-amount').textContent = (count*price).toLocaleString('ko-KR') + '원';
    $('#confirm-booking').disabled = blocked || busy || count === 0 || (!reserved && quantity > remaining);
    if ($('#quantity-value')) {
      $('#quantity-value').textContent = quantity;
      $('#quantity-minus').disabled = quantity <= 1;
      $('#quantity-plus').disabled = quantity >= Math.min(4, remaining);
    }
    sessionStorage.setItem('tg-selection-' + attemptId, JSON.stringify({seats: [...chosen], quantity}));
  }
  if (screen === 'select') {
    try {
      const saved = JSON.parse(sessionStorage.getItem('tg-selection-' + attemptId));
      if (saved) {
        chosen = new Set(saved.seats.filter(s => [...document.querySelectorAll('[data-seat]:not(:disabled)')].some(el => el.dataset.seat === s)).slice(0, 4));
        quantity = Math.max(1, Math.min(4, remaining, saved.quantity || 1));
      }
    } catch (_) { /* Ignore invalid browser-local draft. */ }
    document.querySelectorAll('[data-seat]').forEach(el => el.addEventListener('click', () => {
      if (chosen.has(el.dataset.seat)) { chosen.delete(el.dataset.seat); event('seat_cancel',{seatId:el.dataset.seat,selectedCount:chosen.size}); }
      else {
        if (chosen.size >= 4) return fieldError('#selection-error', '최대 4석까지 선택할 수 있어요. 선택 내역을 수정해 주세요.');
        chosen.add(el.dataset.seat); event('seat_select',{seatId:el.dataset.seat,selectedCount:chosen.size});
      }
      $('#selection-error').hidden = true;
      renderSelection();
    }));
    $('#quantity-minus')?.addEventListener('click', () => { const previousQuantity=quantity; if (quantity > 1) quantity--; renderSelection(); event('quantity_change',{previousQuantity,quantity}); });
    $('#quantity-plus')?.addEventListener('click', () => { const previousQuantity=quantity; if (quantity < Math.min(4, remaining)) quantity++; renderSelection(); event('quantity_change',{previousQuantity,quantity}); });
    renderSelection();
  }
  async function confirm(repeat = false) {
    if (busy || blocked) return;
    busy = true;
    sequence++;
    latestSequence = sequence;
    const sent = sequence;
    sessionStorage.setItem('tg-seq-' + attemptId, String(sequence));
    renderSelection();
    $('#confirm-booking').textContent = '예매를 확인하고 있어요…';
    const payload = {sequence: sent, seats: [...chosen], quantity};
    try {
      const results = repeat ? await Promise.all([api('confirm', payload), api('confirm', payload)]) : [await api('confirm', payload)];
      if (sent !== latestSequence) return;
      sessionStorage.removeItem('tg-active');
      sessionStorage.removeItem('tg-selection-' + attemptId);
      go(results[0].redirect);
    } catch (error) {
      if (sent !== latestSequence) return;
      fieldError('#selection-error', error.error);
      $('#selection-error').focus();
      if (error.sold) document.querySelectorAll('[data-seat]').forEach(el => {
        if (error.sold.includes(el.dataset.seat)) { el.disabled = true; el.classList.add('sold'); chosen.delete(el.dataset.seat); }
      });
      if (error.remaining !== undefined && $('#remaining')) { remaining = error.remaining; $('#remaining').textContent = remaining; }
      if (error.redirect || error.code === 'DUPLICATE_PAGE') failure(error);
    } finally { busy = false; $('#confirm-booking').textContent = '예매 확정 →'; renderSelection(); }
  }
  $('#confirm-booking')?.addEventListener('click', () => confirm());
  $('#repeat-confirm')?.addEventListener('click', async () => { try { await api('scenario',{name:'repeat_confirm',showId}); await confirm(true); } catch(error) { failure(error); } });
  $('#old-confirm')?.addEventListener('click', async () => {
    try { await api('scenario',{name:'old_confirm',showId}); } catch(error) { return failure(error); }
    sequence++;
    latestSequence = sequence;
    sessionStorage.setItem('tg-seq-' + attemptId, String(sequence));
    try { await api('confirm', {sequence, seats: [], quantity: 0}); } catch (_) { /* Reserve sequence with deliberately invalid selection. */ }
    try { await api('confirm', {sequence, seats: [...chosen], quantity}); }
    catch (error) { fieldError('#selection-error', error.error); }
  });
  document.querySelectorAll('[data-scenario]').forEach(el => el.addEventListener('click', async () => {
    try {
      await api('scenario', {name: el.dataset.scenario, showId, seats: [...chosen]});
      if (['open_later', 'open_now', 'four_wrong'].includes(el.dataset.scenario)) window.location.reload();
      else if (['admit', 'expire'].includes(el.dataset.scenario)) await heartbeat();
      else notify('상태가 변경되었어요. 예매 확정을 눌러 복구 안내를 확인해 주세요.');
    } catch (error) { failure(error); }
  }));
  $('#show-events')?.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/events/');
      if (!response.ok) throw new Error();
      const result = await response.json();
      $('#event-log').textContent = JSON.stringify({metrics:result.deliveryMetrics,events:result.events.slice(-15)}, null, 2);
      $('#event-log').hidden = false;
    } catch (_) { notify('이벤트를 불러오지 못했어요. 다시 시도해 주세요.'); }
  });

  setTimeout(async () => {
    event('page_enter',{pageName:screen,previousPageName});
    if (screen==='shows' && sessionStorage.getItem('tg-search-length')!==null) {
      event('search_change',{queryLength:Number(sessionStorage.getItem('tg-search-length')),resultCount:Number(body.dataset.resultCount || 0)});
      sessionStorage.removeItem('tg-search-length');
    }
    if (attemptId) {
      await heartbeat();
      if (!blocked && !moving) {
        sessionStorage.setItem('tg-active', JSON.stringify({id: attemptId, pageId}));
        refreshCaptcha();
        setInterval(heartbeat, screen === 'queue' ? 1000 : 10000);
      }
    } else {
      const active = JSON.parse(sessionStorage.getItem('tg-active') || 'null');
      if (active && active.pageId === pageId && screen !== 'complete') {
        try { await api('cancel', {attemptId: active.id,reason:'page_navigation'}); } catch (_) { /* Expired attempts are already invalid. */ }
      }
      sessionStorage.removeItem('tg-active');
    }
  }, 200);
})();
