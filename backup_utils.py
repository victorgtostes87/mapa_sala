import os
import sqlite3
import tempfile
from datetime import datetime


def criar_backup_sqlite_bytes(db_path):
    origem = sqlite3.connect(db_path, timeout=10)
    tmp = tempfile.NamedTemporaryFile(prefix='backup_mapa_', suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    destino = sqlite3.connect(tmp_path)
    try:
        origem.backup(destino)
        destino.close()
        with open(tmp_path, 'rb') as arquivo:
            return arquivo.read()
    finally:
        origem.close()
        try:
            destino.close()
        except sqlite3.Error:
            pass
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def validar_backup_sqlite(caminho):
    try:
        conn = sqlite3.connect(caminho)
        try:
            integridade = conn.execute('PRAGMA integrity_check').fetchone()[0]
            if integridade != 'ok':
                return False, f'Arquivo SQLite com falha de integridade: {integridade}'

            tabelas = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            obrigatorias = {'usuarios', 'agendamentos', 'logs'}
            faltando = sorted(obrigatorias - tabelas)
            if faltando:
                return False, 'Backup não parece ser deste sistema. Tabelas faltando: ' + ', '.join(faltando)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, f'Arquivo inválido para SQLite: {exc}'

    return True, ''


def salvar_backup_antes_da_restauracao(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    nome = f'antes_restauracao_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    caminho = os.path.join(backup_dir, nome)
    with open(caminho, 'wb') as arquivo:
        arquivo.write(criar_backup_sqlite_bytes(db_path))
    return caminho


def remover_arquivos_sqlite_auxiliares(db_path):
    for sufixo in ('-wal', '-shm'):
        caminho = db_path + sufixo
        try:
            if os.path.exists(caminho):
                os.remove(caminho)
        except OSError:
            pass


def limpar_backups_antigos(pasta, dias):
    if dias <= 0 or not os.path.isdir(pasta):
        return 0
    limite = datetime.now().timestamp() - (dias * 24 * 60 * 60)
    removidos = 0
    for nome in os.listdir(pasta):
        if not nome.startswith('backup_mapa_') or not nome.endswith('.db'):
            continue
        caminho = os.path.join(pasta, nome)
        try:
            if os.path.isfile(caminho) and os.path.getmtime(caminho) < limite:
                os.remove(caminho)
                removidos += 1
        except OSError:
            continue
    return removidos


def salvar_backup_automatico(db_path, backup_dir, retencao_dias):
    os.makedirs(backup_dir, exist_ok=True)
    nome = f'backup_mapa_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    caminho = os.path.join(backup_dir, nome)
    with open(caminho, 'wb') as arquivo:
        arquivo.write(criar_backup_sqlite_bytes(db_path))
    removidos = limpar_backups_antigos(backup_dir, retencao_dias)
    tamanho = os.path.getsize(caminho)
    return {
        'arquivo': caminho,
        'tamanho': tamanho,
        'antigos_removidos': removidos,
        'retencao_dias': retencao_dias,
    }
