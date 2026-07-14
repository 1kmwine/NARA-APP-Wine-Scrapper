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

/* ========== 상세 팝업 ========== */
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

/* ========== 데일리 브리핑 예시 데이터 ========== */
const briefingData={
  domestic:[
    {title:"[와인21] 리오하 와인이 지금 걷고 있는 '제3의 길'",url:"#",new:false,desc:"시간과 장소의 문제 와인의 가치를 장소에 둘 것인가 시간에 둘 것인가."},
    {title:"[한국경제] 해외에 K소주 알리는 \u0027LA 문화의 여왕\u0027",url:"#",new:true,desc:'차례"라며 "한국이 문화·경제적으로 커진 만큼..."'},
    {title:"[한국경제] \"美 로버트 몬다비, 유행보다 전통 고수\"",url:"#",new:false,desc:"어제보다 더 강해져야 한다는 단순한 생각이 60년의 역사를 만들었습니다."},
  ],
  newsroom:[
    {title:"[나라셀라 칼럼] 칠레 화이트 와인 추천｜몬테스가 제시하는 태평양 쿨-클라이밋",url:"#",new:false},
    {title:"[나라셀라 칼럼] 페스티벌 와인 추천 2026 | 뮤직·워터밤·락·바다축제 무드별 추천와인 4선",url:"#",new:false},
  ],
  cafe:[
    {title:"크룩 질문이요! 💬17",url:"#",new:true,desc:"와인에대해 잘모르는 와린이지만 크룩이 유명하고 맛있다고해서..."},
    {title:"일본 후쿠오카 르셉 가격 봐주세요 💬15",url:"#",new:true},
  ],
  youtube:[
    {title:"[비밀이야] [CEO의 삶] 비밀이야의 밀착 24시간",url:"#",new:false,meta:"1일 전·조회수 8.9만회"},
    {title:"[양갱] \"이 좋은걸 몰랐다니!\" 일본 후쿠오카 보르도 와인 페스티벌",url:"#",new:false,meta:"14시간 전·1.5천"},
  ],
  blog:[
    {title:"부산 광안리데이트 뉼리｜결혼기념일을 더욱 특별하게",url:"#",new:true,desc:"또 하나 인상 깊었던 건 입구를 지나면 와인 창고 같은 공간이 보여요.",time:"6분 전"},
    {title:"횡성 반값여행 저문강에 삽을 씻고 정식 먹으러",url:"#",new:true,desc:"와인 에이드 : 4,000원 저문강 정식 : 16,000원",time:"6분 전"},
  ],
  global:[
    {title:"[Decanter] 디캔터의 새로운 북미 지역 에디터를 만나보세요",url:"#",new:false,desc:"당첨자 발표..."},
    {title:"[Wine Spectator] 로제, 응. 하지만 어느 것?",url:"#",new:false,desc:"2025 빈티지는 프랑스 남부의 다양한 스타일, 색상, 품질을 제공합니다."},
    {title:"[OIV] 포도재배 부서장 채용 제안",url:"#",new:false},
  ],
};

function renderBriefing(){
  const today=new Date();
  const wd=['일','월','화','수','목','금','토'];
  document.getElementById('briefingDate').textContent=`${today.getFullYear()}년 ${String(today.getMonth()+1).padStart(2,'0')}월 ${String(today.getDate()).padStart(2,'0')}일 (${wd[today.getDay()]})`;
  const sum=(k)=>briefingData[k].length;
  const tags=`
    <span class="tag">📰 뉴스 ${sum('domestic')}</span>
    <span class="tag">🏛 뉴스룸 ${sum('newsroom')}</span>
    <span class="tag">🍷 와쌉 ${sum('cafe')}</span>
    <span class="tag">🎬 YouTube ${sum('youtube')}</span>
    <span class="tag">📝 블로그 ${sum('blog')}</span>
    <span class="tag">🌐 해외 ${sum('global')}</span>`;
  document.getElementById('briefingTags').innerHTML=tags;

  function ul(id,key){ 
    const el=document.getElementById(id); 
    el.innerHTML=briefingData[key].map(item=>{
      const newb=item.new?'<span class="new-badge">NEW</span>':'';
      const meta=item.meta?` <span style="color:#9ca3af">${item.meta}</span>`:'';
      const desc=item.desc?`<div class="desc">${item.desc}</div>`:'';
      return `<li>${newb}<a href="${item.url}" target="_blank">${item.title}</a>${meta}${desc}</li>`;
    }).join('');
  }
  ul('listDomestic','domestic');
  ul('listNewsroom','newsroom');
  ul('listCafe','cafe');
  ul('listYoutube','youtube');
  ul('listBlog','blog');
  ul('listGlobal','global');
}
renderBriefing();
