#!/usr/bin/env python3
"""
blockchain_chat.py
Version finale intégrée :
- Découverte automatique via multicast
- TCP P2P
- Blockchain complète (Merkle, prev_hash, validation)
- PoET automatique uniquement (pas de minage forcé)
- Affichage du mineur (peer ou vous)
- Anti-boucle (seen_tx / seen_blocks)
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
from typing import List, Tuple

# ----------------------------
# Config
# ----------------------------
TCP_PORT = 5000
MULTICAST_IP = "224.0.0.1"
MULTICAST_PORT = 5001
ANNOUNCE_INTERVAL = 2.0
CHAIN_FILE = "blockchain_data.pkl"

# ----------------------------
# Utilitaires
# ----------------------------
def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------
# Transaction
# ----------------------------
class Transaction:
    def __init__(self, tx_type: str, payload: dict):
        self.txid = str(uuid.uuid4())
        self.tx_type = tx_type  # "register" ou "chat"
        self.payload = payload
        self.timestamp = int(time.time())
        self.signature = ""

    def sign(self, privkey: str):
        self.signature = sha((self.txid + str(privkey)).encode())

    def verify_signature(self, key: str):
        expected = sha((self.txid + str(key)).encode())
        return expected == self.signature


# ----------------------------
# Merkle Tree
# ----------------------------
class MerkleTree:
    @staticmethod
    def compute_root(transactions: List['Transaction']) -> str:
        hashes = [sha(tx.txid.encode()) for tx in transactions]
        if not hashes:
            return sha(b'')
        while len(hashes) > 1:
            new = []
            for i in range(0, len(hashes), 2):
                left = hashes[i]
                right = hashes[i+1] if i+1 < len(hashes) else hashes[i]
                new.append(sha((left + right).encode()))
            hashes = new
        return hashes[0]


# ----------------------------
# Block (miner_id ajouté)
# ----------------------------
class Block:
    def __init__(self, index: int, transactions: List[Transaction], previous_hash: str, miner_id: str):
        self.index = index
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.timestamp = int(time.time())
        self.merkle_root = MerkleTree.compute_root(transactions)
        self.miner_id = miner_id  # <-- AJOUTÉ
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


# ----------------------------
# Blockchain
# ----------------------------
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
        for i, b in enumerate(chain):
            if not b.validate():
                return False
            if i > 0 and b.previous_hash != chain[i-1].current_hash:
                return False
        return True

    def replace_if_longer(self, chain: List[Block]):
        if len(chain) > len(self.chain) and self.validate_chain(chain):
            self.chain = chain
            return True
        return False


# ----------------------------
# PoET Timer
# ----------------------------
class PoETTimer:
    def __init__(self):
        self.wait_time = random.uniform(2, 6)

    def begin_wait(self):
        time.sleep(self.wait_time)


# ----------------------------
# Node
# ----------------------------
class Node:
    def __init__(self, tcp_port: int = TCP_PORT):
        self.host = self.get_local_ip()
        self.tcp_port = tcp_port
        self.node_id = f"{self.host}:{self.tcp_port}"  # <-- identifiant mineur

        self.peers = set()
        self.blockchain = Blockchain()
        self.users = {}  # pseudo -> pubkey

        self.seen_txids = set()
        self.seen_block_hashes = set()

        self.lock = threading.RLock()

        self.load_chain()

    # ---- IP locale
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

    # ---------------- TCP ----------------
    def tcp_server(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((self.host, self.tcp_port))
        sock.listen(10)
        print(f"[TCP] Serveur sur {self.node_id}")

        while True:
            client, addr = sock.accept()
            threading.Thread(target=self.handle_tcp_client, args=(client,), daemon=True).start()

    def handle_tcp_client(self, client):
        try:
            data = b''
            while True:
                part = client.recv(65536)
                if not part:
                    break
                data += part
            if not data:
                return
            obj = pickle.loads(data)
            with self.lock:
                self.process_incoming(obj)
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

    # ---------------- Multicast ----------------
    def multicast_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', MULTICAST_PORT))

        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_IP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = data.decode()
                if ":" in msg:
                    ip, port = msg.split(":")
                    peer = (ip, int(port))
                    if peer != (self.host, self.tcp_port):
                        if peer not in self.peers:
                            self.peers.add(peer)
                            self.send_tcp(peer, ("CHAIN_REQUEST", (self.host, self.tcp_port)))
            except:
                pass

    def multicast_announcer(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        ttl = struct.pack('b', 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        msg = f"{self.host}:{self.tcp_port}".encode()

        while True:
            sock.sendto(msg, (MULTICAST_IP, MULTICAST_PORT))
            time.sleep(ANNOUNCE_INTERVAL)

    # ---------------- RX objects ----------------
    def process_incoming(self, obj):
        if isinstance(obj, Transaction):
            self.handle_transaction(obj)
        elif isinstance(obj, Block):
            self.handle_block(obj)
        elif isinstance(obj, tuple):
            t, data = obj
            if t == "CHAIN_REQUEST":
                requester = data
                self.send_tcp(requester, ("CHAIN_RESPONSE", self.blockchain.chain))
            elif t == "CHAIN_RESPONSE":
                self.handle_chain_response(data)

    # ---------------- Transactions ----------------
    def handle_transaction(self, tx):
        # anti boucle
        if tx.txid in self.seen_txids:
            return

        self.seen_txids.add(tx.txid)

        # --- Register ---
        if tx.tx_type == "register":
            pseudo = tx.payload["pseudo"]
            pubkey = tx.payload["pubkey"]
            self.users[pseudo] = pubkey
            self.blockchain.add_transaction(tx)
            self.broadcast(tx)
            return

        # --- Chat message ---
        if tx.tx_type == "chat":
            sender = tx.payload["sender"]
            content = tx.payload["content"]

            if sender in self.users:
                print(f"\n🔔 Nouveau message reçu de {sender} : {content}\n>> ", end="")
                self.blockchain.add_transaction(tx)
                self.broadcast(tx)

    # ---------------- Bloc ----------------
    def handle_block(self, block: Block):
        if block.current_hash in self.seen_block_hashes:
            return

        if not block.validate():
            return

        # chaînage correct ?
        if block.index == len(self.blockchain.chain):
            # bloc attendu
            self.seen_block_hashes.add(block.current_hash)
            self.blockchain.chain.append(block)

            # AFFICHAGE DU MINEUR
            print(f"\n⛏️ Bloc reçu (miner={block.miner_id}) : idx={block.index}, txs={len(block.transactions)}\n>> ", end="")

            self.broadcast(block)
            self.save_chain()
        else:
            # On attend une synchro (les nodes demanderont la chaîne)
            pass

    # ---------------- Chain response ----------------
    def handle_chain_response(self, chain):
        if self.blockchain.replace_if_longer(chain):
            self.seen_block_hashes = {b.current_hash for b in chain}
            print(f"\n[SYNC] Chaîne mise à jour (longueur={len(chain)})\n>> ", end="")
            self.save_chain()

    # ---------------- Diffusion ----------------
    def broadcast(self, obj):
        for peer in list(self.peers):
            threading.Thread(target=self.send_tcp, args=(peer, obj), daemon=True).start()

    # ---------------- Mining automatique (PoET) ----------------
    def auto_mine(self):
        while True:
            time.sleep(1)
            with self.lock:
                if not self.blockchain.mempool:
                    continue

            # attente PoET
            poet = PoETTimer()
            poet.begin_wait()

            with self.lock:
                block = self.blockchain.create_block(self.node_id)
                if block:
                    self.seen_block_hashes.add(block.current_hash)

                    print(f"\n⛏️ Bloc miné par VOUS ({self.node_id}) : idx={block.index}, txs={len(block.transactions)}\n>> ", end="")

                    self.broadcast(block)
                    self.save_chain()

    # ---------------- Persistence ----------------
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
                        self.seen_block_hashes = {b.current_hash for b in chain}
                        print(f"[LOAD] Blockchain chargée : {len(chain)} blocs")
            except:
                pass

    # ---------------- User actions ----------------
    def register_user(self, pseudo):
        priv = random.randint(100000, 999999)
        pub = priv
        tx = Transaction("register", {"pseudo": pseudo, "pubkey": pub})
        tx.sign(priv)

        self.seen_txids.add(tx.txid)
        self.users[pseudo] = pub
        self.blockchain.add_transaction(tx)
        self.broadcast(tx)
        print(f"[LOCAL] Utilisateur '{pseudo}' enregistré.")

    def send_chat(self, pseudo, content):
        if pseudo not in self.users:
            print("Pseudo inconnu.")
            return
        tx = Transaction("chat", {"sender": pseudo, "content": content})
        tx.sign(self.users[pseudo])
        self.seen_txids.add(tx.txid)
        self.blockchain.add_transaction(tx)
        self.broadcast(tx)
        print(f"[YOU] {pseudo}: {content}")

    # ---------------- Start ----------------
    def start(self):
        threading.Thread(target=self.tcp_server, daemon=True).start()
        threading.Thread(target=self.multicast_listener, daemon=True).start()
        threading.Thread(target=self.multicast_announcer, daemon=True).start()
        threading.Thread(target=self.auto_mine, daemon=True).start()


# ----------------------------
# Interface terminale
# ----------------------------
def repl(node: Node):
    print("\n=== Terminal Node ===\n")
    print("Commandes :")
    print("/register <pseudo>")
    print("/msg <pseudo> <texte>")
    print("/users")
    print("/peers")
    print("/blockchain")
    print("/exit\n")

    while True:
        cmd = input(">> ").strip()
        if not cmd:
            continue

        if cmd.startswith("/register "):
            _, pseudo = cmd.split(maxsplit=1)
            node.register_user(pseudo)

        elif cmd.startswith("/msg "):
            parts = cmd.split(maxsplit=2)
            if len(parts) < 3:
                print("Usage: /msg <pseudo> <texte>")
                continue
            _, pseudo, text = parts
            node.send_chat(pseudo, text)

        elif cmd == "/users":
            print("Utilisateurs :", list(node.users.keys()))

        elif cmd == "/peers":
            print("Pairs :", list(node.peers))

        elif cmd == "/blockchain":
            for b in node.blockchain.chain:
                print(f" - idx={b.index}, miner={b.miner_id}, txs={len(b.transactions)}")

        elif cmd == "/exit":
            print("Sortie…")
            break

        else:
            print("Commande invalide.")


# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    node = Node()
    node.start()
    repl(node)
