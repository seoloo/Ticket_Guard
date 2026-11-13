/*
[홍석환] 이상탐지 시안의 대상 검색과 근거 상세
고정 샘플을 필터링하고 선택 대상의 타임라인을 안전한 텍스트로 구성한다.
*/
(() => {
  'use strict';
  function init(anomaly) {
    const table=document.getElementById('mp-subjects'), search=document.getElementById('mp-subject-search'), filter=document.getElementById('mp-signal-filter');
    let selected = anomaly.subjects[0]?.id;
    function detail(subject) {
      const host=document.getElementById('mp-subject-detail'); host.replaceChildren();
      if (!subject) { const text=document.createElement('p'); text.textContent='조건에 맞는 관측 대상이 없습니다.'; host.append(text); return; }
      const id=document.createElement('div'); id.className='mp-subject-id'; id.textContent=subject.id;
      const meta=document.createElement('p'); meta.className='mp-subject-meta'; meta.textContent=`${subject.attempt} · 관측 신호 ${subject.events.length}건 · KST`;
      const list=document.createElement('ol'); list.className='mp-timeline';
      subject.events.forEach(event=>{
        const li=document.createElement('li'), at=document.createElement('time'), content=document.createElement('div'); at.textContent=event.at;
        const title=document.createElement('h3'); title.textContent=event.label;
        const code=document.createElement('code'); code.textContent=event.code;
        const text=document.createElement('p'); text.textContent=event.detail;
        content.append(title,code,text); li.append(at,content); list.append(li);
      }); host.append(id,meta,list);
    }
    function render() {
      const query=search.value.trim().toLowerCase();
      const rows=anomaly.subjects.filter(subject=>subject.id.toLowerCase().includes(query) && (filter.value==='all'||subject.kinds.includes(filter.value)));
      if (!rows.some(row=>row.id===selected)) selected=rows[0]?.id;
      table.replaceChildren();
      rows.forEach(subject=>{
        const tr=document.createElement('tr'); if(subject.id===selected) tr.className='mp-subject-selected';
        const id=document.createElement('th'); id.scope='row'; id.textContent=subject.id;
        const count=document.createElement('td'); count.textContent=`${subject.events.length}건`;
        const recent=document.createElement('td'); recent.textContent=subject.recent;
        const action=document.createElement('td'), button=document.createElement('button');
        button.type='button'; button.className='mp-text-button'; button.textContent='상세 보기'; button.dataset.subject=subject.id;
        button.setAttribute('aria-label',`${subject.id} 상세 보기`); button.setAttribute('aria-pressed',String(subject.id===selected));
        button.addEventListener('click',()=>{ selected=subject.id; render();
          const same=Array.from(table.querySelectorAll('button')).find(b=>b.dataset.subject===selected); same?.focus(); });
        action.append(button); tr.append(id,count,recent,action); table.append(tr);
      });
      if(!rows.length) { const tr=document.createElement('tr'), td=document.createElement('td'); td.colSpan=4; td.textContent='조건에 맞는 대상 없음'; tr.append(td); table.append(tr); }
      document.getElementById('mp-subject-count').textContent=`${rows.length}개 대상 · 전체 ${anomaly.subjects.length}개`;
      detail(rows.find(row=>row.id===selected));
    }
    search.addEventListener('input',render); filter.addEventListener('change',render); render();
  }
  window.TGPreviewAnomaly = {init};
})();
