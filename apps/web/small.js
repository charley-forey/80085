const t=document.getElementById('theme');
t&&t.addEventListener('click',()=>{const r=document.documentElement;
const d=getComputedStyle(r).getPropertyValue('--paper').trim().startsWith('#00');
const n=d?'light':'dark';r.dataset.theme=n;try{localStorage.setItem('theme',n)}catch(e){}});
for(const b of document.querySelectorAll('.copy[data-copy]')){b.addEventListener('click',()=>{
const ok=()=>{b.textContent='✅';setTimeout(()=>b.textContent='📋',1200)};
navigator.clipboard?.writeText(b.dataset.copy).then(ok,()=>{});});}
