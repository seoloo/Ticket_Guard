/*
[홍석환] 실제 화면과 시안의 공통 관점 전환
주입된 자료만 그래프에 전달하고 해시 탐색·반응형 배치를 관리한다.
*/
(() => {
  'use strict';
  const data=JSON.parse(document.querySelector('[data-monitor-data]').textContent);
  const isLive=document.body.dataset.monitorMode==='live';
  const names={flow:'사용자 흐름',network:'네트워크 상태',anomaly:'이상탐지'};
  const charts=window.TGMonitorCharts;
  function draw() {
    if(data.flow) {
      window.TGMonitorFlow.draw(data.flow);
      charts.draw('mp-presence-chart',data.flow.presence,{label:'동시 접속 추이',unit:data.flow.count_unit || '명',range:data.flow.chart_range});
      charts.draw('mp-booking-chart',data.flow.booking,{label:'예매율 추이',unit:'%',color:'#119e99',percent:true,range:data.flow.chart_range});
    }
    if(data.network) {
      charts.draw('mp-requests-chart',data.network.requestsSeries,{label:'요청 추이',unit:'건'});
      charts.draw('mp-errors-chart',data.network.errorsSeries,{label:'HTTP 오류 추이',unit:'건',color:'#ce9232'});
    }
  }
  function route(focus=false) {
    const hash=location.hash.slice(1), view=Object.hasOwn(names,hash)?hash:'flow';
    if(hash!==view) history.replaceState(null,'',`${location.pathname}${location.search}#${view}`);
    document.querySelectorAll('[data-preview-view]').forEach(panel=>{panel.hidden=panel.dataset.previewView!==view;});
    document.querySelectorAll('.mp-tab').forEach(tab=>{
      const active=tab.hash===`#${view}`; tab.classList.toggle('active',active);
      if(active) tab.setAttribute('aria-current','page'); else tab.removeAttribute('aria-current');
    });
    document.title=`DB 대시보드${isLive ? '' : ' 시안'} · ${names[view]} | 티켓가드`;
    document.getElementById('mp-view-status').textContent=`${names[view]} 화면`;
    draw(); if(focus) document.getElementById(`${view}-title`).focus({preventScroll:true});
  }
  if(data.anomaly) window.TGPreviewAnomaly.init(data.anomaly);
  window.addEventListener('hashchange',()=>route(true));
  let frame=0;
  function resize() { cancelAnimationFrame(frame); frame=requestAnimationFrame(draw); }
  window.addEventListener('resize',resize);
  route();
})();
