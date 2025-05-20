import os

def peer_dir(peer_id):
    return os.path.join("compartilhados", peer_id)

def list_files(peer_id):
    dirpath = peer_dir(peer_id)
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)
    return [f for f in os.listdir(dirpath) if os.path.isfile(os.path.join(dirpath, f)) and not f.startswith('.')]

def get_file_content(peer_id, filename):
    with open(os.path.join(peer_dir(peer_id), filename), "rb") as f:
        return f.read()

def save_file_content(peer_id, filename, content):
    path = os.path.join(peer_dir(peer_id), filename)
    with open(path, "wb") as f:
        if isinstance(content, bytes):
            f.write(content)
        else:
            # Se for string (improvável), converte para bytes
            f.write(content.encode())
