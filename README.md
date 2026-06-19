# Mapa de Salas — Policlínica de Psicologia

Sistema web para gerenciamento de agendamentos de salas em uma policlínica de psicologia universitária. Substitui o controle manual por planilhas Excel, elimina conflitos de horário e oferece visibilidade operacional por papel de usuário.

> **Produção:** [victroid.pythonanywhere.com](https://victroid.pythonanywhere.com)
> **Versão atual:** ver `VERSAO` em `app.py`

---

## Índice

- [Objetivo](#objetivo)
- [Tecnologias](#tecnologias)
- [Papéis e Permissões](#papéis-e-permissões)
- [Funcionalidades](#funcionalidades)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Banco de Dados](#banco-de-dados)
- [Rotas da Aplicação](#rotas-da-aplicação)
- [Regras de Negócio](#regras-de-negócio)
- [Como Rodar Localmente](#como-rodar-localmente)
- [Deploy no PythonAnywhere](#deploy-no-pythonanywhere)
- [Variáveis de Ambiente](#variáveis-de-ambiente)
- [Segurança](#segurança)
- [Backlog / Melhorias Futuras](#backlog--melhorias-futuras)

---

## Objetivo

A coordenação da policlínica precisava de uma forma centralizada de saber **quem está usando qual sala, em qual horário e qual dia da semana**. O controle anterior era feito em planilhas Excel, gerando conflitos de horário, retrabalho e falta de visibilidade.

O sistema resolve isso com:

- Mapa visual interativo por dia da semana e horário
- Controle de acesso por papel (coordenador, recepção, aluno/estagiário)
- Detecção e bloqueio automático de conflitos de sala
- Histórico completo de ações auditáveis
- Exportação CSV e impressão de lista diária para portaria

---

## Tecnologias

| Camada | Tecnologia | Motivo da Escolha |
|---|---|---|
| Backend | Python 3 + Flask | Simples, rápido de desenvolver, fácil de hospedar |
| Autenticação | Flask-Login + Werkzeug | Padrão Flask para sessão e hash de senha |
| Banco de dados | SQLite (arquivo local) | Suficiente para até ~100 usuários simultâneos |
| Frontend | HTML + CSS + JavaScript puro | Sem dependências externas, fácil de manter |
| Hospedagem | PythonAnywhere | Deploy simples para projetos Flask |
| Versionamento | Git + GitHub | Controle de versão e backup do código |
| Configuração | python-dotenv | Carrega variáveis sensíveis do arquivo `.env` |

---

## Papéis e Permissões

| Papel | Código | Permissões |
|---|---|---|
| Coordenador | `coordenador` | Acesso total: criar, editar, excluir agendamentos, gerenciar usuários, visualizar logs, exportar CSV, backup do banco |
| Recepção | `recepcao` | Criar, editar e excluir agendamentos; exportar CSV; impressão |
| Professor Supervisor | `professor` | Visualização do mapa |
| Estagiário | `aluno` | Visualização do próprio mapa (filtrado pelo username) |

Todos os papéis podem trocar a própria senha e editar o próprio perfil.

---

## Funcionalidades

### Mapa de Salas
- Grade visual por dia da semana (Segunda a Sexta)
- 15 salas configuradas: consultórios, ludoterapia, salas de grupo, supervisão, coordenação etc.
- Cores por categoria de agendamento
- Filtros por horário, sala, categoria e busca textual
- Estatísticas de ocupação por dia

### Agendamentos
- Criação, edição e exclusão por coordenador e recepção
- Detecção de conflito em tempo real antes de salvar
- Bloqueio total de conflitos: o sistema não salva agendamentos sobrepostos
- Detecção automática de categoria pelo nome do estagiário
- Campo de data específica para agendamentos pontuais

### Administração
- CRUD completo de usuários (coordenador)
- Redefinição de senha pelo coordenador
- Logs de auditoria com purge automático após 15 dias
- Exportação CSV completa do banco
- Backup manual do banco `.db` via rota protegida
- Impressão da lista de pacientes por dia (para portaria)

---

## Estrutura do Projeto

```
mapa_sala/
├── app.py                     # Aplicação Flask: configuração, rotas, lógica de negócio
├── importar_xlsx.py           # Script utilitário para importação inicial da planilha Excel
├── requirements.txt           # Dependências Python
├── README.md
├── .gitignore
├── .env                       # NÃO versionar — variáveis sensíveis (SECRET_KEY)
├── mysite/
│   └── wsgi.py                # Configuração WSGI para o PythonAnywhere
└── templates/
    ├── index.html             # Mapa principal de salas
    ├── login.html             # Tela de autenticação
    ├── usuarios.html          # Gestão de usuários (coordenador)
    ├── logs.html              # Painel de auditoria (coordenador)
    ├── perfil.html            # Edição de perfil do usuário
    ├── trocar_senha.html      # Troca de senha
    ├── imprimir_selecao.html  # Seleção do dia para impressão
    └── imprimir.html          # Lista de pacientes para impressão/portaria
```

> **Nota:** Arquivos `.bak` não pertencem ao repositório — use `git log` para recuperar versões anteriores.

---

## Banco de Dados

O banco é criado automaticamente em `mapa_salas.db` na primeira execução de `app.py`.

### Tabela `agendamentos`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | Identificador único |
| `dia_semana` | TEXT | SEGUNDA, TERÇA, QUARTA, QUINTA, SEXTA |
| `horario` | TEXT | Formato HH:MM (ex: 08:00) |
| `sala` | TEXT | Nome da sala |
| `estagiario` | TEXT | Nome do estagiário responsável |
| `paciente` | TEXT | Nome do paciente (ou descrição) |
| `categoria` | TEXT | Classificação do agendamento |
| `semestre` | INTEGER | Semestre do estagiário (9 ou 10) |
| `triagem` | INTEGER | 0 = não, 1 = sim |
| `observacao` | TEXT | Campo livre de observações |
| `data_especifica` | TEXT | Para agendamentos de data única |
| `created_at` | TIMESTAMP | Data de criação |
| `updated_at` | TIMESTAMP | Data da última atualização |

**Índice único:** `(dia_semana, horario, sala)` — garante no nível do banco que não existem dois agendamentos no mesmo slot.

### Tabela `usuarios`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | Identificador único |
| `username` | TEXT UNIQUE | Login do usuário |
| `password_hash` | TEXT | Senha armazenada com hash (Werkzeug/PBKDF2) |
| `role` | TEXT | coordenador, recepcao, professor, aluno |
| `nome_completo` | TEXT | Nome completo para exibição |
| `email` | TEXT | E-mail do usuário |
| `created_at` | TIMESTAMP | Data de criação |

### Tabela `historico`

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | Identificador único |
| `usuario` | TEXT | Username de quem realizou a ação |
| `acao` | TEXT | Tipo de ação (LOGIN, CRIAR, EDITAR, EXCLUIR etc.) |
| `dados` | TEXT | Detalhes da ação em texto livre |
| `ts` | TIMESTAMP | Data e hora da ação |

Registros são removidos automaticamente após 15 dias (`LOG_RETENCAO_DIAS`).

---

## Rotas da Aplicação

### Páginas

| Rota | Método | Acesso | Descrição |
|---|---|---|---|
| `/login` | GET, POST | Público | Tela de autenticação |
| `/logout` | GET | Autenticado | Encerra sessão |
| `/` | GET | Autenticado | Mapa principal de salas |
| `/perfil` | GET, POST | Autenticado | Edição de perfil |
| `/trocar-senha` | GET, POST | Autenticado | Troca de senha |
| `/usuarios` | GET | Coordenador | Gestão de usuários |
| `/logs` | GET | Coordenador | Painel de auditoria |
| `/imprimir` | GET | Coord., Recepção | Seleção de dia para impressão |
| `/imprimir/<dia>` | GET | Coord., Recepção | Lista de pacientes do dia |

### API (JSON)

| Rota | Método | Acesso | Descrição |
|---|---|---|---|
| `/api/versao` | GET | Público | Versão atual do sistema |
| `/api/agendamentos` | GET | Autenticado | Lista agendamentos (com filtros) |
| `/api/agendamentos` | POST | Coord., Recepção | Cria agendamento |
| `/api/agendamentos/<id>` | GET | Autenticado | Busca agendamento por ID |
| `/api/agendamentos/<id>` | PUT | Coord., Recepção | Atualiza agendamento |
| `/api/agendamentos/<id>` | DELETE | Coord., Recepção | Remove agendamento |
| `/api/conflito` | GET | Autenticado | Verifica conflito de sala |
| `/api/stats` | GET | Autenticado | Estatísticas de ocupação por dia |
| `/api/export` | GET | Coord., Recepção | Exporta CSV completo |
| `/api/usuarios` | GET | Coordenador | Lista usuários |
| `/api/usuarios` | POST | Coordenador | Cria usuário |
| `/api/usuarios/<id>` | PUT | Coordenador | Atualiza usuário |
| `/api/usuarios/<id>` | DELETE | Coordenador | Remove usuário |
| `/api/estagiarios` | GET | Autenticado | Lista usuários com papel aluno |
| `/api/logs` | GET | Coordenador | Lista logs de auditoria |
| `/api/backup` | GET | Coordenador | Download do arquivo `.db` |

---

## Regras de Negócio

1. **Conflito de sala é bloqueante:** não é possível salvar dois agendamentos no mesmo `(dia_semana, horario, sala)`. O bloqueio ocorre tanto na API (HTTP 409) quanto no índice único do banco.
2. **Aluno só vê seus próprios agendamentos:** o filtro usa o `username` do usuário logado no campo `estagiario`.
3. **Usuário não pode excluir a própria conta.**
4. **Detecção automática de categoria:** o sistema infere a categoria pelo texto dos campos `estagiario` e `paciente` via regex, mas pode ser sobrescrita manualmente.
5. **Logs têm retenção de 15 dias:** registros mais antigos são removidos automaticamente a cada nova entrada no histórico.
6. **Senha padrão do coordenador é `mudar@2026`:** deve ser trocada imediatamente após o primeiro acesso em produção.

---

## Como Rodar Localmente

### Pré-requisitos
- Python 3.8+
- Git

### Passo a passo

```bash
# 1. Clonar o repositório
git clone https://github.com/victorgtostes87/mapa_sala.git
cd mapa_sala

# 2. Criar e ativar ambiente virtual
python -m venv venv
source venv/bin/activate   # Mac/Linux
# venv\Scripts\activate    # Windows

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Criar o arquivo .env
echo "SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env

# 5. Rodar
python app.py
```

Acesse: **http://localhost:5000**
Login inicial: `coordenador` / `mudar@2026`

> O banco `mapa_salas.db` é criado automaticamente na primeira execução.

---

## Deploy no PythonAnywhere

### Atualizar após push

```bash
# No console do PythonAnywhere:
cd ~/mapa_sala && git pull origin main
```

Depois: **Web > Reload** no painel do PythonAnywhere.

### Backup manual do banco

Use a rota protegida `/api/backup` (somente coordenador) para baixar o arquivo `.db` atual.

### Backup automático (recomendado)

No painel do PythonAnywhere, em **Tasks**, adicionar tarefa diária:

```bash
cp /home/victroid/mapa_sala/mapa_salas.db /home/victroid/backups/mapa_$(date +%Y%m%d).db
```

---

## Variáveis de Ambiente

O arquivo `.env` deve estar na raiz do projeto e **nunca ser versionado** (já está no `.gitignore`).

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | **Sim** | Chave de assinatura das sessões Flask. Mínimo 32 caracteres aleatórios. |

### Gerar uma SECRET_KEY segura

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Colar o resultado no `.env`:

```
SECRET_KEY=cole_aqui_o_valor_gerado
```

> **Atenção:** Se a `SECRET_KEY` for exposta (ex: compartilhada em conversa ou commit público), gere uma nova imediatamente. Todas as sessões ativas serão invalidadas automaticamente.

---

## Segurança

- Senhas armazenadas com hash PBKDF2 via Werkzeug (sem texto plano)
- Todas as rotas protegidas por `@login_required`
- Controle de acesso por papel em cada rota sensível
- Queries com parâmetros `?` — sem risco de SQL injection
- `SECRET_KEY` carregada via variável de ambiente
- Usuário não pode excluir a própria conta
- Logs de todas as ações sensíveis (login, logout, criação, edição, exclusão, exportação, backup)

---

## Backlog / Melhorias Futuras

| Melhoria | Prioridade | Observação |
|---|---|---|
| Backup automático diário | Alta | Configurar via PythonAnywhere Tasks |
| Corrigir filtro de aluno (usar `=` em vez de `LIKE`) | Alta | Evita vazamento de agendamentos entre usuários |
| Rate limiting no login | Média | `flask-limiter` — evita tentativas em massa |
| Suporte mobile melhorado | Média | CSS responsivo no `index.html` |
| Dashboard de ocupação semanal | Média | Visão consolidada de todas as salas |
| Notificações por e-mail | Baixa | Avisar quando agendamento for criado/cancelado |
| Separar `app.py` em módulos | Baixa | Só vale quando o arquivo ultrapassar ~800 linhas |
| Testes automatizados | Baixa | Útil se o projeto ganhar mais colaboradores |

---

## Origem

Projeto desenvolvido para a **Policlínica de Psicologia** como solução interna de gestão de espaços. Construído de forma iterativa a partir de uma planilha Excel existente (`MAPA DE SALA 2026.1.xlsx`), com importação automática dos dados originais via `importar_xlsx.py`.
