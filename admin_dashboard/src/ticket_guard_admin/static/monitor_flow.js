/*
[홍석환] 식별자 기반 공통 사용자 흐름 그래프
실제 단계 수·연결 종류·결측값을 반영하고 선택 항목의 근거를 표시한다.
*/
(() => {
  'use strict';
  function draw(flow) {
    const host = document.getElementById('mp-flow-graph');
    if (!host || !host.getBoundingClientRect().width) return;
    if(!flow.nodes.length) {
      const empty=document.createElement('p'); empty.className='mp-empty-chart'; empty.textContent='공개된 단계 정보가 없습니다.';
      host.replaceChildren(empty); return;
    }
    const nodes=flow.nodes, byId=new Map(nodes.map((node,index)=>[node.id,{...node,index}]));
    const routes=[...flow.edges.map(e=>({...e,kind:e.kind || 'forward'})), ...(flow.secondary || [])];
    const secondary=routes.filter(edge=>edge.kind!=='retry' && !(edge.kind==='forward' && byId.get(edge.target)?.index===byId.get(edge.source)?.index+1));
    host.style.minWidth=`${Math.max(640,nodes.length*188)}px`;
    const width = host.clientWidth, height=Math.max(290,255+secondary.length*30);
    host.style.height=`${height}px`;
    const x = i => nodes.length===1 ? width/2-77 : 12+i*(width-178)/(nodes.length-1);
    const format=value=>value===null || value===undefined ? '—' : Number(value).toLocaleString('ko-KR',{maximumFractionDigits:2});
    const seconds=value=>value===null ? '표본 없음' : `${format(value)}초`;
    const rate=value=>value===null || value===undefined ? '집계 불가' : `${(value*100).toFixed(1)}%`;
    const unit=flow.count_unit || '명';
    const {svgElement} = window.TGMonitorCharts;
    const svg = svgElement('svg', {viewBox:`0 0 ${width} ${height}`, class:'mp-flow-svg', 'aria-hidden':'true'});
    const defs = svgElement('defs');
    for (const [id,color] of [['blue','#7fa4ef'],['purple','#9d8dc8'],['amber','#c8a657'],['gray','#a1afc2']]) {
      const marker=svgElement('marker',{id:`mp-arrow-${id}`,viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:5,markerHeight:5,orient:'auto'});
      marker.append(svgElement('path',{d:'M0 0 L10 5 L0 10 Z',fill:color})); defs.append(marker);
    }
    svg.append(defs); host.replaceChildren(svg);
    const detail = document.getElementById('mp-flow-detail');
    function show(text) { detail.textContent = text; }
    let lane=0;
    routes.forEach(edge=>{
      const source=byId.get(edge.source), target=byId.get(edge.target);
      if(!source || (!target && edge.kind!=='cancel')) {
        show('일부 연결 정보의 단계 식별자를 확인할 수 없습니다.'); return;
      }
      const adjacent=edge.kind==='forward' && target.index===source.index+1;
      const button=document.createElement('button'); button.type='button';
      const labels={forward:'진행',backward:'뒤로 이동',retry:'재시도',cancel:'취소'};
      let buttonLeft, buttonTop;
      if(adjacent) {
        const from=x(source.index)+154,to=x(target.index);
        svg.append(svgElement('path',{d:`M${from} 146 L${to-4} 146`,class:'mp-forward-path',
          'stroke-width':Math.max(2,(edge.ratio || 0)*4),'marker-end':'url(#mp-arrow-blue)'}));
        button.className='mp-edge-button'; buttonLeft=(from+to)/2-16;
        button.textContent=edge.ratio===null ? '—' : rate(edge.ratio);
      } else {
        button.className=`mp-route-button ${edge.kind}`;
        const color=edge.kind==='retry'?'#c8a657':edge.kind==='cancel'?'#a1afc2':'#9d8dc8';
        const arrow=edge.kind==='retry'?'amber':edge.kind==='cancel'?'gray':'purple';
        let path;
        if(edge.kind==='retry' && source.id===target?.id) {
          const xx=x(source.index); path=`M${xx+35} 77 C${xx+35} 21 ${xx+118} 21 ${xx+118} 77`;
          buttonLeft=xx+20; buttonTop=15;
        } else {
          const yy=246+lane++*30, from=x(source.index)+77, to=target ? x(target.index)+77 : from;
          path=target ? `M${from} 214 C${from} ${yy+15} ${to} ${yy+15} ${to} 214` : `M${from} 214 L${from} ${yy-4}`;
          buttonLeft=Math.max(0,Math.min(width-140,(from+to)/2-55)); buttonTop=yy+3;
        }
        svg.append(svgElement('path',{d:path,class:'mp-secondary-path',stroke:color,'marker-end':`url(#mp-arrow-${arrow})`}));
        button.textContent=`${edge.label || labels[edge.kind]} ${format(edge.moves ?? edge.count)}건`;
      }
      button.style.left=`${buttonLeft}px`; if(buttonTop!==undefined) button.style.top=`${buttonTop}px`;
      const targetLabel=target?.label || '취소';
      const evidence=edge.denominator===undefined ? '' : ` / 진입 ${format(edge.denominator)}건 · 전환율 ${rate(edge.ratio)}`;
      const description=`${source.label} → ${targetLabel} · ${labels[edge.kind]} · 고유 이동 ${format(edge.moves ?? edge.count)}건${evidence}`;
      button.setAttribute('aria-label',description);
      button.addEventListener('click',()=>show(description)); host.append(button);
    });
    nodes.forEach((node,index)=>{
      const button=document.createElement('button'); button.type='button'; button.className=`mp-stage${node.id==='complete' ? ' mp-stage-last' : ''}`;
      button.style.left=`${x(index)}px`;
      const name=document.createElement('span'); name.className='mp-stage-name'; name.textContent=node.label;
      name.title=node.label;
      const count=document.createElement('span'); count.className='mp-stage-count'; count.textContent=node.current;
      const suffix=document.createElement('small'); suffix.textContent=unit; count.append(suffix);
      const times=document.createElement('span'); times.className='mp-stage-times'; times.textContent=node.samples===0 ? '완료 체류 표본 없음' : `평균 ${seconds(node.mean)} / 중앙값 ${seconds(node.median)}`;
      button.append(name,count,times);
      button.setAttribute('aria-label',`${node.label}, 현재 ${node.current}${unit}, 체류 평균 ${seconds(node.mean)}, 중앙값 ${seconds(node.median)}, 완료 표본 ${node.samples}건`);
      button.setAttribute('aria-pressed','false');
      button.addEventListener('click',()=>{
        host.querySelectorAll('.mp-stage').forEach(other=>{ other.classList.remove('selected'); other.setAttribute('aria-pressed','false'); });
        button.classList.add('selected'); button.setAttribute('aria-pressed','true');
        show(`${node.label} · 현재 ${node.current}${unit} · 완료 체류 평균 ${seconds(node.mean)} / 중앙값 ${seconds(node.median)} · 표본 ${format(node.samples)}건 · 진행 중 ${format(node.ongoing ?? null)} · 진행 중 체류는 완료 통계에서 제외`);
      }); host.append(button);
    });
  }
  window.TGMonitorFlow = {draw};
})();
