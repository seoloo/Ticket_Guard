const items = window.previewPosts || [
  {category:'서비스 안내', title:'안전한 예매를 위한 이용 안내', date:'2026.11.10', views:128, pinned:true, description:'예매 전 확인하면 좋은 안내를 모았습니다.\n\n공연 일정과 관람 정보를 확인하고, 본인 계정으로 예매를 진행해 주세요. 이 글은 시안 확인용 예시입니다.'},
  {category:'점검 안내', title:'서비스 정기 점검 안내', date:'2026.11.09', views:96, pinned:true, description:'더 안정적인 서비스 제공을 위한 정기 점검 안내입니다. 점검 시간과 대상 기능은 실제 공지 등록 시 안내합니다.'},
  {category:'예매 안내', title:'공연별 예매 오픈 일정 확인 방법', date:'2026.11.08', views:84, description:'공연 상세 화면에서 예매 일시와 관람 정보를 확인할 수 있습니다.'},
  {category:'서비스 안내', title:'티켓가드 이용을 환영합니다', date:'2026.11.07', views:72, description:'좋아하는 무대와 만나는 순간, 티켓가드의 새 소식을 이곳에서 확인하세요.'},
  {category:'예매 안내', title:'지정석과 자유석 예매 안내', date:'2026.11.06', views:65, description:'지정석은 좌석을, 자유석은 관람 인원을 선택합니다. 예매 전 공연별 안내를 확인해 주세요.'},
  {category:'서비스 안내', title:'예매 내역 확인 방법', date:'2026.11.05', views:49, description:'로그인 후 상단 예매 내역 메뉴에서 예매 결과를 확인할 수 있습니다.'}
];
let category='전체';
const list=document.querySelector('[data-notices]');
const variant=document.body.dataset.variant;
function render(){
  const q=document.querySelector('input[type="search"]').value.trim();
  const matches=items.filter(item=>(category==='전체'||item.category===category)&&item.title.includes(q));
  list.replaceChildren();
  document.querySelector('[data-count]').textContent=matches.length;
  for(const item of matches){
    const button=document.createElement('button');
    button.type='button';
    button.style.textAlign='left';
    button.style.fontFamily='inherit';
    if(variant==='a'){
      button.className='notice-row'+(item.pinned?' pinned':'');
      button.style.width='100%';button.style.borderRight='0';button.style.borderLeft='0';button.style.borderBottom='0';
      button.innerHTML=`<div class="number">${item.pinned?'<span class="badge">중요</span>':items.length-items.indexOf(item)}</div><div class="title">${item.title}${items.indexOf(item)===0?'<span class="new">NEW</span>':''}</div>${document.body.dataset.board==='free'?`<div class="author">${item.author}</div>`:''}<div class="date">${item.date}</div><div class="views">${item.views}</div>`;
    }else{
      button.className='notice-card';
      button.innerHTML=`<div class="card-top"><span class="badge">${item.category}</span>${item.pinned?'<span class="new">중요 공지</span>':''}</div><h3>${item.title}</h3><p>${item.description.split('\n')[0]}</p><div class="card-date"><time>${item.date}</time><span>자세히 보기 ↗</span></div>`;
    }
    button.addEventListener('click',()=>openNotice(item));list.append(button);
  }
  if(!matches.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='검색 결과가 없습니다.';list.append(empty);}
}
function openNotice(item){const dialog=document.querySelector('dialog');dialog.querySelector('h2').textContent=item.title;dialog.querySelector('time').textContent=item.date;dialog.querySelector('p').textContent=item.description;dialog.showModal();}
document.querySelectorAll('[data-category]').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.category;document.querySelectorAll('[data-category]').forEach(tab=>{tab.classList.toggle('active',tab===button);tab.setAttribute('aria-pressed',String(tab===button));});render();}));
document.querySelector('.search').addEventListener('submit',event=>{event.preventDefault();render();});
document.querySelector('input[type="search"]').addEventListener('input',render);
document.querySelector('dialog button').addEventListener('click',()=>document.querySelector('dialog').close());
document.querySelector('[data-featured]')?.addEventListener('click',()=>openNotice(items[0]));
render();
