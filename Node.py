import socket
import threading
import pickle
import time
import hashlib
import random
import struct
from typing import List

# ========================
# USER ET TRANSACTIONS
# ========================
class User:
    def __init__(self, pseudo: str, pubkey: int, privkey: int):
        self.pseudo = pseudo
        self.pubkey = pubkey
        self.privkey = privkey

class Transaction:
    def __init__(self, tx_id: str, timestamp: int, signature: str = ""):
        self.tx_id = tx_id
        self.timestamp = timestamp
        self.signature = signature

    def sign(self, privkey: int):
        self.signature = hashlib.sha256(f"{self.tx_id}{privkey}".encode()).hexdigest()

    def check_transaction(self) -> bool:
        return bool(self.signature)

class UserRegister(Transaction):
    def __init__(self, pseudo: str, pubkey: int, timestamp: int):
        super().__init__(f"register-{pseudo}", timestamp)
        self.pseudo = pseudo
        self.pubkey = pubkey

class ChatMessage(Transaction):
    def __init__(self, sender_pseudo: str, content: str, timestamp: int):
        super().__init__(f"msg-{sender_pseudo}-{timestamp}", timestamp)
        self.sender_pseudo = sender_pseudo
        self.content = content

# ========================
# BLOCK ET BLOCKCHAIN
# ========================
class MerkleTree:
    def __init__(self, transactions: List[Transaction]):
        self.leaves = [hashlib.sha256(tx.tx_id.encode()).hexdigest() for tx in transactions]
        self.root = self.compute_root()

    def compute_root(self):
        nodes = self.leaves.copy()
        if not nodes:
            return ""
        while len(nodes) > 1:
            temp = []
            for i in range(0, len(nodes), 2):
                left = nodes[i]
                right = nodes[i+1] if i+1 < len(nodes) else nodes[i]
                temp.append(hashlib.sha256((left+right).encode()).hexdigest())
            nodes = temp
        return nodes[0]

class Block:
    def __init__(self, index: int, transactions: List[Transaction], previous_hash: str = ""):
        self.index = index
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.timestamp = int(time.time())
        self.merkle_tree = MerkleTree(transactions)
        self.block_hash = self.compute_hash()

    def compute_hash(self):
        return hashlib.sha256(f"{self.index}{self.previous_hash}{self.timestamp}{self.merkle_tree.root}".encode()).hexdigest()

class Blockchain:
    def __init__(self):
        self.chain: List[Block] = []
        self.mempool: List[Transaction] = []

    def add_transaction(self, tx: Transaction):
        if tx.check_transaction() and tx not in self.mempool:
            self.mempool.append(tx)

    def create_block(self):
        if not self.mempool:
            return None
        index = len(self.chain)
        previous_hash = self.chain[-1].block_hash if self.chain else "0"
        block = Block(index, self.mempool.copy(), previous_hash)
        self.mempool.clear()
        self.chain.append(block)
        return block

# ========================
# POET TIMER
# ========================
class PoETTimer:
    def __init__(self):
        self.wait_time = random.randint(1, 5)

    def begin_wait(self):
        time.sleep(self.wait_time)

# ========================
# NODE P2P AUTONOME
# ========================
MULTICAST_IP = "224.0.0.1"
MULTICAST_PORT = 5001
TCP_PORT = 5000

class Node:
    def __init__(self, host="0.0.0.0"):
        self.host = host
        self.tcp_port = TCP_PORT
        self.peers = set()  # set of (ip, port)
        self.blockchain = Blockchain()
        self.users = {}
        self.lock = threading.Lock()
        self.poet = PoETTimer()

    # ------------------------
    # TCP LISTEN
    # ------------------------
    def listen_tcp(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.host, self.tcp_port))
        server.listen()
        print(f"[TCP] Listening on {self.host}:{self.tcp_port}")
        while True:
            client, addr = server.accept()
            threading.Thread(target=self.handle_tcp_client, args=(client,), daemon=True).start()

    def handle_tcp_client(self, client):
        try:
            data = client.recv(65536)
            obj = pickle.loads(data)
            with self.lock:
                if isinstance(obj, Transaction):
                    self.receive_transaction(obj)
                elif isinstance(obj, Block):
                    self.receive_block(obj)
                elif isinstance(obj, tuple):
                    peer = obj
                    if peer not in self.peers and peer != (self.host, self.tcp_port):
                        self.peers.add(peer)
                        self.send_chain(peer)
        except:
            pass
        finally:
            client.close()

    def broadcast(self, obj):
        for peer in self.peers:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(peer)
                s.send(pickle.dumps(obj))
                s.close()
            except:
                continue

    # ------------------------
    # TRANSACTIONS ET BLOCS
    # ------------------------
    def receive_transaction(self, tx: Transaction):
        if isinstance(tx, UserRegister) and tx.pseudo not in self.users:
            self.users[tx.pseudo] = User(tx.pseudo, tx.pubkey, 0)
            print(f"[Node] Nouvel utilisateur inscrit: {tx.pseudo}")
            self.blockchain.add_transaction(tx)
            self.broadcast(tx)
        elif isinstance(tx, ChatMessage):
            if tx.sender_pseudo in self.users:
                print(f"[Node] Nouveau message de {tx.sender_pseudo}: {tx.content}")
                self.blockchain.add_transaction(tx)
                self.broadcast(tx)

    def receive_block(self, block: Block):
        if not self.blockchain.chain or block.index > self.blockchain.chain[-1].index:
            self.blockchain.chain.append(block)
            print(f"[Node] Nouveau bloc reçu: index={block.index}, tx={len(block.transactions)}")
            self.broadcast(block)

    def send_message(self, user: User, content: str):
        timestamp = int(time.time())
        msg = ChatMessage(user.pseudo, content, timestamp)
        msg.sign(user.privkey)
        self.blockchain.add_transaction(msg)
        self.broadcast(msg)

    def register_user(self, user: User):
        tx = UserRegister(user.pseudo, user.pubkey, int(time.time()))
        tx.sign(user.privkey)
        self.users[user.pseudo] = user
        self.blockchain.add_transaction(tx)
        self.broadcast(tx)

    # ------------------------
    # MINAGE
    # ------------------------
    def mine_block(self):
        self.poet.begin_wait()
        with self.lock:
            block = self.blockchain.create_block()
            if block:
                print(f"[Node] Bloc miné: index={block.index}, tx={len(block.transactions)}")
                self.broadcast(block)

    # ------------------------
    # SYNCHRONISATION
    # ------------------------
    def send_chain(self, peer):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(peer)
            s.send(pickle.dumps(self.blockchain.chain))
            s.close()
        except:
            pass

    def receive_chain(self, chain: List[Block]):
        with self.lock:
            if len(chain) > len(self.blockchain.chain):
                self.blockchain.chain = chain
                print(f"[Node] Blockchain synchronisée. Taille={len(chain)}")

    # ------------------------
    # MULTICAST LAN POUR DISCOVERY
    # ------------------------
    def listen_multicast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_IP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while True:
            data, addr = sock.recvfrom(1024)
            peer_ip = addr[0]
            if peer_ip != self.host:
                self.peers.add((peer_ip, TCP_PORT))
                # reply with our address
                sock.sendto(f"{self.host}:{TCP_PORT}".encode(), addr)

    def announce_multicast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        ttl = struct.pack('b', 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        while True:
            sock.sendto(f"{self.host}:{TCP_PORT}".encode(), (MULTICAST_IP, MULTICAST_PORT))
            time.sleep(2)

# ========================
# INTERFACE TERMINAL
# ========================
def main():
    node = Node()
    threading.Thread(target=node.listen_tcp, daemon=True).start()
    threading.Thread(target=node.listen_multicast, daemon=True).start()
    threading.Thread(target=node.announce_multicast, daemon=True).start()

    pseudo = input("Pseudo utilisateur: ")
    user = User(pseudo, random.randint(1000,9999), random.randint(1000,9999))
    node.register_user(user)

    print("\n=== Terminal Node ===")
    print("Commands:")
    print("/msg <message> -> envoyer message")
    print("/blockchain -> afficher blockchain")
    print("/users -> afficher utilisateurs")
    print("/mine -> miner bloc")
    print("/exit -> quitter\n")

    while True:
        cmd = input(">> ")
        if cmd.startswith("/msg "):
            node.send_message(user, cmd[5:])
        elif cmd == "/blockchain":
            with node.lock:
                for b in node.blockchain.chain:
                    print(f"[{b.index}] prev={b.previous_hash[:6]} root={b.merkle_tree.root[:6]} tx={len(b.transactions)}")
        elif cmd == "/users":
            with node.lock:
                print("Utilisateurs:", list(node.users.keys()))
        elif cmd == "/mine":
            threading.Thread(target=node.mine_block).start()
        elif cmd == "/exit":
            break
        else:
            print("Commande inconnue")

if __name__ == "__main__":
    main()
