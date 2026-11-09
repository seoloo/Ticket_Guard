/* 실제 조회 데이터만 표시 · 이벤트와 판정 생성 금지 */
(() => {
  const data = document.getElementById('live-data');
  if (!data) return;
  const users = JSON.parse(data.textContent);
  const get = (id) => document.getElementById(id);
  const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let page = 1;
  let selected = users[0];
  function renderUsers() {
    const query = get('live-search').value.trim().toLowerCase();
    const result = get('live-result').value;
    const rows = users.filter((user) => user.id.toLowerCase().includes(query) && (result === 'all' || (result === 'rejected' ? user.rejected > 0 : user.failed > 0)));
    const pages = Math.max(1, Math.ceil(rows.length / 10));
    page = Math.min(page, pages);
    get('live-users').innerHTML = rows.slice((page-1)*10, page*10).map((user) => `<tr><th>${escape(user.id)}</th><td>${user.attempt_count}</td><td>${user.count}</td><td>${user.rejected}</td><td>${user.failed}</td><td>${escape(user.recent)}</td><td><button class="outline blue" data-live-user="${escape(user.id)}">상세 보기</button></td></tr>`).join('') || '<tr><td colspan="7" class="empty">선택 조건의 관측 사용자 없음</td></tr>';
    get('live-count').textContent = `총 ${rows.length}개 ID · ${page} / ${pages} 페이지`;
    get('live-pagination').innerHTML = `<button data-page="${page-1}" ${page===1?'disabled':''} aria-label="이전 페이지">‹</button><button aria-current="page">${page}</button><button data-page="${page+1}" ${page===pages?'disabled':''} aria-label="다음 페이지">›</button>`;
  }
  function detail() {
    if (!selected) {
      get('live-user-id').textContent = '관측 사용자 없음';
      get('live-user-metrics').innerHTML = '';
      get('live-timeline').innerHTML = '<p class="empty">선택 조건의 이벤트 없음</p>';
      get('live-evidence').innerHTML = '';
      return;
    }
    get('live-user-id').textContent = selected.id;
    get('live-user-metrics').innerHTML = [['예매 시도 · bookingAttemptId', selected.attempt_count+'건'],['거부 · result=rejected',selected.rejected+'건'],['최근 관측 · occurredAt',selected.recent]].map(([label,value]) => `<article class="metric"><div><h3>${label}</h3><strong style="font-size:20px;white-space:normal">${escape(value)}</strong></div></article>`).join('');
    const groups = new Map();
    selected.events.forEach((event) => { const key=event.bookingAttemptId; if (!groups.has(key)) groups.set(key,[]); groups.get(key).push(event); });
    get('live-timeline').innerHTML = [...groups].map(([id,events], index) => `<details class="attempt" ${index===0?'open':''}><summary>${id==='미기록'?'예매 시도 ID 없음':escape(id)}</summary><ol class="timeline-events">${[...events].reverse().map((event) => `<li class="${event.result==='rejected'?'denied-event':''}"><time>${escape(event.time)}</time><span>${escape(event.label)}</span><div class="event-detail">eventType: <b>${escape(event.eventType)}</b> · result: ${escape(event.result)}<br>errorCode: <b>${escape(event.errorCode)}</b><br>eventId: ${escape(event.eventId)}<br>showId: ${escape(event.showId)} · scheduleId: ${escape(event.scheduleId)}</div></li>`).join('')}</ol></details>`).join('');
    const signals = selected.events.filter((event) => ['failure','rejected'].includes(event.result));
    get('live-evidence').innerHTML = signals.map((event) => `<article class="evidence-card"><div><h3>${escape(event.label)}</h3><p>${escape(event.time)}</p><p>errorCode: ${escape(event.errorCode)}</p><p>eventId: ${escape(event.eventId)}</p></div></article>`).join('') || '<p class="empty">선택 조건의 실패 · 거부 근거 없음</p>';
  }
  function render() {
    const [requested,id] = location.hash.slice(1).split('/');
    const view = ['flow','activity','user'].includes(requested) ? requested : 'flow';
    if (id) { try { selected = users.find((user) => user.id===decodeURIComponent(id)); } catch { selected=undefined; } }
    document.querySelectorAll('[data-live-panel]').forEach((panel) => { panel.hidden=panel.dataset.livePanel!==view; });
    document.querySelectorAll('[data-live-view]').forEach((button) => { const active=button.dataset.liveView===view; button.classList.toggle('selected',active); if(active) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current'); });
    if(view==='user') detail();
    renderUsers();
  }
  document.querySelectorAll('[data-live-view]').forEach((button) => button.addEventListener('click',() => { location.hash=button.dataset.liveView; }));
  get('live-users').addEventListener('click',(event) => { const button=event.target.closest('[data-live-user]'); if(button) location.hash='user/'+encodeURIComponent(button.dataset.liveUser); });
  get('live-pagination').addEventListener('click',(event) => { const button=event.target.closest('[data-page]'); if(button&&!button.disabled) { page=Number(button.dataset.page); renderUsers(); } });
  ['live-search','live-result'].forEach((id) => get(id).addEventListener('input',() => { page=1; renderUsers(); }));
  window.addEventListener('hashchange',render);
  render();
})();
