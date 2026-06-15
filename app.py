import sqlite3, csv, io, os, re
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'mapa_salas_secret_2026'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapa_salas.db')

# ── Flask-Login ──────────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar o sistema.'

class Usuario(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM usuarios WHERE id=?', (user_id,)).fetchone()
    conn.close()
    if row:
        return Usuario(row['id'], row['username'], row['role'])
    return None

# ── Decorator de papel ───────────────────────────────────────────────────────
def requer_papel(*papeis):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in papeis:
                return jsonify({'erro': 'Acesso negado'}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ── Constantes ───────────────────────────────────────────────────────────────
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

# ── Banco de dados ───────────────────────────────────────────────────────────
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
        "usuario TEXT DEFAULT '',"
        "acao TEXT,"
        "dados TEXT,"
        "ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
        "CREATE TABLE IF NOT EXISTS usuarios ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "username TEXT NOT NULL UNIQUE,"
        "password_hash TEXT NOT NULL,"
        "role TEXT NOT NULL DEFAULT 'aluno',"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
    )
    existe = conn.execute("SELECT id FROM usuarios WHERE username='coordenador'").fetchone()
    if not existe:
        conn.execute(
            "INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)",
            ('coordenador', generate_password_hash('mudar@2026'), 'coordenador')
        )
    conn.commit()
    conn.close()

def registrar_log(acao, dados=''):
    usuario = current_user.username if current_user.is_authenticated else 'sistema'
    conn = get_db()
    conn.execute('INSERT INTO historico(usuario, acao, dados) VALUES(?,?,?)', (usuario, acao, dados))
    conn.commit()
    conn.close()

# ── Helpers ──────────────────────────────────────────────────────────────────
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

# ── Rotas de autenticação ────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        row = conn.execute('SELECT * FROM usuarios WHERE username=?', (username,)).fetchone()
        conn.close()
        if row and check_password_hash(row['password_hash'], password):
            user = Usuario(row['id'], row['username'], row['role'])
            login_user(user)
            registrar_log('LOGIN', f'Usuário {username} fez login')
            return redirect(url_for('index'))
        flash('Usuário ou senha inválidos.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    registrar_log('LOGOUT', f'Usuário {current_user.username} saiu')
    logout_user()
    return redirect(url_for('login'))

# ── Rota principal ───────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    return render_template('index.html', salas=SALAS, horarios=HORARIOS,
                           categorias=CATEGORIAS, dias=DIAS,
                           usuario=current_user.username, papel=current_user.role)

# ── API de agendamentos ──────────────────────────────────────────────────────
@app.route('/api/agendamentos', methods=['GET'])
@login_required
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
@login_required
def get_ag(aid):
    conn = get_db(); r = conn.execute('SELECT * FROM agendamentos WHERE id=?',(aid,)).fetchone(); conn.close()
    return (jsonify(dict(r)) if r else (jsonify({'erro':'Não encontrado'}), 404))

@app.route('/api/agendamentos', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
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
    registrar_log('CRIAR', f'Agendamento #{nid} criado — sala: {d.get("sala")} {d.get("horario")}')
    return jsonify({'id': nid, 'message': 'Criado'}), 201

@app.route('/api/agendamentos/<int:aid>', methods=['PUT'])
@login_required
@requer_papel('coordenador', 'recepcao')
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
    registrar_log('EDITAR', f'Agendamento #{aid} editado — sala: {d.get("sala")} {d.get("horario")}')
    return jsonify({'message': 'Atualizado'})

@app.route('/api/agendamentos/<int:aid>', methods=['DELETE'])
@login_required
@requer_papel('coordenador', 'recepcao')
def delete_ag(aid):
    conn = get_db()
    r = conn.execute('SELECT * FROM agendamentos WHERE id=?',(aid,)).fetchone()
    conn.execute('DELETE FROM agendamentos WHERE id=?',(aid,))
    conn.commit(); conn.close()
    if r:
        registrar_log('EXCLUIR', f'Agendamento #{aid} excluído — sala: {r["sala"]} {r["horario"]}')
    return jsonify({'message': 'Removido'})

@app.route('/api/stats')
@login_required
def stats():
    dia = request.args.get('dia_semana', 'SEGUNDA')
    conn = get_db()
    total = conn.execute('SELECT COUNT(*) FROM agendamentos WHERE dia_semana=?',(dia,)).fetchone()[0]
    livre = conn.execute("SELECT COUNT(*) FROM agendamentos WHERE dia_semana=? AND categoria='LIVRE'",(dia,)).fetchone()[0]
    por_cat = conn.execute('SELECT categoria, COUNT(*) as n FROM agendamentos WHERE dia_semana=? GROUP BY categoria ORDER BY n DESC',(dia,)).fetchall()
    conn.close()
    return jsonify({'total': total, 'livre': livre, 'por_categoria': [dict(r) for r in por_cat]})

@app.route('/api/export')
@login_required
@requer_papel('coordenador', 'recepcao')
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
    registrar_log('EXPORTAR', 'CSV exportado')
    return send_file(io.BytesIO(out.read().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,
                     download_name=f'mapa_salas_{datetime.now().strftime("%Y%m%d_%H%M")}.csv')

# ── Painel de log (só coordenador) ───────────────────────────────────────────
@app.route('/api/logs')
@login_required
@requer_papel('coordenador')
def get_logs():
    conn = get_db()
    rows = conn.execute('SELECT * FROM historico ORDER BY ts DESC LIMIT 200').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

if __name__ == '__main__':
    init_db()
    print('\n=================================================')
    print('  Mapa de Salas - Policlinica de Psicologia')
    print('  Acesse: http://localhost:5000')
    print('  Login padrão: coordenador / mudar@2026')
    print('  Ctrl+C para encerrar')
    print('=================================================\n')
    app.run(debug=True, port=5000)
