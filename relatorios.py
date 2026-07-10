from datetime import datetime, timedelta


def coletar_painel_coordenacao(conn, hoje, dias, dias_pt):
    filtro_agendamento_ativo = (
        "((a.data_especifica IS NULL OR a.data_especifica = '') "
        "OR a.data_especifica >= ?)"
    )
    joins_aluno = (
        "LEFT JOIN usuarios aluno ON aluno.id = a.usuario_id "
        "LEFT JOIN usuarios aluno_nome ON aluno_nome.username = a.estagiario "
        "     AND aluno_nome.role='aluno' AND a.usuario_id IS NULL "
        "LEFT JOIN usuarios prof ON prof.id = COALESCE(aluno.supervisor_id, aluno_nome.supervisor_id)"
    )
    nome_aluno = "COALESCE(NULLIF(aluno.nome_completo, ''), aluno.username, NULLIF(aluno_nome.nome_completo, ''), aluno_nome.username, a.estagiario)"
    nome_supervisor = "COALESCE(NULLIF(prof.nome_completo, ''), prof.username, 'Sem supervisor')"

    total_alunos = conn.execute(
        "SELECT COUNT(*) FROM usuarios WHERE role='aluno' AND ativo=1"
    ).fetchone()[0]

    alunos_sem_paciente = conn.execute(
        """
        SELECT u.id, COALESCE(NULLIF(u.nome_completo, ''), u.username) AS aluno,
               COALESCE(NULLIF(p.nome_completo, ''), p.username, 'Sem supervisor') AS supervisor
        FROM usuarios u
        LEFT JOIN usuarios p ON p.id = u.supervisor_id
        WHERE u.role='aluno' AND u.ativo=1
          AND NOT EXISTS (
            SELECT 1
            FROM agendamentos a
            WHERE TRIM(COALESCE(a.paciente, '')) != ''
              AND COALESCE(a.status_atendimento, '') = ''
              AND ((a.usuario_id = u.id) OR (a.usuario_id IS NULL AND a.estagiario = u.username))
              AND ((a.data_especifica IS NULL OR a.data_especifica = '') OR a.data_especifica >= ?)
          )
        ORDER BY supervisor COLLATE NOCASE, aluno COLLATE NOCASE
        LIMIT 80
        """,
        (hoje,)
    ).fetchall()

    triagens_abertas = conn.execute(
        f"""
        SELECT a.id, a.dia_semana, a.horario, a.sala,
               {nome_aluno} AS aluno,
               {nome_supervisor} AS supervisor,
               a.categoria, a.data_especifica
        FROM agendamentos a
        {joins_aluno}
        WHERE a.triagem=1
          AND TRIM(COALESCE(a.paciente, '')) = ''
          AND COALESCE(a.status_atendimento, '') = ''
          AND {filtro_agendamento_ativo}
        ORDER BY supervisor COLLATE NOCASE, aluno COLLATE NOCASE, a.dia_semana, a.horario
        LIMIT 80
        """,
        (hoje,)
    ).fetchall()

    horarios_ociosos = conn.execute(
        f"""
        SELECT a.id, a.dia_semana, a.horario, a.sala,
               {nome_aluno} AS aluno,
               {nome_supervisor} AS supervisor,
               a.categoria, a.data_especifica
        FROM agendamentos a
        {joins_aluno}
        WHERE COALESCE(a.ocupa_sala, 0)=0
          AND TRIM(COALESCE(a.paciente, '')) = ''
          AND COALESCE(a.status_atendimento, '') = ''
          AND COALESCE(a.categoria, '') != 'NÃO MARCAR'
          AND {filtro_agendamento_ativo}
        ORDER BY a.dia_semana, a.horario, a.sala
        LIMIT 120
        """,
        (hoje,)
    ).fetchall()

    ocupacao_por_dia = conn.execute(
        """
        SELECT dia_semana, COUNT(*) AS total
        FROM agendamentos a
        WHERE COALESCE(a.ocupa_sala, 0)=1
          AND COALESCE(a.status_atendimento, '') = ''
          AND ((a.data_especifica IS NULL OR a.data_especifica = '') OR a.data_especifica >= ?)
        GROUP BY dia_semana
        """,
        (hoje,)
    ).fetchall()

    mapa_dias = {r['dia_semana']: r['total'] for r in ocupacao_por_dia}
    return {
        'total_alunos': total_alunos,
        'alunos_sem_paciente': [dict(r) for r in alunos_sem_paciente],
        'triagens_abertas': [dict(r) for r in triagens_abertas],
        'horarios_ociosos': [dict(r) for r in horarios_ociosos],
        'dias': [{'label': dias_pt.get(dia, dia), 'total': mapa_dias.get(dia, 0)} for dia in dias],
    }


def periodo_semana_atual():
    hoje_dt = datetime.now().date()
    inicio_dt = hoje_dt - timedelta(days=hoje_dt.weekday())
    fim_dt = inicio_dt + timedelta(days=6)
    return inicio_dt, fim_dt


def preparar_status_reservas(rows, label_status):
    return [{'status': label_status(r['status']), 'total': r['total']} for r in rows]


def coletar_relatorio_semanal(conn, inicio, fim, supervisor_id, listar_professores, dias, dias_pt, label_status):
    joins_supervisor = (
        " LEFT JOIN usuarios aluno ON aluno.id = a.usuario_id "
        " LEFT JOIN usuarios aluno_por_nome ON aluno_por_nome.username = a.estagiario "
        "      AND aluno_por_nome.role='aluno' AND a.usuario_id IS NULL "
        " LEFT JOIN usuarios prof ON prof.id = COALESCE(aluno.supervisor_id, aluno_por_nome.supervisor_id) "
    )
    filtro_supervisor = ''
    params_supervisor = []
    if supervisor_id:
        filtro_supervisor = " AND COALESCE(aluno.supervisor_id, aluno_por_nome.supervisor_id)=?"
        params_supervisor.append(supervisor_id)

    professores = listar_professores(conn)
    total_ocupados = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM agendamentos a
        {joins_supervisor}
        WHERE a.ocupa_sala=1
          AND (
            (a.data_especifica BETWEEN ? AND ?)
            OR (a.data_especifica IS NULL OR a.data_especifica='')
          )
          {filtro_supervisor}
        """,
        [inicio, fim] + params_supervisor
    ).fetchone()['total']
    pontuais = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM agendamentos a
        {joins_supervisor}
        WHERE a.ocupa_sala=1
          AND a.data_especifica BETWEEN ? AND ?
          {filtro_supervisor}
        """,
        [inicio, fim] + params_supervisor
    ).fetchone()['total']
    abertos = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM agendamentos a
        {joins_supervisor}
        WHERE (a.data_especifica IS NULL OR a.data_especifica='')
          AND TRIM(COALESCE(a.paciente, ''))=''
          AND (a.categoria='MARCAR' OR a.triagem=1)
          {filtro_supervisor}
        """,
        params_supervisor
    ).fetchone()['total']
    reservas_sala = conn.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM reservas
        WHERE tipo='sala' AND data_uso BETWEEN ? AND ?
        GROUP BY status
        """,
        (inicio, fim)
    ).fetchall()
    reservas_instrumento = conn.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM reservas
        WHERE tipo='instrumento' AND data_uso BETWEEN ? AND ?
        GROUP BY status
        """,
        (inicio, fim)
    ).fetchall()
    por_dia = conn.execute(
        f"""
        SELECT a.dia_semana, COUNT(*) AS total
        FROM agendamentos a
        {joins_supervisor}
        WHERE a.ocupa_sala=1
          {filtro_supervisor}
        GROUP BY a.dia_semana
        """,
        params_supervisor
    ).fetchall()
    por_supervisor = conn.execute(
        """
        SELECT COALESCE(NULLIF(prof.nome_completo, ''), prof.username, 'Sem supervisor') AS supervisor,
               COUNT(*) AS total
        FROM agendamentos a
        LEFT JOIN usuarios aluno ON aluno.id = a.usuario_id
        LEFT JOIN usuarios aluno_por_nome ON aluno_por_nome.username = a.estagiario
             AND aluno_por_nome.role='aluno' AND a.usuario_id IS NULL
        LEFT JOIN usuarios prof ON prof.id = COALESCE(aluno.supervisor_id, aluno_por_nome.supervisor_id)
        WHERE a.ocupa_sala=1
        GROUP BY supervisor
        ORDER BY total DESC, supervisor COLLATE NOCASE
        LIMIT 10
        """
    ).fetchall()

    mapa_dias = {r['dia_semana']: r['total'] for r in por_dia}
    dias_relatorio = [
        {'label': dias_pt.get(dia, dia.title()), 'total': mapa_dias.get(dia, 0)}
        for dia in dias
    ]
    return {
        'professores': professores,
        'total_ocupados': total_ocupados,
        'pontuais': pontuais,
        'abertos': abertos,
        'reservas_sala': preparar_status_reservas(reservas_sala, label_status),
        'reservas_instrumento': preparar_status_reservas(reservas_instrumento, label_status),
        'dias_relatorio': dias_relatorio,
        'por_supervisor': [dict(r) for r in por_supervisor],
    }
