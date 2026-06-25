import os
import tempfile
import unittest

os.environ['SECRET_KEY'] = 'chave-de-teste-com-tamanho-suficiente-123'
_tmpdir = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = os.path.join(_tmpdir.name, 'mapa_salas_teste.db')

import app as mapa  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


class MapaSalasTestCase(unittest.TestCase):
    def setUp(self):
        mapa.app.config['TESTING'] = True
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
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = self.csrf
        return self.client.post(
            '/login',
            data={
                'username': username,
                'password': 'senha123',
                'csrf_token': self.csrf
            }
        )

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

    def test_agendamentos_tem_chave_estrangeira_para_usuarios(self):
        conn = mapa.get_db()
        try:
            fks = conn.execute('PRAGMA foreign_key_list(agendamentos)').fetchall()
        finally:
            conn.close()

        self.assertTrue(
            any(row['table'] == 'usuarios' and row['from'] == 'usuario_id' for row in fks)
        )

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
        resp = self.client.get('/api/conflito?dia_semana=SEGUNDA&horario=10:00&sala=Consultório+3')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {'conflito': True})

    def test_conflito_bloqueia_agendamento_duplicado(self):
        self._login('recepcao')

        primeiro = self._criar_agendamento_api(estagiario='aluno1', sala='Consultório 4')
        segundo = self._criar_agendamento_api(estagiario='aluno2', sala='Consultório 4')

        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 409)

    def test_data_especifica_aparece_na_lista_normal_do_dia(self):
        conn = mapa.get_db()
        try:
            mapa.inserir_agendamento(conn, {
                'dia': 'SEGUNDA',
                'horario': '11:00',
                'sala': 'Consultório 5',
                'estagiario': 'aluno1',
                'paciente': 'Paciente Pontual',
                'categoria': 'ESTAGIÁRIO 9°',
                'semestre': 9,
                'triagem': 0,
                'observacao': '',
                'data_especifica': '2026-06-29',
                'usuario_id': None
            })
            conn.commit()
        finally:
            conn.close()

        self._login('recepcao')
        resp = self.client.get('/api/agendamentos?dia_semana=SEGUNDA')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()[0]['paciente'], 'Paciente Pontual')


if __name__ == '__main__':
    unittest.main()
