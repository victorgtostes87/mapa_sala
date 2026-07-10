import re
from datetime import datetime


TERMOS_CLINICOS_OBSERVACAO = (
    'diagnóstico', 'diagnostico', 'cid', 'hipótese', 'hipotese',
    'queixa', 'evolução', 'evolucao', 'sessão', 'sessao',
    'trauma', 'abuso', 'suicid', 'medicação', 'medicacao',
    'laudo', 'sintoma', 'transtorno', 'relato clínico', 'relato clinico',
)


def normalize(t):
    if not t:
        return ''
    for antigo, novo in [('ş', 'º'), ('Ş', 'º'), ('ţ', 'ç')]:
        t = t.replace(antigo, novo)
    return t.strip()


def normalizar_data_especifica(data_especifica, dias):
    data_especifica = (data_especifica or '').strip()
    if not data_especifica:
        return '', None

    try:
        data_obj = datetime.strptime(data_especifica, '%Y-%m-%d')
    except ValueError:
        return None, 'Data específica inválida. Use o formato AAAA-MM-DD (ex: 2026-08-15).'

    if data_obj.weekday() >= len(dias):
        return None, 'Data específica deve cair entre segunda e sexta-feira.'

    return data_especifica, None


def dia_semana_da_data(data_especifica, dias):
    data_obj = datetime.strptime(data_especifica, '%Y-%m-%d')
    return dias[data_obj.weekday()]


def numero_semana_sqlite(dia, dias):
    # SQLite usa domingo=0, segunda=1 ... sexta=5.
    return str(dias.index(dia) + 1)


def validar_valores_agendamento(dia, horario, sala, categoria, dias, horarios, salas, categorias):
    if dia not in dias:
        return 'Escolha um dia da semana válido.'
    if horario not in horarios:
        return 'Escolha um horário disponível na lista.'
    if sala not in salas:
        return 'Escolha uma sala cadastrada no sistema.'
    if categoria and categoria not in categorias:
        return 'Escolha uma categoria cadastrada no sistema.'
    return None


def validar_observacao_operacional(observacao):
    observacao = (observacao or '').strip()
    if len(observacao) > 500:
        return 'A observação deve ter no máximo 500 caracteres.'

    texto = normalize(observacao).lower()
    for termo in TERMOS_CLINICOS_OBSERVACAO:
        if termo in texto:
            return (
                'Use a observação apenas para informações operacionais. '
                'Não registre diagnóstico, queixa, evolução, sessão, CID ou outros dados clínicos do paciente.'
            )
    return None


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


def motivo_ocupacao_sala(categoria, paciente='', observacao='', data_especifica='', triagem=0, categorias_ocupam=None):
    categorias_ocupam = categorias_ocupam or set()
    categoria = (categoria or '').strip().upper()
    paciente = (paciente or '').strip()
    observacao = (observacao or '').strip()
    data_especifica = (data_especifica or '').strip()

    if paciente:
        return 'paciente'
    if valor_triagem(triagem, 0) and paciente:
        return 'triagem_com_paciente'
    if categoria in categorias_ocupam:
        return 'categoria'
    if data_especifica and observacao:
        return 'reserva_pontual'
    return ''


def calcular_ocupa_sala(categoria, paciente='', observacao='', data_especifica='', triagem=0, categorias_ocupam=None):
    if motivo_ocupacao_sala(categoria, paciente, observacao, data_especifica, triagem, categorias_ocupam):
        return 1
    return 0


def detect_cat(est, pac):
    texto = normalize(est + ' ' + pac).upper()
    if 'NÃO MARCAR' in texto or 'NAO MARCAR' in texto:
        return 'NÃO MARCAR'
    if 'PSICODIAG' in texto:
        return 'PSICODIAGNÓSTICO'
    if 'SUPERVISÃO' in texto or 'SUPERVISAO' in texto or 'PROF.' in texto or re.search(r'PROF\s+\w', texto):
        return 'SUPERVISÃO'
    if 'NACE' in texto:
        return 'NACE'
    if re.search(r'\bSOU\b', texto):
        return 'SOU'
    if 'MARCAR' in texto:
        return 'MARCAR'
    if 'NUTRIÇÃO' in texto or 'NUTRICAO' in texto:
        return 'NUTRIÇÃO'
    if 'PSIQUIATRIA' in texto:
        return 'PSIQUIATRIA'
    if 'AMBULAT' in texto:
        return 'AMBULATÓRIO NEUROPSICOLOGIA'
    if 'PLANTÃO' in texto or 'PLANTAO' in texto:
        return 'PLANTÃO PSICOLÓGICO'
    if 'PRONTUÁRIO' in texto or 'PRONTUARIO' in texto or 'ESTUDAR' in texto:
        return 'PRONTUÁRIO/ESTUDAR'
    if re.search(r'10[°º]', texto):
        return 'ESTAGIÁRIO 10°'
    if re.search(r'9[°º]', texto):
        return 'ESTAGIÁRIO 9°'

    estagiario_normalizado = normalize(est).strip()
    if estagiario_normalizado and not any(
        termo in estagiario_normalizado.upper()
        for termo in ['PSICODIAG', 'NÃO', 'MARCAR', 'SUPERVISÃO']
    ):
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


def preparar_dados_agendamento(
    dados,
    usuario_id_padrao,
    dias,
    horarios,
    salas,
    categorias,
    categorias_ocupam,
    status_atendimento_validos,
):
    dia = (dados.get('dia_semana') or 'SEGUNDA').strip()
    horario = (dados.get('horario') or '').strip()
    sala = (dados.get('sala') or '').strip()
    data_esp = (dados.get('data_especifica') or '').strip()
    categoria_informada, triagem_categoria = normalizar_categoria_triagem(dados.get('categoria'))

    if not horario or not sala:
        return None, 'Os campos horário e sala são obrigatórios.'

    data_esp, erro_data = normalizar_data_especifica(data_esp, dias)
    if erro_data:
        return None, erro_data
    if data_esp:
        dia = dia_semana_da_data(data_esp, dias)

    erro_validacao = validar_valores_agendamento(
        dia, horario, sala, categoria_informada, dias, horarios, salas, categorias
    )
    if erro_validacao:
        return None, erro_validacao

    estagiario = dados.get('estagiario', '')
    paciente = dados.get('paciente', '')
    categoria = categoria_informada or detect_cat(estagiario, paciente)
    semestre = dados.get('semestre', 0) or detect_sem(estagiario)
    triagem_padrao = 1 if texto_indica_triagem(estagiario, paciente) else 0
    triagem = triagem_categoria if triagem_categoria is not None else valor_triagem(dados.get('triagem'), triagem_padrao)
    observacao = (dados.get('observacao') or '').strip()
    erro_observacao = validar_observacao_operacional(observacao)
    if erro_observacao:
        return None, erro_observacao
    status_atendimento = (dados.get('status_atendimento') or '').strip()
    if status_atendimento not in status_atendimento_validos:
        return None, 'Escolha um status de atendimento válido.'
    ocupa_calculado = calcular_ocupa_sala(categoria, paciente, observacao, data_esp, triagem, categorias_ocupam)
    ocupa_sala = 0 if status_atendimento else valor_ocupa_sala(dados.get('ocupa_sala'), ocupa_calculado)

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
        'status_atendimento': status_atendimento,
    }, None
