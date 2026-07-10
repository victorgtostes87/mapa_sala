import re
import unicodedata


def valor_ativo(valor, padrao=1):
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return 1 if valor else 0
    return 0 if str(valor).strip().lower() in ('0', 'false', 'nao', 'não', 'inativo') else 1


def sugerir_username_por_nome(nome_completo):
    partes = unicodedata.normalize('NFKD', nome_completo or '')
    partes = ''.join(ch for ch in partes if not unicodedata.combining(ch))
    partes = re.sub(r'[^a-zA-Z\s]+', ' ', partes).lower().strip().split()
    if not partes:
        return ''
    if len(partes) == 1:
        return partes[0]
    return f'{partes[0]}.{partes[-1]}'


def normalizar_supervisor_id(valor):
    if str(valor or '').strip() == '':
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 'invalido'
