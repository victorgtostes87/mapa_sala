def adicionar_coluna_se_ausente(conn, tabela, coluna, sql_alter):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})").fetchall()]
    if coluna in cols:
        return False
    conn.execute(sql_alter)
    return True


def migration_ja_aplicada(conn, version):
    row = conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone()
    return bool(row)


def registrar_migration(conn, version, description):
    conn.execute(
        'INSERT OR IGNORE INTO schema_migrations(version, description) VALUES(?,?)',
        (version, description)
    )


def executar_migration(conn, version, description, func):
    if migration_ja_aplicada(conn, version):
        return False
    func(conn)
    registrar_migration(conn, version, description)
    return True
