import Pyro5.api

class Tracker:
    def __init__(self, epoch):
        self.epoch = epoch # Época do tracker.
        self.file_index = {}  # Index de arquivos.
    
    # Registra a lista de arquivos que um peer possui localmente.
    # Chamado sempre que um peer sobe ou um novo tracker é eleito.
    @Pyro5.api.expose
    def register_files(self, peer_uri, file_list):
        # Remove peer dos arquivos antigos
        for peers in self.file_index.values():
            if peer_uri in peers:
                peers.remove(peer_uri)
        # Adiciona novos arquivos
        for f in file_list:
            self.file_index.setdefault(f, []).append(peer_uri)
        # Remover URIs duplicados
        for k in self.file_index:
            self.file_index[k] = list(set(self.file_index[k]))
    
    # Chamado sempre que um peer cria/adiciona um novo arquivo local
    @Pyro5.api.expose
    def update_file_add(self, peer_uri, filename):
        self.file_index.setdefault(filename, []).append(peer_uri)
    
    # Chamado sempre que um peer remove/deleta um arquivo local
    @Pyro5.api.expose
    def update_file_remove(self, peer_uri, filename):
        peers = self.file_index.get(filename, [])
        if peer_uri in peers:
            peers.remove(peer_uri)
        if not peers:
            del self.file_index[filename]

    # Retorna a lista de peers que possuem o arquivo pesquisado.
    @Pyro5.api.expose
    def who_has(self, filename):
        return self.file_index.get(filename, [])

    # Heartbeat.
    # Verificação periódica da disponibilidade do tracker.
    @Pyro5.api.expose
    def heartbeat(self):
        return True
    
    # Mostra todos os arquivos compartilhados na rede e quem possui cada um deles.
    @Pyro5.api.expose
    def list_all_files(self):
        return self.file_index

