/* ============================================================
   NARA Wine Intelligence — 와인 스크래퍼 + 데일리 브리핑
   ============================================================ */

/* ========== 탭 ========== */
const tabBtns=document.querySelectorAll('.tab-btn');
const tabPanels=document.querySelectorAll('.tab-panel');
tabBtns.forEach(btn=>btn.addEventListener('click',()=>{
  const tab=btn.dataset.tab;
  tabBtns.forEach(b=>b.classList.toggle('active',b===btn));
  tabPanels.forEach(p=>p.classList.toggle('active',p.id===`tab-${tab}`));
}));

/* ========== API 기본 ========== */
const API_BASE = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? 'http://localhost:8001'
  : 'api';

/* 백엔드 run_job(jobs.py)의 카테고리 처리 순서와 반드시 일치해야 한다 —
   뉴스 → 유튜브 → 와쌉 → 해외소스. 진행률 뷰가 누적 done 값을 이 순서로
   구간별로 나눠 계산하기 때문(아래 computeProgressRows 참고). */
const CATEGORY_META=[
  {key:'news', label:'뉴스·매거진'},
  {key:'youtube', label:'유튜브'},
  {key:'wassap', label:'와쌉카페'},
  {key:'international', label:'해외소스'},
];

/* ========== 스크래퍼: DOM 참조 ========== */
const searchView=document.getElementById('scraperSearchView');
const progressView=document.getElementById('scraperProgressView');
const resultsView=document.getElementById('scraperResultsView');
const queryInput=document.getElementById('queryInput');
const searchSubtitle=document.getElementById('searchSubtitle');
const recentQueriesEl=document.getElementById('recentQueries');
const btnStartSearch=document.getElementById('btnStartSearch');
const progressQueryEl=document.getElementById('progressQuery');
const progressDoneEl=document.getElementById('progressDone');
const progressTotalEl=document.getElementById('progressTotal');
const progressBarFill=document.getElementById('progressBarFill');
const progressRowsEl=document.getElementById('progressRows');
const resultsQueryEl=document.getElementById('resultsQuery');
const resultsCountEl=document.getElementById('resultsCount');
const resultsFailuresBlock=document.getElementById('resultsFailures');
const failureCountEl=document.getElementById('failureCount');
const failuresListEl=document.getElementById('failuresList');
const failuresToggleLabelEl=document.getElementById('failuresToggleLabel');
const btnToggleFailures=document.getElementById('btnToggleFailures');
const resultsGroupsEl=document.getElementById('resultsGroups');
const btnResetSearch=document.getElementById('btnResetSearch');

let sourceCounts={news:0, youtube:0, wassap:0, international:0};
let pollTimer=null, pollDeadline=null;
const POLL_TIMEOUT_MS=60000;

function showScraperView(name){
  searchView.classList.toggle('hidden', name!=='search');
  progressView.classList.toggle('hidden', name!=='progress');
  resultsView.classList.toggle('hidden', name!=='results');
}

/* ---- 소스 개수/이름 로드 (검색 화면 문구 + 소스 패널 "등록된 소스"용) ---- */
async function loadSourceCounts(){
  try{
    const res=await fetch(`${API_BASE}/sources`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const body=await res.json();
    sourceCounts=body.counts;
    renderSearchSubtitle();
    renderExistingSources(body.names);
  }catch(e){
    searchSubtitle.textContent='소스 정보를 불러오지 못했습니다.';
  }
}

function renderSearchSubtitle(){
  const total=Object.values(sourceCounts).reduce((a,b)=>a+b,0);
  const parts=CATEGORY_META.map(c=>`${c.label} ${sourceCounts[c.key]||0}`).join(' · ');
  searchSubtitle.textContent=`등록된 소스 ${total}개 전체 대상 · ${parts}`;
}

/* ---- 최근 검색어 (localStorage) ---- */
const RECENT_QUERIES_KEY='naraRecentQueries';
function getRecentQueries(){
  try{ const v=JSON.parse(localStorage.getItem(RECENT_QUERIES_KEY)); return Array.isArray(v)?v:[]; }catch(e){ return []; }
}
function addRecentQuery(q){
  const list=getRecentQueries().filter(x=>x!==q);
  list.unshift(q);
  localStorage.setItem(RECENT_QUERIES_KEY, JSON.stringify(list.slice(0,5)));
  renderRecentQueries();
}
function renderRecentQueries(){
  recentQueriesEl.innerHTML='';
  getRecentQueries().forEach(q=>{
    const btn=document.createElement('button');
    btn.className='recent-chip';
    btn.textContent=q;
    btn.addEventListener('click',()=>{ queryInput.value=q; });
    recentQueriesEl.appendChild(btn);
  });
}

/* ---- 검색 시작 ---- */
async function startSearch(){
  const query=queryInput.value.trim();
  if(!query){ alert('와인명 또는 브랜드를 입력해주세요.'); return; }
  addRecentQuery(query);
  progressQueryEl.textContent=`"${query}"`;
  progressDoneEl.textContent='0';
  progressTotalEl.textContent='0';
  progressBarFill.style.width='0%';
  progressRowsEl.innerHTML='';
  showScraperView('progress');

  try{
    const res=await fetch(`${API_BASE}/jobs`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({wine_name:query, brand:''}),
    });
    if(!res.ok){ const body=await res.json().catch(()=>({})); throw new Error(body.detail||`HTTP ${res.status}`); }
    const {job_id}=await res.json();
    pollDeadline=Date.now()+POLL_TIMEOUT_MS;
    pollJob(job_id, query);
  }catch(e){
    alert(`검색 시작 실패: ${e.message}`);
    showScraperView('search');
  }
}
btnStartSearch.addEventListener('click', startSearch);
queryInput.addEventListener('keydown', e=>{ if(e.key==='Enter') startSearch(); });

/* ---- 진행률: 누적 done을 카테고리 순서(뉴스→유튜브→와쌉→해외소스)로 구간 분할 ---- */
function computeProgressRows(done){
  let remaining=done;
  return CATEGORY_META.map(c=>{
    const total=sourceCounts[c.key]||0;
    const rowDone=Math.max(0, Math.min(total, remaining));
    remaining=Math.max(0, remaining-total);
    return {label:c.label, done:rowDone, total, complete: total>0 && rowDone>=total, spinning: rowDone<total};
  });
}

function renderProgressRows(done){
  const rows=computeProgressRows(done);
  progressRowsEl.innerHTML='';
  rows.forEach(row=>{
    const div=document.createElement('div');
    div.className='progress-row';
    const indicator = row.total===0 ? ''
      : row.complete ? '<div class="check-badge">✓</div>'
      : row.spinning ? '<div class="spinner"></div>' : '';
    div.innerHTML=`
      <div class="progress-row-label">${row.label}</div>
      <div class="progress-row-right">
        <div class="progress-row-count">${row.done}/${row.total}</div>
        ${indicator}
      </div>`;
    progressRowsEl.appendChild(div);
  });
}

async function pollJob(jobId, query){
  if(Date.now()>pollDeadline){
    if(pollTimer) clearTimeout(pollTimer);
    alert('60초 안에 끝나지 않아 중단했습니다. 다시 시도해주세요.');
    showScraperView('search');
    return;
  }
  try{
    const res=await fetch(`${API_BASE}/jobs/${jobId}`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const job=await res.json();
    progressDoneEl.textContent=job.done;
    progressTotalEl.textContent=job.total;
    progressBarFill.style.width=`${job.total?(job.done/job.total)*100:0}%`;
    renderProgressRows(job.done);

    if(job.status==='succeeded'||job.status==='partial'||job.status==='failed'){
      if(job.status==='failed'){
        alert(`스크래핑 실패: ${job.error||'알 수 없는 오류'}`);
        showScraperView('search');
        return;
      }
      renderResultsView(query, job.results, job.failures||[]);
      showScraperView('results');
      return;
    }
    pollTimer=setTimeout(()=>pollJob(jobId, query), 1000);
  }catch(e){
    alert(`상태 조회 실패: ${e.message}`);
    showScraperView('search');
  }
}

/* ---- 카드 그리드 렌더링 (스크래퍼 결과 뷰 + 데일리 브리핑 상세가 공유) ---- */
function groupByCategory(items){
  const groups={};
  CATEGORY_META.forEach(c=>{ groups[c.key]=[]; });
  items.forEach(item=>{ (groups[item.source_category]||(groups[item.source_category]=[])).push(item); });
  return groups;
}

function itemInitial(sourceName){
  return (sourceName||'').replace('YouTube: ','').charAt(0) || '?';
}

function renderResultGroups(container, items){
  // title/excerpt/source_name은 스크래핑된 외부 콘텐츠이므로 innerHTML이 아니라
  // textContent로만 채운다 — HTML 인젝션을 원천 차단하기 위해서다.
  const groups=groupByCategory(items);
  container.innerHTML='';
  CATEGORY_META.forEach(c=>{
    const groupItems=groups[c.key]||[];
    if(!groupItems.length) return;

    const groupEl=document.createElement('div');
    groupEl.className='result-group';
    const groupTitle=document.createElement('div');
    groupTitle.className='result-group-title';
    const countSpan=document.createElement('span');
    countSpan.className='result-group-count';
    countSpan.textContent=groupItems.length;
    groupTitle.textContent=c.label+' ';
    groupTitle.appendChild(countSpan);
    groupEl.appendChild(groupTitle);

    const grid=document.createElement('div');
    grid.className='result-grid';
    groupItems.forEach(item=>{
      const a=document.createElement('a');
      a.href=item.external_url || '#';
      a.target='_blank';
      a.rel='noopener';
      a.className='result-card';

      const avatar=document.createElement('div');
      avatar.className='result-card-avatar';
      avatar.textContent=itemInitial(item.source_name);

      const body=document.createElement('div');
      body.className='result-card-body';

      const title=document.createElement('div');
      title.className='result-card-title';
      title.textContent=item.title;

      const excerpt=document.createElement('div');
      excerpt.className='result-card-excerpt';
      excerpt.textContent=item.excerpt||'';

      body.appendChild(title);
      body.appendChild(excerpt);

      if((item.matched_brands||[]).length){
        const chipsWrap=document.createElement('div');
        chipsWrap.className='result-card-chips';
        item.matched_brands.forEach(b=>{
          const chip=document.createElement('span');
          chip.className='result-card-chip';
          chip.textContent=b;
          chipsWrap.appendChild(chip);
        });
        body.appendChild(chipsWrap);
      }

      const meta=document.createElement('div');
      meta.className='result-card-meta';
      const src=document.createElement('span'); src.textContent=item.source_name;
      const date=document.createElement('span'); date.textContent=item.published_date||'';
      meta.appendChild(src); meta.appendChild(date);
      body.appendChild(meta);

      a.appendChild(avatar);
      a.appendChild(body);
      grid.appendChild(a);
    });
    groupEl.appendChild(grid);
    container.appendChild(groupEl);
  });
}

function renderResultsView(query, results, failures){
  resultsQueryEl.textContent=query;
  resultsCountEl.textContent=`${results.length}건 수집됨`;
  renderResultGroups(resultsGroupsEl, results);

  if(failures.length){
    resultsFailuresBlock.classList.remove('hidden');
    failureCountEl.textContent=failures.length;
    failuresListEl.innerHTML='';
    failures.forEach(f=>{
      const row=document.createElement('div');
      row.className='failure-row';
      const s1=document.createElement('span'); s1.textContent=f.source_name;
      const s2=document.createElement('span'); s2.textContent=f.reason;
      row.appendChild(s1); row.appendChild(s2);
      failuresListEl.appendChild(row);
    });
  }else{
    resultsFailuresBlock.classList.add('hidden');
  }
  failuresListEl.classList.add('hidden');
  failuresToggleLabelEl.textContent='보기';
}

btnToggleFailures.addEventListener('click', ()=>{
  const open=failuresListEl.classList.toggle('hidden');
  failuresToggleLabelEl.textContent = open ? '보기' : '닫기';
});

btnResetSearch.addEventListener('click', ()=>{
  queryInput.value='';
  showScraperView('search');
  loadSourceCounts();
});

/* ========== 소스 추가 패널 ========== */
const sourceOverlay=document.getElementById('sourceOverlay');
const sourcePanel=document.getElementById('sourcePanel');
const btnOpenSourcePanel=document.getElementById('btnOpenSourcePanel');
const btnCloseSourcePanel=document.getElementById('btnCloseSourcePanel');
const sourceCatRow=document.getElementById('sourceCatRow');
const sourceFieldsEl=document.getElementById('sourceFields');
const sourceHelperEl=document.getElementById('sourceHelper');
const btnSubmitSource=document.getElementById('btnSubmitSource');
const sourceExistingGroupsEl=document.getElementById('sourceExistingGroups');
const sourceAddedBlock=document.getElementById('sourceAddedBlock');
const sourceAddedListEl=document.getElementById('sourceAddedList');
const toastEl=document.getElementById('toast');

/* 각 카테고리의 필드 key는 backend/app/main.py의 AddSourceRequest 필드명과
   정확히 일치해야 한다(Task 11/12 참고) — payload를 그대로 JSON.stringify해서
   보낸다. */
const SOURCE_FIELD_DEFS={
  news:[
    {key:'press', label:'매체명', placeholder:'예: 와인나라'},
    {key:'news_category', label:'분류 (뉴스/매거진)', placeholder:'예: 매거진'},
    {key:'query', label:'검색어', placeholder:'예: 뒤가피'},
    {key:'url', label:'URL', placeholder:'https://...'},
  ],
  youtube:[
    {key:'channel_name', label:'채널명', placeholder:'예: 소믈리에 리나'},
    {key:'url', label:'채널 URL', placeholder:'https://youtube.com/@...'},
    {key:'channel_id', label:'Channel ID (선택)', placeholder:'비우면 자동 추출 시도'},
  ],
  wassap:[
    {key:'url', label:'카페 URL', placeholder:'https://cafe.naver.com/...'},
    {key:'clubid', label:'clubid', placeholder:'예: 10050146'},
  ],
  international:[
    {key:'source_name', label:'소스명', placeholder:'예: Wine Spectator'},
    {key:'url', label:'URL', placeholder:'https://...'},
    {key:'note', label:'비고 (선택)', placeholder:''},
  ],
};
const SOURCE_HELPERS={
  news:'', youtube:'Channel ID는 URL에서 자동 추출을 시도합니다. 실패하면 직접 입력해주세요.', wassap:'', international:'',
};

let sourceCategory='news';
let addedSources=[];

function openSourcePanel(){
  sourceOverlay.classList.remove('hidden');
  sourcePanel.classList.remove('hidden');
  renderSourceCategories();
  renderSourceFields();
}
function closeSourcePanel(){
  sourceOverlay.classList.add('hidden');
  sourcePanel.classList.add('hidden');
}
btnOpenSourcePanel.addEventListener('click', openSourcePanel);
btnCloseSourcePanel.addEventListener('click', closeSourcePanel);
sourceOverlay.addEventListener('click', closeSourcePanel);

function renderSourceCategories(){
  sourceCatRow.innerHTML='';
  CATEGORY_META.forEach(c=>{
    const btn=document.createElement('button');
    btn.className='source-cat-pill'+(sourceCategory===c.key?' active':'');
    btn.textContent=c.label;
    btn.addEventListener('click', ()=>{ sourceCategory=c.key; renderSourceCategories(); renderSourceFields(); });
    sourceCatRow.appendChild(btn);
  });
}

function renderSourceFields(){
  const fields=SOURCE_FIELD_DEFS[sourceCategory]||[];
  sourceFieldsEl.innerHTML='';
  fields.forEach(f=>{
    const wrap=document.createElement('div');
    const label=document.createElement('div');
    label.className='source-field-label';
    label.textContent=f.label;
    const input=document.createElement('input');
    input.type='text'; input.id=`srcfield_${f.key}`; input.className='input'; input.placeholder=f.placeholder||'';
    wrap.appendChild(label); wrap.appendChild(input);
    sourceFieldsEl.appendChild(wrap);
  });
  const helper=SOURCE_HELPERS[sourceCategory];
  sourceHelperEl.textContent=helper||'';
  sourceHelperEl.classList.toggle('hidden', !helper);
}

async function submitSourceForm(){
  const fields=SOURCE_FIELD_DEFS[sourceCategory]||[];
  const payload={category:sourceCategory};
  fields.forEach(f=>{ payload[f.key]=document.getElementById(`srcfield_${f.key}`).value.trim(); });
  const catMeta=CATEGORY_META.find(c=>c.key===sourceCategory);
  const displayName=payload.press||payload.channel_name||payload.source_name||payload.url||'새 소스';

  try{
    const res=await fetch(`${API_BASE}/sources`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload),
    });
    const body=await res.json().catch(()=>({}));
    if(!res.ok){ throw new Error(body.detail||`HTTP ${res.status}`); }

    addedSources.unshift({name:displayName, category:catMeta.label});
    renderAddedSources();
    fields.forEach(f=>{ document.getElementById(`srcfield_${f.key}`).value=''; });
    showToast(`"${displayName}" 소스가 scraping-sources.md에 추가되었습니다.`);
    loadSourceCounts();
  }catch(e){
    showToast(`추가 실패: ${e.message}`);
  }
}
btnSubmitSource.addEventListener('click', submitSourceForm);

function renderAddedSources(){
  if(!addedSources.length){ sourceAddedBlock.classList.add('hidden'); return; }
  sourceAddedBlock.classList.remove('hidden');
  sourceAddedListEl.innerHTML='';
  addedSources.forEach(a=>{
    const row=document.createElement('div');
    row.className='source-added-row';
    const s1=document.createElement('span'); s1.textContent=a.name;
    const s2=document.createElement('span'); s2.textContent=a.category;
    row.appendChild(s1); row.appendChild(s2);
    sourceAddedListEl.appendChild(row);
  });
}

function renderExistingSources(names){
  sourceExistingGroupsEl.innerHTML='';
  CATEGORY_META.forEach(c=>{
    const list=(names && names[c.key]) || [];
    const group=document.createElement('div');
    group.className='source-existing-group';
    const head=document.createElement('div');
    head.className='source-existing-group-head';
    head.textContent=c.label+' ';
    const count=document.createElement('span');
    count.className='source-existing-count';
    count.textContent=list.length;
    head.appendChild(count);
    const namesEl=document.createElement('div');
    namesEl.className='source-existing-names';
    list.forEach(n=>{
      const d=document.createElement('div');
      d.className='source-existing-name';
      d.textContent=n;
      namesEl.appendChild(d);
    });
    group.appendChild(head);
    group.appendChild(namesEl);
    sourceExistingGroupsEl.appendChild(group);
  });
}

let toastTimer=null;
function showToast(msg){
  if(toastTimer) clearTimeout(toastTimer);
  toastEl.textContent=msg;
  toastEl.classList.remove('hidden');
  toastTimer=setTimeout(()=>toastEl.classList.add('hidden'), 1900);
}

/* ========== 초기화 ========== */
renderRecentQueries();
loadSourceCounts();


/* ============================================================
   데일리 브리핑 — 주간 달력 (데모 데이터, 실 연동은 범위 밖)
   ============================================================ */
const DAY_LABELS=['일','월','화','수','목','금','토'];

function generateDemoData(){
  const data={};
  const base=new Date();
  for(let d=-14; d<=14; d++){
    const dt=new Date(base); dt.setDate(base.getDate()+d);
    const key=fmtDateKey(dt);
    data[key]=createDayBriefing(dt, d===0, d>0);
  }
  return data;
}
function fmtDateKey(d){ return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function createDayBriefing(date, isToday, isFuture){
  if(isFuture) return {isToday:false, isFuture:true, groups:{news:[],youtube:[],wassap:[],international:[]}};
  const rand=n=>Math.floor(Math.random()*(n+1));
  const mk=(sourceName, brand)=>({
    title:`[데모] ${sourceName} 관련 소식`, excerpt:'실 데이터 연동은 범위 밖 — 데모용 텍스트입니다.',
    source_name:sourceName, published_date:fmtDateKey(date), external_url:'#', matched_brands:[brand],
  });
  const groups={
    news: isToday ? [mk('와인나라','오퍼스원'), mk('디캔터코리아','샤토 마고')] : (rand(1)?[mk('와인나라','뒤가피')]:[]),
    youtube: isToday ? [mk('YouTube: 와인클래스 준','케이머스')] : [],
    wassap: isToday ? [mk('와쌉','오퍼스원')] : (rand(1)?[mk('와쌉','뒤가피')]:[]),
    international: isToday ? [mk('Wine Spectator','샤토 마고')] : [],
  };
  return {isToday, isFuture:false, groups};
}

const briefingData=generateDemoData();
let currentWeekStart=getWeekStart(new Date());
let selectedDateKey=fmtDateKey(new Date());

function getWeekStart(d){
  const dt=new Date(d);
  const day=dt.getDay();
  const diff=day===0?-6:1-day;
  dt.setDate(dt.getDate()+diff);
  dt.setHours(0,0,0,0);
  return dt;
}
function addDays(d,n){ const dt=new Date(d); dt.setDate(dt.getDate()+n); return dt; }
function fmtMonthDay(d){ return `${d.getMonth()+1}/${d.getDate()}`; }

function renderWeekNav(){
  const start=currentWeekStart;
  const end=addDays(start,6);
  const year=start.getFullYear();
  const month=start.getMonth()+1;
  const weekNum=Math.ceil(start.getDate()/7);
  document.getElementById('weekLabel').textContent=`${year}년 ${month}월 ${weekNum}주차`;
  document.getElementById('weekRange').textContent=`${fmtMonthDay(start)} ~ ${fmtMonthDay(end)}`;
}

function countOf(data){
  return Object.values(data.groups).reduce((a,arr)=>a+arr.length,0);
}

function renderCalendar(){
  const grid=document.getElementById('weekCalendar');
  grid.innerHTML='';
  for(let i=0;i<7;i++){
    const cellDate=addDays(currentWeekStart,i);
    const key=fmtDateKey(cellDate);
    const data=briefingData[key]||{isToday:false,isFuture:false,groups:{news:[],youtube:[],wassap:[],international:[]}};
    const count=countOf(data);
    const isSelected=key===selectedDateKey;

    const cell=document.createElement('button');
    cell.className='calendar-cell'
      +(isSelected?' selected':'')
      +(data.isToday?' today':'');
    cell.disabled=data.isFuture;

    const dow=document.createElement('span'); dow.className='calendar-dow'; dow.textContent=DAY_LABELS[cellDate.getDay()];
    const num=document.createElement('span'); num.className='calendar-daynum'; num.textContent=cellDate.getDate();
    const dot=document.createElement('span'); dot.className='calendar-dot';
    dot.style.background = count>0 ? 'var(--accent)' : 'transparent';
    cell.appendChild(dow); cell.appendChild(num); cell.appendChild(dot);

    if(!data.isFuture){ cell.addEventListener('click', ()=>{ selectedDateKey=key; renderCalendar(); renderBriefingDetail(); }); }
    grid.appendChild(cell);
  }
}

function renderWeeklySummary(){
  const el=document.getElementById('weeklySummary');
  el.innerHTML='';
  const title=document.createElement('div');
  title.className='weekly-summary-title';
  title.textContent='주간 요약';
  const item=document.createElement('div');
  item.className='weekly-summary-item';
  const bullet=document.createElement('span'); bullet.className='weekly-summary-bullet'; bullet.textContent='•';
  const text=document.createElement('span'); text.textContent='실 데이터 연동은 범위 밖입니다 — 데모용 화면입니다.';
  item.appendChild(bullet); item.appendChild(text);
  el.appendChild(title); el.appendChild(item);
}

function renderBriefingDetail(){
  const data=briefingData[selectedDateKey];
  const [y,m,d]=selectedDateKey.split('-');
  document.getElementById('detailDateLabel').textContent=`${y}.${m}.${d}`;
  document.getElementById('todayBadge').classList.toggle('hidden', !(data&&data.isToday));

  const allItems=data?Object.values(data.groups).flat():[];
  document.getElementById('detailTotal').textContent=allItems.length;
  const brandSet=new Set(); allItems.forEach(it=>(it.matched_brands||[]).forEach(b=>brandSet.add(b)));
  document.getElementById('detailBrandCount').textContent=brandSet.size;

  const groupsEl=document.getElementById('briefingGroups');
  const emptyEl=document.getElementById('briefingEmpty');
  if(!allItems.length){
    groupsEl.innerHTML=''; emptyEl.classList.remove('hidden');
  }else{
    emptyEl.classList.add('hidden');
    renderResultGroups(groupsEl, allItems);
  }
}

document.getElementById('btnPrevWeek').addEventListener('click',()=>{
  currentWeekStart=addDays(currentWeekStart,-7);
  renderWeekNav(); renderCalendar();
});
document.getElementById('btnNextWeek').addEventListener('click',()=>{
  currentWeekStart=addDays(currentWeekStart,7);
  renderWeekNav(); renderCalendar();
});

renderWeekNav();
renderCalendar();
renderWeeklySummary();
renderBriefingDetail();
