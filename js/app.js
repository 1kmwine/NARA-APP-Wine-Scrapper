/* ============================================================
   NARA Wine Intelligence JS
   ============================================================ */

/* ========== 탭 ========== */
const tabBtns=document.querySelectorAll('.tab-btn');
const tabPanels=document.querySelectorAll('.tab-panel');
tabBtns.forEach(btn=>btn.addEventListener('click',()=>{
  const tab=btn.dataset.tab;
  tabBtns.forEach(b=>b.classList.toggle('active',b===btn));
  tabPanels.forEach(p=>p.classList.toggle('active',p.id===`tab-${tab}`));
}));

/* ========== 소스 관리 ========== */
const DEFAULT_SOURCES=[
  {id:'sommelier',name:'소믈리에 타임즈',url:'https://www.sommeliertimes.com',on:true},
  {id:'wine21',name:'와인21',url:'https://www.wine21.com',on:true},
  {id:'winein',name:'와인인',url:'https://winein.co.kr',on:true},
  {id:'hankyung',name:'한국경제',url:'https://www.hankyung.com',on:true},
  {id:'mk',name:'매일경제',url:'https://www.mk.co.kr',on:false},
  {id:'chosun',name:'조선비즈',url:'https://biz.chosun.com',on:false},
  {id:'decanter',name:'Decanter',url:'https://www.decanter.com',on:true},
  {id:'ws',name:'Wine-Searcher',url:'https://www.wine-searcher.com',on:true},
  {id:'js',name:'James Suckling',url:'https://www.jamessuckling.com',on:true},
  {id:'rp',name:'Wine Advocate',url:'https://winejournal.robertparker.com',on:true},
  {id:'wspec',name:'Wine Spectator',url:'https://www.winespectator.com',on:true},
  {id:'wmag',name:'Wine Enthusiast',url:'https://www.winemag.com',on:true},
];
function loadSources(){
  try{ const s=JSON.parse(localStorage.getItem('naraSources')); if(Array.isArray(s)&&s.length) return s; }catch(e){}
  return DEFAULT_SOURCES;
}
function saveSources(){ localStorage.setItem('naraSources', JSON.stringify(sources)); }
let sources=loadSources();
const sourceList=document.getElementById('sourceList');
const sourceCount=document.getElementById('sourceCount');

function renderSources(){
  sourceList.innerHTML='';
  sources.forEach((src,i)=>{
    const label=document.createElement('label');
    label.className='source-item';
    label.innerHTML=`<input type="checkbox" ${src.on?'checked':''}> ${src.name}<span class="del" data-i="${i}">&times;</span>`;
    const cb=label.querySelector('input');
    cb.addEventListener('change',()=>{ src.on=cb.checked; saveSources(); updateCount(); });
    label.querySelector('.del').addEventListener('click',e=>{ e.stopPropagation(); sources.splice(i,1); saveSources(); renderSources(); updateCount(); });
    sourceList.appendChild(label);
  });
  updateCount();
}
function updateCount(){ sourceCount.textContent=`${sources.filter(s=>s.on).length}개 선택`; }
renderSources();

document.getElementById('btnAddSource').addEventListener('click',()=>{
  const name=document.getElementById('newSourceName').value.trim();
  const url=document.getElementById('newSourceUrl').value.trim();
  if(!name) return;
  sources.push({id:'src_'+Date.now(),name,url:url||'',on:true});
  document.getElementById('newSourceName').value='';
  document.getElementById('newSourceUrl').value='';
  saveSources(); renderSources();
});

/* ========== 스크래퍼 시뮬레이션 ========== */
const btnStart=document.getElementById('btnScrapeStart');
const btnStop=document.getElementById('btnScrapeStop');
const progress=document.getElementById('scrapeProgress');
const progressFill=document.getElementById('scrapeFill');
const progressText=document.getElementById('scrapeText');
const resultBody=document.getElementById('resultBody');
const resultBadge=document.getElementById('resultBadge');
let running=false,timer=null;

function renderResult(list){
  resultBody.innerHTML='';
  if(!list.length){ resultBody.innerHTML='<tr class="empty"><td colspan="5">검색 결과가 없습니다.</td></tr>'; resultBadge.textContent='0'; return; }
  resultBadge.textContent=list.length;
  list.forEach(item=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${item.name}</td><td>${item.brand}</td><td>${item.vintage}</td><td>${item.price}</td><td>${item.status}</td>`;
    tr.addEventListener('click',()=>showDetail(item));
    resultBody.appendChild(tr);
  });
}

btnStart.addEventListener('click',()=>{
  if(running) return;
  const wineName=document.getElementById('wineName').value.trim();
  if(!wineName){ alert('와인명을 입력해주세요.'); return; }
  running=true; btnStart.disabled=true; btnStop.disabled=false; progress.classList.remove('hidden');
  const active=sources.filter(s=>s.on);
  const total=active.length*3; let done=0;
  const results=[];
  let idx=0;
  function next(){
    if(!running||idx>=total){ finish(); return; }
    const src=active[Math.floor(idx/3)];
    idx++; done++;
    progressFill.style.width=`${(done/total)*100}%`;
    progressText.textContent=`${done} / ${total}`;
    results.push({
      name:`${wineName} ${idx}`,
      brand:document.getElementById('wineBrand').value.trim()||'-',
      vintage:2018+Math.floor(Math.random()*6),
      price:'₩'+(Math.floor(Math.random()*15)+5)+'0,000',
      status:'완료',
      region:'Napa Valley',
      variety:'Cabernet Sauvignon'
    });
    renderResult(results.slice());
    timer=setTimeout(next, 300+Math.random()*400);
  }
  function finish(){ running=false; btnStart.disabled=false; btnStop.disabled=true; timer=null; }
  next();
});
btnStop.addEventListener('click',()=>{
  running=false; if(timer) clearTimeout(timer); timer=null;
  btnStart.disabled=false; btnStop.disabled=true; progress.classList.add('hidden');
});

const overlay=document.getElementById('detailOverlay');
document.getElementById('closeDetail').addEventListener('click',()=>overlay.classList.add('hidden'));
overlay.addEventListener('click',e=>{ if(e.target===overlay) overlay.classList.add('hidden'); });
function showDetail(item){
  document.getElementById('detailTitle').textContent=item.name;
  const dl=document.getElementById('detailList');
  dl.innerHTML='';
  Object.entries(item).forEach(([k,v])=>{ const dt=document.createElement('dt'); dt.textContent=k; const dd=document.createElement('dd'); dd.textContent=v; dl.appendChild(dt); dl.appendChild(dd); });
  overlay.classList.remove('hidden');
}

/* ============================================================
   데일리 브리핑 — 주간 달력
   ============================================================ */
const DAY_LABELS=['월','화','수','목','금','토','일'];

/* 데모: 날짜 → 브리핑 데이터 매핑 (2주치)
   실제로는 API/JSON에서 받아오거나 localStorage에 저장 */
function generateDemoData(){
  const data={};
  const base=new Date();
  for(let d=-14; d<=14; d++){
    const dt=new Date(base); dt.setDate(base.getDate()+d);
    const key=fmtDateKey(dt);
    data[key]=createDayBriefing(dt, d===0);
  }
  return data;
}
function fmtDateKey(d){ return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function createDayBriefing(date, isToday){
  const rand=n=>Math.floor(Math.random()*(n+1));
  const count=isToday?58:rand(45);
  return {
    count,
    isToday,
    sections:{
      domestic:rand(isToday?14:8),
      newsroom:rand(isToday?12:6),
      cafe:rand(isToday?10:5),
      youtube:rand(isToday?10:5),
      blog:rand(isToday?12:7),
      global:rand(isToday?0:3),
    },
    items:{
      domestic:[
        {title:"[와인21] 리오하 와인이 지금 걷고 있는 '제3의 길'",url:"#",new:!isToday,desc:"시간과 장소의 문제 와인의 가치를 장소에 둘 것인가 시간에 둘 것인가."},
        {title:"[한국경제] 해외에 K소주 알리는 'LA 문화의 여왕'",url:"#",new:isToday,desc:'차례"라며 "한국이 문화·경제적으로 커진 만큼..."'},
        {title:'[한국경제] "美 로버트 몬다비, 유행보다 전통 고수"',url:"#",new:false,desc:"어제보다 더 강해져야 한다는 단순한 생각이 60년의 역사를 만들었습니다."},
      ].slice(0,isToday?3:rand(3)),
      newsroom:[
        {title:"[나라셀라 칼럼] 칠레 화이트 와인 추천｜몬테스가 제시하는 태평양 쿨-클라이밋",url:"#",new:false},
        {title:"[나라셀라 칼럼] 페스테벌 와인 추천 2026 | 뮤직·워터밤·락·바다축제 무드별 추천와인 4선",url:"#",new:false},
      ].slice(0,isToday?2:rand(2)),
      cafe:[
        {title:"크룩 질문이요! 💬17",url:"#",new:isToday,desc:"와인에대해 잘모르는 와린이지만 크룩이 유명하고 맛있다고해서..."},
        {title:"일본 후쿠오카 르셉 가격 봐주세요 💬15",url:"#",new:isToday},
      ].slice(0,isToday?2:rand(2)),
      youtube:[
        {title:"[비밀이야] [CEO의 삶] 비밀이야의 밀착 24시간",url:"#",new:false,meta:"1일 전·조회수 8.9만회"},
        {title:'[양갱] "이 좋은걸 몰랐다니!" 일본 후쿠오카 보르도 와인 페스티벌',url:"#",new:false,meta:"14시간 전·1.5천"},
      ].slice(0,isToday?2:rand(2)),
      blog:[
        {title:"부산 광안리데이트 뉼리｜결혼기념일을 더욱 특별하게",url:"#",new:isToday,desc:"또 하나 인상 깊었던 건 입구를 지나면 와인 창고 같은 공간이 보여요.",time:"6분 전"},
        {title:"횡성 반값여행 저문강에 삽을 씻고 정식 먹으러",url:"#",new:isToday,desc:"와인 에이드 : 4,000원 저문강 정식 : 16,000원",time:"6분 전"},
      ].slice(0,isToday?2:rand(2)),
      global:[
        {title:"[Decanter] 디캔터의 새로운 북미 지역 에디터를 만나보세요",url:"#",new:false,desc:"당첨자 발표..."},
        {title:"[Wine Spectator] 로제, 응. 하지만 어느 것?",url:"#",new:false,desc:"2025 빈티지는 프랑스 남부의 다양한 스타일, 색상, 품질을 제공합니다."},
        {title:"[OIV] 포도재배 부서장 채용 제안",url:"#",new:false},
      ].slice(0,isToday?3:rand(3)),
    }
  };
}

const briefingData=generateDemoData();
let currentWeekStart=getWeekStart(new Date());

/* 해당 날짜가 속한 주의 월요일 구하기 */
function getWeekStart(d){
  const dt=new Date(d);
  const day=dt.getDay(); // 0=일, 1=월,...
  const diff=day===0?-6:1-day;
  dt.setDate(dt.getDate()+diff);
  dt.setHours(0,0,0,0);
  return dt;
}
function addDays(d,n){ const dt=new Date(d); dt.setDate(dt.getDate()+n); return dt; }
function fmtMonthDay(d){ return `${d.getMonth()+1}/${d.getDate()}`; }

/* 주 네비게이션 렌더링 */
function renderWeekNav(){
  const start=currentWeekStart;
  const end=addDays(start,6);
  const year=start.getFullYear();
  const month=start.getMonth()+1;
  const weekNum=Math.ceil(start.getDate()/7); // 단순 근사
  document.getElementById('weekLabel').textContent=`${year}년 ${month}월 ${weekNum}주차`;
  document.getElementById('weekRange').textContent=`${fmtMonthDay(start)} ~ ${fmtMonthDay(end)}`;
}

/* 주간 달력 렌더링 */
function renderCalendar(){
  const grid=document.getElementById('weekCalendar');
  grid.innerHTML='';
  for(let i=0;i<7;i++){
    const cellDate=addDays(currentWeekStart,i);
    const key=fmtDateKey(cellDate);
    const data=briefingData[key]||{count:0,sections:{},isToday:false,items:{}};
    const isToday=data.isToday;
    const hasNew=Object.values(data.sections||{}).some(v=>v>0);

    const cell=document.createElement('div');
    cell.className='calendar-cell'+(isToday?' today':'')+(data.count===0?' empty':'');
    cell.dataset.date=key;

    let countHtml='';
    if(data.count>0){
      const parts=[];
      Object.entries(data.sections||{}).forEach(([k,v])=>{ if(v>0) parts.push(`${sectionLabel(k)} ${v}`); });
      countHtml=parts.length?`<div class="day-count">${parts.slice(0,2).join('<br>')}</div>`:`<div class="day-count">${data.count}건</div>`;
    }else{
      countHtml='<div class="day-count">—</div>';
    }

    cell.innerHTML=`
      <div class="day-name">${DAY_LABELS[i]}</div>
      <div class="day-num">${cellDate.getDate()}</div>
      ${countHtml}
      ${isToday?'<div class="has-new" title="오늘"></div>':''}
    `;

    if(data.count>0){
      cell.addEventListener('click',()=>{ showBriefingDetail(key, cellDate); });
    }
    grid.appendChild(cell);
  }
}

function sectionLabel(key){
  const map={domestic:'📰',newsroom:'🏛',cafe:'🍷',youtube:'🎬',blog:'📝',global:'🌐'};
  return map[key]||key;
}

/* 날짜 클릭 시 상세 브리핑 표시 */
function showBriefingDetail(dateKey, dateObj){
  const data=briefingData[dateKey];
  if(!data) return;

  // 달력 선택 상태
  document.querySelectorAll('.calendar-cell').forEach(c=>c.classList.remove('selected'));
  const selected=document.querySelector(`.calendar-cell[data-date="${dateKey}"]`);
  if(selected) selected.classList.add('selected');

  // 상세 패널 표시
  const detail=document.getElementById('briefingDetail');
  detail.classList.remove('hidden');

  const wd=['일','월','화','수','목','금','토'];
  document.getElementById('detailDateLabel').textContent=
    `${dateObj.getFullYear()}.${String(dateObj.getMonth()+1).padStart(2,'0')}.${String(dateObj.getDate()).padStart(2,'0')} (${wd[dateObj.getDay()]}) 브리핑`;
  document.getElementById('detailTotal').textContent=data.count;

  // 태그
  const tags=Object.entries(data.sections||{})
    .filter(([_,v])=>v>0)
    .map(([k,v])=>`<span class="tag">${sectionLabel(k)} ${v}</span>`)
    .join('');
  document.getElementById('detailTags').innerHTML=tags;

  // 각 섹션 아이템
  function renderSection(elId, key){
    const el=document.getElementById(elId);
    const items=(data.items&&data.items[key])||[];
    if(!items.length){ el.innerHTML='<li class="empty">수집된 항목이 없습니다.</li>'; return; }
    el.innerHTML=items.map(item=>{
      const newb=item.new?'<span class="new-badge">NEW</span>':'';
      const meta=item.meta?` <span style="color:var(--color-text-faintest)">${item.meta}</span>`:'';
      const desc=item.desc?`<div class="desc">${item.desc}</div>`:'';
      return `<li>${newb}<a href="${item.url}" target="_blank">${item.title}</a>${meta}${desc}</li>`;
    }).join('');
  }
  renderSection('detailDomestic','domestic');
  renderSection('detailNewsroom','newsroom');
  renderSection('detailCafe','cafe');
  renderSection('detailYoutube','youtube');
  renderSection('detailBlog','blog');
  renderSection('detailGlobal','global');

  // 스크롤 이동
  detail.scrollIntoView({behavior:'smooth', block:'start'});
}

/* 주 네비게이션 */
document.getElementById('btnPrevWeek').addEventListener('click',()=>{
  currentWeekStart=addDays(currentWeekStart,-7);
  refreshWeek();
});
document.getElementById('btnNextWeek').addEventListener('click',()=>{
  currentWeekStart=addDays(currentWeekStart,7);
  refreshWeek();
});

function refreshWeek(){
  renderWeekNav();
  renderCalendar();
  document.getElementById('briefingDetail').classList.add('hidden');
}

/* 초기 렌더 */
renderWeekNav();
renderCalendar();
