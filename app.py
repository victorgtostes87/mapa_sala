import csv
import io
import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from functools import wraps
import click
from flask import Flask, render_template, render_template_string, jsonify, request, send_file, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from jinja2 import TemplateNotFound
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# ========================================
# CONFIGURACAO
# ========================================

app = Flask(__name__)
try:
    from dotenv import load_dotenv as _ld
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
DB_PATH = os.environ.get(
    'DB_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapa_salas.db')
)

VERSAO = '2026-06-26-v21'

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


# ========================================
# MODELOS E PERMISSOES
# ========================================

def gerar_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


@app.context_processor
def injetar_csrf_token():
    return {
        'csrf_token': gerar_csrf_token,
        'versao': VERSAO,
        'papeis_label': PAPEIS_LABEL,
        'reservas_pendentes_count': contar_reservas_pendentes()
    }


@app.before_request
def proteger_csrf():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None

    token_salvo = session.get('_csrf_token')
    token_enviado = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
    if token_salvo and token_enviado and secrets.compare_digest(token_salvo, token_enviado):
        return None

    if request.path.startswith('/api/'):
        return jsonify({'erro': 'Sua sessao expirou. Recarregue a pagina e tente novamente.'}), 400

    flash('Sua sessao expirou. Recarregue a pagina e tente novamente.', 'error')
    return redirect(url_for('login'))


class Usuario(UserMixin):
    def __init__(self, id, username, role, nome_completo='', email='', ativo=1):
        self.id = id
        self.username = username
        self.role = role
        self.nome_completo = nome_completo
        self.email = email
        self.ativo = ativo


def get_db():
    # timeout=10 reduz falhas quando duas pessoas salvam dados quase ao mesmo tempo.
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    # WAL melhora leitura simultanea em sistemas pequenos com varios usuarios internos.
    conn.execute('PRAGMA journal_mode=WAL')
    # NORMAL equilibra seguranca e desempenho para um SQLite usado em aplicacao web interna.
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM usuarios WHERE id=? AND ativo=1', (user_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return Usuario(row['id'], row['username'], row['role'],
                   row['nome_completo'] or '', row['email'] or '', row['ativo'])


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


# ========================================
# CONSTANTES DE NEGOCIO
# ========================================

SALAS = [
    'Consultório 1', 'Consultório 2', 'Consultório 3', 'Consultório 4',
    'Consultório 5', 'Consultório 6 (Divã)', 'Consultório 7 (Divã)',
    'Consultório 8', 'SOU / NACE', 'Ludoterapia', 'Multifuncional',
    'Sala de Grupo 1', 'Sala de Grupo 2', 'Supervisão', 'Coordenação'
]

HORARIOS = ['07:00', '08:00', '09:00', '10:00', '11:00', '12:00', '13:00',
            '14:00', '15:00', '16:00', '17:00', '18:00', '19:00', '20:00']
SALAS_RESERVAVEIS = [
    'Consultório 1', 'Consultório 2', 'Consultório 3', 'Consultório 4',
    'Consultório 5', 'Consultório 6 (Divã)', 'Consultório 7 (Divã)',
    'Consultório 8', 'Ludoterapia', 'Multifuncional',
    'Sala de Grupo 1', 'Sala de Grupo 2'
]
SALAS_COM_COMPUTADOR = [
    'Consultório 3', 'Consultório 4', 'Consultório 5',
    'Consultório 6 (Divã)', 'Consultório 7 (Divã)'
]
DIAS = ['SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA']
DIAS_PT = {
    'SEGUNDA': 'Segunda-feira', 'TERÇA': 'Terça-feira', 'QUARTA': 'Quarta-feira',
    'QUINTA': 'Quinta-feira', 'SEXTA': 'Sexta-feira',
}

CATEGORIAS = [
    'ESTAGIÁRIO 10°', 'ESTAGIÁRIO 9°',
    'SUPERVISÃO', 'NACE', 'SOU', 'MARCAR', 'NÃO MARCAR',
    'NUTRIÇÃO', 'PSICODIAGNÓSTICO', 'PSIQUIATRIA',
    'AMBULATÓRIO NEUROPSICOLOGIA', 'PLANTÃO PSICOLÓGICO',
    'PRONTUÁRIO/ESTUDAR', 'LIVRE', 'OUTRO'
]

PAPEIS_LABEL = {
    'coordenador': 'Coordenador',
    'recepcao': 'Recepcionista',
    'professor': 'Professor',
    'aluno': 'Aluno'
}

LOG_RETENCAO_DIAS = 15


# ========================================
# BANCO DE DADOS
# ========================================

def normalizar_data_especifica(data_especifica):
    data_especifica = (data_especifica or '').strip()
    if not data_especifica:
        return '', None

    try:
        data_obj = datetime.strptime(data_especifica, '%Y-%m-%d')
    except ValueError:
        return None, 'Data especifica invalida. Use o formato AAAA-MM-DD (ex: 2026-08-15).'

    if data_obj.weekday() >= len(DIAS):
        return None, 'Data especifica deve cair entre segunda e sexta-feira.'

    return data_especifica, None


def dia_semana_da_data(data_especifica):
    data_obj = datetime.strptime(data_especifica, '%Y-%m-%d')
    return DIAS[data_obj.weekday()]


def numero_semana_sqlite(dia):
    # SQLite usa domingo=0, segunda=1 ... sexta=5.
    return str(DIAS.index(dia) + 1)


def validar_valores_agendamento(dia, horario, sala, categoria=''):
    if dia not in DIAS:
        return f'Dia inválido: {dia}'
    if horario not in HORARIOS:
        return f'Horário inválido: {horario}'
    if sala not in SALAS:
        return f'Sala inválida: {sala}'
    if categoria and categoria not in CATEGORIAS:
        return f'Categoria inválida: {categoria}'
    return None


def data_hoje_iso():
    return datetime.now().strftime('%Y-%m-%d')


def normalizar_categoria_triagem(categoria):
    categoria = (categoria or '').strip()
    if categoria == 'ESTAGIÁRIO 10° TRIAGEM':
        return 'ESTAGIÁRIO 10°', 1
    if categoria == 'ESTAGIÁRIO 9° TRIAGEM':
        return 'ESTAGIÁRIO 9°', 1
    return categoria, None


def texto_indica_triagem(estagiario, paciente):
    return 'TRIAGEM' in normalize(f'{estagiario} {paciente}').upper()


def valor_triagem(valor, padrao=0):
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return 1 if valor else 0
    return 1 if str(valor).strip().lower() in ('1', 'true', 'sim', 'yes') else 0


def valor_ocupa_sala(valor, padrao=None):
    if valor in (None, ''):
        return padrao
    if isinstance(valor, bool):
        return 1 if valor else 0
    return 1 if str(valor).strip().lower() in ('1', 'true', 'sim', 'yes') else 0


def calcular_ocupa_sala(categoria, paciente='', observacao='', data_especifica='', triagem=0):
    categoria = (categoria or '').strip().upper()
    paciente = (paciente or '').strip()
    observacao = (observacao or '').strip()
    data_especifica = (data_especifica or '').strip()

    if paciente:
        return 1
    if valor_triagem(triagem, 0) and paciente:
        return 1
    if categoria in (
        'SUPERVISÃO', 'NACE', 'SOU', 'NUTRIÇÃO', 'PSICODIAGNÓSTICO',
        'PSIQUIATRIA', 'AMBULATÓRIO NEUROPSICOLOGIA', 'PLANTÃO PSICOLÓGICO',
        'PRONTUÁRIO/ESTUDAR'
    ):
        return 1
    if data_especifica and observacao:
        return 1
    return 0


def preparar_dados_agendamento(dados, usuario_id_padrao=None):
    dia = (dados.get('dia_semana') or 'SEGUNDA').strip()
    horario = (dados.get('horario') or '').strip()
    sala = (dados.get('sala') or '').strip()
    data_esp = (dados.get('data_especifica') or '').strip()
    categoria_informada, triagem_categoria = normalizar_categoria_triagem(dados.get('categoria'))

    if not horario or not sala:
        return None, 'Os campos horário e sala são obrigatórios.'

    data_esp, erro_data = normalizar_data_especifica(data_esp)
    if erro_data:
        return None, erro_data
    if data_esp:
        dia = dia_semana_da_data(data_esp)

    erro_validacao = validar_valores_agendamento(dia, horario, sala, categoria_informada)
    if erro_validacao:
        return None, erro_validacao

    estagiario = dados.get('estagiario', '')
    paciente = dados.get('paciente', '')
    categoria = categoria_informada or detect_cat(estagiario, paciente)
    semestre = dados.get('semestre', 0) or detect_sem(estagiario)
    triagem_padrao = 1 if texto_indica_triagem(estagiario, paciente) else 0
    triagem = triagem_categoria if triagem_categoria is not None else valor_triagem(dados.get('triagem'), triagem_padrao)
    observacao = dados.get('observacao', '')
    ocupa_calculado = calcular_ocupa_sala(categoria, paciente, observacao, data_esp, triagem)
    ocupa_sala = valor_ocupa_sala(dados.get('ocupa_sala'), ocupa_calculado)

    return {
        'dia': dia,
        'horario': horario,
        'sala': sala,
        'estagiario': estagiario,
        'paciente': paciente,
        'categoria': categoria,
        'semestre': semestre,
        'triagem': triagem,
        'observacao': observacao,
        'data_especifica': data_esp,
        'usuario_id': dados.get('usuario_id') or usuario_id_padrao,
        'ocupa_sala': ocupa_sala,
    }, None


def usuario_pode_ver_agendamento(row):
    if not row:
        return False
    if current_user.role != 'aluno':
        return True
    return row['usuario_id'] == current_user.id or (
        row['usuario_id'] is None and row['estagiario'] == current_user.username
    )


def buscar_usuario_id_aluno(username, conn):
    username = (username or '').strip()
    if not username:
        return None
    row = conn.execute(
        "SELECT id FROM usuarios WHERE username=? AND role='aluno' AND ativo=1",
        (username,)
    ).fetchone()
    return row['id'] if row else None


def vincular_aluno_do_agendamento(dados_ag, conn):
    aluno_id = buscar_usuario_id_aluno(dados_ag.get('estagiario'), conn)
    if aluno_id:
        dados_ag['usuario_id'] = aluno_id
    return dados_ag


def inserir_agendamento(conn, dados_ag):
    vincular_aluno_do_agendamento(dados_ag, conn)
    if 'ocupa_sala' not in dados_ag:
        dados_ag['ocupa_sala'] = calcular_ocupa_sala(
            dados_ag.get('categoria', ''),
            dados_ag.get('paciente', ''),
            dados_ag.get('observacao', ''),
            dados_ag.get('data_especifica', ''),
            dados_ag.get('triagem', 0)
        )
    cur = conn.execute(
        'INSERT INTO agendamentos(dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,observacao,data_especifica,usuario_id,ocupa_sala)'
        ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            dados_ag['dia'], dados_ag['horario'], dados_ag['sala'],
            dados_ag['estagiario'], dados_ag['paciente'], dados_ag['categoria'],
            dados_ag['semestre'], dados_ag['triagem'], dados_ag['observacao'],
            dados_ag['data_especifica'], dados_ag['usuario_id'], dados_ag['ocupa_sala']
        )
    )
    return cur.lastrowid


def valor_ativo(valor, padrao=1):
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return 1 if valor else 0
    return 0 if str(valor).strip().lower() in ('0', 'false', 'nao', 'não', 'inativo') else 1


def limpar_logs_antigos(conn):
    """Remove historico antigo para impedir crescimento continuo do arquivo SQLite."""
    cur = conn.execute(
        "DELETE FROM historico WHERE ts < datetime('now', '-' || ? || ' days')",
        (LOG_RETENCAO_DIAS,)
    )
    return cur.rowcount


def criar_indices_agendamentos(conn):
    conn.executescript(
        "DROP INDEX IF EXISTS idx_conflito;"
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_conflito_semanal "
        "ON agendamentos(dia_semana, horario, sala) "
        "WHERE ocupa_sala = 1 AND (data_especifica IS NULL OR data_especifica = '');"
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_conflito_data "
        "ON agendamentos(data_especifica, horario, sala) "
        "WHERE ocupa_sala = 1 AND data_especifica IS NOT NULL AND data_especifica != '';"
        "CREATE INDEX IF NOT EXISTS idx_dia_semana ON agendamentos(dia_semana);"
        "CREATE INDEX IF NOT EXISTS idx_data_especifica ON agendamentos(data_especifica);"
        "CREATE INDEX IF NOT EXISTS idx_ocupa_sala ON agendamentos(ocupa_sala);"
    )


def migrar_fk_usuario_id_agendamentos(conn):
    fks = conn.execute("PRAGMA foreign_key_list(agendamentos)").fetchall()
    if any(row['table'] == 'usuarios' and row['from'] == 'usuario_id' for row in fks):
        return

    cols = [r[1] for r in conn.execute("PRAGMA table_info(agendamentos)").fetchall()]
    if 'usuario_id' not in cols:
        return

    conn.executescript(
        "DROP INDEX IF EXISTS idx_conflito;"
        "DROP INDEX IF EXISTS idx_conflito_semanal;"
        "DROP INDEX IF EXISTS idx_conflito_data;"
        "DROP INDEX IF EXISTS idx_dia_semana;"
        "DROP INDEX IF EXISTS idx_data_especifica;"
        "DROP INDEX IF EXISTS idx_ocupa_sala;"
        "ALTER TABLE agendamentos RENAME TO agendamentos_old;"
        "CREATE TABLE agendamentos ("
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
        "usuario_id INTEGER DEFAULT NULL REFERENCES usuarios(id) ON DELETE SET NULL,"
        "ocupa_sala INTEGER DEFAULT 0,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
        "INSERT INTO agendamentos("
        "id,dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,"
        "observacao,data_especifica,usuario_id,ocupa_sala,created_at,updated_at"
        ") SELECT "
        "id,dia_semana,horario,sala,estagiario,paciente,categoria,semestre,triagem,"
        "observacao,data_especifica,"
        "CASE WHEN usuario_id IS NULL OR EXISTS (SELECT 1 FROM usuarios u WHERE u.id = agendamentos_old.usuario_id) "
        "THEN usuario_id ELSE NULL END,"
        "ocupa_sala,"
        "created_at,updated_at "
        "FROM agendamentos_old;"
        "DROP TABLE agendamentos_old;"
    )


def corrigir_vinculos_alunos_agendamentos(conn):
    conn.execute(
        """
        UPDATE agendamentos
        SET usuario_id = (
            SELECT u.id
            FROM usuarios u
            WHERE u.username = agendamentos.estagiario
              AND u.role = 'aluno'
              AND u.ativo = 1
        )
        WHERE EXISTS (
            SELECT 1
            FROM usuarios u
            WHERE u.username = agendamentos.estagiario
              AND u.role = 'aluno'
              AND u.ativo = 1
        )
        """
    )


def migrar_categorias_triagem(conn):
    conn.execute(
        """
        UPDATE agendamentos
        SET categoria = 'ESTAGIÁRIO 10°',
            triagem = 1
        WHERE categoria = 'ESTAGIÁRIO 10° TRIAGEM'
        """
    )
    conn.execute(
        """
        UPDATE agendamentos
        SET categoria = 'ESTAGIÁRIO 9°',
            triagem = 1
        WHERE categoria = 'ESTAGIÁRIO 9° TRIAGEM'
        """
    )


def recalcular_ocupacao_sala_agendamentos(conn):
    conn.execute(
        """
        UPDATE agendamentos
        SET ocupa_sala = CASE
            WHEN TRIM(COALESCE(paciente, '')) != '' THEN 1
            WHEN categoria IN (
                'SUPERVISÃO', 'NACE', 'SOU', 'NUTRIÇÃO', 'PSICODIAGNÓSTICO',
                'PSIQUIATRIA', 'AMBULATÓRIO NEUROPSICOLOGIA', 'PLANTÃO PSICOLÓGICO',
                'PRONTUÁRIO/ESTUDAR'
            ) THEN 1
            WHEN TRIM(COALESCE(data_especifica, '')) != ''
                 AND TRIM(COALESCE(observacao, '')) != '' THEN 1
            ELSE 0
        END
        """
    )


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
        "usuario_id INTEGER DEFAULT NULL REFERENCES usuarios(id) ON DELETE SET NULL,"
        "ocupa_sala INTEGER DEFAULT 0,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ");"
            "CREATE TABLE IF NOT EXISTS historico ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "usuario TEXT DEFAULT '',"
            "acao TEXT,"
            "dados TEXT,"
            "ip TEXT DEFAULT '',"
            "user_agent TEXT DEFAULT '',"
            "ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ");"
            "CREATE TABLE IF NOT EXISTS usuarios ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "username TEXT NOT NULL UNIQUE,"
            "password_hash TEXT NOT NULL,"
            "role TEXT NOT NULL DEFAULT 'aluno',"
            "nome_completo TEXT DEFAULT '',"
            "email TEXT DEFAULT '',"
            "ativo INTEGER DEFAULT 1,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ");"
            "CREATE TABLE IF NOT EXISTS reservas ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "usuario_id INTEGER DEFAULT NULL REFERENCES usuarios(id) ON DELETE SET NULL,"
            "usuario TEXT DEFAULT '',"
            "tipo TEXT NOT NULL,"
            "status TEXT DEFAULT 'pendente',"
            "data_uso TEXT NOT NULL,"
            "horario_inicio TEXT DEFAULT '',"
            "horario_fim TEXT DEFAULT '',"
            "tipo_sala TEXT DEFAULT '',"
            "sala_atribuida TEXT DEFAULT '',"
            "instrumento TEXT DEFAULT '',"
            "finalidade TEXT DEFAULT '',"
            "observacao TEXT DEFAULT '',"
            "resposta TEXT DEFAULT '',"
            "agendamento_ids TEXT DEFAULT '',"
            "analisado_por TEXT DEFAULT '',"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ");"
            "CREATE INDEX IF NOT EXISTS idx_reservas_status ON reservas(status);"
            "CREATE INDEX IF NOT EXISTS idx_reservas_usuario ON reservas(usuario_id);"
        )
        existe = conn.execute("SELECT id FROM usuarios WHERE username='coordenador'").fetchone()
        if not existe:
            conn.execute(
                "INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)",
                ('coordenador', generate_password_hash('mudar@2026'), 'coordenador')
            )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(agendamentos)").fetchall()]
        ocupa_col_criada = False
        if 'usuario_id' not in cols:
            conn.execute("ALTER TABLE agendamentos ADD COLUMN usuario_id INTEGER DEFAULT NULL")
            conn.commit()
        if 'ocupa_sala' not in cols:
            conn.execute("ALTER TABLE agendamentos ADD COLUMN ocupa_sala INTEGER DEFAULT 0")
            ocupa_col_criada = True
            conn.commit()
        cols_usuarios = [r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()]
        if 'email' not in cols_usuarios:
            conn.execute("ALTER TABLE usuarios ADD COLUMN email TEXT DEFAULT ''")
            conn.commit()
        if 'ativo' not in cols_usuarios:
            conn.execute("ALTER TABLE usuarios ADD COLUMN ativo INTEGER DEFAULT 1")
            conn.commit()
        cols_historico = [r[1] for r in conn.execute("PRAGMA table_info(historico)").fetchall()]
        if 'ip' not in cols_historico:
            conn.execute("ALTER TABLE historico ADD COLUMN ip TEXT DEFAULT ''")
            conn.commit()
        if 'user_agent' not in cols_historico:
            conn.execute("ALTER TABLE historico ADD COLUMN user_agent TEXT DEFAULT ''")
            conn.commit()
        migrar_fk_usuario_id_agendamentos(conn)
        corrigir_vinculos_alunos_agendamentos(conn)
        migrar_categorias_triagem(conn)
        if ocupa_col_criada:
            recalcular_ocupacao_sala_agendamentos(conn)
        criar_indices_agendamentos(conn)
        limpar_logs_antigos(conn)
        conn.commit()
    finally:
        conn.close()


def registrar_log(acao, dados=''):
    usuario = current_user.username if current_user.is_authenticated else 'sistema'
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    user_agent = (request.headers.get('User-Agent') or '')[:300]
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO historico(usuario, acao, dados, ip, user_agent) VALUES(?,?,?,?,?)',
            (usuario, acao, dados, ip, user_agent)
        )
        limpar_logs_antigos(conn)
        conn.commit()
    finally:
        conn.close()


def checar_conflito(dia, horario, sala, data_especifica='', excluir_id=None):
    conn = get_db()
    try:
        try:
            eid = int(excluir_id) if excluir_id else None
        except (ValueError, TypeError):
            eid = None

        data_especifica = (data_especifica or '').strip()
        params = [horario, sala]
        q = 'SELECT * FROM agendamentos WHERE horario=? AND sala=? AND ocupa_sala=1'

        if data_especifica:
            q += (
                ' AND (data_especifica=? '
                'OR (dia_semana=? AND (data_especifica IS NULL OR data_especifica = \'\')))'
            )
            params.extend([data_especifica, dia])
        else:
            q += (
                ' AND ('
                '(dia_semana=? AND (data_especifica IS NULL OR data_especifica = \'\')) '
                'OR (data_especifica IS NOT NULL AND data_especifica != \'\' '
                'AND data_especifica >= ? AND strftime(\'%w\', data_especifica)=?)'
                ')'
            )
            params.extend([dia, data_hoje_iso(), numero_semana_sqlite(dia)])

        if eid:
            q += ' AND CAST(id AS INTEGER)!=?'
            params.append(eid)

        r = conn.execute(q, params).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def contar_reservas_pendentes():
    if not current_user.is_authenticated or current_user.role not in ('coordenador', 'recepcao'):
        return 0
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM reservas WHERE status='pendente'"
            ).fetchone()
        finally:
            conn.close()
        return row['total'] if row else 0
    except sqlite3.Error:
        return 0


def validar_antecedencia_minima(data_uso, horario_inicio):
    try:
        inicio = datetime.strptime(f'{data_uso} {horario_inicio}', '%Y-%m-%d %H:%M')
    except ValueError:
        return None, 'Data ou horário inválido.'
    if inicio < datetime.now() + timedelta(hours=24):
        return None, 'Reservas precisam ser feitas com no mínimo 24h de antecedência.'
    return inicio, None


def horarios_do_intervalo(horario_inicio, horario_fim):
    if horario_inicio not in HORARIOS or horario_fim not in HORARIOS:
        return None, 'Horário inválido.'
    ini = HORARIOS.index(horario_inicio)
    fim = HORARIOS.index(horario_fim)
    if fim <= ini:
        return None, 'O horário final deve ser depois do horário inicial.'
    return HORARIOS[ini:fim], None


def candidatos_sala_reserva(tipo_sala):
    if tipo_sala == 'computador':
        return [s for s in SALAS_COM_COMPUTADOR if s in SALAS]
    return [s for s in SALAS_RESERVAVEIS if s not in SALAS_COM_COMPUTADOR]


def encontrar_sala_disponivel(data_uso, horario_inicio, horario_fim, tipo_sala):
    data_uso, erro_data = normalizar_data_especifica(data_uso)
    if erro_data:
        return None, erro_data
    slots, erro_horario = horarios_do_intervalo(horario_inicio, horario_fim)
    if erro_horario:
        return None, erro_horario

    dia = dia_semana_da_data(data_uso)
    for sala in candidatos_sala_reserva(tipo_sala):
        if all(not checar_conflito(dia, slot, sala, data_especifica=data_uso) for slot in slots):
            return sala, None
    return None, 'Não há sala disponível nesse período.'


def sala_disponivel_para_reserva(data_uso, horario_inicio, horario_fim, sala):
    if sala not in SALAS_RESERVAVEIS:
        return False, 'Sala inválida para reserva.'

    data_uso, erro_data = normalizar_data_especifica(data_uso)
    if erro_data:
        return False, erro_data
    slots, erro_horario = horarios_do_intervalo(horario_inicio, horario_fim)
    if erro_horario:
        return False, erro_horario

    dia = dia_semana_da_data(data_uso)
    for slot in slots:
        if checar_conflito(dia, slot, sala, data_especifica=data_uso):
            return False, f'{sala} já está ocupada nesse período.'
    return True, None


def label_status_reserva(status):
    return {
        'pendente': 'Pendente',
        'aprovada': 'Aprovada',
        'recusada': 'Recusada'
    }.get(status, status)


# ========================================
# REGRAS DE NEGOCIO
# ========================================

def normalize(t):
    if not t:
        return ''
    for o, n in [('?', 'ã'), ('?', 'Ã'), ('ş', 'º'), ('Ş', 'º'), ('ţ', 'ç')]:
        t = t.replace(o, n)
    return t.strip()


def detect_cat(est, pac):
    c = normalize(est + ' ' + pac).upper()
    if 'NÃO MARCAR' in c or 'NAO MARCAR' in c:
        return 'NÃO MARCAR'
    if 'PSICODIAG' in c:
        return 'PSICODIAGNÓSTICO'
    if 'SUPERVISÃO' in c or 'SUPERVISAO' in c or 'PROF.' in c or re.search(r'PROF\s+\w', c):
        return 'SUPERVISÃO'
    if 'NACE' in c:
        return 'NACE'
    if re.search(r'\bSOU\b', c):
        return 'SOU'
    if 'MARCAR' in c:
        return 'MARCAR'
    if 'NUTRIÇÃO' in c or 'NUTRICAO' in c:
        return 'NUTRIÇÃO'
    if 'PSIQUIATRIA' in c:
        return 'PSIQUIATRIA'
    if 'AMBULAT' in c:
        return 'AMBULATÓRIO NEUROPSICOLOGIA'
    if 'PLANTÃO' in c or 'PLANTAO' in c:
        return 'PLANTÃO PSICOLÓGICO'
    if 'PRONTUÁRIO' in c or 'PRONTUARIO' in c or 'ESTUDAR' in c:
        return 'PRONTUÁRIO/ESTUDAR'
    if re.search(r'10[°º]', c):
        return 'ESTAGIÁRIO 10°'
    if re.search(r'9[°º]', c):
        return 'ESTAGIÁRIO 9°'
    en = normalize(est).strip()
    if en and not any(x in en.upper() for x in ['PSICODIAG', 'NÃO', 'MARCAR', 'SUPERVISÃO']):
        return 'ESTAGIÁRIO 9°'
    if not normalize(est).strip() and not normalize(pac).strip():
        return 'LIVRE'
    return 'OUTRO'


def detect_sem(t):
    t = normalize(t)
    if re.search(r'10[°º]', t):
        return 10
    if re.search(r'9[°º]', t):
        return 9
    return 0


# ========================================
# API PUBLICA
# ========================================

def pagina_erro(titulo, mensagem, status):
    try:
        return render_template(
            'error.html',
            titulo=titulo,
            mensagem=mensagem,
            status=status,
            versao=VERSAO
        ), status
    except TemplateNotFound:
        return render_template_string(
            '''
            <!doctype html>
            <html lang="pt-BR">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>{{ status }} - {{ titulo }}</title>
              <style>
                body{font-family:Arial,sans-serif;background:#f4f6f9;color:#1f2937;margin:0}
                main{max-width:680px;margin:80px auto;padding:24px}
                .box{background:#fff;border-radius:10px;padding:28px;box-shadow:0 10px 30px rgba(0,0,0,.08)}
                h1{margin:0 0 10px;font-size:28px}
                p{line-height:1.5;color:#4b5563}
                a{display:inline-block;margin-top:14px;background:#2563eb;color:#fff;text-decoration:none;padding:10px 14px;border-radius:8px}
                footer{margin-top:18px;color:#6b7280;font-size:12px}
              </style>
            </head>
            <body>
              <main>
                <div class="box">
                  <h1>{{ status }} - {{ titulo }}</h1>
                  <p>{{ mensagem }}</p>
                  <a href="{{ url_for('index') }}">Voltar ao mapa</a>
                  <footer>Versão {{ versao }}</footer>
                </div>
              </main>
            </body>
            </html>
            ''',
            titulo=titulo,
            mensagem=mensagem,
            status=status,
            versao=VERSAO
        ), status


@app.errorhandler(403)
def erro_403(e):
    return pagina_erro('Acesso negado', 'Você não tem permissão para acessar esta área.', 403)


@app.errorhandler(404)
def erro_404(e):
    return pagina_erro('Página não encontrada', 'Confira o endereço ou volte para o mapa de salas.', 404)


@app.errorhandler(500)
def erro_500(e):
    return pagina_erro('Erro interno', 'Algo saiu do esperado. Tente novamente e avise a coordenação se persistir.', 500)


@app.route('/api/versao')
def api_versao():
    return jsonify({'versao': VERSAO, 'ok': True})


# ========================================
# ROTAS DE AUTENTICACAO
# ========================================

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
        if row and not row['ativo']:
            flash('Usuário inativo. Procure a coordenação.')
            return render_template('login.html')
        if row and check_password_hash(row['password_hash'], password):
            user = Usuario(row['id'], row['username'], row['role'],
                           row['nome_completo'] or '', row['email'] or '', row['ativo'])
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


# ========================================
# ROTAS DE PAGINAS
# ========================================

@app.route('/')
@login_required
def index():
    if current_user.role == 'aluno':
        return redirect(url_for('meus_agendamentos'))
    return render_template(
        'index.html',
        salas=SALAS,
        horarios=HORARIOS,
        categorias=CATEGORIAS,
        dias=DIAS,
        usuario=current_user.username,
        papel=current_user.role
    )


@app.route('/meus-agendamentos')
@login_required
@requer_papel_page('aluno')
def meus_agendamentos():
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM agendamentos
            WHERE (usuario_id = ? OR (usuario_id IS NULL AND estagiario = ?))
              AND (
                data_especifica IS NULL
                OR data_especifica = ''
                OR data_especifica >= ?
              )
            ORDER BY
              CASE dia_semana
                WHEN 'SEGUNDA' THEN 1
                WHEN 'TERÇA' THEN 2
                WHEN 'QUARTA' THEN 3
                WHEN 'QUINTA' THEN 4
                WHEN 'SEXTA' THEN 5
                ELSE 6
              END,
              horario,
              sala,
              data_especifica
            """,
            (current_user.id, current_user.username, data_hoje_iso())
        ).fetchall()
    finally:
        conn.close()

    agendamentos = []
    atendimentos_paciente = []
    horarios_fixos = []
    pacientes_pontuais_por_horario = {}

    for row in rows:
        ag = dict(row)
        ag['dia_label'] = DIAS_PT.get(ag['dia_semana'], ag['dia_semana'].title())
        ag['tipo'] = 'Pontual' if ag.get('data_especifica') else 'Fixo semanal'
        ag['tipo_slug'] = 'pontual' if ag.get('data_especifica') else 'fixo'
        ag['tem_paciente'] = bool((ag.get('paciente') or '').strip())
        ag['eh_fixo'] = not bool(ag.get('data_especifica'))
        ag['eh_triagem'] = bool(int(ag.get('triagem') or 0))
        ag['data_label'] = ''
        if ag.get('data_especifica'):
            try:
                ag['data_label'] = datetime.strptime(ag['data_especifica'], '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                ag['data_label'] = ag['data_especifica']

        if ag['tem_paciente']:
            atendimentos_paciente.append(ag)
            if ag.get('data_especifica'):
                chave = (ag['dia_semana'], ag['horario'], ag['sala'])
                pacientes_pontuais_por_horario.setdefault(chave, []).append(ag)
        agendamentos.append(ag)

    for ag in agendamentos:
        if not ag['eh_fixo']:
            continue

        chave = (ag['dia_semana'], ag['horario'], ag['sala'])
        pacientes_pontuais = pacientes_pontuais_por_horario.get(chave, [])
        ag['paciente_pontual_label'] = ''
        if pacientes_pontuais:
            primeiro = pacientes_pontuais[0]
            ag['paciente_pontual_label'] = (
                f"{primeiro.get('paciente', '')} em {primeiro.get('data_label') or primeiro.get('data_especifica')}"
            )

        if ag['tem_paciente'] or pacientes_pontuais:
            continue

        categoria_upper = (ag.get('categoria') or '').upper()
        if ag['eh_triagem']:
            ag['status_fixo'] = 'Triagem sem paciente marcado'
            ag['status_slug'] = 'aguardando'
            ag['status_descricao'] = 'Horário reservado para triagem, mas ainda sem paciente vinculado.'
        elif categoria_upper == 'MARCAR':
            ag['status_fixo'] = 'Horário aberto sem paciente'
            ag['status_slug'] = 'aberto'
            ag['status_descricao'] = 'Horário liberado para paciente, mas a recepção ainda não marcou ninguém.'
        else:
            ag['status_fixo'] = 'Reservado sem paciente'
            ag['status_slug'] = 'livre'
            ag['status_descricao'] = 'Horário fixo reservado, mas sem paciente marcado.'

        horarios_fixos.append(ag)

    return render_template(
        'meus_agendamentos.html',
        agendamentos=agendamentos,
        atendimentos_paciente=atendimentos_paciente,
        horarios_fixos=horarios_fixos,
        total=len(agendamentos),
        total_fixos=len(horarios_fixos),
        total_atendimentos=len(atendimentos_paciente),
        total_pontuais=sum(1 for ag in atendimentos_paciente if ag.get('data_especifica')),
        total_triagens_livres=sum(
            1 for ag in horarios_fixos
            if ag.get('eh_triagem') and not ag.get('tem_paciente') and not ag.get('paciente_pontual_label')
        ),
        usuario=current_user.username,
        papel=current_user.role,
        papel_label=PAPEIS_LABEL.get(current_user.role, current_user.role)
    )


@app.route('/reservas')
@login_required
def reservas():
    conn = get_db()
    try:
        if current_user.role == 'aluno':
            rows = conn.execute(
                """
                SELECT *
                FROM reservas
                WHERE usuario_id=?
                ORDER BY
                  CASE status WHEN 'pendente' THEN 1 WHEN 'aprovada' THEN 2 ELSE 3 END,
                  data_uso,
                  horario_inicio
                """,
                (current_user.id,)
            ).fetchall()
            pendentes = []
        elif current_user.role in ('coordenador', 'recepcao'):
            pendentes = conn.execute(
                """
                SELECT *
                FROM reservas
                WHERE status='pendente'
                ORDER BY created_at, data_uso, horario_inicio
                """
            ).fetchall()
            rows = conn.execute(
                """
                SELECT *
                FROM reservas
                WHERE status!='pendente'
                ORDER BY updated_at DESC
                LIMIT 50
                """
            ).fetchall()
        else:
            flash('Acesso negado.', 'error')
            return redirect(url_for('index'))

        caderno_rows = conn.execute(
            """
            SELECT *
            FROM reservas
            WHERE tipo='instrumento'
              AND status!='recusada'
              AND data_uso>=?
            ORDER BY data_uso, horario_inicio, usuario
            """,
            (data_hoje_iso(),)
        ).fetchall()
    finally:
        conn.close()

    def preparar_reserva(row):
        r = dict(row)
        r['status_label'] = label_status_reserva(r.get('status'))
        r['tipo_label'] = 'Sala' if r.get('tipo') == 'sala' else 'Instrumento'
        r['tipo_sala_label'] = 'Sala com computador' if r.get('tipo_sala') == 'computador' else 'Sala comum'
        r['salas_aprovacao'] = candidatos_sala_reserva(r.get('tipo_sala')) if r.get('tipo') == 'sala' else []
        try:
            r['data_label'] = datetime.strptime(r['data_uso'], '%Y-%m-%d').strftime('%d/%m/%Y')
        except (ValueError, TypeError):
            r['data_label'] = r.get('data_uso') or ''
        return r

    minhas_reservas = [preparar_reserva(r) for r in rows]
    pendentes = [preparar_reserva(r) for r in pendentes]
    caderno_instrumentos = [preparar_reserva(r) for r in caderno_rows]

    return render_template(
        'reservas.html',
        usuario=current_user.username,
        papel=current_user.role,
        papel_label=PAPEIS_LABEL.get(current_user.role, current_user.role),
        horarios=HORARIOS,
        minhas_reservas=minhas_reservas,
        minhas_salas=[r for r in minhas_reservas if r.get('tipo') == 'sala'],
        minhas_instrumentos=[r for r in minhas_reservas if r.get('tipo') == 'instrumento'],
        pendentes=pendentes,
        pendentes_sala=[r for r in pendentes if r.get('tipo') == 'sala'],
        pendentes_instrumento=[r for r in pendentes if r.get('tipo') == 'instrumento'],
        caderno_instrumentos=caderno_instrumentos,
        recentes_sala=[r for r in minhas_reservas if r.get('tipo') == 'sala'],
        recentes_instrumento=[r for r in minhas_reservas if r.get('tipo') == 'instrumento'],
    )


@app.route('/reservas/sala', methods=['POST'])
@login_required
@requer_papel('aluno')
def criar_reserva_sala():
    data_uso = request.form.get('data_uso', '').strip()
    horario_inicio = request.form.get('horario_inicio', '').strip()
    horario_fim = request.form.get('horario_fim', '').strip()
    tipo_sala = request.form.get('tipo_sala', 'comum').strip()
    finalidade = request.form.get('finalidade', '').strip()
    observacao = request.form.get('observacao', '').strip()

    if tipo_sala not in ('comum', 'computador'):
        flash('Tipo de sala inválido.', 'error')
        return redirect(url_for('reservas'))
    if not finalidade:
        flash('Informe a finalidade da reserva de sala.', 'error')
        return redirect(url_for('reservas'))

    data_uso, erro_data = normalizar_data_especifica(data_uso)
    if erro_data:
        flash(erro_data, 'error')
        return redirect(url_for('reservas'))
    _, erro_antecedencia = validar_antecedencia_minima(data_uso, horario_inicio)
    if erro_antecedencia:
        flash(erro_antecedencia, 'error')
        return redirect(url_for('reservas'))
    _, erro_intervalo = horarios_do_intervalo(horario_inicio, horario_fim)
    if erro_intervalo:
        flash(erro_intervalo, 'error')
        return redirect(url_for('reservas'))

    sala_sugerida, erro_sala = encontrar_sala_disponivel(data_uso, horario_inicio, horario_fim, tipo_sala)
    if erro_sala:
        flash(erro_sala, 'error')
        return redirect(url_for('reservas'))

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO reservas(
              usuario_id, usuario, tipo, data_uso, horario_inicio, horario_fim,
              tipo_sala, sala_atribuida, finalidade, observacao
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                current_user.id, current_user.username, 'sala', data_uso, horario_inicio,
                horario_fim, tipo_sala, sala_sugerida, finalidade, observacao
            )
        )
        conn.commit()
    finally:
        conn.close()

    registrar_log('SOLICITAR_RESERVA_SALA', f'{current_user.username} solicitou {tipo_sala} em {data_uso} {horario_inicio}-{horario_fim}')
    flash('Solicitação enviada para a recepção/coordenação.', 'success')
    return redirect(url_for('reservas'))


@app.route('/reservas/instrumento', methods=['POST'])
@login_required
@requer_papel('aluno')
def criar_reserva_instrumento():
    data_uso = request.form.get('data_uso', '').strip()
    horario_inicio = request.form.get('horario_inicio', '').strip()
    instrumento = request.form.get('instrumento', '').strip()
    finalidade = request.form.get('finalidade', '').strip()
    observacao = request.form.get('observacao', '').strip()

    if not instrumento:
        flash('Informe qual teste ou instrumento você precisa reservar.', 'error')
        return redirect(url_for('reservas'))
    data_uso, erro_data = normalizar_data_especifica(data_uso)
    if erro_data:
        flash(erro_data, 'error')
        return redirect(url_for('reservas'))
    _, erro_antecedencia = validar_antecedencia_minima(data_uso, horario_inicio)
    if erro_antecedencia:
        flash(erro_antecedencia, 'error')
        return redirect(url_for('reservas'))

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO reservas(
              usuario_id, usuario, tipo, data_uso, horario_inicio,
              instrumento, finalidade, observacao
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                current_user.id, current_user.username, 'instrumento', data_uso,
                horario_inicio, instrumento, finalidade, observacao
            )
        )
        conn.commit()
    finally:
        conn.close()

    registrar_log('SOLICITAR_RESERVA_INSTRUMENTO', f'{current_user.username} solicitou {instrumento} em {data_uso} {horario_inicio}')
    flash('Solicitação de instrumento enviada.', 'success')
    return redirect(url_for('reservas'))


@app.route('/reservas/<int:rid>/aprovar', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
def aprovar_reserva(rid):
    resposta = request.form.get('resposta', '').strip()
    sala_escolhida = request.form.get('sala_atribuida', '').strip()
    conn = get_db()
    try:
        reserva = conn.execute("SELECT * FROM reservas WHERE id=?", (rid,)).fetchone()
        if not reserva or reserva['status'] != 'pendente':
            flash('Solicitação não encontrada ou já analisada.', 'error')
            return redirect(url_for('reservas'))

        agendamento_ids = ''
        sala_atribuida = reserva['sala_atribuida'] or ''
        if reserva['tipo'] == 'sala':
            _, erro_antecedencia = validar_antecedencia_minima(reserva['data_uso'], reserva['horario_inicio'])
            if erro_antecedencia:
                flash('Não é possível aprovar: a solicitação já está com menos de 24h de antecedência.', 'error')
                return redirect(url_for('reservas'))

            if sala_escolhida:
                if sala_escolhida not in candidatos_sala_reserva(reserva['tipo_sala']):
                    flash('A sala escolhida não combina com o tipo solicitado.', 'error')
                    return redirect(url_for('reservas'))
                disponivel, erro_sala = sala_disponivel_para_reserva(
                    reserva['data_uso'],
                    reserva['horario_inicio'],
                    reserva['horario_fim'],
                    sala_escolhida
                )
                if not disponivel:
                    flash(erro_sala, 'error')
                    return redirect(url_for('reservas'))
                sala_atribuida = sala_escolhida
            else:
                sala_atribuida, erro_sala = encontrar_sala_disponivel(
                    reserva['data_uso'],
                    reserva['horario_inicio'],
                    reserva['horario_fim'],
                    reserva['tipo_sala']
                )
                if erro_sala:
                    flash(erro_sala, 'error')
                    return redirect(url_for('reservas'))

            dia = dia_semana_da_data(reserva['data_uso'])
            slots, _ = horarios_do_intervalo(reserva['horario_inicio'], reserva['horario_fim'])
            novos_ids = []
            for slot in slots:
                nid = inserir_agendamento(conn, {
                    'dia': dia,
                    'horario': slot,
                    'sala': sala_atribuida,
                    'estagiario': reserva['usuario'],
                    'paciente': '',
                    'categoria': 'PRONTUÁRIO/ESTUDAR',
                    'semestre': detect_sem(reserva['usuario']),
                    'triagem': 0,
                    'observacao': f'Reserva aprovada: {reserva["finalidade"]}',
                    'data_especifica': reserva['data_uso'],
                    'usuario_id': reserva['usuario_id'],
                    'ocupa_sala': 1
                })
                novos_ids.append(str(nid))
            agendamento_ids = ','.join(novos_ids)

        conn.execute(
            """
            UPDATE reservas
            SET status='aprovada', resposta=?, sala_atribuida=?, agendamento_ids=?,
                analisado_por=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (resposta, sala_atribuida, agendamento_ids, current_user.username, rid)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Não foi possível aprovar: a sala ficou ocupada por outro agendamento.', 'error')
        return redirect(url_for('reservas'))
    finally:
        conn.close()

    registrar_log('APROVAR_RESERVA', f'Reserva #{rid} aprovada por {current_user.username}')
    flash('Reserva aprovada.', 'success')
    return redirect(url_for('reservas'))


@app.route('/reservas/<int:rid>/recusar', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
def recusar_reserva(rid):
    resposta = request.form.get('resposta', '').strip()
    conn = get_db()
    try:
        reserva = conn.execute("SELECT * FROM reservas WHERE id=?", (rid,)).fetchone()
        if not reserva or reserva['status'] != 'pendente':
            flash('Solicitação não encontrada ou já analisada.', 'error')
            return redirect(url_for('reservas'))
        conn.execute(
            """
            UPDATE reservas
            SET status='recusada', resposta=?, analisado_por=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (resposta, current_user.username, rid)
        )
        conn.commit()
    finally:
        conn.close()

    registrar_log('RECUSAR_RESERVA', f'Reserva #{rid} recusada por {current_user.username}')
    flash('Reserva recusada.', 'success')
    return redirect(url_for('reservas'))


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
            conn.execute(
                'UPDATE usuarios SET nome_completo=?, email=? WHERE id=?',
                (nome_completo, email, current_user.id)
            )
            conn.commit()
        finally:
            conn.close()
        registrar_log('EDITAR_PERFIL', f'Usuário {current_user.username} atualizou o perfil')
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('perfil'))

    return render_template(
        'perfil.html',
        usuario=current_user.username,
        papel=current_user.role,
        papel_label=PAPEIS_LABEL.get(current_user.role, current_user.role),
        nome_completo=row['nome_completo'] or '',
        email=row['email'] or ''
    )


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
            conn.execute(
                'UPDATE usuarios SET password_hash=? WHERE id=?',
                (generate_password_hash(nova_senha), current_user.id)
            )
            conn.commit()
        finally:
            conn.close()
        registrar_log('TROCAR_SENHA', f'Usuário {current_user.username} alterou a própria senha')
        flash('Senha alterada com sucesso!', 'success')
        return redirect(url_for('perfil'))
    return render_template('trocar_senha.html', usuario=current_user.username, papel=current_user.role)


@app.route('/imprimir')
@login_required
@requer_papel_page('coordenador', 'recepcao')
def imprimir_selecao():
    return render_template(
        'imprimir_selecao.html',
        dias=DIAS,
        dias_pt=DIAS_PT,
        usuario=current_user.username,
        papel=current_user.role
    )


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
    return render_template(
        'imprimir.html',
        dia_nome=DIAS_PT.get(dia, dia),
        gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'),
        pacientes=pacientes
    )


@app.route('/logs')
@login_required
@requer_papel_page('coordenador')
def logs_page():
    return render_template('logs.html', usuario=current_user.username, papel=current_user.role)


# ========================================
# ROTAS DE USUARIOS
# ========================================

@app.route('/usuarios')
@login_required
@requer_papel_page('coordenador')
def usuarios_page():
    conn = get_db()
    try:
        rows = conn.execute('SELECT id, username, email, role, ativo, created_at FROM usuarios ORDER BY created_at').fetchall()
    finally:
        conn.close()
    return render_template(
        'usuarios.html',
        usuarios=[dict(r) for r in rows],
        usuario=current_user.username,
        papel=current_user.role,
        papeis_label=PAPEIS_LABEL
    )


@app.route('/api/estagiarios', methods=['GET'])
@login_required
def api_list_estagiarios():
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, username FROM usuarios WHERE role='aluno' AND ativo=1 ORDER BY username").fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/usuarios', methods=['GET'])
@login_required
@requer_papel('coordenador')
def api_list_usuarios():
    conn = get_db()
    try:
        rows = conn.execute('SELECT id, username, email, role, ativo, created_at FROM usuarios ORDER BY created_at').fetchall()
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
    email = (d.get('email') or '').strip()
    password = (d.get('password') or '').strip()
    role = (d.get('role') or 'aluno').strip()
    ativo = valor_ativo(d.get('ativo'), 1)

    if not username or not password:
        return jsonify({'erro': 'Usuário e senha são obrigatórios'}), 400
    if len(password) < 8:
        return jsonify({'erro': 'A senha deve ter no mínimo 8 caracteres'}), 400
    if role not in PAPEIS_VALIDOS:
        return jsonify({'erro': 'Papel inválido'}), 400

    try:
        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO usuarios(username, email, password_hash, role, ativo) VALUES(?,?,?,?,?)',
                (username, email, generate_password_hash(password), role, ativo)
            )
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
        new_username = (d.get('username', row['username']) or '').strip()
        new_email = (d.get('email', row['email']) or '').strip()
        if not new_username:
            return jsonify({'erro': 'Usuario e obrigatorio'}), 400
        new_role = (d.get('role') or row['role']).strip()
        if new_role not in PAPEIS_VALIDOS:
            return jsonify({'erro': 'Papel inválido'}), 400
        ativo = valor_ativo(d.get('ativo'), row['ativo'])
        if row['id'] == current_user.id and not ativo:
            return jsonify({'erro': 'Você não pode inativar sua própria conta'}), 400
        new_pass = (d.get('password') or '').strip()
        if new_pass and len(new_pass) < 8:
            return jsonify({'erro': 'A senha deve ter no mínimo 8 caracteres'}), 400
        if new_pass:
            conn.execute(
                'UPDATE usuarios SET username=?, email=?, role=?, ativo=?, password_hash=? WHERE id=?',
                (new_username, new_email, new_role, ativo, generate_password_hash(new_pass), uid)
            )
        else:
            conn.execute(
                'UPDATE usuarios SET username=?, email=?, role=?, ativo=? WHERE id=?',
                (new_username, new_email, new_role, ativo, uid)
            )
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
        conn.execute('UPDATE usuarios SET ativo=0 WHERE id=?', (uid,))
        conn.commit()
    finally:
        conn.close()
    registrar_log('INATIVAR_USUARIO', f'Usuário "{row["username"]}" inativado')
    return jsonify({'message': 'Usuário inativado'})


# ========================================
# API DE AGENDAMENTOS
# ========================================

@app.route('/api/conflito', methods=['GET'])
@login_required
def api_conflito():
    dia = request.args.get('dia_semana', '')
    horario = request.args.get('horario', '')
    sala = request.args.get('sala', '')
    data_esp = request.args.get('data_especifica', '').strip()
    excluir = request.args.get('excluir_id', None)
    ocupa_manual = valor_ocupa_sala(request.args.get('ocupa_sala'), None)
    if ocupa_manual is None:
        ocupa_manual = calcular_ocupa_sala(
            request.args.get('categoria', ''),
            request.args.get('paciente', ''),
            request.args.get('observacao', ''),
            data_esp,
            request.args.get('triagem', 0)
        )
    if not ocupa_manual:
        return jsonify({'conflito': False, 'ocupa_sala': False})
    if not dia or not horario or not sala:
        return jsonify({'conflito': False})
    erro_validacao = validar_valores_agendamento(dia, horario, sala)
    if erro_validacao:
        return jsonify({'erro': erro_validacao}), 400
    if data_esp:
        data_esp, erro_data = normalizar_data_especifica(data_esp)
        if erro_data:
            return jsonify({'erro': erro_data}), 400
        dia = dia_semana_da_data(data_esp)
    conflito = checar_conflito(dia, horario, sala, data_especifica=data_esp, excluir_id=excluir)
    if conflito:
        if current_user.role == 'aluno':
            return jsonify({'conflito': True})
        return jsonify({
            'conflito': True,
            'estagiario': conflito.get('estagiario', ''),
            'paciente': conflito.get('paciente', ''),
            'categoria': conflito.get('categoria', ''),
            'id': conflito.get('id')
        })
    return jsonify({'conflito': False})


@app.route('/api/agendamentos', methods=['GET'])
@login_required
def list_ag():
    dia = request.args.get('dia_semana', 'SEGUNDA')
    horario = request.args.get('horario', '')
    sala = request.args.get('sala', '')
    cat = request.args.get('categoria', '')
    ocupa_sala = request.args.get('ocupa_sala', '').strip()
    busca = request.args.get('busca', '').strip()
    data_ref = request.args.get('data', '').strip()

    dia_ref = None
    if data_ref:
        data_ref, erro_data = normalizar_data_especifica(data_ref)
        if erro_data:
            return jsonify({'erro': erro_data}), 400
        dia_ref = dia_semana_da_data(data_ref)

    dia_busca = dia_ref or dia
    erro_validacao = validar_valores_agendamento(
        dia_busca,
        horario or HORARIOS[0],
        sala or SALAS[0],
        cat
    )
    if erro_validacao:
        return jsonify({'erro': erro_validacao}), 400

    if data_ref:
        q = ('SELECT * FROM agendamentos WHERE ('
             '(dia_semana=? AND (data_especifica IS NULL OR data_especifica = \'\'))'
             ' OR data_especifica=?'
             ')')
        p = [dia_busca, data_ref]
    else:
        q = (
            'SELECT * FROM agendamentos WHERE ('
            '(dia_semana=? AND (data_especifica IS NULL OR data_especifica = \'\')) '
            'OR (data_especifica IS NOT NULL AND data_especifica != \'\' '
            'AND data_especifica >= ? AND strftime(\'%w\', data_especifica)=?)'
            ')'
        )
        p = [dia_busca, data_hoje_iso(), numero_semana_sqlite(dia_busca)]
    if horario:
        q += ' AND horario=?'
        p.append(horario)
    if sala:
        q += ' AND sala=?'
        p.append(sala)
    if cat:
        q += ' AND categoria=?'
        p.append(cat)
    if ocupa_sala in ('0', '1'):
        q += ' AND ocupa_sala=?'
        p.append(int(ocupa_sala))
    if busca:
        q += ' AND (estagiario LIKE ? OR paciente LIKE ? OR observacao LIKE ?)'
        p += [f'%{busca}%'] * 3
    if current_user.role == 'aluno':
        q += ' AND (usuario_id = ? OR (usuario_id IS NULL AND estagiario = ?))'
        p += [current_user.id, current_user.username]
    q += ' ORDER BY horario, sala, data_especifica'
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
    if not usuario_pode_ver_agendamento(r):
        return jsonify({'erro': 'Não encontrado'}), 404
    return jsonify(dict(r))


@app.route('/api/agendamentos', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('60 per minute')
def create_ag():
    d = request.get_json(silent=True)
    if not d:
        return jsonify({'erro': 'JSON inválido ou Content-Type incorreto'}), 400

    dados_ag, erro = preparar_dados_agendamento(d, current_user.id if current_user.is_authenticated else None)
    if erro:
        return jsonify({'erro': erro}), 400

    conflito = checar_conflito(
        dados_ag['dia'],
        dados_ag['horario'],
        dados_ag['sala'],
        data_especifica=dados_ag['data_especifica']
    ) if dados_ag['ocupa_sala'] else None
    if conflito:
        ocu = conflito.get('estagiario') or conflito.get('categoria') or 'outro agendamento'
        return jsonify({
            'erro': (
                f'Conflito: {dados_ag["sala"]} já está ocupada às {dados_ag["horario"]} '
                f'({dados_ag["data_especifica"] or dados_ag["dia"]}) por: {ocu}'
            ),
            'conflito': True,
            'conflito_id': conflito.get('id')
        }), 409

    try:
        conn = get_db()
        try:
            nid = inserir_agendamento(conn, dados_ag)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.IntegrityError:
        return jsonify({'erro': 'Conflito: esse horário já foi ocupado por outro agendamento.'}), 409

    registrar_log('CRIAR', f'Agendamento #{nid} criado — sala: {dados_ag["sala"]} {dados_ag["horario"]}')
    return jsonify({'id': nid, 'message': 'Criado'}), 201


@app.route('/api/agendamentos/<int:aid>', methods=['PUT'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('60 per minute')
def update_ag(aid):
    d = request.get_json(silent=True)
    if not d:
        return jsonify({'erro': 'JSON inválido ou Content-Type incorreto'}), 400

    dados_ag, erro = preparar_dados_agendamento(d)
    if erro:
        return jsonify({'erro': erro}), 400

    conflito = checar_conflito(
        dados_ag['dia'],
        dados_ag['horario'],
        dados_ag['sala'],
        data_especifica=dados_ag['data_especifica'],
        excluir_id=aid
    ) if dados_ag['ocupa_sala'] else None
    if conflito:
        ocu = conflito.get('estagiario') or conflito.get('categoria') or 'outro agendamento'
        return jsonify({
            'erro': (
                f'Conflito: {dados_ag["sala"]} já está ocupada às {dados_ag["horario"]} '
                f'({dados_ag["data_especifica"] or dados_ag["dia"]}) por: {ocu}'
            ),
            'conflito': True,
            'conflito_id': conflito.get('id')
        }), 409

    try:
        conn = get_db()
        try:
            cur = conn.execute(
                'UPDATE agendamentos SET dia_semana=?,horario=?,sala=?,estagiario=?,paciente=?,categoria=?,semestre=?,'
                'triagem=?,observacao=?,data_especifica=?,usuario_id=?,ocupa_sala=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (
                    dados_ag['dia'], dados_ag['horario'], dados_ag['sala'],
                    dados_ag['estagiario'], dados_ag['paciente'], dados_ag['categoria'],
                    dados_ag['semestre'], dados_ag['triagem'], dados_ag['observacao'],
                    dados_ag['data_especifica'],
                    buscar_usuario_id_aluno(dados_ag['estagiario'], conn) or dados_ag['usuario_id'],
                    dados_ag['ocupa_sala'],
                    aid
                )
            )
            if cur.rowcount == 0:
                return jsonify({'erro': 'Agendamento nao encontrado'}), 404
            conn.commit()
        finally:
            conn.close()
    except sqlite3.IntegrityError:
        return jsonify({'erro': 'Conflito: esse horário já foi ocupado por outro agendamento.'}), 409

    registrar_log('EDITAR', f'Agendamento #{aid} editado — sala: {dados_ag["sala"]} {dados_ag["horario"]}')
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


# ========================================
# API DE RELATORIOS E ADMINISTRACAO
# ========================================

@app.route('/api/stats')
@login_required
def stats():
    dia = request.args.get('dia_semana', 'SEGUNDA')
    if dia not in DIAS:
        return jsonify({'erro': f'Dia inválido: {dia}'}), 400
    filtro_visao = (
        "((dia_semana=? AND (data_especifica IS NULL OR data_especifica = '')) "
        "OR (data_especifica IS NOT NULL AND data_especifica != '' "
        "AND data_especifica >= ? AND strftime('%w', data_especifica)=?))"
    )
    params = (dia, data_hoje_iso(), numero_semana_sqlite(dia))
    conn = get_db()
    try:
        total = conn.execute(f'SELECT COUNT(*) FROM agendamentos WHERE {filtro_visao}', params).fetchone()[0]
        livre = conn.execute(
            f"SELECT COUNT(*) FROM agendamentos WHERE {filtro_visao} AND categoria='LIVRE'",
            params
        ).fetchone()[0]
        por_cat = conn.execute(
            f'SELECT categoria, COUNT(*) as n FROM agendamentos WHERE {filtro_visao} GROUP BY categoria ORDER BY n DESC',
            params
        ).fetchall()
    finally:
        conn.close()
    return jsonify({'total': total, 'livre': livre, 'por_categoria': [dict(r) for r in por_cat]})


@app.route('/api/export')
@login_required
@requer_papel('coordenador', 'recepcao')
def export_xlsx():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return jsonify({
            'erro': 'Exportação XLSX indisponível. Instale as dependências com: pip install -r requirements.txt'
        }), 500

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

    wb = Workbook()
    ws = wb.active
    ws.title = 'Mapa de Salas'
    headers = ['ID', 'Dia', 'Horário', 'Sala', 'Estagiário (usuário)', 'Nome Completo', 'Paciente',
               'Categoria', 'Semestre', 'Triagem', 'Ocupa Sala', 'Data Esp.', 'Obs.']
    ws.append(headers)

    header_fill = PatternFill('solid', fgColor='1E293B')
    header_font = Font(color='FFFFFF', bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font

    for r in rows:
        ws.append([
            r['id'], r['dia_semana'], r['horario'], r['sala'],
            r['estagiario'], r['nome_real'], r['paciente'],
            r['categoria'], r['semestre'], 'Sim' if r['triagem'] else 'Não',
            'Sim' if r['ocupa_sala'] else 'Não', r['data_especifica'], r['observacao']
        ])

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 42)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    registrar_log('EXPORTAR', 'XLSX exportado')
    return send_file(
        out,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'mapa_salas_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    )


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
    if usuario:
        q += ' AND usuario LIKE ?'
        p.append(f'%{usuario}%')
    if acao:
        q += ' AND acao LIKE ?'
        p.append(f'%{acao}%')
    if data_ini:
        q += ' AND ts >= ?'
        p.append(data_ini)
    if data_fim:
        q += ' AND ts <= ?'
        p.append(data_fim + ' 23:59:59')

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
        removidos = limpar_logs_antigos(conn)
        conn.commit()
    finally:
        conn.close()
    registrar_log('LIMPAR_LOGS', f'{removidos} logs antigos removidos (retenção: {LOG_RETENCAO_DIAS} dias)')
    return jsonify({'message': f'{removidos} logs removidos'})


@app.route('/api/admin/apagar-logs-recentes', methods=['POST'])
@login_required
@requer_papel('coordenador')
def apagar_logs_recentes():
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM historico WHERE ts >= datetime('now', '-' || ? || ' days')",
            (LOG_RETENCAO_DIAS,)
        )
        removidos = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    registrar_log('APAGAR_LOGS_RECENTES', f'{removidos} logs dos últimos {LOG_RETENCAO_DIAS} dias removidos')
    return jsonify({'message': f'{removidos} logs dos últimos {LOG_RETENCAO_DIAS} dias removidos'})


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


def chave_sem_acento(valor):
    valor = unicodedata.normalize('NFKD', str(valor or ''))
    valor = ''.join(ch for ch in valor if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', '', valor.lower())


def normalizar_sala_excel(valor):
    mapa = {chave_sem_acento(sala): sala for sala in SALAS}
    chave = chave_sem_acento(valor)
    if chave in mapa:
        return mapa[chave]
    aliases = {
        'consultorio1': 'Consultório 1',
        'consultorio2': 'Consultório 2',
        'consultorio3': 'Consultório 3',
        'consultorio4': 'Consultório 4',
        'consultorio5': 'Consultório 5',
        'consultorio6diva': 'Consultório 6 (Divã)',
        'consultorio7diva': 'Consultório 7 (Divã)',
        'consultorio8': 'Consultório 8',
        'sounace': 'SOU / NACE',
        'saladegrupo1': 'Sala de Grupo 1',
        'saladegrupo2': 'Sala de Grupo 2',
        'supervisao': 'Supervisão',
        'coordenacao': 'Coordenação',
    }
    return aliases.get(chave)


def texto_celula_excel(valor):
    if valor is None:
        return ''
    texto = str(valor).replace('\r', '\n')
    partes = [p.strip() for p in texto.split('\n') if p and p.strip()]
    return ' - '.join(partes).strip()


def horario_excel(valor):
    if valor is None or valor == '':
        return ''
    if hasattr(valor, 'strftime'):
        return valor.strftime('%H:%M')
    try:
        numero = float(valor)
        minutos = int(round(numero * 24 * 60))
        return f'{minutos // 60:02d}:{minutos % 60:02d}'
    except (TypeError, ValueError):
        texto = str(valor).strip()
        m = re.search(r'(\d{1,2})[:h](\d{2})', texto)
        if m:
            return f'{int(m.group(1)):02d}:{int(m.group(2)):02d}'
        return texto


def extrair_data_pontual_excel(texto, ano=None):
    ano = ano or datetime.now().year
    if not re.search(r'\b(s[óo]|somente|apenas|dia)\b', texto, flags=re.I):
        return ''
    m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', texto)
    if not m:
        return ''
    dia = int(m.group(1))
    mes = int(m.group(2))
    ano_encontrado = int(m.group(3)) if m.group(3) else ano
    if ano_encontrado < 100:
        ano_encontrado += 2000
    try:
        return datetime(ano_encontrado, mes, dia).strftime('%Y-%m-%d')
    except ValueError:
        return ''


def limpar_marcadores_excel(texto):
    texto = re.sub(r'\(?\btriagem\b\)?', '', texto, flags=re.I)
    texto = re.sub(r'\b(s[óo]|somente|apenas)\s+(dia\s+)?\d{1,2}/\d{1,2}(/\d{2,4})?', '', texto, flags=re.I)
    texto = re.sub(r'\bdia\s+\d{1,2}/\d{1,2}(/\d{2,4})?', '', texto, flags=re.I)
    return re.sub(r'\s+', ' ', texto).strip(' -')


def categoria_por_texto_excel(texto):
    up = texto.upper()
    if 'NÃO MARCAR' in up or 'NAO MARCAR' in up:
        return 'NÃO MARCAR'
    if 'MARCAR' in up:
        return 'MARCAR'
    if 'SUPERVIS' in up or up.startswith('PROF.'):
        return 'SUPERVISÃO'
    if 'NACE' in up:
        return 'NACE'
    if re.search(r'\bSOU\b', up):
        return 'SOU'
    if 'PRONT' in up or 'ESTUDAR' in up:
        return 'PRONTUÁRIO/ESTUDAR'
    if 'NUTRI' in up:
        return 'NUTRIÇÃO'
    if 'PSICODIAGN' in up:
        return 'PSICODIAGNÓSTICO'
    if 'PSIQUIATR' in up:
        return 'PSIQUIATRIA'
    if 'AMBULAT' in up or 'NEUROPSICOLOGIA' in up:
        return 'AMBULATÓRIO NEUROPSICOLOGIA'
    if 'PLANT' in up:
        return 'PLANTÃO PSICOLÓGICO'
    if re.search(r'\b10\s*[°º]', texto):
        return 'ESTAGIÁRIO 10°'
    if re.search(r'\b9\s*[°º]', texto):
        return 'ESTAGIÁRIO 9°'
    return 'OUTRO'


def montar_agendamento_excel(dia, horario, sala, texto_principal, texto_secundario, ano=None):
    textos = [t for t in (texto_principal, texto_secundario) if t]
    if not textos:
        return None, 'Célula vazia'
    texto_total = ' - '.join(textos)
    if chave_sem_acento(texto_total) in ('tt', 't'):
        return None, 'Marcador interno ignorado'

    triagem = 1 if re.search(r'\btriagem\b', texto_total, flags=re.I) else 0
    data_especifica = extrair_data_pontual_excel(texto_total, ano)
    categoria = categoria_por_texto_excel(texto_total)
    estagiario = ''
    paciente = ''
    observacao = ''

    if categoria.startswith('ESTAGIÁRIO'):
        estagiario = limpar_marcadores_excel(texto_principal)
        paciente = limpar_marcadores_excel(texto_secundario)
        if paciente.upper() in ('MARCAR', 'MARCAR TRIAGEM', 'NÃO MARCAR', 'NAO MARCAR'):
            observacao = paciente
            paciente = ''
    elif categoria in ('MARCAR', 'NÃO MARCAR'):
        estagiario = limpar_marcadores_excel(texto_principal)
        observacao = limpar_marcadores_excel(texto_total)
        if categoria == 'MARCAR':
            estagiario = ''
    else:
        estagiario = limpar_marcadores_excel(texto_principal)
        observacao = limpar_marcadores_excel(texto_total)

    if not estagiario and categoria == 'OUTRO':
        estagiario = limpar_marcadores_excel(texto_principal) or 'Importado do Excel'

    dados_ag, erro = preparar_dados_agendamento({
        'dia_semana': dia,
        'horario': horario,
        'sala': sala,
        'estagiario': estagiario,
        'paciente': paciente,
        'categoria': categoria,
        'triagem': triagem,
        'observacao': observacao,
        'data_especifica': data_especifica,
    })
    return dados_ag, erro


def importar_xlsx_mapa(file_storage, substituir=False):
    try:
        from openpyxl import load_workbook
    except ImportError:
        return None, {'erro': 'Importação XLSX indisponível. Instale as dependências com: pip install -r requirements.txt'}, 500

    file_storage.stream.seek(0)
    wb = load_workbook(file_storage.stream, data_only=True, read_only=True)
    abas_dias = {chave_sem_acento(dia): dia for dia in DIAS}
    inseridos = 0
    conflitos = []
    erros = []
    ignorados = 0
    ano = datetime.now().year

    conn = get_db()
    try:
        if substituir:
            conn.execute('DELETE FROM agendamentos')

        for nome_aba in wb.sheetnames:
            dia = abas_dias.get(chave_sem_acento(nome_aba))
            if not dia:
                continue
            ws = wb[nome_aba]
            salas_colunas = {}
            for col in range(2, ws.max_column + 1):
                sala = normalizar_sala_excel(ws.cell(row=1, column=col).value)
                if sala:
                    salas_colunas[col] = sala

            row = 2
            while row <= ws.max_row:
                horario = horario_excel(ws.cell(row=row, column=1).value)
                if horario not in HORARIOS:
                    row += 1
                    continue

                for col, sala in salas_colunas.items():
                    texto_principal = texto_celula_excel(ws.cell(row=row, column=col).value)
                    texto_secundario = texto_celula_excel(ws.cell(row=row + 1, column=col).value) if row + 1 <= ws.max_row else ''
                    if not texto_principal and not texto_secundario:
                        continue

                    dados_ag, erro = montar_agendamento_excel(dia, horario, sala, texto_principal, texto_secundario, ano)
                    if erro:
                        ignorados += 1
                        continue

                    conflito = None if substituir or not dados_ag['ocupa_sala'] else checar_conflito(
                        dados_ag['dia'],
                        dados_ag['horario'],
                        dados_ag['sala'],
                        data_especifica=dados_ag['data_especifica']
                    )
                    if conflito:
                        conflitos.append({
                            'aba': nome_aba,
                            'horario': dados_ag['horario'],
                            'sala': dados_ag['sala'],
                            'ocupado_por': conflito.get('estagiario') or conflito.get('categoria')
                        })
                        continue

                    try:
                        inserir_agendamento(conn, dados_ag)
                        inseridos += 1
                    except sqlite3.IntegrityError as exc:
                        conflitos.append({
                            'aba': nome_aba,
                            'horario': dados_ag['horario'],
                            'sala': dados_ag['sala'],
                            'ocupado_por': str(exc)
                        })
                    except Exception as exc:
                        erros.append(f'{nome_aba} {horario} {sala}: {exc}')

                row += 2

        conn.commit()
    finally:
        conn.close()
        wb.close()

    registrar_log('IMPORTAR_XLSX', f'{inseridos} agendamentos importados do Excel, {len(conflitos)} conflitos, {len(erros)} erros')
    return {
        'inseridos': inseridos,
        'conflitos': conflitos[:50],
        'erros': erros[:50],
        'ignorados': ignorados,
        'substituiu': bool(substituir),
        'message': f'{inseridos} agendamento(s) importado(s) do Excel.'
    }, None, 200


@app.route('/api/import', methods=['POST'])
@login_required
@requer_papel('coordenador', 'recepcao')
@limiter.limit('10 per minute')
def import_csv():
    if 'file' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    f = request.files['file']
    filename = (f.filename or '').lower()
    substituir = request.form.get('substituir') in ('1', 'true', 'sim', 'on')
    if filename.endswith('.xlsx'):
        resultado, erro, status = importar_xlsx_mapa(f, substituir=substituir)
        if erro:
            return jsonify(erro), status
        return jsonify(resultado), status
    if not filename.endswith('.csv'):
        return jsonify({'erro': 'Apenas arquivos .csv ou .xlsx são aceitos'}), 400

    stream = io.StringIO(f.read().decode('utf-8-sig'))
    reader = csv.DictReader(stream)
    inseridos = 0
    conflitos = []
    erros = []

    conn = get_db()
    try:
        for i, row in enumerate(reader, start=2):
            try:
                dia = (row.get('Dia') or row.get('dia_semana') or '').strip().upper()
                horario = (row.get('Horário') or row.get('horario') or '').strip()
                sala = (row.get('Sala') or row.get('sala') or '').strip()
                estagiario = (row.get('Estagiário (usuário)') or row.get('Estagiário') or row.get('estagiario') or '').strip()
                paciente = (row.get('Paciente') or row.get('paciente') or '').strip()
                categoria = (row.get('Categoria') or row.get('categoria') or '').strip()
                semestre = int(row.get('Semestre') or row.get('semestre') or 0)
                triagem = 1 if str(row.get('Triagem') or '').strip().lower() in ('sim', '1', 'true') else 0
                obs = (row.get('Obs.') or row.get('observacao') or '').strip()
                data_esp = (row.get('Data Esp.') or row.get('data_especifica') or '').strip()
                ocupa_sala = row.get('Ocupa Sala') or row.get('ocupa_sala') or ''

                dados_ag, erro = preparar_dados_agendamento({
                    'dia_semana': dia,
                    'horario': horario,
                    'sala': sala,
                    'estagiario': estagiario,
                    'paciente': paciente,
                    'categoria': categoria,
                    'semestre': semestre,
                    'triagem': triagem,
                    'observacao': obs,
                    'data_especifica': data_esp,
                    'ocupa_sala': ocupa_sala
                })
                if erro:
                    erros.append(f'Linha {i}: {erro}')
                    continue

                conflito = checar_conflito(
                    dados_ag['dia'],
                    dados_ag['horario'],
                    dados_ag['sala'],
                    data_especifica=dados_ag['data_especifica']
                )
                if conflito:
                    conflitos.append({
                        'linha': i,
                        'dia': dados_ag['dia'],
                        'horario': dados_ag['horario'],
                        'sala': dados_ag['sala'],
                        'ocupado_por': conflito.get('estagiario') or conflito.get('categoria')
                    })
                    continue

                inserir_agendamento(conn, dados_ag)
                inseridos += 1
            except Exception as e:
                erros.append(f'Linha {i}: {str(e)}')
        conn.commit()
    finally:
        conn.close()

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
        return render_template(
            'backup.html',
            usuario=current_user.username,
            papel=current_user.role,
            versao=VERSAO
        )
    registrar_log('BACKUP', f'Backup manual baixado por {current_user.username} — IP: {request.remote_addr}')
    return send_file(
        DB_PATH,
        as_attachment=True,
        download_name=f'backup_mapa_{datetime.now().strftime("%Y%m%d_%H%M")}.db'
    )


def executar_manutencao(vacuum=False):
    conn = get_db()
    try:
        integridade = conn.execute('PRAGMA integrity_check').fetchone()[0]
        logs_removidos = limpar_logs_antigos(conn)
        total_usuarios = conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0]
        usuarios_ativos = conn.execute('SELECT COUNT(*) FROM usuarios WHERE ativo=1').fetchone()[0]
        total_agendamentos = conn.execute('SELECT COUNT(*) FROM agendamentos').fetchone()[0]
        total_logs = conn.execute('SELECT COUNT(*) FROM historico').fetchone()[0]
        conn.commit()
        if vacuum:
            conn.execute('VACUUM')
        return {
            'integridade': integridade,
            'logs_removidos': logs_removidos,
            'usuarios_total': total_usuarios,
            'usuarios_ativos': usuarios_ativos,
            'agendamentos_total': total_agendamentos,
            'logs_total': total_logs,
            'vacuum_executado': vacuum
        }
    finally:
        conn.close()


@app.cli.command('manutencao')
@click.option('--vacuum', is_flag=True, help='Compacta o arquivo SQLite depois da limpeza.')
def comando_manutencao(vacuum):
    resultado = executar_manutencao(vacuum=vacuum)
    click.echo('Manutencao concluida.')
    for chave, valor in resultado.items():
        click.echo(f'{chave}: {valor}')


# ========================================
# INICIALIZACAO DA APLICACAO
# ========================================

with app.app_context():
    init_db()

if __name__ == '__main__':
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        init_db()
    print(f'\n Versão: {VERSAO} | http://localhost:5000\n')
    app.run(debug=True, port=5000)
