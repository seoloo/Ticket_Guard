/* Plain browser JS. Authoritative state, prices and checks live on Django. */
(() => {
  'use strict';
  // Safe stand-ins from browser-support.js: never call sessionStorage / crypto.randomUUID directly.
  const {storage, uuid} = window.tgBrowser;
  const $ = (selector) => document.querySelector(selector);
  const body = document.body;
  const screen = body.dataset.screen;
  const attemptId = body.dataset.attempt;
  const showId = body.dataset.show || null;
  const pageViewId = window.ticketGuardCapture?.pageViewId || uuid();
  const previousPage = storage.getItem('tg-last-page');
  const pageNames = ['login','signup','shows','detail','queue','captcha','select','complete','history'];
  const previousPageName = pageNames.includes(previousPage) ? previousPage : null;
  storage.setItem('tg-last-page',screen);
  const price = Number(body.dataset.price);
  const reserved = body.dataset.kind === 'reserved';
  let pageId = storage.getItem('tg-page') || uuid();
  storage.setItem('tg-page', pageId);
  let sequence = Math.max(Number(body.dataset.sequence), Number(storage.getItem('tg-seq-' + attemptId) || 0));
  let latestSequence = sequence;
  let quantity = 1;
  let remaining = Number($('#remaining')?.textContent || 28);
  let chosen = new Set();
  let paused = false;
  let busy = false;
  let moving = false;
  let verificationOutage = false;
  let blocked = false;
  let offline = false;  // captcha/select: heartbeat cannot reach the server
  const startedAt = Date.now();
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]').value;

  // Duplicating a tab may copy storage. Keep the older tab's identifier.
  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('ticket-guard-tabs') : null;
  if (channel) {
    channel.onmessage = ({data}) => {
      if (data.id !== pageId || data.startedAt === startedAt) return;
      if (data.type === 'probe' && data.startedAt > startedAt) channel.postMessage({type: 'occupied', id: pageId, startedAt});
      if (data.type === 'occupied' && data.startedAt < startedAt) {
        pageId = uuid();
        storage.setItem('tg-page', pageId);
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

  // A request with no answer must not leave buttons disabled forever.
  const REQUEST_TIMEOUT_MS = 10000;
  let rejectionReported = false;
  // Recorded as browser_error so it reaches the dashboard (browser_errors) even
  // when the server never saw the request; telemetry.js retries delivery later.
  function requestFailure(timedOut, action, startedAt) {
    // While already offline, background retries are covered by connection_lost/restored.
    if (!(offline && action === 'heartbeat')) event('browser_error', {kind: timedOut ? 'request_timeout' : 'request_failed', action, url: '/api/action/',
      timeoutMs: REQUEST_TIMEOUT_MS, elapsedMs: Date.now() - startedAt});
    return timedOut
      ? {error: '서버 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.', code: 'TIMEOUT'}
      : {error: '연결이 원활하지 않아요. 네트워크를 확인한 뒤 다시 시도해 주세요.', code: 'NETWORK'};
  }
  async function api(action, extra = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const startedAt = Date.now();
    try {
      let response;
      try {
        response = await fetch('/api/action/', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
          body: JSON.stringify({action, pageId, pageViewId, attemptId, ...extra}), signal: controller.signal});
      } catch (_) { throw requestFailure(controller.signal.aborted, action, startedAt); }
      let result;
      try { result = await response.json(); }
      catch (_) {
        if (controller.signal.aborted) throw requestFailure(true, action, startedAt);
        // Non-JSON answer (e.g. Django's 403 page when the session/CSRF token expired).
        // Once per page: heartbeats would otherwise report the same rejection every few seconds.
        if (!rejectionReported) { rejectionReported = true; event('browser_error', {kind: 'request_rejected', action, url: '/api/action/', status: response.status}); }
        if (response.status === 403) throw {error: '페이지를 연 지 오래되어 요청이 거절됐어요. 새로고침한 뒤 다시 시도해 주세요.', code: 'FORBIDDEN'};
        throw {error: '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.', code: 'SERVER'};
      }
      if (!response.ok) throw result;
      return result;
    } finally { clearTimeout(timer); }
  }
  const isConnectionError = error => ['NETWORK', 'TIMEOUT'].includes(error.code);

  function go(url) { moving = true; window.location.assign(url); }
  function failure(error) {
    notify(error.error || '처리 중 오류가 발생했어요. 다시 시도해 주세요.', error.redirect);
    if (['DUPLICATE_PAGE', 'EXPIRED', 'STALE_ATTEMPT', 'CAPTCHA_LIMIT'].includes(error.code)) {
      blocked = true;
      if ($('#confirm-booking')) $('#confirm-booking').disabled = true;
      if (error.code !== 'DUPLICATE_PAGE') storage.removeItem('tg-active');
    }
  }

  function event(type, details = {}, overrides = {}, keepalive = false) {
    window.ticketGuardCapture?.record(type, details, {
      pageInstanceId:pageId,pageViewId,bookingAttemptId:attemptId || null,showId,
      scheduleId:showId ? showId+'-evening' : null,...overrides
    });
  }
  window.addEventListener('pagehide', () => { if (pageNames.includes(screen)) event('page_exit',{pageName:screen,previousPageName}); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) window.location.reload(); });
  document.querySelectorAll('.money').forEach(el => {
    const value = Number(el.textContent.replace(/[^0-9]/g, ''));
    el.textContent = value.toLocaleString('ko-KR') + '원';
  });
  document.querySelectorAll('.card-bottom strong, .selection-meta strong, .queue-show strong').forEach(el => {
    el.innerHTML = el.innerHTML.replace(/\b(\d{4,})\b/g, value => Number(value).toLocaleString('ko-KR'));
  });

  [['#toggle-password', '#password'], ['#toggle-signup-password', '#signup-password']].forEach(([toggle, input]) => {
    $(toggle)?.addEventListener('click', (e) => {
      const visible = $(input).type === 'password';
      $(input).type = visible ? 'text' : 'password';
      e.currentTarget.textContent = visible ? '숨기기' : '보기';
      e.currentTarget.setAttribute('aria-pressed', String(visible));
    });
  });
  // No account storage yet: never let the browser submit the form natively.
  $('#signup-form')?.addEventListener('submit', e => {
    e.preventDefault();
    $('#signup-password').value = '';
    fieldError('#signup-error', '회원가입은 아직 준비 중이에요. 개발용 계정으로 로그인해 주세요.');
  });
  $('#login-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const button = e.currentTarget.querySelector('[type=submit]');
    button.disabled = true;
    $('#login-error').hidden = true;
    $('#login-lock').hidden = true;
    try { const result = await api('login', {username: $('#username').value.trim(), password: $('#password').value}); storage.removeItem('tg-active'); storage.removeItem('tg-events'); go(result.redirect); }
    catch (error) {
      // Locked: say so, without any remaining time. The form stays usable for a later retry.
      if (error.code === 'LOGIN_LOCKED') { $('#login-lock-message').textContent = error.error; $('#login-lock').hidden = false; $('#password').value = ''; return; }
      fieldError('#login-error', error.error);
      if (!isConnectionError(error) && error.code !== 'FORBIDDEN') { $('#password').setAttribute('aria-invalid', 'true'); $('#password').setAttribute('aria-describedby', 'login-error'); $('#password').focus(); }
    }
    finally { button.disabled = false; }
  });
  $('#logout')?.addEventListener('click', async () => {
    try { const result = await api('logout'); storage.removeItem('tg-active'); storage.removeItem('tg-events'); go(result.redirect); }
    catch (error) { failure(error); }
  });
  document.querySelectorAll('[data-history-back]').forEach(el => el.addEventListener('click', () => {
    if (history.length > 1) history.back(); else go('/');
  }));
  $('#search')?.closest('form').addEventListener('submit', () => storage.setItem('tg-search-length',String($('#search').value.length)));
  document.querySelectorAll('[data-genre]').forEach(el => el.addEventListener('click', () => event('genre_change',{genre:el.dataset.genre},{},true)));
  document.querySelectorAll('[data-show-link]').forEach(el => el.addEventListener('click', () => event('show_select',{clickTarget:el.dataset.clickTarget || 'poster'},{showId:el.dataset.showLink,scheduleId:null},true)));
  ['#date-select', '#time-select'].forEach(id => $(id)?.addEventListener('change', () => event('schedule_select',{trigger:id==='#date-select'?'date_change':'time_change',selectedDate:$('#date-select').value})));
  function expandFeaturedCard(card) {
    const previous = $('.featured-show-card.is-expanded');
    const layout = card.closest('.featured-layout');
    const layoutBounds = layout.getBoundingClientRect();
    const cardBounds = card.getBoundingClientRect();
    card.style.setProperty('--expand-top', `${Math.max(0, cardBounds.top - layoutBounds.top)}px`);
    card.style.setProperty('--expand-bottom', `${Math.max(0, layoutBounds.bottom - cardBounds.bottom)}px`);
    document.querySelectorAll('.featured-show-card').forEach(item => {
      item.classList.toggle('is-previous-expanded', previous !== card && item === previous);
      item.classList.toggle('is-active', item === card);
      item.classList.toggle('is-expanded', item === card);
    });
    const hero = $('#featured-hero');
    hero.hidden = window.matchMedia('(min-width: 761px)').matches;
    if (hero.hidden) return;
    hero.style.setProperty('--hero-image', `url('${card.dataset.heroImage}')`);
    $('#hero-title').textContent = card.dataset.heroTitle;
    $('#hero-tagline').textContent = card.dataset.heroTagline;
    $('#hero-show-meta').textContent = card.dataset.heroMeta;
    $('#hero-show-description').textContent = card.dataset.heroDescription;
    $('#hero-show-detail').hidden = false;
    const mobileLink = $('#featured-mobile-link');
    mobileLink.href = card.querySelector('.featured-card-expansion').href;
    mobileLink.setAttribute('aria-label', `${card.dataset.heroTitle} 공연 상세 보기`);
    mobileLink.hidden = false;
  }
  document.querySelectorAll('.featured-show-card').forEach(card => {
    card.addEventListener('mouseenter', () => expandFeaturedCard(card));
    const trigger = card.querySelector('.featured-card-trigger');
    trigger.addEventListener('focus', () => expandFeaturedCard(card));
    trigger.addEventListener('click', () => expandFeaturedCard(card));
    card.querySelector('.featured-card-expansion').addEventListener('animationend', (event) => {
      if (event.animationName !== 'featured-card-unfold' || !card.classList.contains('is-expanded')) return;
      document.querySelectorAll('.featured-show-card.is-previous-expanded').forEach(item => item.classList.remove('is-previous-expanded'));
    });
  });
  window.matchMedia('(min-width: 761px)').addEventListener('change', () => {
    const selected = $('.featured-show-card.is-expanded');
    if (selected) expandFeaturedCard(selected);
  });

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
      storage.setItem('tg-active', JSON.stringify({id: result.id, pageId}));
      event('schedule_select',{trigger:'booking_start',selectedDate:$('#date-select').value},{},true);
      go(result.redirect);
    } catch (error) { failure(error); e.currentTarget.disabled = false; }
  });

  async function cancel() {
    const result = await api('cancel',{reason:'user_cancel'});
    storage.removeItem('tg-active');
    storage.removeItem('tg-selection-' + attemptId);
    go(result.redirect);
  }
  $('#cancel-booking')?.addEventListener('click', () => {
    if (window.confirm('진행 중인 예매를 취소할까요? 다시 입장하면 마지막 순번으로 등록돼요.')) cancel().catch(failure);
  });
  if (attemptId) {
    document.querySelectorAll('.site-header a').forEach(link => link.addEventListener('click', async e => {
      e.preventDefault();
      if (!window.confirm('페이지를 나가면 현재 입장 권한이 해제돼요. 이동할까요?')) return;
      try { await api('cancel',{reason:'menu_navigation'}); storage.removeItem('tg-active'); go(link.href); }
      catch (error) { failure(error); }
    }));
  }

  let heartbeatInFlight = false;
  async function heartbeat() {
    // Queue polls every second; while one request hangs, don't stack more.
    if (paused || blocked || moving || heartbeatInFlight) return;
    heartbeatInFlight = true;
    try {
      const result = await api('heartbeat');
      if ($('#connection-state')) $('#connection-state').innerHTML = '● 정상 연결 중 <span>순서가 되면 자동으로 이동해요.</span>';
      if ($('#reconnect')) $('#reconnect').hidden = true;
      if (screen === 'queue') {
        $('#queue-rank').textContent = result.rank;
        $('#queue-wait').textContent = result.wait > 0 ? '약 ' + result.wait + '초' : '곧 입장해요';
        $('#queue-bar').style.width = Math.max(5, 100 / Math.max(1, result.rank)) + '%';
      }
      setOnline();
      if (result.stage !== screen) go(result.redirect);
    } catch (error) {
      if (isConnectionError(error) && screen === 'queue') {
        $('#connection-state').textContent = error.code === 'TIMEOUT' ? '서버 응답이 지연되고 있어요. 다시 연결해 주세요.' : '연결이 끊겼어요. 다시 연결해 주세요.';
        $('#reconnect').hidden = false;
      } else if (isConnectionError(error) && $('#connection-alert')) setOffline(error.code);
      else { setOnline(); failure(error); }  // the server answered (e.g. EXPIRED): connection is back
    } finally { heartbeatInFlight = false; }
  }

  // Captcha/select: one steady notice instead of a toast every 10s; retry in the background.
  let offlineSince = 0;
  let offlineRetry = null;
  function setOffline(code) {
    $('#connection-alert-title').textContent = code === 'TIMEOUT' ? '서버 응답이 지연되고 있어요' : '연결이 끊겼어요';
    if (offline) return;
    offline = true;
    offlineSince = Date.now();
    $('#connection-alert').hidden = false;
    event('browser_error', {kind: 'connection_lost', pageName: screen, cause: code === 'TIMEOUT' ? 'timeout' : 'network'});
    offlineRetry = setInterval(heartbeat, 3000);
    updateOfflineControls();
  }
  function setOnline() {
    if (!offline) return;
    offline = false;
    clearInterval(offlineRetry);
    $('#connection-alert').hidden = true;
    event('browser_error', {kind: 'connection_restored', pageName: screen, downMs: Date.now() - offlineSince});
    updateOfflineControls();
  }
  function updateOfflineControls() {
    const submit = $('#captcha-form [type=submit]');
    if (submit) submit.disabled = blocked || offline;
    renderSelection();
  }
  $('#connection-retry')?.addEventListener('click', async e => {
    const button = e.currentTarget;
    button.disabled = true;
    button.textContent = '연결 중…';
    await heartbeat();
    button.disabled = false;
    button.textContent = '다시 연결';
  });
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
      if (isConnectionError(error)) setOffline(error.code);
      else if (error.redirect || error.code !== 'CAPTCHA_WRONG') failure(error);
    } finally { button.disabled = blocked || offline; }
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
    $('#confirm-booking').disabled = blocked || busy || offline || count === 0 || (!reserved && quantity > remaining);
    if ($('#quantity-value')) {
      $('#quantity-value').textContent = quantity;
      $('#quantity-minus').disabled = quantity <= 1;
      $('#quantity-plus').disabled = quantity >= Math.min(4, remaining);
    }
    storage.setItem('tg-selection-' + attemptId, JSON.stringify({seats: [...chosen], quantity}));
  }
  if (screen === 'select') {
    try {
      const saved = JSON.parse(storage.getItem('tg-selection-' + attemptId));
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
    if (busy || blocked || offline) return;
    busy = true;
    sequence++;
    latestSequence = sequence;
    const sent = sequence;
    storage.setItem('tg-seq-' + attemptId, String(sequence));
    renderSelection();
    $('#confirm-booking').textContent = '예매를 확인하고 있어요…';
    const payload = {sequence: sent, seats: [...chosen], quantity};
    try {
      const results = repeat ? await Promise.all([api('confirm', payload), api('confirm', payload)]) : [await api('confirm', payload)];
      if (sent !== latestSequence) return;
      storage.removeItem('tg-active');
      storage.removeItem('tg-selection-' + attemptId);
      go(results[0].redirect);
    } catch (error) {
      if (sent !== latestSequence) return;
      // The server may have confirmed already; a retry returns that same booking.
      fieldError('#selection-error', error.code === 'TIMEOUT'
        ? '예매 확인 응답이 지연되고 있어요. 다시 누르면 같은 예매로 안전하게 처리돼요.' : error.error);
      $('#selection-error').focus();
      if (error.sold) document.querySelectorAll('[data-seat]').forEach(el => {
        if (error.sold.includes(el.dataset.seat)) { el.disabled = true; el.classList.add('sold'); chosen.delete(el.dataset.seat); }
      });
      if (error.remaining !== undefined && $('#remaining')) { remaining = error.remaining; $('#remaining').textContent = remaining; }
      if (isConnectionError(error)) setOffline(error.code);
      else if (error.redirect || error.code === 'DUPLICATE_PAGE') failure(error);
    } finally { busy = false; $('#confirm-booking').textContent = '예매 확정 →'; renderSelection(); }
  }
  $('#confirm-booking')?.addEventListener('click', () => confirm());
  $('#repeat-confirm')?.addEventListener('click', async () => { try { await api('scenario',{name:'repeat_confirm',showId}); await confirm(true); } catch(error) { failure(error); } });
  $('#old-confirm')?.addEventListener('click', async () => {
    try { await api('scenario',{name:'old_confirm',showId}); } catch(error) { return failure(error); }
    sequence++;
    latestSequence = sequence;
    storage.setItem('tg-seq-' + attemptId, String(sequence));
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
    if (pageNames.includes(screen)) event('page_enter',{pageName:screen,previousPageName});
    if (screen==='shows' && storage.getItem('tg-search-length')!==null) {
      event('search_change',{queryLength:Number(storage.getItem('tg-search-length')),resultCount:Number(body.dataset.resultCount || 0)});
      storage.removeItem('tg-search-length');
    }
    if (attemptId) {
      await heartbeat();
      if (!blocked && !moving) {
        storage.setItem('tg-active', JSON.stringify({id: attemptId, pageId}));
        refreshCaptcha();
        setInterval(heartbeat, screen === 'queue' ? 1000 : 10000);
      }
    } else {
      const active = JSON.parse(storage.getItem('tg-active') || 'null');
      // An error page must not cancel the booking the user may return to.
      if (active && active.pageId === pageId && screen !== 'complete' && screen !== 'error') {
        try { await api('cancel', {attemptId: active.id,reason:'page_navigation'}); } catch (_) { /* Expired attempts are already invalid. */ }
      }
      storage.removeItem('tg-active');
    }
  }, 200);
})();
