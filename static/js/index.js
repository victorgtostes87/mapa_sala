const SALAS = window.MAPA_CONFIG.salas;
const HORARIOS = window.MAPA_CONFIG.horarios;
const DIAS = window.MAPA_CONFIG.dias;
const PAPEL = window.MAPA_CONFIG.papel;
const CSRF_TOKEN = window.MAPA_CONFIG.csrfToken;
const PODE_EDITAR = ['coordenador','recepcao'].includes(PAPEL);
let currentDay = DIAS[0];
let debTimer = null;
let conflictTimer = null;
let temConflito = false;

const CAT_CLASS = {
  'ESTAGIÁRIO 10°':'cat-est10','ESTAGIÁRIO 10° TRIAGEM':'cat-est10t',
  'ESTAGIÁRIO 9°':'cat-est9','ESTAGIÁRIO 9° TRIAGEM':'cat-est9t',
  'SUPERVISÃO':'cat-sup','NACE':'cat-nace','SOU':'cat-sou',
  'MARCAR':'cat-marcar','NÃO MARCAR':'cat-nmarcar',
  'NUTRIÇÃO':'cat-nutri','PSICODIAGNÓSTICO':'cat-psico',
  'PSIQUIATRIA':'cat-psiq','AMBULATÓRIO NEUROPSICOLOGIA':'cat-ambul',
  'PLANTÃO PSICOLÓGICO':'cat-plantao','PRONTUÁRIO/ESTUDAR':'cat-pront',
  'LIVRE':'cat-livre','OUTRO':'cat-outro'
};

function selectDay(dia, el) {
  currentDay = dia;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderGrid();
}
async function loadData() {
  const horario = document.getElementById('filterHorario').value;
  const sala    = document.getElementById('filterSala').value;
  const cat     = document.getElementById('filterCat').value;
  const busca   = document.getElementById('searchInput').value.trim();
  const data    = document.getElementById('filterData').value;
  const p = new URLSearchParams({dia_semana: currentDay});
  if (horario) p.set('horario', horario);
  if (sala)    p.set('sala', sala);
  if (cat)     p.set('categoria', cat);
  if (busca)   p.set('busca', busca);
  if (data)    p.set('data', data);
  const res = await fetch('/api/agendamentos?' + p);
  if (!res.ok) throw new Error('Não foi possível carregar os agendamentos.');
  return await res.json();
}
async function loadStats() {
  const res = await fetch('/api/stats?dia_semana='+currentDay);
  if (!res.ok) return;
  const d = await res.json();
  document.getElementById('stTotal').textContent = d.total;
  document.getElementById('stLivre').textContent = d.livre;
  const est = (d.por_categoria||[]).filter(c=>c.categoria&&c.categoria.startsWith('ESTAGIÁRIO')).reduce((a,c)=>a+c.n,0);
  document.getElementById('stEst').textContent = est;
}
async function renderGrid() {
  updateDateFilterBadge();
  const loading = document.getElementById('loadingMsg');
  loading.style.display = 'flex';
  let data = [];
  try {
    data = await loadData();
  } catch (err) {
    showToast(err.message || 'Falha ao carregar o mapa. Tente novamente.', 'error');
  } finally {
    loading.style.display = 'none';
  }
  const filterSala = document.getElementById('filterSala').value;
  const filterHor  = document.getElementById('filterHorario').value;
  const salas = filterSala ? [filterSala] : SALAS;
  const hors  = filterHor  ? [filterHor]  : HORARIOS;
  const lk = {};
  for (const ag of data) {
    const key = ag.horario+'|'+ag.sala;
    if(!lk[key]) lk[key] = [];
    lk[key].push(ag);
  }
  document.getElementById('tableHead').innerHTML =
    '<tr><th>Hora</th>' + salas.map(s=>'<th>'+s+'</th>').join('') + '</tr>';
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';
  for (const h of hors) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+h+'</td>';
    for (const s of salas) {
      const ags = lk[h+'|'+s] || [];
      const td = document.createElement('td');
      if (ags.length) {
        td.innerHTML = ags.map(renderAgendamentoCell).join('');
      } else {
        if (PODE_EDITAR) {
          td.innerHTML = `<div class="cell cat-livre" onclick="openModalNew('${h}','${s}')">
            <span style="color:#475569;font-size:10px">livre</span></div>`;
        } else {
          td.innerHTML = `<div class="cell cat-livre">
            <span style="color:#475569;font-size:10px">livre</span></div>`;
        }
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  loadStats();
}
function renderAgendamentoCell(ag){
  const cls = CAT_CLASS[ag.categoria] || 'cat-outro';
  const badgeHtml = ag.triagem ? '<span class="badge">triagem</span>' : '';
  const dataHtml  = ag.data_especifica ? '<span class="badge">'+esc(ag.data_especifica)+'</span>' : '';
  const editBtn   = PODE_EDITAR ? `<button class="edit-btn" onclick="event.stopPropagation();openModal(${ag.id})">✏️</button>` : '';
  return `<div class="cell ${cls}" onclick="openModal(${ag.id})">
    ${editBtn}
    <div class="intern">${esc(ag.estagiario)}</div>
    ${ag.paciente ? '<div class="patient">'+esc(ag.paciente)+'</div>' : ''}
    <div style="display:flex;gap:3px;flex-wrap:wrap">${badgeHtml}${dataHtml}</div>
  </div>`;
}
function updateDateFilterBadge(){
  const el = document.getElementById('dateFilterBadge');
  const data = document.getElementById('filterData').value;
  if(!el) return;
  if(!data){
    el.style.display = 'none';
    el.textContent = '';
    return;
  }
  const [ano, mes, dia] = data.split('-');
  el.textContent = `Mostrando data específica: ${dia}/${mes}/${ano}`;
  el.style.display = 'inline-flex';
}
function esc(t){ if(!t)return''; return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function debounceRender(){ clearTimeout(debTimer); debTimer=setTimeout(renderGrid,300); }
function clearFilters(){ document.getElementById('searchInput').value=''; document.getElementById('filterData').value=''; document.getElementById('filterHorario').value=''; document.getElementById('filterSala').value=''; document.getElementById('filterCat').value=''; renderGrid(); }
async function verificarConflito() {
  clearTimeout(conflictTimer);
  conflictTimer = setTimeout(async () => {
    const id=document.getElementById('fId').value;
    const dia=document.getElementById('fDia').value;
    const horario=document.getElementById('fHorario').value;
    const sala=document.getElementById('fSala').value;
    const dataEsp=document.getElementById('fData').value.trim();
    const p=new URLSearchParams({dia_semana:dia,horario,sala});
    if(dataEsp) p.set('data_especifica',dataEsp);
    if(id) p.set('excluir_id',id);
    let res;
    let data;
    try {
      res=await fetch('/api/conflito?'+p);
      data=await res.json();
    } catch (err) {
      showToast('Não foi possível verificar conflito agora.', 'error');
      return;
    }
    const box=document.getElementById('conflictBox');
    const msg=document.getElementById('conflictMsg');
    const btn=document.getElementById('saveBtn');
    if(!res.ok){
      msg.textContent=data.erro||'Não foi possível verificar conflito.';
      box.classList.add('show');
      btn.disabled=true; btn.style.opacity='0.4'; btn.style.cursor='not-allowed'; temConflito=true;
    } else if(data.conflito){
      msg.textContent=`${sala} — ${horario} (${dia}): ocupada por ${data.estagiario||data.categoria||'outro'}`;
      box.classList.add('show');
      btn.disabled=true; btn.style.opacity='0.4'; btn.style.cursor='not-allowed'; temConflito=true;
    } else {
      box.classList.remove('show');
      btn.disabled=false; btn.style.opacity='1'; btn.style.cursor='pointer'; temConflito=false;
    }
  },300);
}
function resetSaveBtn(){
  const btn=document.getElementById('saveBtn');
  btn.disabled=false; btn.style.opacity='1'; btn.style.cursor='pointer';
  btn.className='btn btn-primary'; btn.innerHTML='<i data-lucide="save"></i> Salvar';
  temConflito=false; document.getElementById('conflictBox').classList.remove('show');
}
async function openModal(id){
  resetSaveBtn();
  document.getElementById('fId').value=id||'';
  document.getElementById('modalTitle').textContent=id?'Agendamento':'Novo Agendamento';
  if(!PODE_EDITAR&&id){
    document.getElementById('readOnlyView').style.display='block';
    document.getElementById('editView').style.display='none';
    try {
      const r = await fetch('/api/agendamentos/'+id);
      const d = await r.json();
      if (!r.ok) throw new Error(d.erro || 'Não foi possível abrir o agendamento.');
      document.getElementById('readOnlyContent').innerHTML=
        `<strong>Sala:</strong> ${esc(d.sala)}<br><strong>Horário:</strong> ${esc(d.horario)}<br>
         <strong>Estagiário:</strong> ${esc(d.estagiario)||'—'}<br>
         <strong>Paciente:</strong> ${esc(d.paciente)||'—'}<br>
         <strong>Categoria:</strong> ${esc(d.categoria)||'—'}<br>
         ${d.observacao?'<strong>Obs:</strong> '+esc(d.observacao):''}`;
    } catch (err) {
      showToast(err.message || 'Falha ao abrir o agendamento.', 'error');
    }
    document.getElementById('modalOverlay').classList.add('open'); return;
  }
  document.getElementById('readOnlyView').style.display='none';
  document.getElementById('editView').style.display='block';
  document.getElementById('deleteBtn').style.display=id?'inline-flex':'none';
  if(id){
    try {
      const r = await fetch('/api/agendamentos/'+id);
      const d = await r.json();
      if (!r.ok) throw new Error(d.erro || 'Não foi possível abrir o agendamento.');
      setF('fDia',d.dia_semana); setF('fHorario',d.horario); setF('fSala',d.sala);
      document.getElementById('fEstagiario').value=d.estagiario||'';
      document.getElementById('fPaciente').value=d.paciente||'';
      setF('fCategoria',d.categoria); setF('fTriagem',d.triagem);
      document.getElementById('fData').value=d.data_especifica||'';
      document.getElementById('fObs').value=d.observacao||'';
    } catch (err) {
      showToast(err.message || 'Falha ao abrir o agendamento.', 'error');
      return;
    }
  } else {
    setF('fDia',currentDay); setF('fCategoria',''); setF('fTriagem',0);
    ['fEstagiario','fPaciente','fData','fObs'].forEach(id=>document.getElementById(id).value='');
    document.getElementById('fData').value=document.getElementById('filterData').value||'';
  }
  document.getElementById('modalOverlay').classList.add('open');
}
function openModalNew(h,s){ if(!PODE_EDITAR)return; openModal(null); setTimeout(()=>{setF('fHorario',h);setF('fSala',s);verificarConflito();},50); }
function setF(id,val){ const el=document.getElementById(id); if(el) el.value=val; }
function closeModal(){ document.getElementById('modalOverlay').classList.remove('open'); }
function closeModalIfBg(e){ if(e.target.id==='modalOverlay') closeModal(); }
async function saveAg(){
  if(temConflito){ showToast('🚫 Resolva o conflito antes de salvar!','error'); return; }
  const id=document.getElementById('fId').value;
  const body={
    dia_semana:document.getElementById('fDia').value,
    horario:document.getElementById('fHorario').value,
    sala:document.getElementById('fSala').value,
    estagiario:document.getElementById('fEstagiario').value.trim(),
    paciente:document.getElementById('fPaciente').value.trim(),
    categoria:document.getElementById('fCategoria').value,
    triagem:parseInt(document.getElementById('fTriagem').value)||0,
    data_especifica:document.getElementById('fData').value.trim(),
    observacao:document.getElementById('fObs').value.trim()
  };
  let res;
  let data;
  try {
    res=await fetch(id?'/api/agendamentos/'+id:'/api/agendamentos',
      {method:id?'PUT':'POST',headers:{'Content-Type':'application/json','X-CSRFToken':CSRF_TOKEN},body:JSON.stringify(body)});
    data=await res.json();
  } catch (err) {
    showToast('Não foi possível salvar agora. Verifique a conexão e tente novamente.','error');
    return;
  }
  if(res.ok){ showToast('✅ Salvo!','success'); closeModal(); renderGrid(); }
  else if(res.status===409){
    document.getElementById('conflictMsg').textContent=data.erro||'Conflito de sala.';
    document.getElementById('conflictBox').classList.add('show');
    const btn=document.getElementById('saveBtn');
    btn.disabled=true; btn.style.opacity='0.4'; btn.style.cursor='not-allowed';
    showToast('🚫 Conflito de sala!','error');
  } else { showToast('❌ '+(data.erro||'Erro ao salvar'),'error'); }
}
function deleteAg(){
  const id=document.getElementById('fId').value;
  if(!id) return;
  const sala    = document.getElementById('fSala').value;
  const horario = document.getElementById('fHorario').value;
  const dia     = document.getElementById('fDia').value;
  const est     = document.getElementById('fEstagiario').value;
  document.getElementById('confirmDetail').innerHTML =
    `<strong style="color:var(--text)">${sala}</strong> &mdash; ${horario} (${dia})`+
    (est ? `<br>Estagiário: <strong style="color:var(--text)">${esc(est)}</strong>` : '');
  document.getElementById('confirmOverlay').classList.add('open');
  document.getElementById('confirmDeleteBtn').onclick = async function(){
    fecharConfirm();
    let res;
    try {
      res=await fetch('/api/agendamentos/'+id,{method:'DELETE',headers:{'X-CSRFToken':CSRF_TOKEN}});
    } catch (err) {
      showToast('Não foi possível remover agora. Verifique a conexão e tente novamente.','error');
      return;
    }
    if(res.ok){ showToast('Removido','success'); closeModal(); renderGrid(); }
    else{ const e=await res.json(); showToast((e.erro||'Erro ao remover'),'error'); }
  };
}
function fecharConfirm(){ document.getElementById('confirmOverlay').classList.remove('open'); }
function exportCSV(){ window.location='/api/export'; }
function showToast(msg,type='success'){
  const t=document.getElementById('toast');
  t.textContent=msg; t.className='toast show '+type;
  setTimeout(()=>t.className='toast',3000);
}
renderGrid();

function toggleMenu(e){
  e.stopPropagation();
  document.getElementById('dropdownMenu').classList.toggle('open');
}
document.addEventListener('click', function(){
  const m = document.getElementById('dropdownMenu');
  if(m) m.classList.remove('open');
});



var _estList = [];
fetch('/api/estagiarios').then(function(r){return r.json();}).then(function(users){
  _estList = users.map(function(u){return u.username;});
}).catch(function(){
  _estList = [];
});

document.addEventListener('DOMContentLoaded', function() {
  if(window.lucide) lucide.createIcons();
  var fEst = document.getElementById('fEstagiario');
  var acBox = document.getElementById('estSuggestions');
  if (!fEst || !acBox) return;
  var acIdx = -1;

  fEst.addEventListener('input', function() {
    var val = this.value.trim().toLowerCase();
    acBox.innerHTML = '';
    acIdx = -1;
    if (!val || !_estList.length) { acBox.style.display='none'; return; }
    var matches = _estList.filter(function(n){ return n.toLowerCase().includes(val); });
    if (!matches.length) { acBox.style.display='none'; return; }
    matches.forEach(function(name) {
      var d = document.createElement('div');
      d.className = 'ac-item';
      d.textContent = name;
      d.addEventListener('mousedown', function() { fEst.value = name; acBox.style.display='none'; });
      acBox.appendChild(d);
    });
    acBox.style.display = 'block';
  });

  fEst.addEventListener('keydown', function(e) {
    var items = acBox.querySelectorAll('.ac-item');
    if (e.key==='ArrowDown'){acIdx=Math.min(acIdx+1,items.length-1);items.forEach(function(el,i){el.classList.toggle('active',i===acIdx);});e.preventDefault();}
    else if(e.key==='ArrowUp'){acIdx=Math.max(acIdx-1,0);items.forEach(function(el,i){el.classList.toggle('active',i===acIdx);});e.preventDefault();}
    else if(e.key==='Enter'&&acIdx>=0){fEst.value=items[acIdx].textContent;acBox.style.display='none';e.preventDefault();}
    else if(e.key==='Escape'){acBox.style.display='none';}
  });

  document.addEventListener('click', function(e){ if(fEst && !fEst.contains(e.target)) acBox.style.display='none'; });
});
