import Pyro5.api

class Tracker:
    def __init__(self, epoch):
        self.epoch = epoch
        self.file_index = {}  # nome_arquivo: [peer_uris]
    
    @Pyro5.api.expose
    def register_files(self, peer_uri, file_list):
        """Atualiza índice dos arquivos compartilhados por cada peer"""
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
    
    @Pyro5.api.expose
    def update_file_add(self, peer_uri, filename):
        self.file_index.setdefault(filename, []).append(peer_uri)
    
    @Pyro5.api.expose
    def update_file_remove(self, peer_uri, filename):
        peers = self.file_index.get(filename, [])
        if peer_uri in peers:
            peers.remove(peer_uri)
        if not peers:
            del self.file_index[filename]

    @Pyro5.api.expose
    def who_has(self, filename):
        """Retorna peers com o arquivo"""
        return self.file_index.get(filename, [])

    @Pyro5.api.expose
    def heartbeat(self):
        """Heartbeat do tracker"""
        return True
    
    @Pyro5.api.expose
    def list_all_files(self):
        """
        Retorna um dicionário {nome_arquivo: [peer_uris]}
        """
        return self.file_index

