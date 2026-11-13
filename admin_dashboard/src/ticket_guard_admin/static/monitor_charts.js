/*
[홍석환] 실제 공개 지표와 시안의 공통 시계열 그래프
실제 시각 간격·결측·0을 구분하고 많은 표본의 선택 요소 수를 제한한다.
*/
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  function svgElement(tag, attributes = {}, text = null) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== null) node.textContent = text;
    return node;
  }
  const timeLabel = value => new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul', hour:'2-digit', minute:'2-digit', hour12:false}).format(new Date(value));
  function draw(id, points, {label, unit, color = '#3971ed', percent = false, range = null}) {
    const host = document.getElementById(id);
    if (!host || !host.getBoundingClientRect().width) return;
    const width = Math.max(330, host.clientWidth), height = 224;
    const left = 44, top = 12, right = 16, bottom = 35;
    const plotWidth = width-left-right, plotHeight = height-top-bottom;
    const valid = points.filter(point => point.observed && point.value !== null);
    if(!points.length) {
      const empty=document.createElement('p'); empty.className='mp-empty-chart';
      empty.textContent='선택한 범위에 표시 가능한 관측 표본이 없습니다.';
      host.replaceChildren(empty); return;
    }
    const scale = percent ? 100 : 1;
    const maximum = Math.max(1, ...valid.map(point => point.value * scale));
    const step = percent ? 25 : Math.max(1, Math.ceil(maximum/4 / (maximum > 100 ? 25 : 1)) * (maximum > 100 ? 25 : 1));
    const ceiling = percent ? 100 : step*4;
    const start=Date.parse(range?.start || points[0].at), end=Date.parse(range?.end || points.at(-1).at);
    const xAt = time => left+(end===start ? .5 : (time-start)/(end-start))*plotWidth;
    const x = index => xAt(Date.parse(points[index].at));
    const y = value => top+plotHeight - value*scale/ceiling*plotHeight;
    const svg = svgElement('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':`${label} · 최근 12시간 · 단위 ${unit}. 미관측 구간은 선을 끊어 표시합니다.`});
    svg.append(svgElement('title', {}, label));
    const desc = svgElement('desc', {}, '표본에 초점을 이동하거나 포인터를 올리면 시간과 값, 미관측 여부와 시작 시도 없는 구간을 확인할 수 있습니다. 값이 없는 구간의 아래쪽 표식은 0을 의미하지 않습니다.');
    svg.append(desc);
    for (let i=0; i<=4; i++) {
      const yy = top+i*plotHeight/4;
      svg.append(svgElement('line', {x1:left, y1:yy, x2:width-right, y2:yy, class:'mp-grid-line'}));
      svg.append(svgElement('text', {x:left-10, y:yy+4, 'text-anchor':'end', class:'mp-axis-label'}, String(ceiling-i*ceiling/4)));
    }
    for(let tick=0;tick<=6;tick++) {
      const time=start+(end-start)*tick/6;
      svg.append(svgElement('text',{x:left+plotWidth*tick/6,y:height-9,'text-anchor':'middle',class:'mp-axis-label'},timeLabel(time)));
    }
    const segments = []; let segment = [];
    points.forEach((point,index) => {
      if (!point.observed || point.value === null) {
        if (segment.length) segments.push(segment);
        segment = [];
      } else segment.push({point,index});
    });
    if (segment.length) segments.push(segment);
    segments.forEach(group => {
      const line = group.map(({point,index},i) => `${i ? 'L' : 'M'}${x(index)},${y(point.value)}`).join(' ');
      const area = `${line} L${x(group.at(-1).index)},${top+plotHeight} L${x(group[0].index)},${top+plotHeight} Z`;
      svg.append(svgElement('path', {d:area, fill:color, 'fill-opacity':'.055'}));
      svg.append(svgElement('path', {d:line, stroke:color, 'stroke-width':2.5, fill:'none', 'stroke-linejoin':'round', 'stroke-linecap':'round'}));
    });
    const readout = document.createElement('p'); readout.className = 'mp-chart-readout';
    readout.textContent = '표본을 선택하면 해당 시점의 값을 확인할 수 있습니다.';
    readout.setAttribute('aria-live','polite');
    points.forEach((point,index) => {
      
      const stride=Math.max(1,Math.ceil(points.length/160));
      if(index%stride!==0 && index!==points.length-1 && points[index-1]?.observed!==false && points[index+1]?.observed!==false) return;
      const value = !point.observed ? '미관측' : point.value===null ? '집계 불가 · 시작 시도 없음' : percent ? `${(point.value*100).toFixed(1)}%` : `${point.value.toLocaleString('ko-KR')}${unit}`;
      const details = point.observed && point.denominator !== undefined ? ` · 성공 ${point.numerator} / 시작 ${point.denominator}건${point.ongoing === undefined ? '' : ` · 진행 중 ${point.ongoing}건`}` : '';
      const description = `${timeLabel(point.at)} KST · ${value}${details}`;
      const circle = svgElement('circle', {cx:x(index), cy:point.value===null ? top+plotHeight : y(point.value), r:3.5, fill:point.value===null ? '#e5eaf2' : '#fff', stroke:color, 'stroke-width':1.8,
        tabindex:'0', role:'img', 'aria-label':description, class:'mp-point'});
      circle.append(svgElement('title', {}, description));
      ['pointerenter','focus'].forEach(event => circle.addEventListener(event, () => { readout.textContent = description; }));
      svg.append(circle);
    });
    host.replaceChildren(svg, readout);
  }
  window.TGMonitorCharts = {draw, svgElement};
})();
