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
        self.uri = None
        self.tracker_uri = None
        self.tracker_proxy = None
        self.epoch = 0
        self.is_tracker = False
        self.voted_for = {}
        self.rodando = True
        self.heartbeat_timeout = 0.4
        self.election_in_progress = False
        self.election_lock = threading.Lock()
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

    @Pyro5.api.expose
    def solicitar_voto(self, epoch, candidato_id):
        if self.voted_for.get(epoch):
            return False
        self.voted_for[epoch] = candidato_id
        return True

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

    @Pyro5.api.expose
    def notify_election_started(self, candidato_id):
        # Notificação recebida de que uma eleição começou
        print(f"\n[!] Eleição iniciada pelo peer {candidato_id}")
        with self.election_lock:
            self.election_in_progress = True

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

    def _register_in_ns(self, daemon, ns):
        obj_name = f"peer.{self.peer_id}"
        self.uri = daemon.register(self)
        ns.register(obj_name, self.uri)
        print(f"[{self.peer_id}] Registrado no NS como {obj_name}")

    def _find_tracker(self, ns):
        for name, uri in ns.list(prefix="tracker.").items():
            return uri
        return None

    def _notify_all_peers(self, ns, method, *args):
        for name, uri in ns.list(prefix="peer.").items():
            try:
                with Pyro5.api.Proxy(uri) as proxy:
                    getattr(proxy, method)(*args)
            except Exception:
                continue

    def _heartbeat_loop(self):
        # Pequeno delay ao iniciar para dar tempo dos peers subirem e do tracker se registrar
        time.sleep(random.uniform(0.5, 2.0))
        while self.rodando and not self.is_tracker:
            wait_time = random.uniform(0.2, 0.4)
            try:
                # Sempre tenta buscar tracker do NS antes de declarar morte do tracker
                with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
                    self.conectar_tracker(ns)
                if self.tracker_proxy:
                    try:
                        self.tracker_proxy.heartbeat()
                        time.sleep(wait_time)
                    except Exception as e:
                        print(f"\n[{self.peer_id}] Tracker off! ({type(e).__name__}: {e}) Iniciando eleição...")
                        self.tracker_proxy = None
                        self.tracker_uri = None
                        self.iniciar_eleicao()
                else:
                    # Se não há tracker, espera um pouco antes de tentar eleição (não dispara na largada)
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

    def _elect(self, ns):
        with self.election_lock:
            if self.election_in_progress:
                print(f"[{self.peer_id}] Eleição já em andamento. Ignorando novo disparo.")
                return
            self.election_in_progress = True
        # Notifica todos que a eleição foi iniciada
        self._notify_all_peers(ns, "notify_election_started", self.peer_id)

        peers = [uri for name, uri in ns.list(prefix="peer.").items() if name != f"peer.{self.peer_id}"]
        votos_true = 1  # vota em si
        respondentes = 1
        lock = threading.Lock()

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
        for t in threads:
            t.join(timeout=0.6)
        print(f"[{self.peer_id}] Votos: {votos_true} de {respondentes} peers online")
        if votos_true > respondentes // 2:
            self.epoch += 1
            self.virar_tracker(ns)
            self._notify_all_peers(ns, "notify_election_result", self.peer_id, self.epoch)
        else:
            print(f"[{self.peer_id}] Não conseguiu maioria.")
            # Finaliza eleição em andamento
            with self.election_lock:
                self.election_in_progress = False

    def virar_tracker(self, ns):
        self.is_tracker = True
        daemon = Pyro5.api.Daemon()
        tracker = Tracker(self.epoch)
        tracker_uri = daemon.register(tracker)
        tracker_name = f"tracker.{self.epoch}"
        ns.register(tracker_name, tracker_uri)
        print(f"[{self.peer_id}] Virei Tracker! Registrado como {tracker_name}")
        threading.Thread(target=daemon.requestLoop, daemon=True).start()

    def conectar_tracker(self, ns):
        tracker_uri = self._find_tracker(ns)
        if tracker_uri:
            self.tracker_proxy = Pyro5.api.Proxy(tracker_uri)
            self.tracker_uri = tracker_uri
        else:
            self.tracker_proxy = None
            self.tracker_uri = None

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

    def baixar_arquivo(self, ns, nome_arquivo):
        self.conectar_tracker(ns)
        peers = []
        if self.tracker_proxy:
            peers = self.tracker_proxy.who_has(nome_arquivo)
            print(f"[{self.peer_id}] URIs retornadas pelo tracker para {nome_arquivo}: {peers}")
        for peer_uri in peers:
            if peer_uri == str(self.uri):
                continue
            if "tracker" in peer_uri:
                continue
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

    def iniciar_eleicao(self):
        with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
            self._elect(ns)

    def cli(self):
        print(f"Peer {self.peer_id} CLI. Comandos: list, listAll, add <arq>, remove <arq>, download <arq>, eleger, kill, exit")
        with Pyro5.api.locate_ns(host=NS_HOST, port=NS_PORT) as ns:
            threading.Thread(target=self._heartbeat_loop, daemon=True).start()
            while True:
                cmd = input(f"[{self.peer_id}]> ").strip().split()
                if not cmd:
                    continue
                if cmd[0] == "list":
                    print(list_files(self.peer_id))
                elif cmd[0] == "add":
                    nome = cmd[1]
                    path = os.path.join(peer_dir(self.peer_id), nome)
                    with open(path, "w") as f:
                        f.write(f"Arquivo {nome} criado por {self.peer_id}")
                    self.atualizar_tracker_arquivos(ns)
                elif cmd[0] == "remove":
                    nome = cmd[1]
                    path = os.path.join(peer_dir(self.peer_id), nome)
                    try:
                        os.remove(path)
                        self.atualizar_tracker_arquivos(ns)
                    except FileNotFoundError:
                        print("Arquivo não existe.")
                elif cmd[0] == "download":
                    nome = cmd[1]
                    self.baixar_arquivo(ns, nome)
                elif cmd[0] == "eleger":
                    self.iniciar_eleicao()
                elif cmd[0] == "tracker":
                    print(f"Tracker URI: {self.tracker_uri}")
                elif cmd[0] == "kill" or cmd[0] == "exit":
                    print("Saindo...")
                    self.rodando = False
                    sys.exit(0)
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
        threading.Thread(target=daemon.requestLoop, daemon=True).start()
        peer.cli()

if __name__ == "__main__":
    main()
