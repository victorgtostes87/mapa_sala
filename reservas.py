import sqlite3
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user


def contar_reservas_pendentes(get_db):
    if not current_user.is_authenticated or current_user.role not in ('coordenador', 'recepcao'):
        return 0
    try:
        conn = get_db()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM reservas
                WHERE status='pendente'
                  AND (tipo!='sala' OR data_uso>=?)
                """,
                (datetime.now().strftime('%Y-%m-%d'),)
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
        return None, 'Reservas precisam ser feitas com não mínimo 24h de antecedência.'
    return inicio, None


def horarios_do_intervalo(horario_inicio, horario_fim, horarios):
    if horario_inicio not in horarios or horario_fim not in horarios:
        return None, 'Horário inválido.'
    ini = horarios.index(horario_inicio)
    fim = horarios.index(horario_fim)
    if fim <= ini:
        return None, 'O horário final deve ser depois do horário inicial.'
    return horarios[ini:fim], None


def candidatos_sala_reserva(tipo_sala, salas, salas_reservaveis, salas_com_computador):
    if tipo_sala == 'computador':
        return [s for s in salas_com_computador if s in salas]
    return [s for s in salas_reservaveis if s not in salas_com_computador]


def encontrar_sala_disponivel(
    data_uso,
    horario_inicio,
    horario_fim,
    tipo_sala,
    *,
    normalizar_data_especifica,
    dia_semana_da_data,
    checar_conflito,
    horarios,
    salas,
    salas_reservaveis,
    salas_com_computador,
):
    data_uso, erro_data = normalizar_data_especifica(data_uso)
    if erro_data:
        return None, erro_data
    slots, erro_horario = horarios_do_intervalo(horario_inicio, horario_fim, horarios)
    if erro_horario:
        return None, erro_horario

    dia = dia_semana_da_data(data_uso)
    for sala in candidatos_sala_reserva(tipo_sala, salas, salas_reservaveis, salas_com_computador):
        if all(not checar_conflito(dia, slot, sala, data_especifica=data_uso) for slot in slots):
            return sala, None
    return None, 'Não há sala disponível nesse período.'


def sala_disponivel_para_reserva(
    data_uso,
    horario_inicio,
    horario_fim,
    sala,
    *,
    normalizar_data_especifica,
    dia_semana_da_data,
    checar_conflito,
    horarios,
    salas_reservaveis,
):
    if sala not in salas_reservaveis:
        return False, 'Sala inválida para reserva.'

    data_uso, erro_data = normalizar_data_especifica(data_uso)
    if erro_data:
        return False, erro_data
    slots, erro_horario = horarios_do_intervalo(horario_inicio, horario_fim, horarios)
    if erro_horario:
        return False, erro_horario

    dia = dia_semana_da_data(data_uso)
    for slot in slots:
        if checar_conflito(dia, slot, sala, data_especifica=data_uso):
            return False, f'{sala} já está ocupada nesse período.'
    return True, None


def label_status_reserva(status):
    return {
        'pendente': 'Aguardando análise',
        'aprovada': 'Aprovada',
        'separado': 'Instrumento separado',
        'guardado': 'Guardado',
        'retirado': 'Retirado',
        'devolvido': 'Devolvido',
        'recusada': 'Recusada'
    }.get(status, status)


def preparar_reserva(row, candidatos_sala):
    r = dict(row)
    r['status_label'] = label_status_reserva(r.get('status'))
    r['tipo_label'] = 'Sala' if r.get('tipo') == 'sala' else 'Instrumento'
    r['tipo_sala_label'] = 'Sala com computador' if r.get('tipo_sala') == 'computador' else 'Sala comum'
    r['salas_aprovacao'] = candidatos_sala(r.get('tipo_sala')) if r.get('tipo') == 'sala' else []
    try:
        r['data_label'] = datetime.strptime(r['data_uso'], '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        r['data_label'] = r.get('data_uso') or ''
    return r


def ids_agendamentos_reserva(reserva):
    ids = []
    reserva_dict = dict(reserva)
    for valor in str(reserva_dict.get('agendamento_ids') or '').split(','):
        valor = valor.strip()
        if not valor:
            continue
        try:
            ids.append(int(valor))
        except ValueError:
            continue
    return ids


def registrar_rotas_reservas(app, deps):
    get_db = deps['get_db']
    login_required = deps['login_required']
    requer_papel = deps['requer_papel']
    data_hoje_iso = deps['data_hoje_iso']
    normalizar_data_especifica = deps['normalizar_data_especifica']
    dia_semana_da_data = deps['dia_semana_da_data']
    checar_conflito = deps['checar_conflito']
    inserir_agendamento = deps['inserir_agendamento']
    detect_sem = deps['detect_sem']
    registrar_log = deps['registrar_log']
    notificar_reserva_email = deps.get('notificar_reserva_email')
    notificar_reserva_solicitada_email = deps.get('notificar_reserva_solicitada_email')
    horarios = deps['HORARIOS']
    salas = deps['SALAS']
    salas_reservaveis = deps['SALAS_RESERVAVEIS']
    salas_com_computador = deps['SALAS_COM_COMPUTADOR']
    papeis_label = deps['PAPEIS_LABEL']

    def candidatos_sala(tipo_sala):
        return candidatos_sala_reserva(tipo_sala, salas, salas_reservaveis, salas_com_computador)

    def encontrar_sala(data_uso, horario_inicio, horario_fim, tipo_sala):
        return encontrar_sala_disponivel(
            data_uso,
            horario_inicio,
            horario_fim,
            tipo_sala,
            normalizar_data_especifica=normalizar_data_especifica,
            dia_semana_da_data=dia_semana_da_data,
            checar_conflito=checar_conflito,
            horarios=horarios,
            salas=salas,
            salas_reservaveis=salas_reservaveis,
            salas_com_computador=salas_com_computador,
        )

    def sala_disponivel(data_uso, horario_inicio, horario_fim, sala):
        return sala_disponivel_para_reserva(
            data_uso,
            horario_inicio,
            horario_fim,
            sala,
            normalizar_data_especifica=normalizar_data_especifica,
            dia_semana_da_data=dia_semana_da_data,
            checar_conflito=checar_conflito,
            horarios=horarios,
            salas_reservaveis=salas_reservaveis,
        )

    reserva_select = """
        SELECT r.*,
               COALESCE(NULLIF(p.nome_completo, ''), p.username, '') AS supervisor_nome
        FROM reservas r
        LEFT JOIN usuarios u ON u.id = r.usuario_id
        LEFT JOIN usuarios p ON p.id = u.supervisor_id
    """

    def limpar_salas_vencidas(conn):
        vencidas = conn.execute(
            """
            SELECT *
            FROM reservas
            WHERE tipo='sala'
              AND data_uso < ?
            """,
            (data_hoje_iso(),)
        ).fetchall()
        total = 0
        for reserva in vencidas:
            ids = ids_agendamentos_reserva(reserva)
            if ids:
                placeholders = ','.join('?' for _ in ids)
                conn.execute(f'DELETE FROM agendamentos WHERE id IN ({placeholders})', ids)
            conn.execute('DELETE FROM reservas WHERE id=?', (reserva['id'],))
            total += 1
        return total

    @app.route('/reservas')
    @login_required
    def reservas():
        conn = get_db()
        try:
            removidas = limpar_salas_vencidas(conn)
            if removidas:
                conn.commit()
            if current_user.role == 'aluno':
                rows = conn.execute(
                    reserva_select + """
                    WHERE r.usuario_id=?
                      AND (r.tipo!='sala' OR r.data_uso>=?)
                    ORDER BY
                      CASE r.status WHEN 'pendente' THEN 1 WHEN 'aprovada' THEN 2 ELSE 3 END,
                      r.data_uso,
                      r.horario_inicio
                    """,
                    (current_user.id, data_hoje_iso())
                ).fetchall()
                pendentes = []
            elif current_user.role in ('coordenador', 'recepcao'):
                pendentes = conn.execute(
                    reserva_select + """
                    WHERE r.status='pendente'
                      AND (r.tipo!='sala' OR r.data_uso>=?)
                    ORDER BY r.created_at, r.data_uso, r.horario_inicio
                    """,
                    (data_hoje_iso(),)
                ).fetchall()
                rows = conn.execute(
                    reserva_select + """
                    WHERE r.status!='pendente'
                      AND (r.tipo!='sala' OR r.data_uso>=?)
                    ORDER BY r.updated_at DESC
                    """,
                    (data_hoje_iso(),)
                ).fetchall()
            else:
                flash('Acesso negado.', 'error')
                return redirect(url_for('index'))

            caderno_rows = conn.execute(
                reserva_select + """
                WHERE r.tipo='instrumento'
                  AND r.status!='recusada'
                  AND r.status!='guardado'
                  AND r.status!='retirado'
                  AND r.status!='devolvido'
                  AND r.data_uso>=?
                ORDER BY r.data_uso, r.horario_inicio, r.usuario
                """,
                (data_hoje_iso(),)
            ).fetchall()
        finally:
            conn.close()

        minhas_reservas = [preparar_reserva(r, candidatos_sala) for r in rows]
        pendentes = [preparar_reserva(r, candidatos_sala) for r in pendentes]
        caderno_instrumentos = [preparar_reserva(r, candidatos_sala) for r in caderno_rows]
        aprovadas_sala = [
            r for r in minhas_reservas
            if r.get('tipo') == 'sala' and r.get('status') == 'aprovada'
        ]
        aprovadas_instrumentos = [
            r for r in minhas_reservas
            if r.get('tipo') == 'instrumento' and r.get('status') in ('aprovada', 'separado', 'retirado', 'devolvido', 'guardado')
        ]

        return render_template(
            'reservas.html',
            usuario=current_user.username,
            papel=current_user.role,
            papel_label=papeis_label.get(current_user.role, current_user.role),
            horarios=horarios,
            minhas_reservas=minhas_reservas,
            minhas_salas=[r for r in minhas_reservas if r.get('tipo') == 'sala'],
            minhas_instrumentos=[r for r in minhas_reservas if r.get('tipo') == 'instrumento'],
            pendentes=pendentes,
            pendentes_sala=[r for r in pendentes if r.get('tipo') == 'sala'],
            pendentes_instrumento=[r for r in pendentes if r.get('tipo') == 'instrumento'],
            recusadas_sala=[r for r in minhas_reservas if r.get('tipo') == 'sala' and r.get('status') == 'recusada'],
            recusadas_instrumento=[r for r in minhas_reservas if r.get('tipo') == 'instrumento' and r.get('status') == 'recusada'],
            caderno_instrumentos=caderno_instrumentos,
            recentes_sala=[r for r in minhas_reservas if r.get('tipo') == 'sala'],
            recentes_instrumento=[r for r in minhas_reservas if r.get('tipo') == 'instrumento'],
            aprovadas_sala=aprovadas_sala,
            aprovadas_instrumentos=aprovadas_instrumentos,
        )

    @app.route('/reservas/limpar-salas-vencidas', methods=['POST'])
    @login_required
    @requer_papel('coordenador', 'recepcao')
    def limpar_salas_vencidas_manual():
        conn = get_db()
        try:
            removidas = limpar_salas_vencidas(conn)
            conn.commit()
        finally:
            conn.close()

        registrar_log('LIMPAR_RESERVAS_SALA_VENCIDAS', f'{removidas} reserva(s) de sala vencida(s) removida(s)')
        if removidas:
            flash(f'{removidas} reserva(s) de sala vencida(s) removida(s).', 'success')
        else:
            flash('Não havia reservas de sala vencidas para limpar.', 'success')
        return redirect(url_for('reservas'))

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
        _, erro_intervalo = horarios_do_intervalo(horario_inicio, horario_fim, horarios)
        if erro_intervalo:
            flash(erro_intervalo, 'error')
            return redirect(url_for('reservas'))

        sala_sugerida, erro_sala = encontrar_sala(data_uso, horario_inicio, horario_fim, tipo_sala)
        if erro_sala:
            flash(erro_sala, 'error')
            return redirect(url_for('reservas'))

        reserva_email = None
        conn = get_db()
        try:
            cur = conn.execute(
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
            reserva_email = {
                'id': cur.lastrowid,
                'usuario_id': current_user.id,
                'usuario': current_user.username,
                'tipo': 'sala',
                'data_uso': data_uso,
                'horario_inicio': horario_inicio,
                'horario_fim': horario_fim,
                'tipo_sala': tipo_sala,
                'sala_atribuida': sala_sugerida,
                'finalidade': finalidade,
                'observacao': observacao,
            }
            conn.commit()
        finally:
            conn.close()

        registrar_log('SOLICITAR_RESERVA_SALA', f'{current_user.username} solicitou {tipo_sala} em {data_uso} {horario_inicio}-{horario_fim}')
        if callable(notificar_reserva_solicitada_email):
            notificar_reserva_solicitada_email(reserva_email)
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

        reserva_email = None
        conn = get_db()
        try:
            cur = conn.execute(
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
            reserva_email = {
                'id': cur.lastrowid,
                'usuario_id': current_user.id,
                'usuario': current_user.username,
                'tipo': 'instrumento',
                'data_uso': data_uso,
                'horario_inicio': horario_inicio,
                'instrumento': instrumento,
                'finalidade': finalidade,
                'observacao': observacao,
            }
            conn.commit()
        finally:
            conn.close()

        registrar_log('SOLICITAR_RESERVA_INSTRUMENTO', f'{current_user.username} solicitou {instrumento} em {data_uso} {horario_inicio}')
        if callable(notificar_reserva_solicitada_email):
            notificar_reserva_solicitada_email(reserva_email)
        flash('Solicitação de instrumento enviada.', 'success')
        return redirect(url_for('reservas'))

    @app.route('/reservas/<int:rid>/aprovar', methods=['POST'])
    @login_required
    @requer_papel('coordenador', 'recepcao')
    def aprovar_reserva(rid):
        resposta = request.form.get('resposta', '').strip()
        sala_escolhida = request.form.get('sala_atribuida', '').strip()
        conn = get_db()
        reserva_email = None
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
                    if sala_escolhida not in candidatos_sala(reserva['tipo_sala']):
                        flash('A sala escolhida não combina com o tipo solicitado.', 'error')
                        return redirect(url_for('reservas'))
                    disponivel, erro_sala = sala_disponivel(
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
                    sala_atribuida, erro_sala = encontrar_sala(
                        reserva['data_uso'],
                        reserva['horario_inicio'],
                        reserva['horario_fim'],
                        reserva['tipo_sala']
                    )
                    if erro_sala:
                        flash(erro_sala, 'error')
                        return redirect(url_for('reservas'))

                dia = dia_semana_da_data(reserva['data_uso'])
                slots, _ = horarios_do_intervalo(reserva['horario_inicio'], reserva['horario_fim'], horarios)
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
            reserva_email = dict(reserva)
            reserva_email['sala_atribuida'] = sala_atribuida
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('No foi possvel aprovar: a sala ficou ocupada por outro agendamento.', 'error')
            return redirect(url_for('reservas'))
        finally:
            conn.close()

        registrar_log('APROVAR_RESERVA', f'Reserva #{rid} aprovada por {current_user.username}')
        if callable(notificar_reserva_email):
            notificar_reserva_email(reserva_email, 'aprovada', resposta)
        flash('Reserva aprovada.', 'success')
        return redirect(url_for('reservas'))

    @app.route('/reservas/<int:rid>/recusar', methods=['POST'])
    @login_required
    @requer_papel('coordenador', 'recepcao')
    def recusar_reserva(rid):
        resposta = request.form.get('resposta', '').strip()
        conn = get_db()
        reserva_email = None
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
            reserva_email = dict(reserva)
            conn.commit()
        finally:
            conn.close()

        registrar_log('RECUSAR_RESERVA', f'Reserva #{rid} recusada por {current_user.username}')
        if callable(notificar_reserva_email):
            notificar_reserva_email(reserva_email, 'recusada', resposta)
        flash('Reserva recusada.', 'success')
        return redirect(url_for('reservas'))

    @app.route('/reservas/<int:rid>/reabrir', methods=['POST'])
    @login_required
    @requer_papel('coordenador', 'recepcao')
    def reabrir_reserva(rid):
        conn = get_db()
        try:
            reserva = conn.execute("SELECT * FROM reservas WHERE id=?", (rid,)).fetchone()
            if not reserva:
                flash('Reserva não encontrada.', 'error')
                return redirect(url_for('reservas'))
            if reserva['status'] == 'pendente':
                flash('Esta reserva já está pendente.', 'error')
                return redirect(url_for('reservas'))

            if reserva['tipo'] == 'sala':
                ids = ids_agendamentos_reserva(reserva)
                if ids:
                    placeholders = ','.join('?' for _ in ids)
                    conn.execute(f'DELETE FROM agendamentos WHERE id IN ({placeholders})', ids)

            conn.execute(
                """
                UPDATE reservas
                SET status='pendente', resposta='', agendamento_ids='',
                    analisado_por=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (current_user.username, rid)
            )
            conn.commit()
        finally:
            conn.close()

        registrar_log('REABRIR_RESERVA', f'Reserva #{rid} reaberta por {current_user.username}')
        flash('Reserva reaberta para correção. Ela voltou para a lista de pendentes.', 'success')
        return redirect(url_for('reservas'))

    @app.route('/reservas/<int:rid>/corrigir-sala', methods=['POST'])
    @login_required
    @requer_papel('coordenador', 'recepcao')
    def corrigir_reserva_sala(rid):
        acao = request.form.get('acao', '').strip()
        if acao not in ('pendente', 'recusada'):
            flash('Escolha o que deseja corrigir na reserva de sala.', 'error')
            return redirect(url_for('reservas'))

        conn = get_db()
        try:
            reserva = conn.execute("SELECT * FROM reservas WHERE id=?", (rid,)).fetchone()
            if not reserva or reserva['tipo'] != 'sala':
                flash('Reserva de sala não encontrada.', 'error')
                return redirect(url_for('reservas'))

            ids = ids_agendamentos_reserva(reserva)
            if ids:
                placeholders = ','.join('?' for _ in ids)
                conn.execute(f'DELETE FROM agendamentos WHERE id IN ({placeholders})', ids)

            if acao == 'pendente':
                conn.execute(
                    """
                    UPDATE reservas
                    SET status='pendente', resposta='', agendamento_ids='',
                        analisado_por=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (current_user.username, rid)
                )
                mensagem = 'Reserva voltou para pendentes.'
            else:
                conn.execute(
                    """
                    UPDATE reservas
                    SET status='recusada', agendamento_ids='',
                        analisado_por=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (current_user.username, rid)
                )
                mensagem = 'Reserva marcada como recusada.'

            conn.commit()
        finally:
            conn.close()

        registrar_log('CORRIGIR_RESERVA_SALA', f'Reserva #{rid} ajustada para {acao} por {current_user.username}')
        flash(mensagem, 'success')
        return redirect(url_for('reservas'))

    @app.route('/reservas/<int:rid>/status', methods=['POST'])
    @login_required
    @requer_papel('coordenador', 'recepcao')
    def atualizar_status_reserva(rid):
        novo_status = request.form.get('status', '').strip()
        status_validos = ('pendente', 'aprovada', 'separado', 'retirado', 'devolvido', 'guardado', 'recusada')
        if novo_status not in status_validos:
            flash('Status inválido.', 'error')
            return redirect(url_for('reservas'))

        reserva_email = None
        conn = get_db()
        try:
            reserva = conn.execute("SELECT * FROM reservas WHERE id=?", (rid,)).fetchone()
            if not reserva or reserva['tipo'] != 'instrumento':
                flash('Reserva de instrumento não encontrada.', 'error')
                return redirect(url_for('reservas'))
            conn.execute(
                """
                UPDATE reservas
                SET status=?, analisado_por=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (novo_status, current_user.username, rid)
            )
            reserva_email = dict(reserva)
            reserva_email['status'] = novo_status
            conn.commit()
        finally:
            conn.close()

        registrar_log('STATUS_RESERVA_INSTRUMENTO', f'Reserva #{rid} marcada como {novo_status} por {current_user.username}')
        if callable(notificar_reserva_email):
            notificar_reserva_email(reserva_email, novo_status)
        flash('Status do instrumento atualizado.', 'success')
        return redirect(url_for('reservas'))
