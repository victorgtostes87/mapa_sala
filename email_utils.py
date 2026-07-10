import smtplib
from email.message import EmailMessage


def email_configurado(config):
    return bool(config['host'] and config['from'] and config['user'] and config['password'])


def diagnostico_smtp(config):
    faltando = []
    if not config['host']:
        faltando.append('SMTP_HOST')
    if not config['from']:
        faltando.append('EMAIL_FROM')
    if not config['user']:
        faltando.append('SMTP_USER')
    if not config['password']:
        faltando.append('SMTP_PASSWORD')
    return {
        'configurado': not faltando,
        'host': config['host'] or 'não informado',
        'porta': config['port'],
        'tls': config['tls'],
        'usuario_configurado': bool(config['user']),
        'senha_configurada': bool(config['password']),
        'email_saida_configurado': bool(config['from']),
        'base_url_configurada': bool(config['base_url']),
        'faltando': faltando,
    }


def email_de_teste_ou_invalido(email):
    email = (email or '').strip().lower()
    if not email or '@' not in email:
        return True
    dominio = email.rsplit('@', 1)[1]
    dominios_bloqueados = {
        'example.com',
        'example.org',
        'example.net',
        'teste.com',
        'test.com',
        'email.com',
    }
    return dominio in dominios_bloqueados or dominio.endswith('.example')


def validar_email_usuario(email, obrigatorio=False):
    email = (email or '').strip()
    if not email:
        if obrigatorio:
            return 'Informe um e-mail real.'
        return None
    if email_de_teste_ou_invalido(email):
        return 'Use um e-mail real. E-mails de teste como @example.com não podem ser cadastrados.'
    return None


def enviar_email_smtp(config, destinatario, assunto, corpo):
    msg = EmailMessage()
    msg['From'] = config['from']
    msg['To'] = destinatario
    msg['Subject'] = assunto
    msg.set_content(corpo)

    with smtplib.SMTP(config['host'], config['port'], timeout=10) as smtp:
        if config['tls']:
            smtp.starttls()
        if config['user'] and config['password']:
            smtp.login(config['user'], config['password'])
        smtp.send_message(msg)
