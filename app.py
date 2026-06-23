import sqlite3, csv, io, os, re
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
try:
    from dotenv import load_dotenv as _ld
    import os as _os
    _ld(dotenv_path='/home/victroid/mapa_sala/.env')
except ImportError:
    pass

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY não definida. Crie o arquivo .env com SECRET_KEY=<chave> "
        "ou defina a variável de ambiente antes de iniciar o app."
    )

app.secret_key = _secret_key
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapa_salas.db')

VERSAO = '2026-06-22-v15'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar o sistema.'

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri='memory://'
)

PAPEIS_VALIDOS = ('coordenador', 'recepcao', 'professor', 'aluno')

class Usuario(UserMixin):
    def __init__(self, id, username, role, nome_completo='', email=''):
        self.id = id
        self.username = username
        self.role = role
        self.nome_completo = nome_completo
        self.email = email


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM usuarios WHERE id=?', (user_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return Usuario(row['id'], row['username'], row['role'], row['nome_completo'] or '', row['email'] or '')


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
    'Consultório 1', 'Consultório 2', 'Consultório 3', 'Consultório 4',
    'Consultório 5', 'Consultório 6 (Divã)', 'Consultório 7 (Divã)',
    'Consultório 8', 'SOU / NACE', 'Ludoterapia', 'Multifuncional',
    'Sala de Grupo 1', 'Sala de Grupo 2', 'Supervisão', 'Coordenação'
]

HORARIOS = ['07:00', '08:00', '09:00', '10:00', '11:00', '12:00', '13:00',
            '14:00', '15:00', '16:00', '17:00', '18:00', '19:00', '20:00']
DIAS = ['SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA']
DIAS_PT = {
    'SEGUNDA': 'Segunda-feira', 'TERÇA': 'Terça-feira', 'QUARTA': 'Quarta-feira',
    'QUINTA': 'Quinta-feira', 'SEXTA': 'Sexta-feira',
}

CATEGORIAS = [
    'ESTAGIÁRIO 10°', 'ESTAGIÁRIO 10° TRIAGEM',
    'ESTAGIÁRIO 9°', 'ESTAGIÁRIO 9° TRIAGEM',
    'SUPERVISÃO', 'NACE', 'SOU', 'MARCAR', 'NÃO MARCAR',
    'NUTRIÇÃO', 'PSICODIAGNÓSTICO', 'PSIQUIATRIA',
    'AMBULATÓRIO NEUROPSICOLOGIA', 'PLANTÃO PSICOLÓGICO',
    'PRONTUÁRIO/ESTUDAR', 'LIVRE', 'OUTRO'
]

PAPEIS_LABEL = {
    'coordenador': 'Coordenador',
    'recepcao': 'Recepção',
    'professor': 'Professor Supervisor',
    'aluno': 'Estagiário'
}

LOG_RETENCAO_DIAS = 15


def init_db():
    conn = get_db()
    try:
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
            "usuario_id INTEGER DEFAULT NULL,"
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
            "nome_completo TEXT DEFAULT '',"
            "email TEXT DEFAULT '',"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ");"
        )
        existe = conn.execute("SELECT id FROM usuarios WHERE username='coordenador'").fetchone()
        if not existe:
            conn.execute("INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)",
                         ('coordenador', generate_password_hash('mudar@2026'), 'coordenador'))
        conn.executescript(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_conflito ON agendamentos(dia_semana, horario, sala);"
            "CREATE INDEX IF NOT EXISTS idx_dia_semana ON agendamentos(dia_semana);"
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(agendamentos)").fetchall()]
        if 'usuario_id' not in cols:
            conn.execute("ALTER TABLE agendamentos ADD COLUMN usuario_id INTEGER DEFAULT NULL")
            conn.commit()
        conn.commit()
    finally:
        conn.close()


def registrar_log(acao, dados=''):
    usuario = current_user.username if current_user.is_authenticated else 'sistema'
    conn = get_db()
    try:
        conn.execute('INSERT INTO historico(usuario, acao, dados) VALUES(?,?,?)', (usuario, acao, dados))
        conn.commit()
    finally:
        conn.close()


def checar_conflito(dia, horario, sala, excluir_id=None):
    conn = get_db()
    try:
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
    finally:
        conn.close()
    return dict(r) if r else None


def normalize(t):
    if not t:
        return ''
    for o, n in [('ă', 'ã'), ('Ă', 'Ã'), ('ş', 'º'), ('Ş', 'º'), ('ţ', 'ç')]:
        t = t.replace(o, n)
    return t.strip()


def detect_cat(est, pac):
    c = normalize(est + ' ' + pac).upper()
    if 'NÃO MARCAR' in c or 'NAO MARCAR' in c: return 'NÃO MARCAR'
    if 'PSICODIAG' in c: return 'PSICODIAGNÓSTICO'
    if 'SUPERVISÃO' in c or 'SUPERVISAO' in c or 'PROF.' in c or re.search(r'PROF\s+\w', c): return 'SUPERVISÃO'
    if 'NACE' in c: return 'NACE'
    if re.search(r'SOU', c): return 'SOU'
    if 'MARCAR' in c: return 'MARCAR'
    if 'NUTRIÇÃO' in c or 'NUTRICAO' in c: return 'NUTRIÇÃO'
    if 'PSIQUIATRIA' in c: return 'PSIQUIATRIA'
    if 'AMBULAT' in c: return 'AMBULATÓRIO NEUROPSICOLOGIA'
    if 'PLANTÃO' in c or 'PLANTAO' in c: return 'PLANTÃO PSICOLÓGICO'
    if 'PRONTUÁRIO' in c or 'PRONTUARIO' in c or 'ESTUDAR' in c: return 'PRONTUÁRIO/ESTUDAR'
    if re.search(r'10[°º]', c): return 'ESTAGIÁRIO 10° TRIAGEM' if 'TRIAGEM' in c else 'ESTAGIÁRIO 10°'
    if re.search(r'9[°º]', c): return 'ESTAGIÁRIO 9° TRIAGEM' if 'TRIAGEM' in c else 'ESTAGIÁRIO 9°'
    en = normalize(est).strip()
    if en and not any(x in en.upper() for x in ['PSICODIAG', 'NÃO', 'MARCAR', 'SUPERVISÃO']):
        return 'ESTAGIÁRIO 9° TRIAGEM' if 'TRIAGEM' in en.upper() else 'ESTAGIÁRIO 9°'
    if not normalize(est).strip() and not normalize(pac).strip(): return 'LIVRE'
    return 'OUTRO'


def detect_sem(t):
    t = normalize(t)
    if re.search(r'10[°º]', t): return 10
    if re.search(r'9[°º]', t): return 9
    return 0


@app.route('/api/versao')
def api_versao():
    return jsonify({'versao': VERSAO, 'ok': True})


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        try:
            row = conn.execute('SELECT * FROM usuarios WHERE username=?', (username,)).fetchone()
        finally:
            conn.close()
        if row and check_password_hash(row['password_hash'], password):
            user = Usuario(row['id'], row['username'], row['role'],
                           row['nome_completo'] or '', row['email'] or '')
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


@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM usuarios WHERE id=?', (current_user.id,)).fetchone()
    finally:
        conn.close()

    if request.method == 'POST':
        nome_completo = request.form.get('nome_completo', '').strip()
        email = request.form.get('email', '').strip()
        if not nome_completo:
            flash('Nome completo é obrigatório.', 'error')
            return redirect(url_for('perfil'))
        if not email:
            flash('E-mail é obrigatório.', 'error')
            return redirect(url_for('perfil'))
        conn = get_db()
        try:
            conn.execute('UPDATE usuarios SET nome_completo=?, email=? WHERE id=?',
                         (nome_completo, email, current_user.id))
            conn.commit()
        finally:
            conn.close()
        registrar_log('EDITAR_PERFIL', f'Usuário {current_user.username} atualizou o perfil')
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('perfil'))

    return render_template('perfil.html',
                           usuario=current_user.username,
                           papel=current_user.role,
                           papel_label=PAPEIS_LABEL.get(current_user.role, current_user.role),
                           nome_completo=row['nome_completo'] or '',
                           email=row['email'] or '')


@app.route('/trocar-senha', methods=['GET', 'POST'])
@login_required
def trocar_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '')
        nova_senha = request.form.get('nova_senha', '').strip()
        confirmar = request.form.get('confirmar_senha', '').strip()
        conn = get_db()
        try:
            row = conn.execute('SELECT * FROM usuarios WHERE id=?', (current_user.id,)).fetchone()
        finally:
            conn.close()
        if not check_password_hash(row['password_hash'], senha_atual):
            flash('Senha atual incorreta.', 'error')
            return redirect(url_for('trocar_senha'))
        if len(nova_senha) < 8:
            flash('A nova senha deve ter no mínimo 8 caracteres.', 'error')
            return redirect(url_for('trocar_senha'))
        if nova_senha != confirmar:
            flash('As senhas não coincidem.', 'error')
            return redirect(url_for('trocar_senha'))
        conn = get_db()
        try:
            conn.execute('UPDATE usuarios SET password_hash=? WHERE id=?',
                         (generate_password_hash(nova_senha), current_user.id))
            conn.commit()
        finally:
            conn.close()
        registrar_log('TROCAR_SENHA', f'Usuário {current_user.username} alterou a própria senha')
        flash('Senha alterada com sucesso!', 'success')
        return redirect(url_for('perfil'))
    return render_template('trocar_senha.html',
                           usuario=current_user.username,
                           papel=current_user.role)


@app.route('/imprimir')
@login_required
@requer_papel_page('coordenador', 'recepcao')
def imprimir_selecao():
    return render_template('imprimir_selecao.html', dias=DIAS, dias_pt=DIAS_PT,
                           usuario=current_user.username, papel=current_user.role)


@app.route('/imprimir/<dia>')
@login_required
@requer_papel_page('coordenador', 'recepcao')
def imprimir(dia):
    dia = dia.upper()
    if dia not in DIAS:
        return 'Dia inválido', 400
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT horario, paciente FROM agendamentos "
            "WHERE dia_semana=? AND TRIM(paciente) != '' "
            "ORDER BY horario, paciente COLLATE NOCASE",
            (dia,)
        ).fetchall()
    finally:
        conn.close()
    pacientes = [{'horario': r['horario'], 'paciente': r['paciente'].strip().title()} for r in rows]
    return render_template('imprimir.html',
                           dia_nome=DIAS_PT.get(dia, dia),
                           gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'),
                           pacientes=pacientes)


@app.route('/logs')
@login_required
@requer_papel_page('coordenador')
def logs_page():
    return render_template('logs.html', usuario=current_user.username, papel=current_user.role)


@app.route('/usuarios')
@login_required
@requer_papel_page('coordenador')
def usuarios_page():
    conn = get_db()
    try:
        rows = conn.execute('SELECT id, username, role, created_at FROM usuarios ORDER BY created_at').fetchall()
    finally:
        conn.close()
    return render_template('usuarios.html', usuarios=[dict(r) for r in rows],
                           usuario=current_user.username, papel=current_user.role)


@app.route('/api/estagiarios', methods=['GET'])
@login_required
def api_list_estagiarios():
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, username FROM usuarios WHERE role='aluno' ORDER BY username").fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/usuarios', methods=['GET'])
@login_required
@requer_papel('coordenador')
def api_list_usuarios():
    conn = get_db()
    try:
        rows = conn.execute('SELECT id, username, role, created_at FROM usuarios ORDER BY created_at').fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/usuarios', methods=['POST'])
@login_required
@requer_papel('coordenador')
@limiter.limit('20 per minute')
def api_criar_usuario():
    d = request.get_json(silent=True)
    if not d:
        return jsonify({'erro': 'JSON inválido ou Content-Type incorreto'}), 400
    username = (d.get('username') or '').strip()
    password = (d.get('password') or '').strip()
    role = d.get('role', 'aluno')
    if not username or not password:
        return jsonify({'erro': 'Usuário e senha são obrigatórios'}), 400
    if len(password) < 8:
        return jsonify({'erro': 'A senha deve ter no mínimo 8 caracteres'}), 400
    if role not in PAPEIS_VALIDOS:
        return jsonify({'erro': 'Papel inválido'}), 400
    try:
        conn = get_db()
        try:
            conn.execute('INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)',
                         (username, generate_password_hash(password), role))
            conn.commit()
        finally:
            conn.close()
        registrar_log('CRIAR_USUARIO', f'Usuário "{username}" ({role}) criado')
        return jsonify({'message': 'Usuário criado'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'erro': 'Nome de usuário já existe'}), 409


@app.route('/api/usuarios/<int:uid>', methods=['PUT'])
@login_required
@requer_papel('coordenador')
@limiter.limit('20 per minute')
def api_editar_usuario(uid):
    d = request.get_json(silent=True)
    if not d:
        return jsonify({'erro': 'JSON inválido ou Content-Type incorreto'}), 400
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM usuarios WHERE id=?', (uid,)).fetchone()
        if not row:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        new_role = d.get('role', row['role'])
        if new_role not in PAPEIS_VALIDOS:
            return jsonify({'erro': 'Papel inválido'}), 400
        new_pass = (d.get('password') or '').strip()
        if new_pass and len(new_pass) < 8:
            return jsonify({'erro': 'A senha deve ter no mínimo 8 caracteres'}), 400
        if new_pass:
            conn.execute('UPDATE usuarios SET username=?, role=?, password_hash=? WHERE id=?',
                         (d.get('username', row['username']), new_role, generate_password_hash(new_pass), uid))
        else:
            conn.execute('UPDATE usuarios SET username=?, role=? WHERE id=?',
                         (d.get('username', row['username']), new_role, uid))
        try:
            conn.commit()
        except Exception:
            return jsonify({'erro': 'Nome de usuário já existe'}), 400
        registrar_log('EDITAR_USUARIO', f'Usuário "{row["username"]}" atualizado')
        return jsonify({'message': 'Usuário atualizado'})
    finally:
        conn.close()


@app.route('/api/usuarios/<int:uid>', methods=['DELETE'])
@login_required
@requer_papel('coordenador')
@limiter.limit('10 per minute')
def api_excluir_usuario(uid):
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM usuarios WHERE id=?', (uid,)).fetchone()
        if not row:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        if row['id'] == current_user.id:
            return jsonify({'erro': 'Você não pode excluir sua própria conta'}), 400
        conn.execute('DELETE FROM usuarios WHERE id=?', (uid,))
        conn.commit()
    finally:
        conn.close()
    registrar_log('EXCLUIR_USUARIO', f'Usuário "{row["username"]}" excluído')
    return jsonify({'message': 'Usuário excluído'})


@app.route('/api/conflito', methods=['GET'])
@login_required
def api_conflito():
    dia = request.args.get('dia_semana', '')
    horario = request.args.get('horario', '')
    sala = request.args.get('sala', '')
    excluir = request.args.get('excluir_id', None)
    if not dia or not horario or not sala:
        return jsonify({'conflito': False})
    conflito = checar_conflito(dia, horario, sala, excluir_id=excluir)
    if conflito:
        return jsonify({'conflito': True, 'estagiario': conflito.get('estagiario', ''),
                        'paciente': conflito.get('paciente', ''), 'categoria': conflito.get('categoria', ''),
                        'id': conflito.get('id')})
    return jsonify({'conflito': False})


@app.route('/api/agendamentos', methods=['GET'])
@login_required
def list_ag():
    dia = request.args.get('dia_semana', 'SEGUNDA')
    horario = request.args.get('horario', '')
    sala = request.args.get('sala', '')
    cat = request.args.get('categoria', '')
    busca = request.args.get('busca', '').strip()
    data_ref = request.args.get('data', '').strip()
    dia_ref = None
    if data_ref:
        try:
            d_obj = datetime.strptime(data_ref, '%Y-%m-%d')
            dia_ref = DIAS[d_obj.weekday()] if d_obj.weekday() < 5 else None
        except ValueError:
            pass
    dia_busca = dia_ref or dia
    q = ('SELECT * FROM agendamentos WHERE ('
         '(dia_semana=? AND (data_especifica IS NULL OR data_especifica = ''))'
         ' OR data_especifica=?'
         ')')
    p = [dia_busca, data_ref or '']
    if horario: q += ' AND horario=?'; p.append(horario)
    if sala: q += ' AND sala=?'; p.append(sala)
    if cat: q += ' AND categoria=?'; p.append(cat)
    if busca: q += ' AND (estagiario LIKE ? OR paciente LIKE ? OR observacao LIKE ?)'; p += [f'%{busca}%'] * 3
    if current_user.role == 'aluno':
        q += ' AND (usuario_id = ? OR (usuario_id IS NULL AND estagiario = ?))'
        p += [current_user.id, current_user.username]
    q += ' ORDER BY horario, sala'
    conn = get_db()
    try:
        rows = conn.execute(q, p).fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/agendamentos/<int:aid>', methods=['GET'])
@login_required
def get_ag(aid):
    conn = get_db()
    try:
        r = conn.execute('SELECT * FROM agendamentos WHERE id=?', (aid,)).fetchone()
    finally:
        conn.close()
    return (jsonify(dict(r)) if r else (jsonify({'erro': 'Não encontrado'}), 404))


@app.route('/api/agendamentos', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('60 per minute')
def create_ag():
    d = request.get_json(silent=True)
    if not d:
        return jsonify({'erro': 'JSON inválido ou Content-Type incorreto'}), 400
    dia = (d.get('dia_semana') or 'SEGUNDA').strip()
    horario = (d.get('horario') or '').strip()
    sala = (d.get('sala') or '').strip()
    data_esp = (d.get('data_especifica') or '').strip()
    if not horario or not sala:
        return jsonify({'erro': 'Os campos horario e sala são obrigatórios'}), 400
    if data_esp:
        try:
            datetime.strptime(data_esp, '%Y-%m-%d')
        except ValueError:
            return jsonify({'erro': 'data_especifica inválida. Use o formato AAAA-MM-DD (ex: 2026-08-15)'}), 400
    conflito = checar_conflito(dia, horario, sala)
    if conflito:
        ocu = conflito.get('estagiario') or conflito.get('categoria') or 'outro agendamento'
        return jsonify({'erro': f'Conflito: {sala} já está ocupada às {horario} ({dia}) por: {ocu}',
                        'conflito': True, 'conflito_id': conflito.get('id')}), 409
    est = d.get('estagiario', '')
    pac = d.get('paciente', '')
    cat = d.get('categoria', '') or detect_cat(est, pac)
    sem = d.get('semestre', 0) or detect_sem(est)
    uid_ag = d.get('usuario_id') or (current_user.id if current_user.is_authenticated else None)
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO agendamentos(dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,observacao,data_especifica,usuario_id)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (dia, horario, sala, est, pac, cat, sem, d.get('triagem', 0), d.get('observacao', ''), data_esp, uid_ag)
        )
        nid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    registrar_log('CRIAR', f'Agendamento #{nid} criado — sala: {sala} {horario}')
    return jsonify({'id': nid, 'message': 'Criado'}), 201


@app.route('/api/agendamentos/<int:aid>', methods=['PUT'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('60 per minute')
def update_ag(aid):
    d = request.get_json(silent=True)
    if not d:
        return jsonify({'erro': 'JSON inválido ou Content-Type incorreto'}), 400
    dia = (d.get('dia_semana') or 'SEGUNDA').strip()
    horario = (d.get('horario') or '').strip()
    sala = (d.get('sala') or '').strip()
    data_esp = (d.get('data_especifica') or '').strip()
    if not horario or not sala:
        return jsonify({'erro': 'Os campos horario e sala são obrigatórios'}), 400
    if data_esp:
        try:
            datetime.strptime(data_esp, '%Y-%m-%d')
        except ValueError:
            return jsonify({'erro': 'data_especifica inválida. Use o formato AAAA-MM-DD (ex: 2026-08-15)'}), 400
    conflito = checar_conflito(dia, horario, sala, excluir_id=aid)
    if conflito:
        ocu = conflito.get('estagiario') or conflito.get('categoria') or 'outro agendamento'
        return jsonify({'erro': f'Conflito: {sala} já está ocupada às {horario} ({dia}) por: {ocu}',
                        'conflito': True, 'conflito_id': conflito.get('id')}), 409
    est = d.get('estagiario', '')
    pac = d.get('paciente', '')
    cat = d.get('categoria', '') or detect_cat(est, pac)
    sem = d.get('semestre', 0) or detect_sem(est)
    conn = get_db()
    try:
        conn.execute(
            'UPDATE agendamentos SET dia_semana=?,horario=?,sala=?,estagiario=?,paciente=?,categoria=?,semestre=?,'
            'triagem=?,observacao=?,data_especifica=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (dia, horario, sala, est, pac, cat, sem, d.get('triagem', 0), d.get('observacao', ''), data_esp, aid)
        )
        conn.commit()
    finally:
        conn.close()
    registrar_log('EDITAR', f'Agendamento #{aid} editado — sala: {sala} {horario}')
    return jsonify({'message': 'Atualizado'})


@app.route('/api/agendamentos/<int:aid>', methods=['DELETE'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('30 per minute')
def delete_ag(aid):
    conn = get_db()
    try:
        r = conn.execute('SELECT * FROM agendamentos WHERE id=?', (aid,)).fetchone()
        conn.execute('DELETE FROM agendamentos WHERE id=?', (aid,))
        conn.commit()
    finally:
        conn.close()
    if r:
        registrar_log('EXCLUIR', f'Agendamento #{aid} excluído — sala: {r["sala"]} {r["horario"]}')
    return jsonify({'message': 'Removido'})


@app.route('/api/stats')
@login_required
def stats():
    dia = request.args.get('dia_semana', 'SEGUNDA')
    conn = get_db()
    try:
        total = conn.execute('SELECT COUNT(*) FROM agendamentos WHERE dia_semana=?', (dia,)).fetchone()[0]
        livre = conn.execute("SELECT COUNT(*) FROM agendamentos WHERE dia_semana=? AND categoria='LIVRE'", (dia,)).fetchone()[0]
        por_cat = conn.execute('SELECT categoria, COUNT(*) as n FROM agendamentos WHERE dia_semana=? GROUP BY categoria ORDER BY n DESC', (dia,)).fetchall()
    finally:
        conn.close()
    return jsonify({'total': total, 'livre': livre, 'por_categoria': [dict(r) for r in por_cat]})


@app.route('/api/export')
@login_required
@requer_papel('coordenador', 'recepcao')
def export_csv():
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT a.*, COALESCE(u.nome_completo, a.estagiario) as nome_real '
            'FROM agendamentos a '
            'LEFT JOIN usuarios u ON a.usuario_id = u.id '
            'ORDER BY a.dia_semana, a.horario, a.sala'
        ).fetchall()
    finally:
        conn.close()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(['ID', 'Dia', 'Horário', 'Sala', 'Estagiário (usuário)', 'Nome Completo', 'Paciente',
                'Categoria', 'Semestre', 'Triagem', 'Data Esp.', 'Obs.'])
    for r in rows:
        w.writerow([r['id'], r['dia_semana'], r['horario'], r['sala'],
                    r['estagiario'], r['nome_real'], r['paciente'],
                    r['categoria'], r['semestre'], 'Sim' if r['triagem'] else 'Não',
                    r['data_especifica'], r['observacao']])
    out.seek(0)
    registrar_log('EXPORTAR', 'CSV exportado')
    return send_file(io.BytesIO(out.read().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True,
                     download_name=f'mapa_salas_{datetime.now().strftime("%Y%m%d_%H%M")}.csv')


@app.route('/api/logs')
@login_required
@requer_papel('coordenador')
def get_logs():
    pagina = max(1, int(request.args.get('pagina', 1)))
    por_pag = min(100, max(10, int(request.args.get('por_pagina', 50))))
    usuario = request.args.get('usuario', '').strip()
    acao = request.args.get('acao', '').strip()
    data_ini = request.args.get('data_ini', '').strip()
    data_fim = request.args.get('data_fim', '').strip()
    offset = (pagina - 1) * por_pag

    q = 'SELECT * FROM historico WHERE 1=1'
    p = []
    if usuario: q += ' AND usuario LIKE ?'; p.append(f'%{usuario}%')
    if acao: q += ' AND acao LIKE ?'; p.append(f'%{acao}%')
    if data_ini: q += ' AND ts >= ?'; p.append(data_ini)
    if data_fim: q += ' AND ts <= ?'; p.append(data_fim + ' 23:59:59')

    conn = get_db()
    try:
        total = conn.execute(q.replace('SELECT *', 'SELECT COUNT(*)'), p).fetchone()[0]
        rows = conn.execute(q + ' ORDER BY ts DESC LIMIT ? OFFSET ?', p + [por_pag, offset]).fetchall()
    finally:
        conn.close()
    return jsonify({
        'total': total,
        'pagina': pagina,
        'por_pagina': por_pag,
        'paginas': (total + por_pag - 1) // por_pag,
        'logs': [dict(r) for r in rows]
    })


@app.route('/api/admin/limpar-logs', methods=['POST'])
@login_required
@requer_papel('coordenador')
def limpar_logs():
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM historico WHERE ts < datetime('now', '-' || ? || ' days')",
            (LOG_RETENCAO_DIAS,)
        )
        conn.commit()
        removidos = cur.rowcount
    finally:
        conn.close()
    registrar_log('LIMPAR_LOGS', f'{removidos} logs antigos removidos (retenção: {LOG_RETENCAO_DIAS} dias)')
    return jsonify({'message': f'{removidos} logs removidos'})


@app.route('/api/busca')
@login_required
def busca_global():
    q_busca = request.args.get('q', '').strip()
    if not q_busca or len(q_busca) < 2:
        return jsonify({'erro': 'Busca deve ter ao menos 2 caracteres'}), 400
    like = f'%{q_busca}%'
    q = ('SELECT * FROM agendamentos '
         'WHERE (estagiario LIKE ? OR paciente LIKE ? OR observacao LIKE ?)')
    p = [like, like, like]
    if current_user.role == 'aluno':
        q += ' AND (usuario_id = ? OR (usuario_id IS NULL AND estagiario = ?))'
        p += [current_user.id, current_user.username]
    q += ' ORDER BY dia_semana, horario, sala'
    conn = get_db()
    try:
        rows = conn.execute(q, p).fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/import', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('10 per minute')
def import_csv():
    if 'file' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    f = request.files['file']
    if not f.filename.endswith('.csv'):
        return jsonify({'erro': 'Apenas arquivos .csv são aceitos'}), 400

    stream = io.StringIO(f.read().decode('utf-8-sig'))
    reader = csv.DictReader(stream)
    inseridos = 0
    conflitos = []
    erros = []

    for i, row in enumerate(reader, start=2):
        try:
            dia      = (row.get('Dia') or row.get('dia_semana') or '').strip().upper()
            horario  = (row.get('Horário') or row.get('horario') or '').strip()
            sala     = (row.get('Sala') or row.get('sala') or '').strip()
            estagiario = (row.get('Estagiário (usuário)') or row.get('Estagiário') or row.get('estagiario') or '').strip()
            paciente = (row.get('Paciente') or row.get('paciente') or '').strip()
            categoria = (row.get('Categoria') or row.get('categoria') or '').strip()
            semestre = int(row.get('Semestre') or row.get('semestre') or 0)
            triagem  = 1 if str(row.get('Triagem') or '').strip().lower() in ('sim', '1', 'true') else 0
            obs      = (row.get('Obs.') or row.get('observacao') or '').strip()
            data_esp = (row.get('Data Esp.') or row.get('data_especifica') or '').strip()

            if not dia or not horario or not sala:
                erros.append(f'Linha {i}: dia, horário e sala são obrigatórios')
                continue
            if dia not in DIAS:
                erros.append(f'Linha {i}: dia "{dia}" inválido')
                continue

            conflito = checar_conflito(dia, horario, sala)
            if conflito:
                conflitos.append({
                    'linha': i, 'dia': dia, 'horario': horario, 'sala': sala,
                    'ocupado_por': conflito.get('estagiario') or conflito.get('categoria')
                })
                continue

            cat = categoria or detect_cat(estagiario, paciente)
            sem = semestre or detect_sem(estagiario)
            conn = get_db()
            try:
                conn.execute(
                    'INSERT INTO agendamentos(dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,observacao,data_especifica)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (dia, horario, sala, estagiario, paciente, cat, sem, triagem, obs, data_esp)
                )
                conn.commit()
            finally:
                conn.close()
            inseridos += 1
        except Exception as e:
            erros.append(f'Linha {i}: {str(e)}')

    registrar_log('IMPORTAR_CSV', f'{inseridos} agendamentos importados, {len(conflitos)} conflitos, {len(erros)} erros')
    return jsonify({
        'inseridos': inseridos,
        'conflitos': conflitos,
        'erros': erros,
        'message': f'{inseridos} agendamento(s) importado(s) com sucesso.'
    })


@app.route('/api/backup')
@login_required
@requer_papel('coordenador')
@limiter.limit('5 per hour')
def backup_db():
    confirm = request.args.get('confirmar', '')
    if confirm != 'sim':
        return jsonify({
            'erro': 'Confirmação necessária. Adicione ?confirmar=sim na URL.',
            'aviso': 'O backup contém dados sensíveis do banco incluindo hashes de senha.'
        }), 400
    registrar_log('BACKUP', f'Backup manual baixado por {current_user.username} — IP: {request.remote_addr}')
    return send_file(
        DB_PATH,
        as_attachment=True,
        download_name=f'backup_mapa_{datetime.now().strftime("%Y%m%d_%H%M")}.db'
    )


with app.app_context():
    init_db()

if __name__ == '__main__':
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        init_db()
    print(f'
 Versão: {VERSAO} | http://localhost:5000
')
    app.run(debug=True, port=5000)
