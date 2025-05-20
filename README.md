# 🔗 Sistema P2P de Compartilhamento de Arquivos — Pyro5

Este projeto foi desenvolvido para a disciplina de **Sistemas Distribuídos** (UTFPR) e implementa um sistema **peer-to-peer** para compartilhamento direto de arquivos entre múltiplos nós (peers), com **eleição de tracker** e transferência P2P usando **Pyro5**.

---

## ⚙️ **Funcionalidades Principais**

- Gerenciamento descentralizado de peers.
- Eleição automática de tracker (com detecção de falha via heartbeat).
- Compartilhamento, listagem e download direto de arquivos entre peers.
- Atualização dinâmica do tracker sempre que arquivos são modificados.
- Consulta global ao tracker de todos os arquivos compartilhados e seus donos.
- CLI interativa para testes e uso.

---

## 📁 **Estrutura do Projeto**

```text
pyro_app/
│
├── peer.py           # Lógica do peer (nó P2P) — CLI principal
├── tracker.py        # Lógica do tracker (índice central)
├── utils.py          # Utilitários para manipulação de arquivos e diretórios
├── README.md         # Este arquivo
└── compartilhados/   # Pasta raiz para arquivos dos peers
    ├── peer1/
    ├── peer2/
    └── peerN/
````

---

## 🚀 **Dependências**

* Python 3.8+
* Pyro5 (`pip install Pyro5`)

---

## 🔧 **Como Executar**

1. **Suba o NameServer do Pyro5** em um terminal:

   ```bash
   python3 -m Pyro5.nameserver -n localhost
   ```

2. **Abra um terminal para cada peer**. Execute:

   ```bash
   python3 peer.py peer1
   python3 peer.py peer2
   python3 peer.py peer3
   # ... e assim por diante para quantos peers quiser
   ```

3. **O primeiro peer será eleito o tracker, mas você pode forçar uma nova eleição com:**

   ```
   eleger
   ```

4. **Use os comandos do CLI para manipular arquivos:**

   * `list`           — lista os arquivos locais do peer
   * `listAll`        — mostra todos os arquivos compartilhados no tracker e seus donos
   * `add <arq>`      — adiciona um novo arquivo local
   * `remove <arq>`   — remove um arquivo local
   * `download <arq>` — baixa um arquivo de outro peer da rede
   * `eleger`         — força uma nova eleição de tracker
   * `kill`           — encerra o peer atual
   * `exit`           — encerra o peer atual

---

## 💡 **Como Funciona**

* Cada peer possui sua própria pasta em `compartilhados/<peer_id>/`.
* Ao subir, cada peer registra seus arquivos junto ao tracker (quando houver).
* O tracker mantém um **índice global**: arquivo → \[lista de peers que possuem].
* Ao modificar arquivos locais, o peer sempre informa o tracker.
* O comando `listAll` mostra o índice global.
* Ao solicitar um download, o peer consulta o tracker, escolhe um peer dono e faz a transferência **direta P2P**.

---

## 👨‍💻 **Exemplo de Uso**

```bash
python3 peer.py peer1
# Em outro terminal:
python3 peer.py peer2

# No peer1 (vai ser eleito tracker automaticamente):
add arquivo_teste.txt

# No peer2:
listAll
download arquivo_teste.txt
```

---

## 📄 **Licença**

Projeto acadêmico — UTFPR, 2025.

Desenvolvido por **Samuel Canuto Sales de Oliveira** e **Giulia Cavasin**

---
