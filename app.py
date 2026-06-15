import sqlite3, csv, io, os, re
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapa_salas.db')

SALAS = [
    'Consultório 1','Consultório 2','Consultório 3','Consultório 4',
    'Consultório 5','Consultório 6 (Divã)','Consultório 7 (Divã)',
    'Consultório 8','SOU / NACE','Ludoterapia','Multifuncional',
    'Sala de Grupo 1','Sala de Grupo 2','Supervisão','Coordenação'
]
HORARIOS = ['07:00','08:00','09:00','10:00','11:00','12:00','13:00',
            '14:00','15:00','16:00','17:00','18:00','19:00','20:00']
DIAS = ['SEGUNDA','TERÇA','QUARTA','QUINTA','SEXTA','SÁBADO']
CATEGORIAS = [
    'ESTAGIÁRIO 10°','ESTAGIÁRIO 10° TRIAGEM',
    'ESTAGIÁRIO 9°','ESTAGIÁRIO 9° TRIAGEM',
    'SUPERVISÃO','NACE','SOU','MARCAR','NÃO MARCAR',
    'NUTRIÇÃO','PSICODIAGNÓSTICO','PSIQUIATRIA',
    'AMBULATÓRIO NEUROPSICOLOGIA','PLANTÃO PSICOLÓGICO',
    'PRONTUÁRIO/ESTUDAR','LIVRE','OUTRO'
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS agendamentos ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "dia_semana TEXT DEFAULT 'SEGUNDA',"
        "horario TEXT NOT NULL,"
        "sala TEXT NOT NULL,"
        "estagiario TEXT DEFAULT '',"
        "paciente TEXT DEFAULT '',"
        "categoria TEXT DEFAULT '',"
        "semestre INTEGER DEFAULT 0,"
        "triagem INTEGER DEFAULT 0,"
        "observacao TEXT DEFAULT '',"
        "data_especifica TEXT DEFAULT '',"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
        "CREATE TABLE IF NOT EXISTS historico ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "acao TEXT, dados TEXT,"
        "ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
    )
    conn.commit()
    conn.close()

def normalize(t):
    if not t: return ''
    for o, n in [('ă','ã'),('Ă','Ã'),('ş','º'),('Ş','º'),('ţ','ç')]:
        t = t.replace(o, n)
    return t.strip()

def detect_cat(est, pac):
    c = normalize(est + ' ' + pac).upper()
    if 'NÃO MARCAR' in c or 'NAO MARCAR' in c: return 'NÃO MARCAR'
    if 'PSICODIAG' in c: return 'PSICODIAGNÓSTICO'
    if 'SUPERVISÃO' in c or 'SUPERVISAO' in c or 'PROF.' in c or re.search(r'PROF\s+\w', c): return 'SUPERVISÃO'
    if 'NACE' in c: return 'NACE'
    if re.search(r'\bSOU\b', c): return 'SOU'
    if 'MARCAR' in c: return 'MARCAR'
    if 'NUTRIÇÃO' in c or 'NUTRICAO' in c: return 'NUTRIÇÃO'
    if 'PSIQUIATRIA' in c: return 'PSIQUIATRIA'
    if 'AMBULAT' in c: return 'AMBULATÓRIO NEUROPSICOLOGIA'
    if 'PLANTÃO' in c or 'PLANTAO' in c: return 'PLANTÃO PSICOLÓGICO'
    if 'PRONTUÁRIO' in c or 'PRONTUARIO' in c or 'ESTUDAR' in c: return 'PRONTUÁRIO/ESTUDAR'
    if re.search(r'10[°º]', c): return 'ESTAGIÁRIO 10° TRIAGEM' if 'TRIAGEM' in c else 'ESTAGIÁRIO 10°'
    if re.search(r'9[°º]', c): return 'ESTAGIÁRIO 9° TRIAGEM' if 'TRIAGEM' in c else 'ESTAGIÁRIO 9°'
    en = normalize(est).strip()
    if en and not any(x in en.upper() for x in ['PSICODIAG','NÃO','MARCAR','SUPERVISÃO']):
        return 'ESTAGIÁRIO 9° TRIAGEM' if 'TRIAGEM' in en.upper() else 'ESTAGIÁRIO 9°'
    if not normalize(est).strip() and not normalize(pac).strip(): return 'LIVRE'
    return 'OUTRO'

def detect_sem(t):
    t = normalize(t)
    if re.search(r'10[°º]', t): return 10
    if re.search(r'9[°º]', t): return 9
    return 0

@app.route('/')
def index():
    return render_template('index.html', salas=SALAS, horarios=HORARIOS,
                           categorias=CATEGORIAS, dias=DIAS)

@app.route('/api/agendamentos', methods=['GET'])
def list_ag():
    dia     = request.args.get('dia_semana', 'SEGUNDA')
    horario = request.args.get('horario','')
    sala    = request.args.get('sala','')
    cat     = request.args.get('categoria','')
    busca   = request.args.get('busca','').strip()
    q = 'SELECT * FROM agendamentos WHERE dia_semana=?'
    p = [dia]
    if horario: q += ' AND horario=?'; p.append(horario)
    if sala:    q += ' AND sala=?';    p.append(sala)
    if cat:     q += ' AND categoria=?'; p.append(cat)
    if busca:   q += ' AND (estagiario LIKE ? OR paciente LIKE ? OR observacao LIKE ?)'; p += [f'%{busca}%']*3
    q += ' ORDER BY horario, sala'
    conn = get_db(); rows = conn.execute(q, p).fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/agendamentos/<int:aid>', methods=['GET'])
def get_ag(aid):
    conn = get_db(); r = conn.execute('SELECT * FROM agendamentos WHERE id=?',(aid,)).fetchone(); conn.close()
    return (jsonify(dict(r)) if r else (jsonify({'erro':'Não encontrado'}), 404))

@app.route('/api/agendamentos', methods=['POST'])
def create_ag():
    d = request.json
    est = d.get('estagiario',''); pac = d.get('paciente','')
    cat = d.get('categoria','') or detect_cat(est, pac)
    sem = d.get('semestre', 0) or detect_sem(est)
    conn = get_db()
    cur = conn.execute(
        'INSERT INTO agendamentos(dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,observacao,data_especifica)'
        ' VALUES(?,?,?,?,?,?,?,?,?,?)',
        (d.get('dia_semana','SEGUNDA'), d.get('horario'), d.get('sala'), est, pac, cat, sem,
         d.get('triagem',0), d.get('observacao',''), d.get('data_especifica',''))
    )
    nid = cur.lastrowid; conn.commit(); conn.close()
    return jsonify({'id': nid, 'message': 'Criado'}), 201

@app.route('/api/agendamentos/<int:aid>', methods=['PUT'])
def update_ag(aid):
    d = request.json
    est = d.get('estagiario',''); pac = d.get('paciente','')
    cat = d.get('categoria','') or detect_cat(est, pac)
    sem = d.get('semestre', 0) or detect_sem(est)
    conn = get_db()
    conn.execute(
        'UPDATE agendamentos SET dia_semana=?,horario=?,sala=?,estagiario=?,paciente=?,categoria=?,semestre=?,'
        'triagem=?,observacao=?,data_especifica=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (d.get('dia_semana','SEGUNDA'), d.get('horario'), d.get('sala'), est, pac, cat, sem,
         d.get('triagem',0), d.get('observacao',''), d.get('data_especifica',''), aid)
    )
    conn.commit(); conn.close()
    return jsonify({'message': 'Atualizado'})

@app.route('/api/agendamentos/<int:aid>', methods=['DELETE'])
def delete_ag(aid):
    conn = get_db()
    conn.execute('DELETE FROM agendamentos WHERE id=?',(aid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Removido'})

@app.route('/api/stats')
def stats():
    dia = request.args.get('dia_semana', 'SEGUNDA')
    conn = get_db()
    total = conn.execute('SELECT COUNT(*) FROM agendamentos WHERE dia_semana=?',(dia,)).fetchone()[0]
    livre = conn.execute("SELECT COUNT(*) FROM agendamentos WHERE dia_semana=? AND categoria='LIVRE'",(dia,)).fetchone()[0]
    por_cat = conn.execute('SELECT categoria, COUNT(*) as n FROM agendamentos WHERE dia_semana=? GROUP BY categoria ORDER BY n DESC',(dia,)).fetchall()
    conn.close()
    return jsonify({'total': total, 'livre': livre, 'por_categoria': [dict(r) for r in por_cat]})

@app.route('/api/export')
def export_csv():
    conn = get_db()
    rows = conn.execute('SELECT * FROM agendamentos ORDER BY dia_semana, horario, sala').fetchall()
    conn.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['ID','Dia','Horário','Sala','Estagiário','Paciente','Categoria','Semestre','Triagem','Data Esp.','Obs.'])
    for r in rows:
        w.writerow([r['id'],r['dia_semana'],r['horario'],r['sala'],r['estagiario'],r['paciente'],
                    r['categoria'],r['semestre'],'Sim' if r['triagem'] else 'Não',
                    r['data_especifica'],r['observacao']])
    out.seek(0)
    return send_file(io.BytesIO(out.read().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,
                     download_name=f'mapa_salas_{datetime.now().strftime("%Y%m%d_%H%M")}.csv')

if __name__ == '__main__':
    init_db()
    print('\n=================================================')
    print('  Mapa de Salas - Policlinica de Psicologia')
    print('  Acesse: http://localhost:5000')
    print('  Ctrl+C para encerrar')
    print('=================================================\n')
    app.run(debug=True, port=5000)
