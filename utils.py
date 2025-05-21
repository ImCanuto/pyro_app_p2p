import os

# Retorna o caminho do diretório onde um peer armazena seus arquivos.
def peer_dir(peer_id):
    return os.path.join("compartilhados", peer_id)

# Lista todos os arquivos do diretório do peer passado como parâmetro.
# Se o diretório não existir, ele é criado na hora.
def list_files(peer_id):
    dirpath = peer_dir(peer_id)
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)
    return [f for f in os.listdir(dirpath) if os.path.isfile(os.path.join(dirpath, f)) and not f.startswith('.')]

# Lê e retorna o conteúdo de um arquivo pertencente ao peer.
# Usada para atender solicitações de download vindas de outros peers.
def get_file_content(peer_id, filename):
    with open(os.path.join(peer_dir(peer_id), filename), "rb") as f:
        return f.read()

# Salva o conteúdo recebido (download) no diretório do peer.
def save_file_content(peer_id, filename, content):
    path = os.path.join(peer_dir(peer_id), filename)
    with open(path, "wb") as f:
        if isinstance(content, bytes):
            f.write(content)
        else:
            f.write(content.encode())
