# 🏥 Mapa de Salas — Policlínica de Psicologia

Sistema web para gerenciamento de agendamentos de salas em uma policlínica de psicologia. Desenvolvido com Flask e SQLite, hospedado no PythonAnywhere e versionado no GitHub.

---

## 💡 Ideia do Projeto

A coordenação da policlínica precisava de uma forma visual, rápida e centralizada de saber **quem está usando qual sala, em qual horário e qual dia da semana**. Antes, esse controle era feito manualmente em planilhas Excel, o que gerava conflitos de horário, retrabalho e falta de visibilidade para todos os envolvidos.

O sistema resolve isso com:

- Um **mapa interativo** de salas por dia e horário
- **Controle de acesso por papel** (coordenador, recepção, aluno/estagiário)
- **Detecção automática de conflitos** ao agendar
- **Histórico de ações** visível para o coordenador
- **Exportação CSV** do mapa completo
- **Impressão de lista de pacientes** por dia (para portaria)

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|---|---|
| Backend | Python 3 + Flask |
| Autenticação | Flask-Login + Werkzeug |
| Banco de dados | SQLite (arquivo local) |
| Frontend | HTML + CSS + JavaScript puro |
| Hospedagem | PythonAnywhere |
| Versionamento | GitHub |

Sem frameworks frontend (React, Vue etc.) — tudo em JS puro para manter simples e leve.

---

## 👥 Papéis de Usuário

| Papel | O que pode fazer |
|---|---|
| `coordenador` | Tudo: criar, editar, excluir, ver logs, gerenciar usuários, exportar CSV |
| `recepcao` | Criar e editar agendamentos |
| `aluno` | Apenas visualizar o mapa |

Todos os papéis podem trocar a própria senha.

---

## 📋 Funcionalidades

- **Mapa visual** por dia da semana (Segunda a Sábado) com cores por categoria
- **15 salas** configuráveis: consultórios, ludoterapia, sala de grupo, supervisão etc.
- **14 categorias** de agendamento com detecção automática pelo nome do estagiário
- **Detecção de conflito** em tempo real antes de salvar
- **Filtros** por horário, sala, categoria e busca livre
- **Painel de logs** com histórico das últimas ações (purge automático após 15 dias)
- **Impressão** da lista de pacientes do dia para a portaria
- **Exportação CSV** completa do banco
- **Troca de senha** pelo próprio usuário
- **Gestão de usuários** (criar, editar papel, redefinir senha, excluir)

---

## 🚀 Como Rodar Localmente

### 1. Clonar o repositório
```bash
git clone https://github.com/victorgtostes87/mapa_sala.git
cd mapa_sala
```

### 2. Criar e ativar ambiente virtual
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

### 3. Instalar dependências
```bash
pip install flask flask-login werkzeug
```

### 4. Rodar
```bash
python app.py
```

Acesse: **http://localhost:5000**

Login padrão: `coordenador` / `mudar@2026`

> O banco de dados (`mapa_salas.db`) é criado automaticamente na primeira execução.

---

## 📁 Estrutura de Arquivos

```
mapa_sala/
├── app.py                    # Aplicação Flask principal
├── importar_xlsx.py          # Script de importação de planilha Excel
├── README.md
├── .gitignore
└── templates/
    ├── index.html            # Mapa principal
    ├── login.html            # Tela de login
    ├── usuarios.html         # Gestão de usuários
    ├── logs.html             # Painel de logs
    ├── trocar_senha.html     # Troca de senha
    ├── imprimir.html         # Impressão da lista
    └── imprimir_selecao.html # Seleção do dia para impressão
```

---

## 🔒 Segurança

- Senhas armazenadas com hash bcrypt (Werkzeug)
- Rotas protegidas por `@login_required` e verificação de papel
- Usuário não pode excluir a própria conta
- Logs de todas as ações sensíveis (login, criação, edição, exclusão)

---

## 🌐 Deploy (PythonAnywhere)

O projeto está hospedado em [victroid.pythonanywhere.com](https://victroid.pythonanywhere.com).

Para atualizar após um push no GitHub:
```bash
cd ~/mapa_sala && git pull origin main
```
E recarregar o web app no painel do PythonAnywhere.

---

## 📌 Origem

Projeto desenvolvido para a **Policlínica de Psicologia** como solução interna de gestão de espaços. Construído de forma iterativa a partir de uma planilha Excel existente (`MAPA DE SALA 2026.1.xlsx`), com importação automática dos dados originais via `importar_xlsx.py`.
