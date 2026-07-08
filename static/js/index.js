const SALAS = window.MAPA_CONFIG.salas;
const HORARIOS = window.MAPA_CONFIG.horarios;
const DIAS = window.MAPA_CONFIG.dias;
const PROFESSORES = window.MAPA_CONFIG.professores || [];
const PAPEL = window.MAPA_CONFIG.papel;
const CSRF_TOKEN = window.MAPA_CONFIG.csrfToken;
const PODE_EDITAR = ['coordenador','recepcao'].includes(PAPEL);
let currentDay = DIAS[0];
let debTimer = null;
let conflictTimer = null;
let temConflito = false;

const CAT_CLASS = {
  'ESTAGIÁRIO 10°':'cat-est10',
  'ESTAGIÁRIO 9°':'cat-est9',
  'SUPERVISÃO':'cat-sup','NACE':'cat-nace','SOU':'cat-sou',
  'MARCAR':'cat-marcar','NÃO MARCAR':'cat-nmarcar',
  'NUTRIÇÃO':'cat-nutri','PSICODIAGNÓSTICO':'cat-psico',
  'PSIQUIATRIA':'cat-psiq','AMBULATÓRIO NEUROPSICOLOGIA':'cat-ambul',
  'PLANTÃO PSICOLÓGICO':'cat-plantao','PRONTUÁRIO/ESTUDAR':'cat-pront',
  'LIVRE':'cat-livre','OUTRO':'cat-outro'
};
const STATUS_ATENDIMENTO_LABEL = {
  paciente_faltou: 'paciente faltou',
  profissional_desmarcou: 'profissional desmarcou',
  paciente_desmarcou: 'paciente desmarcou'
};

function selectDay(dia, el) {
  const dataFiltro = document.getElementById('filterData');
  const dataIndex = weekdayIndexFromIso(dataFiltro ? dataFiltro.value : '');
  const diaIndex = DIAS.indexOf(dia);
  if (dataFiltro && dataFiltro.value && dataIndex !== diaIndex) {
    dataFiltro.value = '';
  }
  currentDay = dia;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderGrid();
}
function weekdayIndexFromIso(dataIso) {
  if (!dataIso) return null;
  const parts = dataIso.split('-').map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
  const data = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  const diaSemana = data.getUTCDay();
  if (diaSemana < 1 || diaSemana > 5) return null;
  return diaSemana - 1;
}
function setActiveDayByIndex(index) {
  if (index === null || index < 0 || index >= DIAS.length) return;
  currentDay = DIAS[index];
  document.querySelectorAll('.tab').forEach((tab, i) => {
    tab.classList.toggle('active', i === index);
  });
}
function syncDayWithDate(dataIso) {
  const index = weekdayIndexFromIso(dataIso);
  if (index !== null) setActiveDayByIndex(index);
}
function onDateFilterChange() {
  syncDayWithDate(document.getElementById('filterData').value);
  renderGrid();
}
async function loadData() {
  const horario = document.getElementById('filterHorario').value;
  const sala    = document.getElementById('filterSala').value;
  const cat     = document.getElementById('filterCat').value;
  const supervisor = document.getElementById('filterSupervisor')?.value || '';
  const ocupacao= document.getElementById('filterOcupacao').value;
  const busca   = document.getElementById('searchInput').value.trim();
  const data    = document.getElementById('filterData').value;
  const p = new URLSearchParams({dia_semana: currentDay});
  if (horario) p.set('horario', horario);
  if (sala)    p.set('sala', sala);
  if (cat)     p.set('categoria', cat);
  if (supervisor) p.set('supervisor_id', supervisor);
  if (ocupacao !== '') p.set('ocupa_sala', ocupacao);
  if (busca)   p.set('busca', busca);
  if (data)    p.set('data', data);
  const res = await fetch('/api/agendamentos?' + p);
  if (!res.ok) throw new Error('Não foi possível carregar os agendamentos.');
  return await res.json();
}
async function loadStats() {
  const p = new URLSearchParams({dia_semana: currentDay});
  const supervisor = document.getElementById('filterSupervisor')?.value || '';
  if (supervisor) p.set('supervisor_id', supervisor);
  const res = await fetch('/api/stats?'+p);
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
        const cellTemOcupacao = ags.some(ag => parseInt(ag.ocupa_sala) === 1);
        td.innerHTML = ags.map(ag => renderAgendamentoCell(ag, cellTemOcupacao)).join('');
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
function renderAgendamentoCell(ag, cellTemOcupacao=false){
  const cls = CAT_CLASS[ag.categoria] || 'cat-outro';
  const badgeHtml = ag.triagem ? '<span class="badge">triagem</span>' : '';
  const dataHtml  = ag.data_especifica ? '<span class="badge badge-date">somente '+formatarDataCurta(ag.data_especifica)+'</span>' : '<span class="badge badge-fixed">fixo semanal</span>';
  const periodoHtml = parseInt(ag.semestre) ? `<span class="badge badge-periodo">${parseInt(ag.semestre)}- período</span>` : '';
  const statusLabel = STATUS_ATENDIMENTO_LABEL[ag.status_atendimento] || '';
  const statusHtml = statusLabel ? `<span class="badge badge-cancelado">${statusLabel}</span>` : '';
  const ocupa = parseInt(ag.ocupa_sala) === 1;
  const temPaciente = !!String(ag.paciente || '').trim();
  const estadoSala = statusLabel ? 'cell-atendimento-cancelado' : (temPaciente ? 'cell-com-paciente' : 'cell-fixo-sem-paciente');
  const tipoData = ag.data_especifica ? 'cell-pontual' : 'cell-fixo';
  const obsHtml = ag.observacao ? '<div class="obs">'+esc(ag.observacao)+'</div>' : '';
  const supervisorHtml = ag.supervisor_nome ? '<div class="obs">Supervisor: '+esc(ag.supervisor_nome)+'</div>' : '';
  const editBtn   = PODE_EDITAR ? `<button class="edit-btn" onclick="event.stopPropagation();openModal(${ag.id})">Editar</button>` : '';
  const usarBtn = PODE_EDITAR && !ocupa && !cellTemOcupacao ? `<button class="use-room-btn" onclick="event.stopPropagation();openUsoPontual('${escAttr(ag.horario)}','${escAttr(ag.sala)}')">+ Usar sala</button>` : '';
  return `<div class="cell ${cls} ${estadoSala} ${tipoData}" onclick="openModal(${ag.id})">
    ${editBtn}
    <div class="intern">${esc(ag.estagiario)}</div>
    ${ag.paciente ? '<div class="patient">'+esc(ag.paciente)+'</div>' : ''}
    ${supervisorHtml}
    ${obsHtml}
    <div style="display:flex;gap:3px;flex-wrap:wrap">${periodoHtml}${statusHtml}${badgeHtml}${dataHtml}</div>
    ${usarBtn}
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
function formatarDataCurta(data){
  if(!data) return '';
  const partes = String(data).split('-');
  if(partes.length === 3) return `${partes[2]}/${partes[1]}`;
  return data;
}
function esc(t){ if(!t)return''; return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(t){ return esc(t).replace(/'/g,'&#39;').replace(/"/g,'&quot;'); }
function debounceRender(){ clearTimeout(debTimer); debTimer=setTimeout(renderGrid,300); }
function clearFilters(){ document.getElementById('searchInput').value=''; document.getElementById('filterData').value=''; document.getElementById('filterHorario').value=''; document.getElementById('filterSala').value=''; document.getElementById('filterCat').value=''; if(document.getElementById('filterSupervisor')) document.getElementById('filterSupervisor').value=''; document.getElementById('filterOcupacao').value=''; renderGrid(); }
function calcularOcupaSalaLocal(){
  const status = document.getElementById('fStatusAtendimento')?.value || '';
  if(status) return false;

  const manual = document.getElementById('fOcupaSala').value;
  if(manual === '1') return true;
  if(manual === '0') return false;

  const categoria = (document.getElementById('fCategoria').value || '').toUpperCase();
  const paciente = document.getElementById('fPaciente').value.trim();
  const obs = document.getElementById('fObs').value.trim();
  const dataEsp = document.getElementById('fData').value.trim();
  if(paciente) return true;
  if(['SUPERVISÃO','NACE','SOU','NUTRIÇÃO','PSICODIAGNÓSTICO','PSIQUIATRIA','AMBULATÓRIO NEUROPSICOLOGIA','PLANTÃO PSICOLÓGICO','PRONTUÁRIO/ESTUDAR'].includes(categoria)) return true;
  if(dataEsp && obs) return true;
  return false;
}
function atualizarOcupacaoPreview(){
  const hint = document.getElementById('ocupaHint');
  if(!hint) return;
  const status = document.getElementById('fStatusAtendimento')?.value || '';
  if(status){
    hint.textContent = 'Atendimento desmarcado: o registro fica no mapa, mas a sala pode ser usada por outra pessoa.';
    hint.classList.remove('ocupa');
    hint.classList.add('livre');
    return;
  }
  const ocupa = calcularOcupaSalaLocal();
  hint.textContent = ocupa
    ? 'Este registro ocupa a sala e bloqueia outro uso no mesmo horário.'
    : 'Este registro é informativo. A sala continua livre para uso pontual ou atendimento.';
  hint.classList.toggle('ocupa', ocupa);
  hint.classList.toggle('livre', !ocupa);
}
async function verificarConflito() {
  clearTimeout(conflictTimer);
  conflictTimer = setTimeout(async () => {
    const id=document.getElementById('fId').value;
    const dia=document.getElementById('fDia').value;
    const horario=document.getElementById('fHorario').value;
    const sala=document.getElementById('fSala').value;
    const dataEsp=document.getElementById('fData').value.trim();
    const p=new URLSearchParams({
      dia_semana:dia,
      horario,
      sala,
      categoria:document.getElementById('fCategoria').value,
      paciente:document.getElementById('fPaciente').value.trim(),
      observacao:document.getElementById('fObs').value.trim(),
      status_atendimento:document.getElementById('fStatusAtendimento')?.value || '',
      triagem:document.getElementById('fTriagem').value,
      ocupa_sala:calcularOcupaSalaLocal() ? '1' : '0'
    });
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
      msg.textContent=`${sala} · ${horario} (${dia}): ocupada por ${data.estagiario||data.categoria||'outro'}`;
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
         <strong>Estagiário:</strong> ${esc(d.estagiario)||'-'}<br>
         <strong>Paciente:</strong> ${esc(d.paciente)||'-'}<br>
         <strong>Categoria:</strong> ${esc(d.categoria)||'-'}<br>
         <strong>Ocupa sala:</strong> ${parseInt(d.ocupa_sala)===1?'Sim':'Não'}<br>
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
      atualizarSupervisorHint(d.supervisor_nome || '');
      document.getElementById('fPaciente').value=d.paciente||'';
      setCategoriaSelecionada(d.categoria); setF('fSemestre',d.semestre || 0); setF('fTriagem',d.triagem);
      setF('fStatusAtendimento',d.status_atendimento || '');
      document.getElementById('fData').value=d.data_especifica||'';
      document.getElementById('fObs').value=d.observacao||'';
      setF('fOcupaSala', String(d.ocupa_sala ?? ''));
    } catch (err) {
      showToast(err.message || 'Falha ao abrir o agendamento.', 'error');
      return;
    }
  } else {
    setF('fDia',currentDay); setCategoriaSelecionada(''); setF('fSemestre',0); setF('fTriagem',0); setF('fStatusAtendimento',''); setF('fOcupaSala','');
    ['fEstagiario','fPaciente','fData','fObs'].forEach(id=>document.getElementById(id).value='');
    atualizarSupervisorHint('');
    document.getElementById('fObs').placeholder='Ex: estudar, lançar prontuário, professor não liberou, uso interno...';
    document.getElementById('fData').value=document.getElementById('filterData').value||'';
  }
  atualizarOcupacaoPreview();
  document.getElementById('modalOverlay').classList.add('open');
}
function openModalNew(h,s){ if(!PODE_EDITAR)return; openModal(null); setTimeout(()=>{setF('fHorario',h);setF('fSala',s);verificarConflito();},50); }
function todayIso(){ return new Date().toISOString().slice(0,10); }
function openUsoPontual(h,s){
  if(!PODE_EDITAR)return;
  openModal(null);
  setTimeout(()=>{
    setF('fHorario',h);
    setF('fSala',s);
    setF('fCategoria','PRONTUÁRIO/ESTUDAR');
    setF('fOcupaSala','1');
    document.getElementById('fData').value=document.getElementById('filterData').value||todayIso();
    document.getElementById('fObs').placeholder='Ex: Victor estudar, lançar prontuário, reunião pontual...';
    atualizarOcupacaoPreview();
    verificarConflito();
  },50);
}
function setF(id,val){ const el=document.getElementById(id); if(el) el.value=val; }
function setCategoriaSelecionada(valor){
  const select = document.getElementById('fCategoria');
  if(!select) return;
  const existe = Array.from(select.options).some(opt => opt.value === valor);
  if(!existe && valor){
    const opt = document.createElement('option');
    opt.value = valor;
    opt.textContent = `Registro antigo: ${valor}`;
    opt.dataset.legacy = '1';
    select.appendChild(opt);
  }
  select.value = valor || '';
}
function closeModal(){ document.getElementById('modalOverlay').classList.remove('open'); }
function closeModalIfBg(e){ if(e.target.id==='modalOverlay') closeModal(); }
async function saveAg(){
  if(temConflito){ showToast('Resolva o conflito antes de salvar!','error'); return; }
  const id=document.getElementById('fId').value;
  const categoriaSelecionada = document.getElementById('fCategoria').value;
  const semestreSelecionado = parseInt(document.getElementById('fSemestre')?.value)||0;
  if(semestreSelecionado && !categoriaSelecionada){
    showToast('Escolha a função do horário: MARCAR, NÃO MARCAR, prontuário, supervisão etc.','error');
    return;
  }
  const body={
    dia_semana:document.getElementById('fDia').value,
    horario:document.getElementById('fHorario').value,
    sala:document.getElementById('fSala').value,
    estagiario:document.getElementById('fEstagiario').value.trim(),
    paciente:document.getElementById('fPaciente').value.trim(),
    categoria:categoriaSelecionada,
    semestre:semestreSelecionado,
    triagem:parseInt(document.getElementById('fTriagem').value)||0,
    status_atendimento:document.getElementById('fStatusAtendimento')?.value || '',
    data_especifica:document.getElementById('fData').value.trim(),
    observacao:document.getElementById('fObs').value.trim(),
    ocupa_sala:calcularOcupaSalaLocal() ? 1 : 0
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
  if(res.ok){
    showToast('Salvo!','success');
    closeModal();
    if(body.data_especifica) syncDayWithDate(body.data_especifica);
    renderGrid();
  }
  else if(res.status===409){
    document.getElementById('conflictMsg').textContent=data.erro||'Conflito de sala.';
    document.getElementById('conflictBox').classList.add('show');
    const btn=document.getElementById('saveBtn');
    btn.disabled=true; btn.style.opacity='0.4'; btn.style.cursor='not-allowed';
    showToast('Conflito de sala!','error');
  } else { showToast((data.erro||'Erro ao salvar'),'error'); }
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
function openAboutModal(){
  const menu = document.getElementById('dropdownMenu');
  if(menu) menu.classList.remove('open');
  document.getElementById('aboutOverlay').classList.add('open');
}
function closeAboutModal(){
  document.getElementById('aboutOverlay').classList.remove('open');
}
function openImportModal(){
  const menu = document.getElementById('dropdownMenu');
  if(menu) menu.classList.remove('open');
  document.getElementById('importResult').style.display = 'none';
  document.getElementById('importResult').textContent = '';
  document.getElementById('importForm').reset();
  document.getElementById('importOverlay').classList.add('open');
}
function closeImportModal(){
  document.getElementById('importOverlay').classList.remove('open');
}
async function submitImportExcel(e){
  e.preventDefault();
  const btn = document.getElementById('importBtn');
  const result = document.getElementById('importResult');
  const file = document.getElementById('importFile').files[0];
  if(!file){
    showToast('Selecione um arquivo para importar.', 'warn');
    return;
  }
  const form = new FormData();
  form.append('file', file);
  if(document.getElementById('importSubstituir').checked){
    if(!confirm('Substituir todo o mapa atual antes de importar este Excel?')) return;
    form.append('substituir', '1');
  }
  btn.disabled = true;
  btn.style.opacity = '0.6';
  result.style.display = 'block';
  result.textContent = 'Importando arquivo...';
  try {
    const res = await fetch('/api/import', {
      method: 'POST',
      headers: {'X-CSRFToken': CSRF_TOKEN},
      body: form
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.erro || 'Não foi possível importar o arquivo.');
    const conflitos = (data.conflitos || []).length;
    const erros = (data.erros || []).length;
    result.innerHTML =
      `<strong>${data.inseridos || 0}</strong> agendamento(s) importado(s).<br>` +
      `<strong>${conflitos}</strong> conflito(s). <strong>${erros}</strong> erro(s).` +
      (data.ignorados ? `<br>${data.ignorados} célula(s) vazia(s) ou marcadores internos ignorados.` : '');
    showToast('Importação concluída.', 'success');
    renderGrid();
  } catch(err) {
    result.textContent = err.message || 'Falha ao importar.';
    showToast(result.textContent, 'error');
  } finally {
    btn.disabled = false;
    btn.style.opacity = '';
  }
}
async function desfazerUltimaImportacao(){
  const ok = confirm('Desfazer a ultima importacao e voltar o mapa para o estado anterior?');
  if(!ok) return;

  const btn = document.getElementById('undoImportBtn');
  const result = document.getElementById('importResult');
  btn.disabled = true;
  btn.style.opacity = '0.6';
  result.style.display = 'block';
  result.textContent = 'Restaurando mapa anterior...';

  try {
    const res = await fetch('/api/import/desfazer', {
      method: 'POST',
      headers: {'X-CSRFToken': CSRF_TOKEN}
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.erro || 'Nao foi possivel desfazer a importacao.');

    result.innerHTML =
      `<strong>${data.restaurados || 0}</strong> agendamento(s) restaurado(s).` +
      (data.arquivo ? `<br>Importacao desfeita: ${esc(data.arquivo)}` : '');
    showToast('Importacao desfeita.', 'success');
    renderGrid();
  } catch(err) {
    result.textContent = err.message || 'Falha ao desfazer importacao.';
    showToast(result.textContent, 'error');
  } finally {
    btn.disabled = false;
    btn.style.opacity = '';
  }
}
function showToast(msg,type='success'){
  const t=document.getElementById('toast');
  t.textContent=msg; t.className='toast show '+type;
  setTimeout(()=>t.className='toast',3000);
}

function aplicarParametrosMapaInicial(){
  const params = new URLSearchParams(window.location.search);
  const dia = params.get('dia_semana');
  const horario = params.get('horario');
  const sala = params.get('sala');
  const data = params.get('data');
  const supervisor = params.get('supervisor_id');
  if(dia && DIAS.includes(dia)){
    currentDay = dia;
    setActiveDayByIndex(DIAS.indexOf(dia));
  }
  if(horario && HORARIOS.includes(horario)){
    document.getElementById('filterHorario').value = horario;
  }
  if(sala && SALAS.includes(sala)){
    document.getElementById('filterSala').value = sala;
  }
  if(data){
    document.getElementById('filterData').value = data;
    syncDayWithDate(data);
  }
  if(supervisor && document.getElementById('filterSupervisor')){
    document.getElementById('filterSupervisor').value = supervisor;
  }
}

function abrirAgendamentoInicial(){
  const params = new URLSearchParams(window.location.search);
  const abrirId = params.get('abrir_agendamento');
  const horario = params.get('horario');
  const sala = params.get('sala');
  if(abrirId){
    openModal(parseInt(abrirId, 10));
    return;
  }
  if(params.get('novo') === '1' && horario && sala){
    openModalNew(horario, sala);
  }
}

aplicarParametrosMapaInicial();
renderGrid().then(abrirAgendamentoInicial);
document.getElementById('importForm')?.addEventListener('submit', submitImportExcel);

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
  _estList = users || [];
}).catch(function(){
  _estList = [];
});

function supervisorNomeDoAluno(username){
  var alvo = String(username || '').trim().toLowerCase();
  if(!alvo) return '';
  var aluno = _estList.find(function(u){ return String(u.username || '').toLowerCase() === alvo; });
  return aluno ? (aluno.supervisor_nome || '') : '';
}

function atualizarSupervisorHint(nome){
  var hint = document.getElementById('supervisorHint');
  if(!hint) return;
  hint.textContent = nome ? ('Supervisor: ' + nome) : 'Supervisor: nao definido';
}

document.addEventListener('DOMContentLoaded', function() {
  if(window.lucide) lucide.createIcons();
  var fEst = document.getElementById('fEstagiario');
  var acBox = document.getElementById('estSuggestions');
  if (!fEst || !acBox) return;
  var acIdx = -1;

  fEst.addEventListener('input', function() {
    var val = this.value.trim().toLowerCase();
    atualizarSupervisorHint(supervisorNomeDoAluno(this.value));
    acBox.innerHTML = '';
    acIdx = -1;
    if (!val || !_estList.length) { acBox.style.display='none'; return; }
    var matches = _estList.filter(function(u){ return String(u.username || '').toLowerCase().includes(val); });
    if (!matches.length) { acBox.style.display='none'; return; }
    matches.forEach(function(user) {
      var d = document.createElement('div');
      d.className = 'ac-item';
      d.textContent = user.supervisor_nome ? `${user.username} - ${user.supervisor_nome}` : user.username;
      d.addEventListener('mousedown', function() {
        fEst.value = user.username;
        atualizarSupervisorHint(user.supervisor_nome || '');
        acBox.style.display='none';
      });
      acBox.appendChild(d);
    });
    acBox.style.display = 'block';
  });

  fEst.addEventListener('keydown', function(e) {
    var items = acBox.querySelectorAll('.ac-item');
    if (e.key==='ArrowDown'){acIdx=Math.min(acIdx+1,items.length-1);items.forEach(function(el,i){el.classList.toggle('active',i===acIdx);});e.preventDefault();}
    else if(e.key==='ArrowUp'){acIdx=Math.max(acIdx-1,0);items.forEach(function(el,i){el.classList.toggle('active',i===acIdx);});e.preventDefault();}
    else if(e.key==='Enter'&&acIdx>=0){
      var texto = items[acIdx].textContent.split(' - ')[0];
      fEst.value=texto;
      atualizarSupervisorHint(supervisorNomeDoAluno(texto));
      acBox.style.display='none';
      e.preventDefault();
    }
    else if(e.key==='Escape'){acBox.style.display='none';}
  });

  document.addEventListener('click', function(e){ if(fEst && !fEst.contains(e.target)) acBox.style.display='none'; });
});
