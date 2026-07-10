def coletar_saude_sistema(conn, versao, smtp):
    integridade = conn.execute('PRAGMA integrity_check').fetchone()[0]
    ultimo_backup = conn.execute(
        "SELECT ts, usuario, dados FROM historico WHERE acao='BACKUP' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    migrations = conn.execute(
        'SELECT version, description, applied_at FROM schema_migrations ORDER BY applied_at DESC, version DESC'
    ).fetchall()
    return {
        'versao': versao,
        'banco_ok': integridade == 'ok',
        'integridade': integridade,
        'usuarios_total': conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0],
        'usuarios_ativos': conn.execute('SELECT COUNT(*) FROM usuarios WHERE ativo=1').fetchone()[0],
        'agendamentos_total': conn.execute('SELECT COUNT(*) FROM agendamentos').fetchone()[0],
        'reservas_pendentes': conn.execute("SELECT COUNT(*) FROM reservas WHERE status='pendente'").fetchone()[0],
        'logs_total': conn.execute('SELECT COUNT(*) FROM historico').fetchone()[0],
        'ultimo_backup': dict(ultimo_backup) if ultimo_backup else None,
        'migrations': [dict(row) for row in migrations],
        'smtp': smtp,
    }


def executar_manutencao(conn, limpar_logs, vacuum=False):
    integridade = conn.execute('PRAGMA integrity_check').fetchone()[0]
    logs_removidos = limpar_logs(conn)
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
