def buscar_usuario_id_aluno(username, conn):
    username = (username or '').strip()
    if not username:
        return None
    row = conn.execute(
        "SELECT id FROM usuarios WHERE username=? AND role='aluno' AND ativo=1",
        (username,)
    ).fetchone()
    return row['id'] if row else None


def selecionar_usuarios_para_admin(conn, colunas_tabela):
    cols = colunas_tabela(conn, 'usuarios')
    nome_expr = "u.nome_completo" if 'nome_completo' in cols else "''"
    email_expr = "u.email" if 'email' in cols else "''"
    supervisor_id_expr = "u.supervisor_id" if 'supervisor_id' in cols else "NULL"
    ativo_expr = "u.ativo" if 'ativo' in cols else "1"
    created_at_expr = "u.created_at" if 'created_at' in cols else "''"
    join_supervisor = ''
    supervisor_nome_expr = "''"

    if 'supervisor_id' in cols:
        join_supervisor = "LEFT JOIN usuarios p ON p.id = u.supervisor_id"
        if 'nome_completo' in cols:
            supervisor_nome_expr = "COALESCE(NULLIF(p.nome_completo, ''), p.username, '')"
        else:
            supervisor_nome_expr = "COALESCE(p.username, '')"

    order_expr = "COALESCE(NULLIF(u.nome_completo, ''), u.username)" if 'nome_completo' in cols else "u.username"
    return conn.execute(
        f"""
        SELECT u.id,
               u.username,
               {nome_expr} AS nome_completo,
               {email_expr} AS email,
               u.role,
               {supervisor_id_expr} AS supervisor_id,
               {ativo_expr} AS ativo,
               {created_at_expr} AS created_at,
               {supervisor_nome_expr} AS supervisor_nome
        FROM usuarios u
        {join_supervisor}
        ORDER BY {order_expr} COLLATE NOCASE, u.username COLLATE NOCASE
        """
    ).fetchall()


def listar_professores_ativos(conn, colunas_tabela):
    cols = colunas_tabela(conn, 'usuarios')
    nome_expr = "nome_completo" if 'nome_completo' in cols else "''"
    filtro_ativo = "AND ativo=1" if 'ativo' in cols else ""
    order_expr = "COALESCE(NULLIF(nome_completo, ''), username)" if 'nome_completo' in cols else "username"
    rows = conn.execute(
        f"""
        SELECT id, username, {nome_expr} AS nome_completo
        FROM usuarios
        WHERE role='professor' {filtro_ativo}
        ORDER BY {order_expr} COLLATE NOCASE
        """
    ).fetchall()
    return [dict(r) for r in rows]
