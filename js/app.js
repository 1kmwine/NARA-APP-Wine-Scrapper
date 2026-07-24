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

/* CATEGORY_META: "소스 데이터 추가" 패널·"등록된 소스" 카운트용 — 블로그는
   등록 소스 목록이 없는 항상-켜짐 검색이라 여긴 넣지 않는다. */
const CATEGORY_META=[
  {key:'news', label:'뉴스·매거진'},
  {key:'youtube', label:'유튜브'},
  {key:'wassap', label:'와쌉카페'},
  {key:'international', label:'해외소스'},
];

/* RESULT_CATEGORY_META: 결과 그리드·진행률 표시용 — 백엔드 run_job(jobs.py)의
   카테고리 처리 순서와 반드시 일치해야 한다: 뉴스 → 블로그 → 유튜브 → 와쌉 →
   해외소스. 진행률 뷰가 누적 done 값을 이 순서로 구간별로 나눠 계산하기 때문
   (아래 computeProgressRows 참고). */
const RESULT_CATEGORY_META=[
  {key:'news', label:'뉴스·매거진'},
  {key:'blog', label:'네이버 블로그'},
  {key:'youtube', label:'유튜브'},
  {key:'wassap', label:'와쌉카페'},
  {key:'international', label:'해외소스'},
];

/* ========== 스크래퍼: DOM 참조 ========== */
const searchView=document.getElementById('scraperSearchView');
const resultsView=document.getElementById('scraperResultsView');
const queryInput=document.getElementById('queryInput');
const searchSubtitle=document.getElementById('searchSubtitle');
const recentQueriesEl=document.getElementById('recentQueries');
const btnStartSearch=document.getElementById('btnStartSearch');
const resultsProgressEl=document.getElementById('resultsProgress');
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

  resultsQueryEl.textContent=query;
  resultsCountEl.textContent='0건 수집됨';
  resultsFailuresBlock.classList.add('hidden');
  resultsProgressEl.classList.remove('hidden');
  progressBarFill.style.width='0%';
  progressRowsEl.innerHTML='';
  initIncrementalResults();
  showScraperView('results');

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

/* ---- 진행률: 누적 done을 카테고리 순서(뉴스→블로그→유튜브→와쌉→해외소스)로 구간 분할 ---- */
function computeProgressRows(done){
  let remaining=done;
  return RESULT_CATEGORY_META.map(c=>{
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
    progressBarFill.style.width=`${job.total?(job.done/job.total)*100:0}%`;
    renderProgressRows(job.done);
    appendIncrementalResults(job.results, query);
    resultsCountEl.textContent=`${job.results.length}건 수집됨`;

    if(job.status==='succeeded'||job.status==='partial'||job.status==='failed'){
      if(job.status==='failed'){
        alert(`스크래핑 실패: ${job.error||'알 수 없는 오류'}`);
        showScraperView('search');
        return;
      }
      finalizeResultsView(job.failures||[]);
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
  RESULT_CATEGORY_META.forEach(c=>{ groups[c.key]=[]; });
  items.forEach(item=>{ (groups[item.source_category]||(groups[item.source_category]=[])).push(item); });
  return groups;
}

function escapeRegExp(s){ return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

/* 글자 사이에 \s*를 끼워 넣어 표기 스페이싱 차이를 허용한다("파니엔테" 검색어가
   본문엔 "파 니엔테"로 적혀 있는 경우가 실제로 흔했다) — 백엔드 fuzzy_find와
   동일한 개념. */
function fuzzyPattern(term){
  return term.split('').filter(ch=>!/\s/.test(ch)).map(escapeRegExp).join('\\s*');
}

/* 검색어/매칭 브랜드가 title·excerpt 어디에 나오는지 <mark>로 표시한다.
   scrapped 텍스트는 여전히 textContent/createTextNode로만 넣는다 — <mark>는
   우리가 직접 만든 빈 엘리먼트일 뿐, 외부 콘텐츠를 HTML로 파싱하지 않는다.
   패턴 전체를 하나의 캡처 그룹으로 묶어서 split() 했을 때 홀수 인덱스가
   항상 매칭 부분이 되게 한다 — fuzzy 매칭이라 실제로 잡힌 문자열이 term과
   글자 그대로 똑같지 않을 수 있어(스페이싱 차이) 텍스트 비교로는 매칭 여부를
   되짚을 수 없다. */
function renderHighlighted(el, text, terms){
  el.textContent='';
  const patterns=terms.map(fuzzyPattern).filter(Boolean).sort((a,b)=>b.length-a.length);
  if(!patterns.length){ el.textContent=text; return; }
  const re=new RegExp(`(${patterns.join('|')})`, 'gi');
  text.split(re).forEach((part, i)=>{
    if(!part) return;
    if(i%2===1){
      const mark=document.createElement('mark');
      mark.className='result-card-highlight';
      mark.textContent=part;
      el.appendChild(mark);
    }else{
      el.appendChild(document.createTextNode(part));
    }
  });
}

// title/excerpt/source_name은 스크래핑된 외부 콘텐츠이므로 innerHTML이 아니라
// textContent(혹은 renderHighlighted의 createTextNode)로만 채운다 —
// HTML 인젝션을 원천 차단하기 위해서다. img.src는 텍스트가 아니라 URL 속성이라
// 별도 이스케이프 불필요.
function buildResultCard(item, highlightQuery, animate){
  const a=document.createElement('a');
  a.href=item.external_url || '#';
  a.target='_blank';
  a.rel='noopener';
  a.className='result-card'+(animate ? ' result-card-enter' : '');

  if(item.thumbnail_url){
    const img=document.createElement('img');
    img.className='result-card-thumb';
    img.src=item.thumbnail_url;
    img.loading='lazy';
    img.alt='';
    img.referrerPolicy='no-referrer';
    // 썸네일 로드 실패(만료된 CDN 서명 URL 등) 시 이미지 영역 자체를 접는다 —
    // 이니셜 박스로 때우면 오히려 빈 색상 블록만 남아 자리만 차지한다.
    img.addEventListener('error', ()=>{ img.remove(); a.classList.add('result-card-no-thumb'); });
    a.appendChild(img);
  }else{
    // 썸네일을 구할 수 없는 소스(와쌉 등)는 빈 이니셜 박스 대신 썸네일 영역을
    // 아예 없애고 카드를 낮춘다 — 대신 본문(제목+미리보기)이 폭을 다 쓴다.
    a.classList.add('result-card-no-thumb');
  }

  const body=document.createElement('div');
  body.className='result-card-body';

  const terms=[highlightQuery, ...(item.matched_brands||[])].filter(Boolean);

  const title=document.createElement('div');
  title.className='result-card-title';
  renderHighlighted(title, item.title, terms);

  const excerpt=document.createElement('div');
  excerpt.className='result-card-excerpt';
  renderHighlighted(excerpt, item.excerpt||'', terms);

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

  a.appendChild(body);
  return a;
}

function renderResultGroups(container, items, highlightQuery){
  const groups=groupByCategory(items);
  container.innerHTML='';
  RESULT_CATEGORY_META.forEach(c=>{
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
      grid.appendChild(buildResultCard(item, highlightQuery, false));
    });
    groupEl.appendChild(grid);
    container.appendChild(groupEl);
  });
}

/* ---- 스크래퍼 결과: 폴링마다 새로 도착한 아이템만 카드로 추가(애니메이션) ----
   groupByCategory을 매번 다시 돌리는 대신, 카테고리별 그리드를 처음에 고정
   순서로 미리 만들어두고(비어있으면 숨김) 새 URL만 골라 append한다 — 그래야
   카테고리가 도착 순서에 따라 화면에서 뒤섞이지 않는다. */
let renderedResultUrls=new Set();

function initIncrementalResults(){
  renderedResultUrls=new Set();
  resultsGroupsEl.innerHTML='';
  RESULT_CATEGORY_META.forEach(c=>{
    const groupEl=document.createElement('div');
    groupEl.className='result-group hidden';
    groupEl.dataset.category=c.key;
    const groupTitle=document.createElement('div');
    groupTitle.className='result-group-title';
    const countSpan=document.createElement('span');
    countSpan.className='result-group-count';
    countSpan.textContent='0';
    groupTitle.textContent=c.label+' ';
    groupTitle.appendChild(countSpan);
    const grid=document.createElement('div');
    grid.className='result-grid';
    groupEl.appendChild(groupTitle);
    groupEl.appendChild(grid);
    resultsGroupsEl.appendChild(groupEl);
  });
}

function appendIncrementalResults(items, highlightQuery){
  const groups=groupByCategory(items);
  RESULT_CATEGORY_META.forEach(c=>{
    const newItems=(groups[c.key]||[]).filter(item=>!renderedResultUrls.has(item.external_url));
    if(!newItems.length) return;
    const groupEl=resultsGroupsEl.querySelector(`[data-category="${c.key}"]`);
    groupEl.classList.remove('hidden');
    const grid=groupEl.querySelector('.result-grid');
    newItems.forEach(item=>{
      renderedResultUrls.add(item.external_url);
      grid.appendChild(buildResultCard(item, highlightQuery, true));
    });
    groupEl.querySelector('.result-group-count').textContent=grid.children.length;
  });
}

function finalizeResultsView(failures){
  resultsProgressEl.classList.add('hidden');

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
   데일리 브리핑 — 주간 달력 (실 데이터: docs/data/{date}/*.json,
   깃허브 저장소에서 clone해온 스크래핑 결과를 그대로 fetch해 사용한다.
   파일이 없는 날짜는 빈 상태로 표시)
   ============================================================ */
const DAY_LABELS=['일','월','화','수','목','금','토'];

/* 스크래퍼 탭의 CATEGORY_META(4종)와 달리, 실제 브리핑 데이터에는
   뉴스룸(나라셀라 자체 칼럼)·블로그가 별도 카테고리로 존재한다. */
const BRIEFING_CATEGORY_META=[
  {key:'news', label:'뉴스·매거진', emoji:'📰'},
  {key:'newsroom', label:'뉴스룸', emoji:'🏛'},
  {key:'wassap', label:'와쌉카페', emoji:'🍷'},
  {key:'youtube', label:'유튜브', emoji:'🎬'},
  {key:'blog', label:'블로그', emoji:'📝'},
  {key:'international', label:'해외소스', emoji:'🌐'},
];
function emptyBriefingGroups(){
  const g={}; BRIEFING_CATEGORY_META.forEach(c=>{ g[c.key]=[]; }); return g;
}

async function fetchJSON(path){
  try{
    const res=await fetch(path);
    if(!res.ok) return null;
    return await res.json();
  }catch(e){ return null; }
}

function toItems(list, category, dateKey, sourceName){
  return (list||[]).map(it=>({
    title: it.title || it.title_ko || '(제목 없음)',
    excerpt: it.snippet || it.summary_ko || '',
    source_name: sourceName || it.press || it.source || '',
    published_date: dateKey, external_url: it.url || '#',
    matched_brands: [], source_category: category,
  }));
}
function youtubeItems(byChannel, dateKey){
  return Object.entries(byChannel||{}).flatMap(([channel, vids])=>(vids||[]).map(v=>({
    title: v.title || '(제목 없음)', excerpt:'', source_name:`YouTube: ${channel}`,
    published_date: dateKey, external_url: v.url || '#',
    matched_brands: [], source_category:'youtube',
  })));
}
function internationalItems(intl, dateKey){
  if(!intl) return [];
  const buckets=['foreign_magazines','foreign_stats','domestic_stats','events','downstream_market'];
  return buckets.flatMap(k=>(intl[k]||[]).map(it=>({
    title: it.title_ko || it.title || '(제목 없음)',
    excerpt: it.summary_ko || it.snippet || '',
    source_name: it.source || '해외소스',
    published_date: dateKey, external_url: it.url || '#',
    matched_brands: [], source_category:'international',
  })));
}

async function fetchDayGroups(dateKey){
  const base=`docs/data/${dateKey}`;
  const [news, newsroom, wassap, youtube, blog, international]=await Promise.all(
    ['news','newsroom','wassap','youtube','blog','international'].map(f=>fetchJSON(`${base}/${f}.json`))
  );
  return {
    news: toItems(news, 'news', dateKey),
    newsroom: toItems(newsroom, 'newsroom', dateKey),
    wassap: toItems(wassap, 'wassap', dateKey, '와쌉카페'),
    youtube: youtubeItems(youtube, dateKey),
    blog: toItems(blog, 'blog', dateKey, '네이버 블로그'),
    international: internationalItems(international, dateKey),
  };
}

function fmtDateKey(d){ return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
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

/* ±14일 범위만 fetch한다 — 실제 파일이 있는 날짜가 며칠뿐이라 대부분 빈 배열로
   끝나지만, 로컬 정적 서버 fetch라 부담이 없다(원격 API였다면 주 단위 지연 로드로
   바꿔야 한다). */
async function loadBriefingData(){
  const data={};
  const base=new Date();
  const todayKey=fmtDateKey(base);
  const tasks=[];
  for(let d=-14; d<=14; d++){
    const dt=addDays(base,d);
    const key=fmtDateKey(dt);
    if(key>todayKey){ data[key]={isToday:false, isFuture:true, groups:emptyBriefingGroups()}; continue; }
    tasks.push(fetchDayGroups(key).then(groups=>{ data[key]={isToday:key===todayKey, isFuture:false, groups}; }));
  }
  await Promise.all(tasks);
  return data;
}

let briefingData={};
let currentWeekStart=getWeekStart(new Date());
let selectedDateKey=fmtDateKey(new Date());

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
    const data=briefingData[key]||{isToday:false,isFuture:false,groups:emptyBriefingGroups()};
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

/* 글로벌 동향=해외소스, 소비자 트렌드=유튜브·와쌉·블로그(소비자 채널), 업계
   활동=뉴스·뉴스룸(나라셀라 자체 칼럼 포함). 백엔드 briefing_summary.py의
   BUCKETS와 key/분류가 반드시 일치해야 한다. */
const SUMMARY_CATEGORIES=[
  {key:'global', badge:'글', title:'글로벌 동향', match:['international']},
  {key:'consumer', badge:'소', title:'소비자 트렌드', match:['youtube','wassap','blog']},
  {key:'importer', badge:'업', title:'업계 활동', match:['news','newsroom']},
];

/* 백엔드 LLM 키워드 추출(/briefings/weekly-summary)이 실패했을 때만 쓰는 폴백 —
   그 주 제목 중 중복 등장(같은 브랜드/단어가 여러 건에 반복)하는 것 위주로 짧게
   뽑는다. 문장 아니라 칩으로 보여줄 짧은 구 목록. */
function buildCategoryKeywords(items){
  if(!items.length) return [];
  // 단어 빈도 대신 실제 제목 2건을 그대로 보여준다 — LLM 없이는 "일반 단어
  // 제외하고 고유명사 위주로" 같은 판단을 못 해서, 최소한 진짜 헤드라인을
  // 보여주는 게 의미 없는 빈출 단어 나열보다 낫다.
  return items.map(it=>it.title).filter(Boolean).slice(0,2)
    .map(t=> t.length>28 ? t.slice(0,28)+'…' : t);
}

let _weeklySummaryToken=0;

async function renderWeeklySummary(){
  // 다른 주로 넘어가면 이전 요청의 늦은 응답이 화면을 덮어쓰지 않도록 토큰으로 막는다.
  const token=++_weeklySummaryToken;
  const weekStart=fmtDateKey(currentWeekStart);

  const weekItems=[];
  for(let i=0;i<7;i++){
    const data=briefingData[fmtDateKey(addDays(currentWeekStart,i))];
    if(data && !data.isFuture) weekItems.push(...Object.values(data.groups).flat());
  }
  const bucketItems={};
  SUMMARY_CATEGORIES.forEach(cat=>{ bucketItems[cat.key]=weekItems.filter(it=>cat.match.includes(it.source_category)); });

  let llmKeywords=null;
  try{
    const res=await fetch(`${API_BASE}/briefings/weekly-summary?week_start=${weekStart}`);
    if(res.ok){
      const data=await res.json();
      llmKeywords={};
      data.categories.forEach(c=>{ llmKeywords[c.key]=c.keywords; });
    }
  }catch(e){ /* 네트워크 실패 — 아래 발췌 키워드로 폴백 */ }

  if(token!==_weeklySummaryToken) return;

  const el=document.getElementById('weeklySummary');
  el.innerHTML='';
  const title=document.createElement('div');
  title.className='weekly-summary-title';
  title.textContent='이번 주 종합';
  el.appendChild(title);

  const grid=document.createElement('div'); grid.className='weekly-summary-grid';
  el.appendChild(grid);

  SUMMARY_CATEGORIES.forEach((cat,idx)=>{
    const items=bucketItems[cat.key];
    const keywords=(llmKeywords && llmKeywords[cat.key] && llmKeywords[cat.key].length)
      ? llmKeywords[cat.key] : buildCategoryKeywords(items);

    const section=document.createElement('div');
    section.className='summary-category';
    section.style.setProperty('--stagger-index', idx);

    const head=document.createElement('div'); head.className='summary-category-head';
    const badge=document.createElement('span'); badge.className='summary-category-badge'; badge.textContent=cat.badge;
    const name=document.createElement('span'); name.className='summary-category-name'; name.textContent=cat.title;
    const count=document.createElement('span'); count.className='summary-category-count'; count.textContent=`${items.length}건`;
    head.appendChild(badge); head.appendChild(name); head.appendChild(count);
    section.appendChild(head);

    if(keywords.length){
      const list=document.createElement('div'); list.className='summary-keywords';
      keywords.forEach(k=>{
        const chip=document.createElement('span'); chip.className='summary-keyword-chip'; chip.textContent=k;
        list.appendChild(chip);
      });
      section.appendChild(list);
    }else{
      const empty=document.createElement('div'); empty.className='summary-category-empty';
      empty.textContent='이번 주 수집된 소식 없음';
      section.appendChild(empty);
    }

    grid.appendChild(section);
  });
}

/* 데일리 상세 히어로 — docs/briefings/*.html(실제 발송되는 이메일 브리핑) 레이아웃 참고:
   그라디언트 헤드라인 + "오늘의 요약" 카드(소스별 건수 칩 + 카테고리별 하이라이트 2건).
   요청에 따라 하단 카드 그리드는 없음 — 히어로가 그날 상세의 전부. */
function weekdayLabel(dateObj){ return DAY_LABELS[dateObj.getDay()]; }

function renderBriefingHero(data){
  const heroEl=document.getElementById('briefingHero');
  heroEl.innerHTML='';
  const [y,m,d]=selectedDateKey.split('-');
  const dateObj=new Date(Number(y), Number(m)-1, Number(d));
  const allItems=data?Object.values(data.groups).flat():[];

  const hero=document.createElement('div'); hero.className='briefing-hero';
  const eyebrow=document.createElement('div'); eyebrow.className='hero-eyebrow'; eyebrow.textContent='나라셀라 데일리 와인 브리핑';
  const titleRow=document.createElement('div'); titleRow.className='hero-title-row';
  const title=document.createElement('span'); title.className='hero-title';
  title.textContent=`🍾 ${y}년 ${m}월 ${d}일 (${weekdayLabel(dateObj)}) 와인 업계 동향`;
  titleRow.appendChild(title);
  if(data&&data.isToday){ const badge=document.createElement('span'); badge.className='hero-today-badge'; badge.textContent='오늘'; titleRow.appendChild(badge); }
  const activeCats=BRIEFING_CATEGORY_META.filter(c=>(data&&data.groups[c.key]||[]).length>0);
  const sub=document.createElement('div'); sub.className='hero-sub';
  sub.textContent=activeCats.length?activeCats.map(c=>c.label).join(' · '):'수집된 소스 없음';
  hero.appendChild(eyebrow); hero.appendChild(titleRow); hero.appendChild(sub);

  const summaryCard=document.createElement('div'); summaryCard.className='hero-summary-card';
  const summaryHead=document.createElement('div'); summaryHead.className='hero-summary-head';
  const summaryLabel=document.createElement('span'); summaryLabel.textContent='📊 오늘의 요약';
  const summaryTotal=document.createElement('span'); summaryTotal.className='hero-summary-total';
  summaryTotal.textContent=`총 ${allItems.length}건 수집`;
  summaryHead.appendChild(summaryLabel); summaryHead.appendChild(summaryTotal);
  summaryCard.appendChild(summaryHead);

  const chipRow=document.createElement('div'); chipRow.className='hero-chip-row';
  BRIEFING_CATEGORY_META.forEach(c=>{
    const n=(data&&data.groups[c.key]||[]).length;
    const chip=document.createElement('span'); chip.className='hero-chip';
    chip.textContent=`${c.emoji} ${c.label} ${n}`;
    chipRow.appendChild(chip);
  });
  summaryCard.appendChild(chipRow);

  if(activeCats.length){
    summaryCard.appendChild(document.createElement('hr')).className='hero-divider';
    const highlights=document.createElement('div'); highlights.className='hero-highlights';
    activeCats.forEach(c=>{
      const items=data.groups[c.key].slice(0,2);
      const group=document.createElement('div'); group.className='hero-highlight-group';
      const label=document.createElement('div'); label.className='hero-highlight-label'; label.textContent=`${c.emoji} ${c.label}`;
      const list=document.createElement('ul');
      items.forEach(it=>{
        const li=document.createElement('li');
        const a=document.createElement('a'); a.href=it.external_url||'#'; a.target='_blank'; a.rel='noopener'; a.textContent=it.title;
        li.appendChild(a); list.appendChild(li);
      });
      group.appendChild(label); group.appendChild(list);
      highlights.appendChild(group);
    });
    summaryCard.appendChild(highlights);
  }

  heroEl.appendChild(hero);
  heroEl.appendChild(summaryCard);
}

function renderBriefingDetail(){
  renderBriefingHero(briefingData[selectedDateKey]);
}

document.getElementById('btnPrevWeek').addEventListener('click',()=>{
  currentWeekStart=addDays(currentWeekStart,-7);
  renderWeekNav(); renderCalendar(); renderWeeklySummary();
});
document.getElementById('btnNextWeek').addEventListener('click',()=>{
  currentWeekStart=addDays(currentWeekStart,7);
  renderWeekNav(); renderCalendar(); renderWeeklySummary();
});

(async function initBriefing(){
  briefingData=await loadBriefingData();
  renderWeekNav();
  renderCalendar();
  renderWeeklySummary();
  renderBriefingDetail();
})();
