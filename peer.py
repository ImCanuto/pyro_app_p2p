import Pyro5.api
import Pyro5.errors
import threading
import time
import sys
import os
import random
from tracker import Tracker
from utils import list_files, get_file_content, save_file_content, peer_dir

NS_HOST = "localhost"
NS_PORT = 9090
ARQUIVOS_DIR = "./compartilhados"

class Peer:
    def __init__(self, peer_id):
        self.peer_id = peer_id
        self.uri = None                         # URI Pyro5 do próprio peer
        self.tracker_uri = None                 # URI do tracker atual
        self.tracker_proxy = None               # Proxy remoto para o tracker
        self.epoch = 0                          # Época atual (identifica qual tracker está ativo)
        self.is_tracker = False                 # True se este peer for o tracker eleito
        self.voted_for = {}                     # Controle de votos já realizados por época
        self.rodando = True                     # Flag principal de loop
        self.heartbeat_timeout = 0.4            # Temporizador de heartbeat
        self.election_in_progress = False
        self.election_lock = threading.Lock()   # Evita eleições paralelas
        
        # Cria pasta e arquivo único para o peer
        dirpath = peer_dir(peer_id)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        
        # Arquivo padrão
        fname = f"arquivo_{peer_id}.txt"
        path = os.path.join(dirpath, fname)
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write(f"")

    # --------------------------------------------------------
    # Métodos Pyro5 expostos:
    # --------------------------------------------------------

    # Votação para eleição de tracker (uma vez por época)
    @Pyro5.api.expose
    def solicitar_voto(self, epoch, candidato_id):
        if self.voted_for.get(epoch):
            return False
        self.voted_for[epoch] = candidato_id
        return True

    # Recebe solicitação download de arquivo de outro peer
    @Pyro5.api.expose
    def get_file(self, filename):
        print(f"[{self.peer_id}] Recebida solicitação de download de {filename}")
        try:
            conteudo = get_file_content(self.peer_id, filename)
            print(f"[{self.peer_id}] Enviando arquivo {filename}")
            return conteudo
        except FileNotFoundError:
            print(f"[{self.peer_id}] Arquivo {filename} não encontrado!")
            return None

    # Notificação de início de eleição (broadcast para peers)
    @Pyro5.api.expose
    def notify_election_started(self, candidato_id):
        print(f"\n[!] Eleição iniciada pelo peer {candidato_id}")
        with self.election_lock:
            self.election_in_progress = True

    # Notificação de resultado de eleição (quem virou tracker, nova época)
    @Pyro5.api.expose
    def notify_election_result(self, tracker_id, epoch):
        print(f"\n[!] Peer {tracker_id} foi eleito Tracker (época {epoch})")
        with self.election_lock:
            self.election_in_progress = False
            self.epoch = epoch
            if tracker_id == self.peer_id:
                self.is_tracker = True
            else:
                self.is_tracker = False
        # Após eleição, sempre atualiza os arquivos no tracker novo
        with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
            self.atualizar_tracker_arquivos(ns)

    # --------------------------------------------------------
    # Métodos internos (NÃO expostos):
    # --------------------------------------------------------
    
    # Registro do peer no NS (Names Service)
    def _register_in_ns(self, daemon, ns):
        obj_name = f"peer.{self.peer_id}" # Nome único 'peer.<peer_id>'
        self.uri = daemon.register(self)
        ns.register(obj_name, self.uri)
        print(f"[{self.peer_id}] Registrado no NS como {obj_name}")

    # Busca o tracker atual pelo NS (se houver)
    def _find_tracker(self, ns):
        trackers = ns.list(prefix="tracker.")
        if not trackers:
            return None
        # Encontra o tracker com a maior época
        max_epoch = -1
        selected_uri = None
        for name, uri in trackers.items():
            # O nome é 'tracker.<epoch>'
            parts = name.split('.')
            if len(parts) != 2:
                continue
            epoch_str = parts[1]
            try:
                epoch = int(epoch_str)
                if epoch > max_epoch:
                    max_epoch = epoch
                    selected_uri = uri
            except ValueError:
                continue
        return selected_uri

    # Notifica todos os peers de algum evento (eleição e resultado da eleição)
    def _notify_all_peers(self, ns, method, *args):
        for name, uri in ns.list(prefix="peer.").items():
            try:
                with Pyro5.api.Proxy(uri) as proxy:
                    getattr(proxy, method)(*args)
            except Exception:
                continue

    # Loop de verificação do heartbeat do tracker (detecção de "morte")
    def _heartbeat_loop(self):
        # Cada peer detecta tracker off em tempo aleatório
        time.sleep(random.uniform(0.5, 2.0))
        while self.rodando and not self.is_tracker:
            wait_time = random.uniform(0.2, 0.4)
            try:
                # Sempre tenta buscar tracker do NS antes de declarar morte do tracker
                with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
                    self.conectar_tracker(ns)
                if self.tracker_proxy:
                    try:
                        # Verifica se o tracker está ativo
                        self.tracker_proxy.heartbeat()
                        time.sleep(wait_time)
                    except Exception as e:
                        print(f"\n[{self.peer_id}] Tracker off! ({type(e).__name__}: {e}) Iniciando eleição...")
                        self.tracker_proxy = None
                        self.tracker_uri = None
                        self.iniciar_eleicao()
                else:
                    # Sem tracker, espera um pouco e tenta nova eleição.
                    print(f"[{self.peer_id}] Nenhum tracker detectado, aguardando antes de tentar eleição...")
                    time.sleep(1.5)
                    # Antes de disparar eleição, tenta novamente buscar tracker (para evitar múltiplos trackers)
                    with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
                        self.conectar_tracker(ns)
                    if not self.tracker_proxy:
                        self.iniciar_eleicao()
            except Exception as e:
                print(f"[{self.peer_id}] Erro inesperado no loop de heartbeat: {e}")
                time.sleep(1)

    # Eleição de tracker
    def _elect(self, ns):
        with self.election_lock:
            if self.election_in_progress:
                print(f"[{self.peer_id}] Eleição já em andamento. Ignorando novo disparo.")
                return
            self.election_in_progress = True
        # Notifica todos que a eleição foi iniciada
        self._notify_all_peers(ns, "notify_election_started", self.peer_id)

        peers = [uri for name, uri in ns.list(prefix="peer.").items() if name != f"peer.{self.peer_id}"]
        votos_true = 1  # Sempre vota em si mesmo
        respondentes = 1
        lock = threading.Lock()

        # Função paralela para solicitar voto de cada peer
        def solicitar(peer_uri):
            nonlocal votos_true, respondentes
            try:
                with Pyro5.api.Proxy(peer_uri) as proxy:
                    voto = proxy.solicitar_voto(self.epoch+1, self.peer_id)
                    with lock:
                        respondentes += 1
                        if voto:
                            votos_true += 1
            except Exception:
                pass

        threads = []
        for uri in peers:
            t = threading.Thread(target=solicitar, args=(uri,))
            t.start()
            threads.append(t)
        # Espera todos os votos (timeout evita travamento em peers offline)
        for t in threads:
            t.join(timeout=0.6)
        print(f"[{self.peer_id}] Votos: {votos_true} de {respondentes} peers online") # Debug pra ver se deu certo
        # Verifica maioria
        if votos_true > respondentes // 2:
            self.epoch += 1
            self.virar_tracker(ns)
            self._notify_all_peers(ns, "notify_election_result", self.peer_id, self.epoch)
        else:
            print(f"[{self.peer_id}] Não conseguiu maioria.")
            # Finaliza eleição em andamento
            with self.election_lock:
                self.election_in_progress = False

    # Torna o peer atual um tracker, rodando em novo daemon
    def virar_tracker(self, ns):
        self.is_tracker = True
        daemon = Pyro5.api.Daemon()  # Novo daemon para o tracker
        tracker = Tracker(self.epoch)
        tracker_uri = daemon.register(tracker)
        tracker_name = f"tracker.{self.epoch}"
        # Remove trackers antigos do NS
        existing_trackers = ns.list(prefix="tracker.")
        for name in existing_trackers:
            try:
                ns.remove(name)
            except Exception as e:
                print(f"[{self.peer_id}] Erro ao remover tracker antigo: {e}")
        # Registra o novo tracker
        ns.register(tracker_name, tracker_uri)
        print(f"[{self.peer_id}] Virei Tracker! Registrado como {tracker_name}")
        # Inicia o loop do tracker em thread separada
        threading.Thread(target=daemon.requestLoop, daemon=True).start()

    # Atualiza o proxy local para o tracker mais recente registrado no NS
    def conectar_tracker(self, ns):
        tracker_uri = self._find_tracker(ns)
        if tracker_uri:
            self.tracker_proxy = Pyro5.api.Proxy(tracker_uri)
            self.tracker_uri = tracker_uri
        else:
            self.tracker_proxy = None
            self.tracker_uri = None

    # Atualiza o tracker com todos os arquivos locais do peer
    def atualizar_tracker_arquivos(self, ns):
        self.conectar_tracker(ns)
        if self.tracker_proxy:
            try:
                arquivos = list_files(self.peer_id)
                self.tracker_proxy.register_files(str(self.uri), arquivos)
            except Exception as e:
                print(f"[{self.peer_id}] Falha ao registrar arquivos no tracker: {e}")
        else:
            print(f"[{self.peer_id}] Nenhum tracker disponível para atualizar arquivos (ok se ainda não houve eleição).")

    # Lógica para baixar arquivo de outro peer (consulta tracker e transfere P2P)
    def baixar_arquivo(self, ns, nome_arquivo):
        self.conectar_tracker(ns)
        peers = []
        if self.tracker_proxy:
            peers = self.tracker_proxy.who_has(nome_arquivo)
            print(f"[{self.peer_id}] URIs retornadas pelo tracker para {nome_arquivo}: {peers}")
        for peer_uri in peers:
            if peer_uri == str(self.uri):
                continue # Não tenta baixar de si mesmo
            if "tracker" in peer_uri:
                continue # Evita tentar baixar de um tracker (por segurança)
            print(f"[{self.peer_id}] Baixando '{nome_arquivo}' de {peer_uri}")
            try:
                with Pyro5.api.Proxy(peer_uri) as peer_proxy:
                    conteudo = peer_proxy.get_file(nome_arquivo)
                    if conteudo:
                        save_file_content(self.peer_id, nome_arquivo, conteudo)
                        print(f"[{self.peer_id}] Download OK de '{nome_arquivo}' de {peer_uri}")
                        return
            except Exception:
                continue

    # Inicia uma eleição (com consulta ao NS)
    def iniciar_eleicao(self):
        with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
            self._elect(ns)

    # --------------------------------------------------------
    #                           CLI
    # --------------------------------------------------------

    def cli(self):
        print(f"Peer {self.peer_id} CLI. Comandos: list, listAll, add <arq>, remove <arq>, download <arq>, eleger, kill, exit")
        with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
            # Inicia thread de monitoramento de tracker (heartbeat)
            threading.Thread(target=self._heartbeat_loop, daemon=True).start()
            while True:
                cmd = input(f"[{self.peer_id}]> ").strip().split()
                if not cmd:
                    continue
                # Lista arquivos locais do peer
                if cmd[0] == "list":
                    print(list_files(self.peer_id))
                
                # Adiciona um novo arquivo local
                elif cmd[0] == "add":
                    nome = cmd[1]
                    path = os.path.join(peer_dir(self.peer_id), nome)
                    with open(path, "w") as f:
                        f.write(f"Arquivo {nome} criado por {self.peer_id}")
                    self.atualizar_tracker_arquivos(ns)
                
                # Remove arquivo local
                elif cmd[0] == "remove":
                    nome = cmd[1]
                    path = os.path.join(peer_dir(self.peer_id), nome)
                    try:
                        os.remove(path)
                        self.atualizar_tracker_arquivos(ns)
                    except FileNotFoundError:
                        print("Arquivo não existe.")
                
                # Tenta baixar arquivo dr outro peer
                elif cmd[0] == "download":
                    nome = cmd[1]
                    self.baixar_arquivo(ns, nome)
                
                # Força uma nova eleição
                elif cmd[0] == "eleger":
                    self.iniciar_eleicao()
                
                # Mostra URI do tracker atual
                elif cmd[0] == "tracker":
                    print(f"Tracker URI: {self.tracker_uri}")
                
                # "Mata" um peer
                elif cmd[0] == "kill" or cmd[0] == "exit":
                    print("Saindo...")
                    self.rodando = False
                    sys.exit(0)
                
                # Consulta todos os arquivos e seus donos
                elif cmd[0].lower() == "listall":
                    self.conectar_tracker(ns)
                    if self.tracker_proxy:
                        all_files = self.tracker_proxy.list_all_files()
                        if not all_files:
                            print("Nenhum arquivo compartilhado na rede.")
                        else:
                            print("\nArquivos compartilhados no tracker:")
                            for arquivo, peers in all_files.items():
                                print(f"  {arquivo}: {peers}")
                    else:
                        print("Tracker indisponível para consulta.")

                else:
                    print("Comando desconhecido.")

# ------------------------------------------------------------
#      Main: inicializa peer, registra no NS e inicia CLI
# ------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 peer.py <peer_id>")
        sys.exit(1)
    peer_id = sys.argv[1]
    with Pyro5.api.Daemon() as daemon, Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
        peer = Peer(peer_id)
        peer._register_in_ns(daemon, ns)
        peer.conectar_tracker(ns)
        peer.atualizar_tracker_arquivos(ns)
        # Roda o loop do Pyro5 para receber chamadas RPC neste peer
        threading.Thread(target=daemon.requestLoop, daemon=True).start()
        peer.cli()

if __name__ == "__main__":
    main()
