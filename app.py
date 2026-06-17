import sqlite3, csv, io, os, re
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-local-apenas')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapa_salas.db')

VERSAO = '2026-06-16-v8'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar o sistema.'

class Usuario(UserMixin):
    def __init__(self, id, username, role):
        self.id = id; self.username = username; self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM usuarios WHERE id=?', (user_id,)).fetchone()
    conn.close()
    return Usuario(row['id'], row['username'], row['role']) if row else None

def requer_papel(*papeis):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in papeis:
                return jsonify({'erro': 'Acesso negado'}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator

def requer_papel_page(*papeis):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in papeis:
                flash('Acesso negado.', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

SALAS = [
    'Consultório 1','Consultório 2','Consultório 3','Consultório 4',
    'Consultório 5','Consultório 6 (Divã)','Consultório 7 (Divã)',
    'Consultório 8','SOU / NACE','Ludoterapia','Multifuncional',
    'Sala de Grupo 1','Sala de Grupo 2','Supervisão','Coordenação'
]
HORARIOS = ['07:00','08:00','09:00','10:00','11:00','12:00','13:00',
            '14:00','15:00','16:00','17:00','18:00','19:00','20:00']
DIAS = ['SEGUNDA','TERÇA','QUARTA','QUINTA','SEXTA','SÁBADO']
DIAS_PT = {
    'SEGUNDA':'Segunda-feira','TERÇA':'Terça-feira','QUARTA':'Quarta-feira',
    'QUINTA':'Quinta-feira','SEXTA':'Sexta-feira','SÁBADO':'Sábado'
}
CATEGORIAS = [
    'ESTAGIÁRIO 10°','ESTAGIÁRIO 10° TRIAGEM',
    'ESTAGIÁRIO 9°','ESTAGIÁRIO 9° TRIAGEM',
    'SUPERVISÃO','NACE','SOU','MARCAR','NÃO MARCAR',
    'NUTRIÇÃO','PSICODIAGNÓSTICO','PSIQUIATRIA',
    'AMBULATÓRIO NEUROPSICOLOGIA','PLANTÃO PSICOLÓGICO',
    'PRONTUÁRIO/ESTUDAR','LIVRE','OUTRO'
]

LOG_RETENCAO_DIAS = 15

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
        conn.execute("INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)",
            ('coordenador', generate_password_hash('mudar@2026'), 'coordenador'))
    conn.commit(); conn.close()

def registrar_log(acao, dados=''):
    usuario = current_user.username if current_user.is_authenticated else 'sistema'
    conn = get_db()
    conn.execute('INSERT INTO historico(usuario, acao, dados) VALUES(?,?,?)', (usuario, acao, dados))
    conn.execute(
        "DELETE FROM historico WHERE ts < datetime('now', '-' || ? || ' days')",
        (LOG_RETENCAO_DIAS,)
    )
    conn.commit(); conn.close()

def checar_conflito(dia, horario, sala, excluir_id=None):
    conn = get_db()
    try:
        eid = int(excluir_id) if excluir_id else None
    except (ValueError, TypeError):
        eid = None
    if eid:
        r = conn.execute(
            'SELECT * FROM agendamentos WHERE dia_semana=? AND horario=? AND sala=? AND CAST(id AS INTEGER)!=?',
            (dia, horario, sala, eid)).fetchone()
    else:
        r = conn.execute(
            'SELECT * FROM agendamentos WHERE dia_semana=? AND horario=? AND sala=?',
            (dia, horario, sala)).fetchone()
    conn.close()
    return dict(r) if r else None

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

# ── Rotas ────────────────────────────────────────────────────
@app.route('/api/versao')
def api_versao():
    return jsonify({'versao': VERSAO, 'ok': True})

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

@app.route('/')
@login_required
def index():
    return render_template('index.html', salas=SALAS, horarios=HORARIOS,
                           categorias=CATEGORIAS, dias=DIAS,
                           usuario=current_user.username, papel=current_user.role)

# ── Troca de senha ─────────────────────────────────────────────
@app.route('/trocar-senha', methods=['GET', 'POST'])
@login_required
def trocar_senha():
    if request.method == 'POST':
        senha_atual   = request.form.get('senha_atual', '')
        nova_senha    = request.form.get('nova_senha', '').strip()
        confirmar     = request.form.get('confirmar_senha', '').strip()

        conn = get_db()
        row = conn.execute('SELECT * FROM usuarios WHERE id=?', (current_user.id,)).fetchone()
        conn.close()

        if not check_password_hash(row['password_hash'], senha_atual):
            flash('Senha atual incorreta.', 'error')
            return redirect(url_for('trocar_senha'))
        if len(nova_senha) < 6:
            flash('A nova senha deve ter no mínimo 6 caracteres.', 'error')
            return redirect(url_for('trocar_senha'))
        if nova_senha != confirmar:
            flash('As senhas não coincidem.', 'error')
            return redirect(url_for('trocar_senha'))

        conn = get_db()
        conn.execute('UPDATE usuarios SET password_hash=? WHERE id=?',
                     (generate_password_hash(nova_senha), current_user.id))
        conn.commit(); conn.close()
        registrar_log('TROCAR_SENHA', f'Usuário {current_user.username} alterou a própria senha')
        flash('Senha alterada com sucesso!', 'success')
        return redirect(url_for('trocar_senha'))

    return render_template('trocar_senha.html', usuario=current_user.username)

# ── Impressão lista porteiros ─────────────────────────────────────
@app.route('/imprimir')
@login_required
def imprimir_selecao():
    return render_template('imprimir_selecao.html', dias=DIAS, dias_pt=DIAS_PT,
                           usuario=current_user.username, papel=current_user.role)

@app.route('/imprimir/<dia>')
@login_required
def imprimir(dia):
    dia = dia.upper()
    if dia not in DIAS:
        return 'Dia inválido', 400
    conn = get_db()
    rows = conn.execute(
        "SELECT horario, paciente FROM agendamentos "
        "WHERE dia_semana=? AND TRIM(paciente) != '' "
        "ORDER BY horario, paciente COLLATE NOCASE",
        (dia,)
    ).fetchall()
    conn.close()
    pacientes = [{'horario': r['horario'], 'paciente': r['paciente'].strip().title()} for r in rows]
    return render_template('imprimir.html',
        dia_nome=DIAS_PT.get(dia, dia),
        gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'),
        pacientes=pacientes
    )

# ── Logs ────────────────────────────────────────────────────
@app.route('/logs')
@login_required
@requer_papel_page('coordenador')
def logs_page():
    return render_template('logs.html', usuario=current_user.username, papel=current_user.role)

# ── Usuários ────────────────────────────────────────────────────
@app.route('/usuarios')
@login_required
@requer_papel_page('coordenador')
def usuarios_page():
    conn = get_db()
    rows = conn.execute('SELECT id, username, role, created_at FROM usuarios ORDER BY created_at').fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=[dict(r) for r in rows],
                           usuario=current_user.username, papel=current_user.role)

@app.route('/api/usuarios', methods=['GET'])
@login_required
@requer_papel('coordenador')
def api_list_usuarios():
    conn = get_db()
    rows = conn.execute('SELECT id, username, role, created_at FROM usuarios ORDER BY created_at').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/usuarios', methods=['POST'])
@login_required
@requer_papel('coordenador')
def api_criar_usuario():
    d = request.json
    username = (d.get('username') or '').strip()
    password = (d.get('password') or '').strip()
    role     = d.get('role', 'aluno')
    if not username or not password:
        return jsonify({'erro': 'Usuário e senha são obrigatórios'}), 400
    if role not in ('coordenador', 'recepcao', 'aluno'):
        return jsonify({'erro': 'Papel inválido'}), 400
    try:
        conn = get_db()
        conn.execute('INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)',
                     (username, generate_password_hash(password), role))
        conn.commit(); conn.close()
        registrar_log('CRIAR_USUARIO', f'Usuário "{username}" ({role}) criado')
        return jsonify({'message': 'Usuário criado'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'erro': 'Nome de usuário já existe'}), 409

@app.route('/api/usuarios/<int:uid>', methods=['PUT'])
@login_required
@requer_papel('coordenador')
def api_editar_usuario(uid):
    d = request.json
    conn = get_db()
    row = conn.execute('SELECT * FROM usuarios WHERE id=?', (uid,)).fetchone()
    if not row: conn.close(); return jsonify({'erro': 'Usuário não encontrado'}), 404
    new_role = d.get('role', row['role'])
    if new_role not in ('coordenador', 'recepcao', 'aluno'):
        conn.close(); return jsonify({'erro': 'Papel inválido'}), 400
    new_pass = (d.get('password') or '').strip()
    if new_pass:
        conn.execute('UPDATE usuarios SET role=?, password_hash=? WHERE id=?',
                     (new_role, generate_password_hash(new_pass), uid))
    else:
        conn.execute('UPDATE usuarios SET role=? WHERE id=?', (new_role, uid))
    registrar_log('EDITAR_USUARIO', f'Usuário "{row["username"]}" atualizado')
    conn.commit(); conn.close()
    return jsonify({'message': 'Usuário atualizado'})

@app.route('/api/usuarios/<int:uid>', methods=['DELETE'])
@login_required
@requer_papel('coordenador')
def api_excluir_usuario(uid):
    conn = get_db()
    row = conn.execute('SELECT * FROM usuarios WHERE id=?', (uid,)).fetchone()
    if not row: conn.close(); return jsonify({'erro': 'Usuário não encontrado'}), 404
    if row['id'] == current_user.id:
        conn.close(); return jsonify({'erro': 'Você não pode excluir sua própria conta'}), 400
    conn.execute('DELETE FROM usuarios WHERE id=?', (uid,))
    conn.commit(); conn.close()
    registrar_log('EXCLUIR_USUARIO', f'Usuário "{row["username"]}" excluído')
    return jsonify({'message': 'Usuário excluído'})

@app.route('/api/conflito', methods=['GET'])
@login_required
def api_conflito():
    dia     = request.args.get('dia_semana', '')
    horario = request.args.get('horario', '')
    sala    = request.args.get('sala', '')
    excluir = request.args.get('excluir_id', None)
    if not dia or not horario or not sala:
        return jsonify({'conflito': False})
    conflito = checar_conflito(dia, horario, sala, excluir_id=excluir)
    if conflito:
        return jsonify({'conflito': True, 'estagiario': conflito.get('estagiario',''),
                        'paciente': conflito.get('paciente',''), 'categoria': conflito.get('categoria',''),
                        'id': conflito.get('id')})
    return jsonify({'conflito': False})

@app.route('/api/agendamentos', methods=['GET'])
@login_required
def list_ag():
    dia     = request.args.get('dia_semana', 'SEGUNDA')
    horario = request.args.get('horario','')
    sala    = request.args.get('sala','')
    cat     = request.args.get('categoria','')
    busca   = request.args.get('busca','').strip()
    q = 'SELECT * FROM agendamentos WHERE dia_semana=?'; p = [dia]
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
    dia = d.get('dia_semana', 'SEGUNDA'); horario = d.get('horario'); sala = d.get('sala')
    conflito = checar_conflito(dia, horario, sala)
    if conflito:
        ocu = conflito.get('estagiario') or conflito.get('categoria') or 'outro agendamento'
        return jsonify({'erro': f'Conflito: {sala} já está ocupada às {horario} ({dia}) por: {ocu}',
                        'conflito': True, 'conflito_id': conflito.get('id')}), 409
    est = d.get('estagiario',''); pac = d.get('paciente','')
    cat = d.get('categoria','') or detect_cat(est, pac)
    sem = d.get('semestre', 0) or detect_sem(est)
    conn = get_db()
    cur = conn.execute(
        'INSERT INTO agendamentos(dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,observacao,data_especifica)'
        ' VALUES(?,?,?,?,?,?,?,?,?,?)',
        (dia, horario, sala, est, pac, cat, sem, d.get('triagem',0), d.get('observacao',''), d.get('data_especifica',''))
    )
    nid = cur.lastrowid; conn.commit(); conn.close()
    registrar_log('CRIAR', f'Agendamento #{nid} criado — sala: {sala} {horario}')
    return jsonify({'id': nid, 'message': 'Criado'}), 201

@app.route('/api/agendamentos/<int:aid>', methods=['PUT'])
@login_required
@requer_papel('coordenador', 'recepcao')
def update_ag(aid):
    d = request.json
    dia = d.get('dia_semana', 'SEGUNDA'); horario = d.get('horario'); sala = d.get('sala')
    conflito = checar_conflito(dia, horario, sala, excluir_id=aid)
    if conflito:
        ocu = conflito.get('estagiario') or conflito.get('categoria') or 'outro agendamento'
        return jsonify({'erro': f'Conflito: {sala} já está ocupada às {horario} ({dia}) por: {ocu}',
                        'conflito': True, 'conflito_id': conflito.get('id')}), 409
    est = d.get('estagiario',''); pac = d.get('paciente','')
    cat = d.get('categoria','') or detect_cat(est, pac)
    sem = d.get('semestre', 0) or detect_sem(est)
    conn = get_db()
    conn.execute(
        'UPDATE agendamentos SET dia_semana=?,horario=?,sala=?,estagiario=?,paciente=?,categoria=?,semestre=?,'
        'triagem=?,observacao=?,data_especifica=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (dia, horario, sala, est, pac, cat, sem, d.get('triagem',0), d.get('observacao',''), d.get('data_especifica',''), aid)
    )
    conn.commit(); conn.close()
    registrar_log('EDITAR', f'Agendamento #{aid} editado — sala: {sala} {horario}')
    return jsonify({'message': 'Atualizado'})

@app.route('/api/agendamentos/<int:aid>', methods=['DELETE'])
@login_required
@requer_papel('coordenador', 'recepcao')
def delete_ag(aid):
    conn = get_db()
    r = conn.execute('SELECT * FROM agendamentos WHERE id=?',(aid,)).fetchone()
    conn.execute('DELETE FROM agendamentos WHERE id=?',(aid,))
    conn.commit(); conn.close()
    if r: registrar_log('EXCLUIR', f'Agendamento #{aid} excluído — sala: {r["sala"]} {r["horario"]}')
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
@requer_papel('coordenador')
def export_csv():
    conn = get_db()
    rows = conn.execute('SELECT * FROM agendamentos ORDER BY dia_semana, horario, sala').fetchall()
    conn.close()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(['ID','Dia','Horário','Sala','Estagiário','Paciente','Categoria','Semestre','Triagem','Data Esp.','Obs.'])
    for r in rows:
        w.writerow([r['id'],r['dia_semana'],r['horario'],r['sala'],r['estagiario'],r['paciente'],
                    r['categoria'],r['semestre'],'Sim' if r['triagem'] else 'Não',r['data_especifica'],r['observacao']])
    out.seek(0)
    registrar_log('EXPORTAR', 'CSV exportado')
    return send_file(io.BytesIO(out.read().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,
                     download_name=f'mapa_salas_{datetime.now().strftime("%Y%m%d_%H%M")}.csv')

@app.route('/api/logs')
@login_required
@requer_papel('coordenador')
def get_logs():
    conn = get_db()
    rows = conn.execute('SELECT * FROM historico ORDER BY ts DESC LIMIT 500').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/backup')
@login_required
@requer_papel('coordenador')
def backup_db():
    registrar_log('BACKUP', 'Backup manual do banco baixado')
    return send_file(
        DB_PATH,
        as_attachment=True,
        download_name=f'backup_mapa_{datetime.now().strftime("%Y%m%d_%H%M")}.db'
    )

if __name__ == '__main__':
    init_db()
    print(f'\n  Versão: {VERSAO} | http://localhost:5000\n')
    app.run(debug=True, port=5000)
