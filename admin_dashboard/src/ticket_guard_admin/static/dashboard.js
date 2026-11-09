/* 관리자 화면 샘플 상호작용 · 네트워크 요청 및 DB 접근 없음 */
(() => {
  'use strict';
  const users = JSON.parse(document.getElementById('preview-users').textContent);
  const byId = (id) => document.getElementById(id);
  const reviewOwner = document.body.dataset.reviewOwner || '';
  const reviewScope = document.body.dataset.reviewScope || '';
  const storageKey = `ticketguard-admin-sample-reviews-v3:${encodeURIComponent(reviewScope)}:${encodeURIComponent(reviewOwner)}`;
  let reviews = {};
  try { reviews = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch { /* 저장 차단 시 메모리 사용 */ }
  let selectedUser = users[0];
  let page = 1;
  const pageSize = 6;
  const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
  const tone = (priority) => priority === '우선 검토' ? 'orange' : priority === '관찰' ? 'blue' : 'gray';
  const getReview = (user) => {
    const saved = reviews[user.id];
    return {
      status: ['검토 전', '검토 중', '검토 완료'].includes(saved?.status) ? saved.status : user.status,
      note: typeof saved?.note === 'string' ? saved.note : (user.id === 'USR-2004' ? '반복 요청과 거부 기록의 관계 확인 필요.' : ''),
    };
  };

  function renderUsers() {
    const query = byId('user-search').value.trim().toLowerCase();
    const performance = byId('scope-performance').value;
    const rows = users.filter((user, index) => {
      const matches = (id, value) => byId(id).value === 'all' || byId(id).value === value;
      return user.id.toLowerCase().includes(query)
        && matches('signal-filter', user.signal)
        && matches('priority-filter', user.priority)
        && matches('status-filter', getReview(user).status)
        && (performance === 'all' || performance === user.performance)
        && (byId('scope-session').value === 'all' || String(index % 2 + 1) === byId('scope-session').value)
        && (byId('scope-period').value === 'today' || user.recent >= '14:55:00');
    });
    const counts = [rows.length, ...['우선 검토', '관찰', '데이터 확인'].map((priority) => rows.filter((user) => user.priority === priority).length)];
    document.querySelectorAll('#view-activity .metric strong').forEach((element, index) => { element.textContent = `${counts[index]}개 ID`; });
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    page = Math.min(page, pages);
    const visible = rows.slice((page - 1) * pageSize, page * pageSize);
    byId('users-body').innerHTML = visible.map((user) => `<tr class="${user.priority === '우선 검토' ? 'priority-row' : ''}">
      <th scope="row">${escape(user.id)}</th><td><span class="chip ${tone(user.priority)}">${escape(user.priority)}</span></td>
      <td>${escape(user.signal)}</td><td>${user.priority === '우선 검토' ? `${user.attempts}회 · ${user.count}회` : `${user.count || user.attempts}회`} / 최근 5분</td>
      <td>${escape(user.performance)}</td><td>${user.recent}</td><td><span class="chip ${getReview(user).status === '검토 중' ? 'blue' : 'gray'}">${escape(getReview(user).status)}</span></td>
      <td><button class="outline ${tone(user.priority)}" type="button" data-user="${user.id}">상세 보기</button></td></tr>`).join('')
      || '<tr><td colspan="8" class="empty">조건에 맞는 샘플 데이터 없음</td></tr>';
    byId('result-count').textContent = rows.length ? `총 ${rows.length}개 ID 중 ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, rows.length)}` : '총 0개 ID';
    byId('pagination').innerHTML = `<button type="button" data-page="${page - 1}" ${page === 1 ? 'disabled' : ''} aria-label="이전 페이지">‹</button>`
      + Array.from({length: pages}, (_, index) => `<button type="button" data-page="${index + 1}" ${page === index + 1 ? 'aria-current="page"' : ''}>${index + 1}</button>`).join('')
      + `<button type="button" data-page="${page + 1}" ${page === pages ? 'disabled' : ''} aria-label="다음 페이지">›</button>`;
  }

  function buildAttempts(user) {
    const denied = user.signal.includes('접근 거부');
    return Array.from({length: user.attempts}, (_, index) => {
      const number = user.attempts - index;
      const recentSeconds = Number(user.recent.slice(0, 2)) * 3600 + Number(user.recent.slice(3, 5)) * 60 + Number(user.recent.slice(6));
      const end = recentSeconds - index * 28;
      const formatTime = (seconds) => [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60].map((n) => String(n).padStart(2, '0')).join(':');
      const labels = ['대기열 진입', '입장 허용', '보안문자 통과', '좌석 선택', '확정 요청'];
      if (user.signal === '선행 단계 미관측') labels.splice(0, 4);
      const events = labels.map((label, offset) => ({time: formatTime(end - 72 + offset * 14), label, denied: false}));
      if (denied) {
        for (let offset = 0; offset < 3; offset++) events.push({time: formatTime(end - 4 + offset * 2), label: '접근 거부', denied: true});
      } else {
        events.push({time: formatTime(end), label: user.signal, denied: false});
      }
      return {number, id: `ATT-${user.id.slice(4)}-${String(number).padStart(2, '0')}`, end: formatTime(end), events, denied};
    });
  }

  function renderTimeline() {
    const attempts = buildAttempts(selectedUser).filter((attempt) => byId('detail-period').value === '5' || attempt.end >= '14:59:00');
    byId('timeline').innerHTML = attempts.map((attempt, index) => `<details class="attempt" ${index === 0 ? 'open' : ''}>
      <summary>${attempt.id} · ${escape(selectedUser.performance)}${attempt.denied ? '<span class="chip orange">접근 거부 3회</span>' : ''}</summary>
      <ol class="timeline-events">${attempt.events.map((event, eventIndex) => `<li class="${event.denied ? 'denied-event' : ''}"><time>${event.time}</time><span>${escape(event.label)}</span>${event.denied && eventIndex === attempt.events.length - 1 ? `<div class="event-detail">오류 코드: <b>STALE_REQUEST</b><span>이벤트 ID: <b>EVT-${selectedUser.id.slice(4)}-${String(attempt.number * 3).padStart(3, '0')}</b></span></div>` : ''}</li>`).join('')}</ol></details>`).join('')
      || '<p class="empty">선택 기간에 관측된 샘플 이벤트 없음</p>';
  }

  function renderDetail() {
    const user = selectedUser;
    byId('detail-user-id').textContent = user.id;
    byId('detail-priority').textContent = user.priority;
    byId('detail-priority').className = `chip ${tone(user.priority)}`;
    byId('detail-status').textContent = getReview(user).status;
    byId('detail-attempts').textContent = `${user.attempts}회`;
    byId('detail-denied').textContent = `${user.signal.includes('접근 거부') ? user.count : 0}회`;
    byId('detail-recent').textContent = `${user.recent} KST`;
    byId('detail-performance').innerHTML = `<option>${escape(user.performance)}</option>`;
    byId('review-status').value = getReview(user).status;
    byId('review-note').value = getReview(user).note;
    byId('save-result').textContent = '';
    const evidence = user.signal.includes('접근 거부')
      ? [{label: '예매 시도 반복', value: `${user.attempts}회`, threshold: '5분 내 5회 이상'}, {label: '접근 거부 반복', value: `${user.count}회`, threshold: '5분 내 3회 이상'}]
      : [{label: user.signal, value: `${user.count || user.attempts}회`, threshold: '샘플 관측 신호 · 이벤트 확인 필요'}];
    byId('evidence').innerHTML = evidence.map((item) => `<article class="evidence-card"><span class="evidence-symbol">${item.label.includes('거부') ? '!' : '↻'}</span><div><h3>${escape(item.label)}</h3><p>관측값: <b>최근 5분 ${item.value}</b></p><p>시안용 기준: ${item.threshold}</p></div><button type="button" class="outline orange" data-evidence>근거 이벤트 보기 ›</button></article>`).join('');
    renderTimeline();
  }

  function setView() {
    const parts = location.hash.slice(1).split('/');
    const view = ['flow', 'activity', 'user'].includes(parts[0]) ? parts[0] : 'flow';
    if (view === 'user') {
      selectedUser = users.find((user) => user.id === parts[1]) || selectedUser;
      byId('detail-period').value = '5';
      renderDetail();
    }
    document.querySelectorAll('.view').forEach((section) => { section.hidden = section.id !== `view-${view}`; });
    document.querySelectorAll('[data-view]').forEach((button) => {
      const selected = button.dataset.view === view;
      button.classList.toggle('selected', selected);
      if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    byId('scope-filters').hidden = view === 'user';
    document.title = `${{flow: '흐름 분석', activity: '의심 활동', user: `${selectedUser.id} 사용자 상세`}[view]} | TicketGuard QA`;
    renderUsers();
  }

  document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => {
    location.hash = button.dataset.view === 'user' ? `user/${selectedUser.id}` : button.dataset.view;
  }));
  byId('users-body').addEventListener('click', (event) => {
    const button = event.target.closest('[data-user]');
    if (button) location.hash = `user/${button.dataset.user}`;
  });
  byId('pagination').addEventListener('click', (event) => {
    const button = event.target.closest('[data-page]');
    if (button && !button.disabled) { page = Number(button.dataset.page); renderUsers(); }
  });
  ['user-search', 'signal-filter', 'priority-filter', 'status-filter'].forEach((id) => byId(id).addEventListener('input', () => { page = 1; renderUsers(); }));
  byId('scope-filters').addEventListener('submit', (event) => event.preventDefault());
  byId('scope-filters').addEventListener('change', () => {
    page = 1;
    renderUsers();
    const isDefault = byId('scope-period').value === 'today' && byId('scope-performance').value === 'all' && byId('scope-session').value === 'all';
    byId('scope-message').textContent = isDefault ? '' : '선택 조건의 흐름 분석 샘플 없음 · 의심 활동 목록 필터 적용';
    byId('view-flow').querySelectorAll('.metrics, .flow-grid, .flow-bottom').forEach((element) => { element.hidden = !isDefault; });
  });
  byId('detail-period').addEventListener('change', renderTimeline);
  byId('evidence').addEventListener('click', (event) => {
    if (!event.target.closest('[data-evidence]')) return;
    byId('detail-period').value = '5';
    renderTimeline();
    const attempt = byId('timeline').querySelector('details');
    if (attempt) { attempt.open = true; attempt.scrollIntoView({behavior: 'smooth', block: 'center'}); attempt.classList.add('highlight'); }
  });
  byId('review-form').addEventListener('submit', (event) => {
    event.preventDefault();
    reviews[selectedUser.id] = {status: byId('review-status').value, note: byId('review-note').value};
    let message = '샘플 검토 기록 저장 완료 · 현재 브라우저에만 보관';
    try { localStorage.setItem(storageKey, JSON.stringify(reviews)); } catch { message = '브라우저 저장 불가 · 현재 화면에서만 유지'; }
    byId('detail-status').textContent = byId('review-status').value;
    byId('save-result').textContent = message;
    renderUsers();
  });
  window.addEventListener('hashchange', setView);
  setView();
})();
