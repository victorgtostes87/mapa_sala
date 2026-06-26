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

        conn = mapa.get_db()
        try:
            conn.execute('DELETE FROM agendamentos')
            conn.execute('DELETE FROM historico')
            conn.execute('DELETE FROM usuarios')
            self.coord_id = self._criar_usuario(conn, 'coordenador', 'coordenador')
            self.recepcao_id = self._criar_usuario(conn, 'recepcao', 'recepcao')
            self.aluno1_id = self._criar_usuario(conn, 'aluno1', 'aluno')
            self.aluno2_id = self._criar_usuario(conn, 'aluno2', 'aluno')
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
