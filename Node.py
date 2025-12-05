"""
blockchain_chat.py
Version ultime pour ton projet :
- Découverte automatique via multicast
- Réseau TCP P2P
- Blockchain complète : blocs, merkle root, previous hash, validation
- PoET automatique (pas de minage forcé)
- Affichage du mineur du bloc (vous ou un pair)
- Anti-boucle messages et blocs
- Notifications uniquement pour les messages chat
- Interface terminale
"""

import socket
import struct
import threading
import pickle
import time
import hashlib
import random
import uuid
import os
from typing import List

# ======================
# CONFIG
# ======================
TCP_PORT = 5000
MULTICAST_IP = "224.0.0.1"
MULTICAST_PORT = 5001
ANNOUNCE_INTERVAL = 2
CHAIN_FILE = "blockchain.pickle"


# ======================
# UTIL
# ======================
def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ======================
# TRANSACTION
# ======================
class Transaction:
    def __init__(self, tx_type: str, payload: dict):
        self.txid = str(uuid.uuid4())
        self.tx_type = tx_type          # "register" | "chat"
        self.payload = payload
        self.timestamp = int(time.time())
        self.signature = ""

    def sign(self, privkey: str):
        self.signature = sha((self.txid + str(privkey)).encode())

    def verify_signature(self, key: str):
        return sha((self.txid + str(key)).encode()) == self.signature


# ======================
# MERKLE TREE
# ======================
class MerkleTree:
    @staticmethod
    def compute_root(transactions: List[Transaction]) -> str:
        if not transactions:
            return sha(b'')

        nodes = [sha(tx.txid.encode()) for tx in transactions]

        while len(nodes) > 1:
            new = []
            for i in range(0, len(nodes), 2):
                left = nodes[i]
                right = nodes[i+1] if i+1 < len(nodes) else left
                new.append(sha((left + right).encode()))
            nodes = new

        return nodes[0]


# ======================
# BLOCK
# ======================
class Block:
    def __init__(self, index: int, transactions: List[Transaction], previous_hash: str, miner_id: str):
        self.index = index
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.timestamp = int(time.time())
        self.merkle_root = MerkleTree.compute_root(transactions)
        self.miner_id = miner_id
        self.nonce = 0
        self.current_hash = self.compute_hash()

    def compute_hash(self):
        header = f"{self.index}|{self.previous_hash}|{self.timestamp}|{self.merkle_root}|{self.miner_id}|{self.nonce}"
        return sha(header.encode())

    def validate(self):
        if self.merkle_root != MerkleTree.compute_root(self.transactions):
            return False
        if self.current_hash != self.compute_hash():
            return False
        return True


# ======================
# BLOCKCHAIN
# ======================
class Blockchain:
    def __init__(self):
        self.chain: List[Block] = []
        self.mempool: List[Transaction] = []

    def add_transaction(self, tx: Transaction):
        if tx not in self.mempool:
            self.mempool.append(tx)

    def create_block(self, miner_id: str):
        if not self.mempool:
            return None

        idx = len(self.chain)
        prev = self.chain[-1].current_hash if self.chain else "0"*64
        block = Block(idx, self.mempool.copy(), prev, miner_id)

        self.mempool.clear()
        self.chain.append(block)
        return block

    def validate_chain(self, chain: List[Block]):
        for i, blk in enumerate(chain):
            if not blk.validate():
                return False
            if i > 0 and blk.previous_hash != chain[i-1].current_hash:
                return False
        return True

    def replace_if_longer(self, chain: List[Block]):
        if len(chain) > len(self.chain) and self.validate_chain(chain):
            self.chain = chain
            return True
        return False


# ======================
# PoET TIMER
# ======================
class PoETTimer:
    def __init__(self):
        self.wait = random.uniform(2, 6)

    def begin_wait(self):
        time.sleep(self.wait)


# ======================
# NODE
# ======================
class Node:
    def __init__(self):
        self.host = self.get_local_ip()
        self.tcp_port = TCP_PORT
        self.node_id = f"{self.host}:{self.tcp_port}"

        self.peers = set()
        self.blockchain = Blockchain()
        self.users = {}  # pseudo -> key

        self.seen_tx = set()
        self.seen_blocks = set()

        self.lock = threading.RLock()

        self.load_chain()

    # -------------------
    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except:
            ip = "127.0.0.1"
        s.close()
        return ip

    # ======================
    # TCP SERVER
    # ======================
    def tcp_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((self.host, self.tcp_port))
        s.listen(10)
        print(f"[TCP] Serveur actif sur {self.node_id}")

        while True:
            c, addr = s.accept()
            threading.Thread(target=self.handle_client, args=(c,), daemon=True).start()

    def handle_client(self, client):
        try:
            data = b''
            while True:
                p = client.recv(65536)
                if not p:
                    break
                data += p
            if not data:
                return
            obj = pickle.loads(data)
            with self.lock:
                self.receive_object(obj)
        finally:
            client.close()

    def send_tcp(self, peer, obj):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(peer)
            s.sendall(pickle.dumps(obj))
            s.close()
        except:
            pass

    # ======================
    # MULTICAST
    # ======================
    def multicast_listener(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', MULTICAST_PORT))

        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_IP), socket.INADDR_ANY)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        while True:
            try:
                data, addr = s.recvfrom(1024)
                msg = data.decode()
                if ":" in msg:
                    ip, port = msg.split(":")
                    peer = (ip, int(port))
                    if peer != (self.host, self.tcp_port) and peer not in self.peers:
                        self.peers.add(peer)
                        self.send_tcp(peer, ("CHAIN_REQUEST", (self.host, self.tcp_port)))
            except:
                pass

    def multicast_announcer(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        ttl = struct.pack("b", 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        msg = f"{self.host}:{self.tcp_port}".encode()

        while True:
            s.sendto(msg, (MULTICAST_IP, MULTICAST_PORT))
            time.sleep(ANNOUNCE_INTERVAL)

    # ======================
    # RECEPTION OBJETS
    # ======================
    def receive_object(self, obj):
        if isinstance(obj, Transaction):
            self.handle_tx(obj)

        elif isinstance(obj, Block):
            self.handle_block(obj)

        elif isinstance(obj, tuple):
            act, data = obj
            if act == "CHAIN_REQUEST":
                requester = data
                self.send_tcp(requester, ("CHAIN_RESPONSE", self.blockchain.chain))
            elif act == "CHAIN_RESPONSE":
                self.handle_chain_response(data)

    # ======================
    # TRANSACTIONS
    # ======================
    def handle_tx(self, tx):
        if tx.txid in self.seen_tx:
            return

        self.seen_tx.add(tx.txid)

        # register
        if tx.tx_type == "register":
            pseudo = tx.payload["pseudo"]
            pubkey = tx.payload["pubkey"]
            self.users[pseudo] = pubkey
            self.blockchain.add_transaction(tx)
            self.broadcast(tx)
            return

        # chat
        if tx.tx_type == "chat":
            sender = tx.payload["sender"]
            content = tx.payload["content"]
            if sender in self.users:
                print(f"\n🔔 Nouveau message reçu de {sender} : {content}\n>> ", end="")
                self.blockchain.add_transaction(tx)
                self.broadcast(tx)

    # ======================
    # BLOC
    # ======================
    def handle_block(self, block):
        if block.current_hash in self.seen_blocks:
            return

        if not block.validate():
            return

        if block.index == len(self.blockchain.chain):
            self.seen_blocks.add(block.current_hash)
            self.blockchain.chain.append(block)

            print(f"\n⛏️ Bloc reçu miné par {block.miner_id} : idx={block.index}, txs={len(block.transactions)}\n>> ", end="")

            self.broadcast(block)
            self.save_chain()

    def handle_chain_response(self, chain):
        if self.blockchain.replace_if_longer(chain):
            self.seen_blocks = {b.current_hash for b in chain}
            print(f"\n[SYNC] Blockchain mise à jour ({len(chain)} blocs)\n>> ", end="")
            self.save_chain()

    # ======================
    # DIFFUSION
    # ======================
    def broadcast(self, obj):
        for p in list(self.peers):
            threading.Thread(target=self.send_tcp, args=(p, obj), daemon=True).start()

    # ======================
    # MINAGE AUTOMATIQUE
    # ======================
    def auto_mine(self):
        while True:
            time.sleep(1)

            if not self.blockchain.mempool:
                continue

            poet = PoETTimer()
            poet.begin_wait()

            with self.lock:
                block = self.blockchain.create_block(self.node_id)
                if block:
                    self.seen_blocks.add(block.current_hash)

                    print(f"\n⛏️ Bloc miné par VOUS ({self.node_id}) : idx={block.index}, txs={len(block.transactions)}\n>> ", end="")
                    self.broadcast(block)
                    self.save_chain()

    # ======================
    # PERSISTENCE
    # ======================
    def save_chain(self):
        try:
            with open(CHAIN_FILE, "wb") as f:
                pickle.dump(self.blockchain.chain, f)
        except:
            pass

    def load_chain(self):
        if os.path.exists(CHAIN_FILE):
            try:
                with open(CHAIN_FILE, "rb") as f:
                    chain = pickle.load(f)
                if self.blockchain.validate_chain(chain):
                    self.blockchain.chain = chain
                    self.seen_blocks = {b.current_hash for b in chain}
                    print(f"[LOAD] Blockchain chargée ({len(chain)} blocs)")
            except:
                pass

    # ======================
    # ACTIONS USER
    # ======================
    def register_user(self, pseudo):
        priv = random.randint(100000, 999999)
        pub = priv

        tx = Transaction("register", {"pseudo": pseudo, "pubkey": pub})
        tx.sign(priv)

        self.seen_tx.add(tx.txid)
        self.users[pseudo] = pub
        self.blockchain.add_transaction(tx)
        self.broadcast(tx)

        print(f"[LOCAL] Utilisateur '{pseudo}' enregistré.")

    def send_chat(self, pseudo, content):
        if pseudo not in self.users:
            print("Ce pseudo n'est pas enregistré.")
            return

        tx = Transaction("chat", {"sender": pseudo, "content": content})
        tx.sign(self.users[pseudo])

        self.seen_tx.add(tx.txid)
        self.blockchain.add_transaction(tx)
        self.broadcast(tx)

        print(f"[YOU] {pseudo}: {content}")

    # ======================
    # START
    # ======================
    def start(self):
        threading.Thread(target=self.tcp_server, daemon=True).start()
        threading.Thread(target=self.multicast_listener, daemon=True).start()
        threading.Thread(target=self.multicast_announcer, daemon=True).start()
        threading.Thread(target=self.auto_mine, daemon=True).start()


# ======================
# TERMINAL UI
# ======================
def repl(node: Node):
    print("\n=== Terminal Blockchain Chat ===")
    print("/register <pseudo>")
    print("/msg <pseudo> <texte>")
    print("/users")
    print("/peers")
    print("/blockchain")
    print("/exit\n")

    while True:
        cmd = input(">> ").strip()

        if cmd.startswith("/register "):
            node.register_user(cmd.split(" ", 1)[1])

        elif cmd.startswith("/msg "):
            parts = cmd.split(" ", 2)
            if len(parts) < 3:
                print("Usage : /msg <pseudo> <texte>")
            else:
                node.send_chat(parts[1], parts[2])

        elif cmd == "/users":
            print("Utilisateurs :", list(node.users.keys()))

        elif cmd == "/peers":
            print("Pairs :", list(node.peers))

        elif cmd == "/blockchain":
            chain = node.blockchain.chain
            print(f"\nBlockchain complète ({len(chain)} blocs) :\n")

            for b in chain:
                print("────────────────────────────────────────")
                print(f"Bloc #{b.index}")
                print(f"• Miner        : {b.miner_id}")
                print(f"• Timestamp    : {b.timestamp}")
                print(f"• Prev Hash    : {b.previous_hash}")
                print(f"• Merkle Root  : {b.merkle_root}")
                print(f"• Hash         : {b.current_hash}")
                print(f"• Tx count     : {len(b.transactions)}")

                if b.transactions:
                    print("  Transactions :")
                    for tx in b.transactions:
                        print("   -----------------------")
                        print(f"   - TXID  : {tx.txid}")
                        print(f"   - Type  : {tx.tx_type}")
                        print(f"   - Time  : {tx.timestamp}")

                        if tx.tx_type == "register":
                            print(f"   - User  : {tx.payload['pseudo']}")
                            print(f"   - PubKey: {tx.payload['pubkey']}")

                        elif tx.tx_type == "chat":
                            print(f"   - From  : {tx.payload['sender']}")
                            print(f"   - Msg   : {tx.payload['content']}")

                        print(f"   - Signature : {tx.signature}")
                else:
                    print("  (Aucune transaction)")

                print("────────────────────────────────────────\n")

        elif cmd == "/exit":
            print("Sortie…")
            break

        else:
            print("Commande inconnue.")


# ======================
# MAIN
# ======================
if __name__ == "__main__":
    node = Node()
    node.start()
    repl(node)
