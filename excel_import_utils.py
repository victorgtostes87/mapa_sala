import re
import unicodedata
from datetime import datetime


def chave_sem_acento(valor):
    valor = unicodedata.normalize('NFKD', str(valor or ''))
    valor = ''.join(ch for ch in valor if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', '', valor.lower())


def normalizar_sala_excel(valor, salas):
    mapa = {chave_sem_acento(sala): sala for sala in salas}
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
        'salasupervisao': 'Supervisão',
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

    m = re.search(
        r'\b(?:s[óo]|somente|apenas)\s+(?:dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?',
        texto,
        flags=re.I
    )
    if not m:
        m = re.search(
            r'\bdia\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?',
            texto,
            flags=re.I
        )
    if not m:
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
    up = (texto or '').upper()
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
    return 'OUTRO'


def semestre_por_texto_excel(texto):
    if re.search(r'\b10\s*[°º]', texto or ''):
        return 10
    if re.search(r'\b9\s*[°º]', texto or ''):
        return 9
    return 0


def texto_excel_eh_marcador_operacional(texto):
    categoria = categoria_por_texto_excel(texto or '')
    return categoria if categoria in ('MARCAR', 'NÃO MARCAR') else ''


def montar_agendamento_excel(dia, horario, sala, texto_principal, texto_secundario, preparar_dados, ano=None):
    textos = [t for t in (texto_principal, texto_secundario) if t]
    if not textos:
        return None, 'Célula vazia'
    texto_total = ' - '.join(textos)
    if chave_sem_acento(texto_total) in ('tt', 't'):
        return None, 'Marcador interno ignorado'

    triagem = 1 if re.search(r'\btriagem\b', texto_total, flags=re.I) else 0
    data_especifica = extrair_data_pontual_excel(texto_total, ano)
    semestre = semestre_por_texto_excel(texto_total)
    categoria_principal = categoria_por_texto_excel(texto_principal)
    categoria_secundaria = categoria_por_texto_excel(texto_secundario)
    marcador_secundario = texto_excel_eh_marcador_operacional(texto_secundario)
    categoria = categoria_por_texto_excel(texto_total)
    estagiario = ''
    paciente = ''
    observacao = ''

    if marcador_secundario and semestre:
        estagiario = limpar_marcadores_excel(texto_principal)
        categoria = marcador_secundario
        observacao = limpar_marcadores_excel(texto_secundario)
    elif categoria in ('MARCAR', 'NÃO MARCAR'):
        estagiario = limpar_marcadores_excel(texto_principal)
        observacao = limpar_marcadores_excel(texto_total)
        if categoria == 'MARCAR':
            estagiario = ''
    elif semestre:
        estagiario = limpar_marcadores_excel(texto_principal)
        paciente = limpar_marcadores_excel(texto_secundario)
        if categoria_principal != 'OUTRO':
            categoria = categoria_principal
        elif categoria_secundaria != 'OUTRO':
            categoria = categoria_secundaria
        else:
            categoria = 'OUTRO'
    else:
        estagiario = limpar_marcadores_excel(texto_principal)
        observacao = limpar_marcadores_excel(texto_total)

    if not estagiario and categoria == 'OUTRO':
        estagiario = limpar_marcadores_excel(texto_principal) or 'Importado do Excel'

    return preparar_dados({
        'dia_semana': dia,
        'horario': horario,
        'sala': sala,
        'estagiario': estagiario,
        'paciente': paciente,
        'categoria': categoria,
        'semestre': semestre,
        'triagem': triagem,
        'observacao': observacao,
        'data_especifica': data_especifica,
    })
