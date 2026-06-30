import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ['SECRET_KEY'] = 'chave-de-teste-com-tamanho-suficiente-123'
_tmpdir = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = os.path.join(_tmpdir.name, 'mapa_salas_teste.db')

import app as mapa  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


class MapaSalasTestCase(unittest.TestCase):
    def setUp(self):
        mapa.app.config['TESTING'] = True
        mapa.app.config['RATELIMIT_ENABLED'] = False
        self.client = mapa.app.test_client()
        self.csrf = 'csrf-de-teste'

        mapa.init_db()
        conn = mapa.get_db()
        try:
            tabelas = {
                row['name']
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            conn.execute('DELETE FROM agendamentos')
            conn.execute('DELETE FROM historico')
            if 'reservas' in tabelas:
                conn.execute('DELETE FROM reservas')
            if 'tarefas_painel' in tabelas:
                conn.execute('DELETE FROM tarefas_painel')
            conn.execute('DELETE FROM usuarios')
            self.coord_id = self._criar_usuario(conn, 'coordenador', 'coordenador')
            self.recepcao_id = self._criar_usuario(conn, 'recepcao', 'recepcao')
            self.professor_id = self._criar_usuario(conn, 'professor1', 'professor')
            self.aluno1_id = self._criar_usuario(conn, 'aluno1', 'aluno')
            self.aluno2_id = self._criar_usuario(conn, 'aluno2', 'aluno')
            conn.execute('UPDATE usuarios SET supervisor_id=? WHERE id=?', (self.professor_id, self.aluno1_id))
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.client.get('/logout')

    def _criar_usuario(self, conn, username, role):
        cur = conn.execute(
            'INSERT INTO usuarios(username, password_hash, role, ativo) VALUES(?,?,?,1)',
            (username, generate_password_hash('senha123'), role)
        )
        return cur.lastrowid

    def _login(self, username):
        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT id FROM usuarios WHERE username=?', (username,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = self.csrf
            sess['_user_id'] = str(row['id'])
            sess['_fresh'] = True
        return self.client.get('/')

    def _criar_agendamento_api(self, estagiario='aluno1', sala='Consultório 1'):
        return self.client.post(
            '/api/agendamentos',
            json={
                'dia_semana': 'SEGUNDA',
                'horario': '08:00',
                'sala': sala,
                'estagiario': estagiario,
                'paciente': 'Paciente Teste',
                'categoria': 'ESTAGIÁRIO 9°'
            },
            headers={'X-CSRFToken': self.csrf}
        )

    def _proxima_data_util(self, weekday):
        data = datetime.now().date()
        while data.weekday() != weekday:
            data += timedelta(days=1)
        return data.strftime('%Y-%m-%d')

    def _data_util_com_antecedencia(self):
        data = datetime.now().date() + timedelta(days=3)
        while data.weekday() >= 5:
            data += timedelta(days=1)
        return data.strftime('%Y-%m-%d')

    def test_recepcao_cria_agendamento_vinculado_ao_aluno(self):
        self._login('recepcao')

        resp = self._criar_agendamento_api(estagiario='aluno1')

        self.assertEqual(resp.status_code, 201)
        ag_id = resp.get_json()['id']

        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT usuario_id FROM agendamentos WHERE id=?', (ag_id,)).fetchone()
        finally:
            conn.close()

        self.assertEqual(row['usuario_id'], self.aluno1_id)

        self.client.get('/logout')
        self._login('aluno1')
        resp = self.client.get('/api/agendamentos?dia_semana=SEGUNDA')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()), 1)

    def test_aluno_entra_na_tela_de_meus_agendamentos(self):
        resp = self._login('aluno1')

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/meus-agendamentos', resp.headers['Location'])

    def test_recepcao_entra_no_painel_inicial(self):
        resp = self._login('recepcao')

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/painel', resp.headers['Location'])

        painel = self.client.get('/painel')
        html = painel.get_data(as_text=True)

        self.assertEqual(painel.status_code, 200)
        self.assertIn('Painel da recepção', html)
        self.assertIn('Testes e instrumentos', html)

    def test_recepcao_nao_acessa_mapa(self):
        self._login('recepcao')

        resp = self.client.get('/mapa')

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/painel', resp.headers['Location'])

    def test_coordenador_exclui_usuario_criado_por_engano(self):
        conn = mapa.get_db()
        try:
            usuario_id = self._criar_usuario(conn, 'cadastro_errado', 'aluno')
            conn.commit()
        finally:
            conn.close()

        self._login('coordenador')
        resp = self.client.delete(
            f'/api/usuarios/{usuario_id}/excluir-definitivo',
            headers={'X-CSRFToken': self.csrf}
        )

        self.assertEqual(resp.status_code, 200)
        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT * FROM usuarios WHERE id=?', (usuario_id,)).fetchone()
        finally:
            conn.close()

        self.assertIsNone(row)

    def test_professor_entra_na_tela_de_supervisao(self):
        resp = self._login('professor1')

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/minha-supervisao', resp.headers['Location'])

    def test_professor_ve_somente_alunos_supervisionados(self):
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '08:00',
                'sala': 'Consultório 1',
                'estagiario': 'aluno1',
                'paciente': 'Paciente Supervisionado',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': self.aluno1_id
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'TERÇA',
                'horario': '09:00',
                'sala': 'Consultório 2',
                'estagiario': 'aluno2',
                'paciente': 'Paciente De Outro Professor',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': self.aluno2_id
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'QUARTA',
                'horario': '10:00',
                'sala': 'Consultório 3',
                'estagiario': 'aluno1',
                'paciente': '',
                'categoria': 'MARCAR',
                'semestre': 10,
                'triagem': 1,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': self.aluno1_id
            })
            conn.commit()
        finally:
            conn.close()

        self._login('professor1')
        resp = self.client.get('/minha-supervisao')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Minha supervisão', html)
        self.assertIn('aluno1', html)
        self.assertIn('Paciente Supervisionado', html)
        self.assertIn('Triagem aberta', html)
        self.assertNotIn('aluno2', html)
        self.assertNotIn('Paciente De Outro Professor', html)

    def test_recepcao_cria_e_conclui_afazer_compartilhado(self):
        self._login('recepcao')

        criar = self.client.post(
            '/painel/tarefas',
            data={
                'csrf_token': self.csrf,
                'titulo': 'Separar teste HTP',
                'detalhe': 'Aluno retira às 14h'
            }
        )
        self.assertEqual(criar.status_code, 302)

        conn = mapa.get_db()
        try:
            tarefa = conn.execute('SELECT * FROM tarefas_painel').fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(tarefa)

        tela = self.client.get('/afazeres')
        html = tela.get_data(as_text=True)

        self.assertEqual(tela.status_code, 200)
        self.assertIn('Afazeres da recepção', html)
        self.assertIn('Separar teste HTP', html)

        concluir = self.client.post(
            f'/painel/tarefas/{tarefa["id"]}/concluir',
            data={'csrf_token': self.csrf}
        )
        self.assertEqual(concluir.status_code, 302)

        conn = mapa.get_db()
        try:
            total = conn.execute('SELECT COUNT(*) AS total FROM tarefas_painel').fetchone()['total']
        finally:
            conn.close()

        self.assertEqual(total, 0)

    def test_horarios_abertos_lista_marcar_e_triagem_sem_paciente(self):
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '15:00',
                'sala': 'Consultório 2',
                'estagiario': 'aluno1',
                'paciente': '',
                'categoria': 'MARCAR',
                'semestre': 10,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'TERÇA',
                'horario': '16:00',
                'sala': 'Consultório 3',
                'estagiario': 'aluno2',
                'paciente': '',
                'categoria': 'ESTAGIÁRIO 10°',
                'semestre': 10,
                'triagem': 1,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('coordenador')
        resp = self.client.get('/horarios-abertos')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Horários abertos sem paciente', html)
        self.assertIn('Aberto para paciente', html)
        self.assertIn('Triagem livre', html)

        self._login('recepcao')
        resp_recepcao = self.client.get('/horarios-abertos')

        self.assertEqual(resp_recepcao.status_code, 200)
        self.assertIn('Horários abertos sem paciente', resp_recepcao.get_data(as_text=True))

    def test_relatorio_semanal_mostra_resumo(self):
        data_uso = self._data_util_com_antecedencia()
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '08:00',
                'sala': 'Consultório 1',
                'estagiario': 'aluno1',
                'paciente': 'Paciente',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'instrumento', data_uso, '10:00', 'HTP', 'Avaliação')
            )
            conn.commit()
        finally:
            conn.close()

        self._login('coordenador')
        resp = self.client.get('/relatorio-semanal')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Relatório semanal simples', html)
        self.assertIn('Instrumentos', html)

    def test_tela_meus_agendamentos_mostra_somente_do_aluno(self):
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '08:00',
                'sala': 'Consultório 1',
                'estagiario': 'aluno1',
                'paciente': 'Paciente Do Aluno',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '09:00',
                'sala': 'Consultório 2',
                'estagiario': 'aluno2',
                'paciente': 'Paciente De Outro Aluno',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('aluno1')
        resp = self.client.get('/meus-agendamentos')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Paciente Do Aluno', html)
        self.assertNotIn('Paciente De Outro Aluno', html)

    def test_tela_aluno_separa_fixos_de_pacientes_marcados(self):
        data_segunda = self._proxima_data_util(0)
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '14:00',
                'sala': 'Consultório 1',
                'estagiario': 'aluno1',
                'paciente': 'Paciente Fixo',
                'categoria': 'ESTAGIÁRIO 10°',
                'semestre': 10,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '15:00',
                'sala': 'Consultório 2',
                'estagiario': 'aluno1',
                'paciente': '',
                'categoria': 'ESTAGIÁRIO 10°',
                'semestre': 10,
                'triagem': 1,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '15:00',
                'sala': 'Consultório 2',
                'estagiario': 'aluno1',
                'paciente': 'Triagem Marcada',
                'categoria': 'ESTAGIÁRIO 10°',
                'semestre': 10,
                'triagem': 1,
                'observacao': '',
                'data_especifica': data_segunda,
                'usuario_id': None
            })
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '16:00',
                'sala': 'Consultório 3',
                'estagiario': 'aluno1',
                'paciente': '',
                'categoria': 'ESTAGIÁRIO 10°',
                'semestre': 10,
                'triagem': 1,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('aluno1')
        resp = self.client.get('/meus-agendamentos')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Tenho paciente marcado', html)
        self.assertIn('Tenho horário aberto sem paciente', html)
        self.assertIn('Você tem triagem livre ainda sem paciente marcado.', html)
        self.assertIn('Fixos sem paciente', html)
        self.assertIn('Paciente Fixo', html)
        self.assertIn('Triagem Marcada', html)
        self.assertIn('Triagem sem paciente marcado', html)
        self.assertIn('Consultório 3', html)
        self.assertEqual(html.count('Triagem sem paciente marcado'), 1)

    def test_tela_aluno_mostra_horario_aberto_sem_paciente(self):
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '17:00',
                'sala': 'Consultório 4',
                'estagiario': 'aluno1',
                'paciente': '',
                'categoria': 'MARCAR',
                'semestre': 10,
                'triagem': 0,
                'observacao': 'Professor liberou para paciente',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('aluno1')
        resp = self.client.get('/meus-agendamentos')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Horário aberto sem paciente', html)
        self.assertIn('Professor liberou para paciente', html)

    def test_aluno_solicita_reserva_de_instrumento(self):
        data_uso = self._data_util_com_antecedencia()
        self._login('aluno1')

        resp = self.client.post(
            '/reservas/instrumento',
            data={
                'csrf_token': self.csrf,
                'data_uso': data_uso,
                'horario_inicio': '08:00',
                'instrumento': 'HTP',
                'finalidade': 'Avaliação psicológica',
                'observacao': 'Uso em supervisão'
            }
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            row = conn.execute("SELECT * FROM reservas WHERE tipo='instrumento'").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row['status'], 'pendente')
        self.assertEqual(row['instrumento'], 'HTP')

    def test_aluno_solicita_reserva_de_sala_com_sugestao(self):
        data_uso = self._data_util_com_antecedencia()
        self._login('aluno1')

        resp = self.client.post(
            '/reservas/sala',
            data={
                'csrf_token': self.csrf,
                'data_uso': data_uso,
                'horario_inicio': '08:00',
                'horario_fim': '09:00',
                'tipo_sala': 'comum',
                'finalidade': 'Estudo',
                'observacao': ''
            }
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            row = conn.execute("SELECT * FROM reservas WHERE tipo='sala'").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row['status'], 'pendente')
        self.assertEqual(row['usuario_id'], self.aluno1_id)
        self.assertNotIn(row['sala_atribuida'], mapa.SALAS_COM_COMPUTADOR)

    def test_reserva_de_sala_bloqueia_menos_de_24h(self):
        self._login('aluno1')
        hoje = datetime.now().strftime('%Y-%m-%d')

        resp = self.client.post(
            '/reservas/sala',
            data={
                'csrf_token': self.csrf,
                'data_uso': hoje,
                'horario_inicio': '08:00',
                'horario_fim': '09:00',
                'tipo_sala': 'comum',
                'finalidade': 'Estudo',
                'observacao': ''
            }
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            total = conn.execute("SELECT COUNT(*) AS total FROM reservas WHERE tipo='sala'").fetchone()['total']
        finally:
            conn.close()

        self.assertEqual(total, 0)

    def test_reserva_de_sala_bloqueia_intervalo_invalido(self):
        data_uso = self._data_util_com_antecedencia()
        self._login('aluno1')

        resp = self.client.post(
            '/reservas/sala',
            data={
                'csrf_token': self.csrf,
                'data_uso': data_uso,
                'horario_inicio': '10:00',
                'horario_fim': '09:00',
                'tipo_sala': 'comum',
                'finalidade': 'Estudo',
                'observacao': ''
            }
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            total = conn.execute("SELECT COUNT(*) AS total FROM reservas WHERE tipo='sala'").fetchone()['total']
        finally:
            conn.close()

        self.assertEqual(total, 0)

    def test_coordenador_nao_cria_reserva_como_aluno(self):
        data_uso = self._data_util_com_antecedencia()
        self._login('coordenador')

        resp = self.client.post(
            '/reservas/sala',
            data={
                'csrf_token': self.csrf,
                'data_uso': data_uso,
                'horario_inicio': '08:00',
                'horario_fim': '09:00',
                'tipo_sala': 'comum',
                'finalidade': 'Estudo',
                'observacao': ''
            }
        )

        self.assertEqual(resp.status_code, 403)

    def test_recepcao_ve_reservas_separadas_por_tipo(self):
        data_uso = self._data_util_com_antecedencia()
        conn = mapa.get_db()
        try:
            conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, data_uso, horario_inicio, horario_fim, tipo_sala, sala_atribuida, finalidade)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'sala', data_uso, '08:00', '09:00', 'comum', 'Consultório 1', 'Estudo')
            )
            conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'instrumento', data_uso, '10:00', 'HTP', 'Avaliação')
            )
            conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, status, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (self.aluno2_id, 'aluno2', 'instrumento', 'aprovada', data_uso, '11:00', 'WISC', 'Avaliação')
            )
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.get('/reservas')
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Reservas de sala pendentes', html)
        self.assertIn('Reservas de testes e instrumentos', html)
        self.assertIn('HTP', html)
        self.assertIn('WISC', html)

    def test_recepcao_atualiza_status_do_caderno_de_instrumentos(self):
        data_uso = self._data_util_com_antecedencia()
        conn = mapa.get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, status, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'instrumento', 'aprovada', data_uso, '09:00', 'HTP', 'Avaliação')
            )
            reserva_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.post(
            f'/reservas/{reserva_id}/status',
            data={'csrf_token': self.csrf, 'status': 'separado'}
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT status FROM reservas WHERE id=?', (reserva_id,)).fetchone()
        finally:
            conn.close()

        self.assertEqual(row['status'], 'separado')

        resp = self.client.post(
            f'/reservas/{reserva_id}/status',
            data={'csrf_token': self.csrf, 'status': 'guardado'}
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT status FROM reservas WHERE id=?', (reserva_id,)).fetchone()
        finally:
            conn.close()

        self.assertEqual(row['status'], 'guardado')

    def test_status_invalido_de_instrumento_nao_altera_reserva(self):
        data_uso = self._data_util_com_antecedencia()
        conn = mapa.get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, status, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'instrumento', 'aprovada', data_uso, '09:00', 'HTP', 'Avaliacao')
            )
            reserva_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.post(
            f'/reservas/{reserva_id}/status',
            data={'csrf_token': self.csrf, 'status': 'perdido'}
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT status FROM reservas WHERE id=?', (reserva_id,)).fetchone()
        finally:
            conn.close()

        self.assertEqual(row['status'], 'aprovada')

    def test_aprovar_reserva_de_sala_cria_agendamentos_no_mapa(self):
        data_uso = self._data_util_com_antecedencia()
        self._login('aluno1')
        criar = self.client.post(
            '/reservas/sala',
            data={
                'csrf_token': self.csrf,
                'data_uso': data_uso,
                'horario_inicio': '14:00',
                'horario_fim': '16:00',
                'tipo_sala': 'comum',
                'finalidade': 'Estudo de prontuário',
                'observacao': ''
            }
        )
        self.assertEqual(criar.status_code, 302)

        conn = mapa.get_db()
        try:
            reserva = conn.execute("SELECT * FROM reservas WHERE tipo='sala'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(reserva)

        self.client.get('/logout')
        self._login('recepcao')
        aprovar = self.client.post(
            f'/reservas/{reserva["id"]}/aprovar',
            data={'csrf_token': self.csrf, 'resposta': 'Aprovado'}
        )
        self.assertEqual(aprovar.status_code, 302)

        conn = mapa.get_db()
        try:
            reserva_atualizada = conn.execute('SELECT * FROM reservas WHERE id=?', (reserva['id'],)).fetchone()
            total_agendamentos = conn.execute(
                'SELECT COUNT(*) AS total FROM agendamentos WHERE data_especifica=? AND usuario_id=?',
                (data_uso, self.aluno1_id)
            ).fetchone()['total']
        finally:
            conn.close()

        self.assertEqual(reserva_atualizada['status'], 'aprovada')
        self.assertEqual(total_agendamentos, 2)

    def test_aprovar_reserva_permite_escolher_sala_com_computador(self):
        data_uso = self._data_util_com_antecedencia()
        self._login('aluno1')
        criar = self.client.post(
            '/reservas/sala',
            data={
                'csrf_token': self.csrf,
                'data_uso': data_uso,
                'horario_inicio': '10:00',
                'horario_fim': '11:00',
                'tipo_sala': 'computador',
                'finalidade': 'Usar computador',
                'observacao': ''
            }
        )
        self.assertEqual(criar.status_code, 302)

        conn = mapa.get_db()
        try:
            reserva = conn.execute("SELECT * FROM reservas WHERE tipo='sala'").fetchone()
        finally:
            conn.close()
        self.assertIn(reserva['sala_atribuida'], mapa.SALAS_COM_COMPUTADOR)

        self.client.get('/logout')
        self._login('recepcao')
        aprovar = self.client.post(
            f'/reservas/{reserva["id"]}/aprovar',
            data={
                'csrf_token': self.csrf,
                'sala_atribuida': 'Consultório 7 (Divã)',
                'resposta': 'Aprovado na sala 7'
            }
        )
        self.assertEqual(aprovar.status_code, 302)

        conn = mapa.get_db()
        try:
            reserva_atualizada = conn.execute('SELECT * FROM reservas WHERE id=?', (reserva['id'],)).fetchone()
            ag = conn.execute(
                'SELECT sala FROM agendamentos WHERE data_especifica=? AND usuario_id=?',
                (data_uso, self.aluno1_id)
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(reserva_atualizada['status'], 'aprovada')
        self.assertEqual(reserva_atualizada['sala_atribuida'], 'Consultório 7 (Divã)')
        self.assertEqual(ag['sala'], 'Consultório 7 (Divã)')

    def test_aprovar_reserva_de_instrumento_nao_cria_agendamento(self):
        data_uso = self._data_util_com_antecedencia()
        conn = mapa.get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'instrumento', data_uso, '10:00', 'WISC', 'Avaliacao')
            )
            reserva_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.post(
            f'/reservas/{reserva_id}/aprovar',
            data={'csrf_token': self.csrf, 'resposta': 'Separado'}
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            reserva = conn.execute('SELECT * FROM reservas WHERE id=?', (reserva_id,)).fetchone()
            total_agendamentos = conn.execute('SELECT COUNT(*) AS total FROM agendamentos').fetchone()['total']
        finally:
            conn.close()

        self.assertEqual(reserva['status'], 'aprovada')
        self.assertEqual(total_agendamentos, 0)

    def test_recusar_reserva_marca_como_recusada(self):
        data_uso = self._data_util_com_antecedencia()
        conn = mapa.get_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO reservas(usuario_id, usuario, tipo, data_uso, horario_inicio, instrumento, finalidade)
                VALUES(?,?,?,?,?,?,?)
                """,
                (self.aluno1_id, 'aluno1', 'instrumento', data_uso, '10:00', 'WISC', 'Avaliacao')
            )
            reserva_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.post(
            f'/reservas/{reserva_id}/recusar',
            data={'csrf_token': self.csrf, 'resposta': 'Indisponivel'}
        )

        self.assertEqual(resp.status_code, 302)
        conn = mapa.get_db()
        try:
            reserva = conn.execute('SELECT * FROM reservas WHERE id=?', (reserva_id,)).fetchone()
        finally:
            conn.close()

        self.assertEqual(reserva['status'], 'recusada')
        self.assertEqual(reserva['resposta'], 'Indisponivel')

    def test_agendamentos_tem_chave_estrangeira_para_usuarios(self):
        conn = mapa.get_db()
        try:
            fks = conn.execute('PRAGMA foreign_key_list(agendamentos)').fetchall()
        finally:
            conn.close()

        self.assertTrue(
            any(row['table'] == 'usuarios' and row['from'] == 'usuario_id' for row in fks)
        )

    def test_cria_usuario_com_email(self):
        self._login('coordenador')

        resp = self.client.post(
            '/api/usuarios',
            json={
                'username': 'novo_aluno',
                'email': 'novo.aluno@example.com',
                'password': 'senha123',
                'role': 'aluno',
                'ativo': True
            },
            headers={'X-CSRFToken': self.csrf}
        )

        self.assertEqual(resp.status_code, 201)

        conn = mapa.get_db()
        try:
            row = conn.execute('SELECT email FROM usuarios WHERE username=?', ('novo_aluno',)).fetchone()
        finally:
            conn.close()

        self.assertEqual(row['email'], 'novo.aluno@example.com')

    def test_backup_sem_confirmacao_mostra_pagina_amigavel(self):
        self._login('coordenador')

        resp = self.client.get('/api/backup')

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Backup do banco de dados', resp.get_data(as_text=True))

    def test_aluno_nao_abre_detalhe_de_outro_aluno_por_id(self):
        conn = mapa.get_db()
        try:
            ag_id = mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '09:00',
                'sala': 'Consultório 2',
                'estagiario': 'aluno2',
                'paciente': 'Paciente Restrito',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('aluno1')
        resp = self.client.get(f'/api/agendamentos/{ag_id}')

        self.assertEqual(resp.status_code, 404)

    def test_conflito_para_aluno_nao_expoe_ocupante(self):
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '10:00',
                'sala': 'Consultório 3',
                'estagiario': 'aluno2',
                'paciente': 'Paciente Sigiloso',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('aluno1')
        resp = self.client.get('/api/conflito?dia_semana=SEGUNDA&horario=10:00&sala=Consultório+3&ocupa_sala=1')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'conflito': True})

    def test_conflito_bloqueia_agendamento_duplicado(self):
        self._login('recepcao')

        primeiro = self._criar_agendamento_api(estagiario='aluno1', sala='Consultório 4')
        segundo = self._criar_agendamento_api(estagiario='aluno2', sala='Consultório 4')

        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 409)

    def test_registro_informativo_nao_bloqueia_uso_da_sala(self):
        login_resp = self._login('recepcao')
        self.assertIn(login_resp.status_code, (200, 302))
        sessao = self.client.get('/api/agendamentos?dia_semana=SEGUNDA')
        self.assertEqual(sessao.status_code, 200)

        informativo = self.client.post(
            '/api/agendamentos',
            json={
                'dia_semana': 'SEGUNDA',
                'horario': '13:00',
                'sala': 'Consultório 7 (Divã)',
                'estagiario': 'aluno1',
                'categoria': 'NÃO MARCAR',
                'ocupa_sala': 0
            },
            headers={'X-CSRFToken': self.csrf}
        )
        uso_sala = self.client.post(
            '/api/agendamentos',
            json={
                'dia_semana': 'SEGUNDA',
                'horario': '13:00',
                'sala': 'Consultório 7 (Divã)',
                'estagiario': 'Uso pontual',
                'paciente': 'Paciente Teste',
                'categoria': 'ESTAGIÁRIO 9°',
                'ocupa_sala': 1
            },
            headers={'X-CSRFToken': self.csrf}
        )

        self.assertEqual(informativo.status_code, 201)
        self.assertEqual(uso_sala.status_code, 201)

    def test_paciente_marcado_define_ocupa_sala(self):
        dados, erro = mapa.preparar_dados_agendamento({
            'dia_semana': 'SEGUNDA',
            'horario': '14:00',
            'sala': 'Consultório 8',
            'estagiario': 'aluno1',
            'paciente': 'Paciente Ocupante',
            'categoria': 'ESTAGIÁRIO 9°'
        })

        self.assertIsNone(erro)
        self.assertEqual(dados['ocupa_sala'], 1)

    def test_data_especifica_aparece_na_lista_normal_do_dia(self):
        data_segunda = self._proxima_data_util(0)
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'QUARTA',
                'horario': '11:00',
                'sala': 'Consultório 5',
                'estagiario': 'aluno1',
                'paciente': 'Paciente Pontual',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': data_segunda,
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.get('/api/agendamentos?dia_semana=SEGUNDA')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()[0]['paciente'], 'Paciente Pontual')

    def test_categoria_triagem_antiga_vira_categoria_base_com_triagem(self):
        dados, erro = mapa.preparar_dados_agendamento({
            'dia_semana': 'SEGUNDA',
            'horario': '12:00',
            'sala': 'Consultório 6 (Divã)',
            'estagiario': 'aluno1',
            'paciente': 'Paciente Triagem',
            'categoria': 'ESTAGIÁRIO 10° TRIAGEM',
        })

        self.assertIsNone(erro)
        self.assertEqual(dados['categoria'], 'ESTAGIÁRIO 10°')
        self.assertEqual(dados['triagem'], 1)


if __name__ == '__main__':
    unittest.main()
