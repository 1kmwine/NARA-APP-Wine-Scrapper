const wineries = [
  {id:'montes', name:'Montes'},
  {id:'caymus', name:'Caymus'},
  {id:'duckhorn', name:'Duckhorn'},
  {id:'farniente', name:'Far Niente'},
  {id:'donnafugata', name:'Donnafugata'},
  {id:'deutz', name:'Champagne Deutz'},
  {id:'heitz', name:'Heitz Cellar'},
  {id:'bouley', name:'Domaine Bouley'},
  {id:'cesari', name:'Cesari'}
];

const sourceGrid = document.getElementById('sourceGrid');
wineries.forEach(w=>{
  const label=document.createElement('label');
  label.className='source-item';
  label.innerHTML=`<input type="checkbox" value="${w.id}" checked> ${w.name}`;
  sourceGrid.appendChild(label);
});

const btnStart=document.getElementById('btnStart');
const btnStop=document.getElementById('btnStop');
const progressArea=document.getElementById('progressArea');
const progressFill=document.getElementById('progressFill');
const progressText=document.getElementById('progressText');
const resultBody=document.getElementById('resultBody');
const resultCount=document.getElementById('resultCount');
const detailOverlay=document.getElementById('detailOverlay');
const closeDetail=document.getElementById('closeDetail');
let running=false, timer=null;

function renderResults(list){
  resultBody.innerHTML='';
  if(!list.length){ resultBody.innerHTML='<tr class="empty"><td colspan="4">수집된 데이터가 없습니다.</td></tr>'; resultCount.textContent='0'; return; }
  resultCount.textContent=list.length;
  list.forEach(item=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${item.name}</td><td>${item.vintage}</td><td>${item.price}</td><td>${item.status}</td>`;
    tr.addEventListener('click',()=>showDetail(item));
    resultBody.appendChild(tr);
  });
}

function showDetail(item){
  document.getElementById('detailTitle').textContent=item.name;
  const dl=document.getElementById('detailList');
  dl.innerHTML='';
  Object.entries(item).forEach(([k,v])=>{
    const dt=document.createElement('dt'); dt.textContent=k;
    const dd=document.createElement('dd'); dd.textContent=v;
    dl.appendChild(dt); dl.appendChild(dd);
  });
  detailOverlay.classList.remove('hidden');
}

closeDetail.addEventListener('click',()=>detailOverlay.classList.add('hidden'));
detailOverlay.addEventListener('click',e=>{ if(e.target===detailOverlay) detailOverlay.classList.add('hidden'); });

btnStart.addEventListener('click',()=>{
  if(running) return;
  running=true; btnStart.disabled=true; btnStop.disabled=false; progressArea.classList.remove('hidden');
  const selected=Array.from(sourceGrid.querySelectorAll('input:checked')).map(i=>i.value);
  const total=selected.length*3; let done=0;
  const results=[];
  let idx=0;
  function next(){
    if(!running || idx>=total){ finish(); return; }
    const src=selected[Math.floor(idx/3)];
    idx++; done++;
    const pct=(done/total)*100;
    progressFill.style.width=pct+'%';
    progressText.textContent=`${done} / ${total}`;
    results.push({
      name:`${wineries.find(w=>w.id===src)?.name||src} Wine ${done}`,
      vintage:2018+Math.floor(Math.random()*6),
      price:'₩'+ (Math.floor(Math.random()*15)+5)+'0,000',
      status:'완료',
      source:src,
      region:'Napa Valley',
      variety:'Cabernet Sauvignon'
    });
    renderResults(results.slice());
    timer=setTimeout(next, 300+Math.random()*400);
  }
  function finish(){ running=false; btnStart.disabled=false; btnStop.disabled=true; timer=null; }
  next();
});

btnStop.addEventListener('click',()=>{
  running=false; if(timer) clearTimeout(timer); timer=null;
  btnStart.disabled=false; btnStop.disabled=true; progressArea.classList.add('hidden');
});
