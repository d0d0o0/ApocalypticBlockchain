"""
blockchain_chat.py
Blockchain P2P avec chat décentralisé
- Découverte automatique via multicast
- Réseau TCP P2P
- Blockchain complète : blocs, merkle root, previous hash, validation
- PoET automatique (Proof of Elapsed Time)
- Signatures Ed25519 pour authentification
- Consensus sur les pseudos (premier arrivé dans la blockchain)
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
from typing import List, Optional
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

MIN_TX_COUNT=3

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
        self.tx_type = tx_type
        self.payload = payload
        self.timestamp = int(time.time())
        self.signature = None
        self.pubkey = None

    def sign(self, private_key: Ed25519PrivateKey):
        self.pubkey = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw
        )
        message = (self.txid + str(self.payload) + str(self.timestamp)).encode()
        self.signature = private_key.sign(message)

    def verify_signature(self):
        try:
            pub = Ed25519PublicKey.from_public_bytes(self.pubkey)
            message = (self.txid + str(self.payload) + str(self.timestamp)).encode()
            pub.verify(self.signature, message)
            return True
        except Exception:
            return False


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
        # Éviter les doublons dans la mempool
        if not any(t.txid == tx.txid for t in self.mempool):
            self.mempool.append(tx)

    def create_block(self, miner_id: str):

    
        
        if not self.mempool:
            return None

        idx = len(self.chain)
        prev = self.chain[-1].current_hash if self.chain else "0"*64
        
        # Copier les transactions avant de vider la mempool
        txs = self.mempool.copy()
        block = Block(idx, txs, prev, miner_id)

        # Vider la mempool APRÈS création du bloc
        self.mempool.clear()
        return block

    def validate_chain(self, chain: List[Block]):
        if not chain:
            return True
            
        for i, blk in enumerate(chain):
            if not blk.validate():
                return False
            if i > 0 and blk.previous_hash != chain[i-1].current_hash:
                return False
        return True

    def replace_if_longer(self, chain: List[Block]):
        if len(chain) > len(self.chain) and self.validate_chain(chain):
            self.chain = chain
            self.mempool.clear()  # Reset mempool lors d'un remplacement
            return True
        return False

    def get_registered_users(self) -> dict:
        """Reconstruit la liste des utilisateurs depuis la blockchain"""
        users = {}
        for block in self.chain:
            for tx in block.transactions:
                if tx.tx_type == "register":
                    pseudo = tx.payload["pseudo"]
                    # Premier arrivé = gagnant (on ne l'écrase pas)
                    if pseudo not in users:
                        users[pseudo] = tx.pubkey
        return users


# ======================
# PoET TIMER
# ======================
class PoETTimer:
    def __init__(self):
        self.wait = random.uniform(3, 8)

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

        self.seen_tx = set()
        self.seen_blocks = set()

        self.lock = threading.RLock()
        self.private_keys = {}  # pseudo -> PrivateKey (seulement pour les pseudos locaux)
        self.mining = False
        self.synced = False  # Flag de synchronisation initiale
        
        self.load_chain()

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip

    def get_users(self) -> dict:
        """Retourne les utilisateurs enregistrés dans la blockchain"""
        return self.blockchain.get_registered_users()

    # ======================
    # TCP SERVER
    # ======================
    def tcp_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.tcp_port))
        s.listen(10)
        print(f"[TCP] Serveur actif sur {self.node_id}")

        while True:
            c, addr = s.accept()
            threading.Thread(target=self.handle_client, args=(c,), daemon=True).start()

    def handle_client(self, client):
        try:
            # Recevoir la taille d'abord
            data = b''
            while len(data) < 4:
                chunk = client.recv(4 - len(data))
                if not chunk:
                    return
                data += chunk
            
            size = struct.unpack('!I', data)[0]
            
            # Recevoir les données complètes
            data = b''
            while len(data) < size:
                chunk = client.recv(min(65536, size - len(data)))
                if not chunk:
                    return
                data += chunk
            
            obj = pickle.loads(data)
            with self.lock:
                self.receive_object(obj)
        except Exception as e:
            pass
        finally:
            client.close()

    def send_tcp(self, peer, obj):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect(peer)
            
            data = pickle.dumps(obj)
            size = struct.pack('!I', len(data))
            s.sendall(size + data)
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

        # Timer pour marquer comme synced si aucun pair après 5 secondes
        sync_timer = threading.Timer(5.0, self.mark_as_synced)
        sync_timer.daemon = True
        sync_timer.start()

        while True:
            try:
                data, addr = s.recvfrom(1024)
                msg = data.decode()
                if ":" in msg:
                    ip, port = msg.split(":")
                    peer = (ip, int(port))
                    if peer != (self.host, self.tcp_port) and peer not in self.peers:
                        with self.lock:
                            self.peers.add(peer)
                        print(f"\n[PEER] Nouveau pair découvert: {ip}:{port}\n>> ", end="", flush=True)
                        self.send_tcp(peer, ("CHAIN_REQUEST", (self.host, self.tcp_port)))
            except:
                pass

    def multicast_announcer(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        ttl = struct.pack("b", 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        msg = f"{self.host}:{self.tcp_port}".encode()

        while True:
            try:
                s.sendto(msg, (MULTICAST_IP, MULTICAST_PORT))
            except:
                pass
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

        if not tx.verify_signature():
            print("\n❌ Transaction rejetée : signature invalide.\n>> ", end="", flush=True)
            return

        self.seen_tx.add(tx.txid)

        if tx.tx_type == "register":
            pseudo = tx.payload["pseudo"]
            users = self.get_users()

            # Vérifier si le pseudo est DÉJÀ dans la blockchain
            if pseudo in users:
                print(f"\n⚠️  Pseudo '{pseudo}' déjà pris (rejeté)\n>> ", end="", flush=True)
                return

            # Ajouter à la mempool
            self.blockchain.add_transaction(tx)
            self.broadcast(tx)
            # print(f"\n[REGISTER] Transaction d'enregistrement pour '{pseudo}' ajoutée à la mempool\n>> ", end="", flush=True) # SUPPRIMER CETTE LIGNE
            return

        if tx.tx_type == "chat":
            sender = tx.payload["sender"]
            users = self.get_users()

            if sender not in users:
                print(f"\n❌ Message rejeté : l'utilisateur '{sender}' n'existe pas.\n>> ", end="", flush=True)
                return

            if tx.pubkey != users[sender]:
                print("\n❌ Message rejeté : tentative d'usurpation détectée.\n>> ", end="", flush=True)
                return

            #print(f"\n💬 {sender}: {tx.payload['content']}\n>> ", end="", flush=True)
            self.blockchain.add_transaction(tx)
            self.broadcast(tx)
    # ======================
    # BLOC
    # ======================
    def handle_block(self, block):
        if block.current_hash in self.seen_blocks:
            return

        if not block.validate():
            print("\n❌ Bloc invalide reçu\n>> ", end="", flush=True)
            return

        # Vérifier que c'est le bloc suivant attendu
        if block.index != len(self.blockchain.chain):
            return

        # VALIDATION DES TRANSACTIONS DU BLOC
        users_before_block = self.get_users()
        valid_txs = []
        
        for tx in block.transactions:
            if tx.tx_type == "register":
                pseudo = tx.payload["pseudo"]
                # On accepte seulement si le pseudo n'existe pas encore
                if pseudo not in users_before_block and pseudo not in [vtx.payload.get("pseudo") for vtx in valid_txs if vtx.tx_type == "register"]:
                    valid_txs.append(tx)
                    
            elif tx.tx_type == "chat":
                sender = tx.payload["sender"]
                # Vérifier que l'utilisateur existe et que la signature correspond
                if sender in users_before_block and tx.pubkey == users_before_block[sender]:
                    valid_txs.append(tx)

        # Si toutes les transactions sont invalides, rejeter le bloc
        if not valid_txs and block.transactions:
            print("\n❌ Bloc rejeté : aucune transaction valide\n>> ", end="", flush=True)
            return

        self.seen_blocks.add(block.current_hash)
        self.blockchain.chain.append(block)
        
        # Retirer les transactions du bloc de notre mempool
        block_txids = {tx.txid for tx in block.transactions}
        self.blockchain.mempool = [tx for tx in self.blockchain.mempool if tx.txid not in block_txids]

        miner = "VOUS" if block.miner_id == self.node_id else block.miner_id
        print(f"\n⛏️  Bloc #{block.index} miné par {miner} ({len(block.transactions)} txs)\n>> ", end="", flush=True)

        self.broadcast(block)
        self.save_chain()

    def handle_chain_response(self, chain):
        if self.blockchain.replace_if_longer(chain):
            self.seen_blocks = {b.current_hash for b in chain}
            print(f"\n[SYNC] Blockchain mise à jour ({len(chain)} blocs)\n>> ", end="", flush=True)
            self.save_chain()
        
        # Marquer comme synchronisé après avoir reçu une réponse
        if not self.synced:
            self.synced = True
            print(f"\n✅ Synchronisation terminée\n>> ", end="", flush=True)

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
            with self.lock:
                # NOUVEAU CODE : Vérifier la taille de la mempool ici
                if len(self.blockchain.mempool) < MIN_TX_COUNT:
                    continue    
                
                self.mining = True

            # PoET en dehors du lock
            poet = PoETTimer()
            poet.begin_wait()

            with self.lock:
                # Vérifier à nouveau la taille de la mempool et si un bloc n'a pas été miné par un pair pendant l'attente
                if len(self.blockchain.mempool) < MIN_TX_COUNT or not self.mining:
                    self.mining = False
                    continue
                    
                block = self.blockchain.create_block(self.node_id)
                # La vérification est déjà dans create_block, mais on vérifie le résultat
                if block:
                    self.seen_blocks.add(block.current_hash)
                    self.blockchain.chain.append(block)

                    print(f"\n⛏️  Vous avez miné le bloc #{block.index} ({len(block.transactions)} txs)\n>> ", end="", flush=True)
                    self.broadcast(block)
                    self.save_chain()
                
                self.mining = False
    # ======================
    # PERSISTENCE
    # ======================
    def save_chain(self):
        try:
            with open(CHAIN_FILE, "wb") as f:
                pickle.dump(self.blockchain.chain, f)
        except Exception as e:
            print(f"Erreur sauvegarde: {e}")

    def load_chain(self):
        if os.path.exists(CHAIN_FILE):
            try:
                with open(CHAIN_FILE, "rb") as f:
                    chain = pickle.load(f)
                if self.blockchain.validate_chain(chain):
                    self.blockchain.chain = chain
                    self.seen_blocks = {b.current_hash for b in chain}
                    print(f"[LOAD] Blockchain chargée ({len(chain)} blocs)")
            except Exception as e:
                print(f"Erreur chargement: {e}")

    def mark_as_synced(self):
        """Marque le nœud comme synchronisé après un délai"""
        with self.lock:
            if not self.synced:
                self.synced = True
                if not self.peers:
                    print(f"\n[INFO] Aucun pair trouvé - Mode solo activé\n>> ", end="", flush=True)
                else:
                    print(f"\n✅ Synchronisation terminée\n>> ", end="", flush=True)

    # ======================
    # ACTIONS USER
    # ======================
    def register_user(self, pseudo):
        # Vérifier si on est synchronisé
        if not self.synced:
            print("⏳ Synchronisation en cours... Veuillez patienter.")
            return

        with self.lock:
            users = self.get_users()
            
            # Vérifier dans la blockchain
            if pseudo in users:
                print("❌ Ce pseudo est déjà enregistré dans la blockchain.")
                return
            
            # Vérifier dans la mempool (en attente de minage)
            for tx in self.blockchain.mempool:
                if tx.tx_type == "register" and tx.payload.get("pseudo") == pseudo:
                    print("⚠️  Ce pseudo est déjà en attente de validation (mempool).")
                    return

            private_key = Ed25519PrivateKey.generate()

            tx = Transaction("register", {"pseudo": pseudo})
            tx.sign(private_key)

            self.seen_tx.add(tx.txid)
            self.private_keys[pseudo] = private_key  # Sauvegarder localement

            self.blockchain.add_transaction(tx)
            self.broadcast(tx)

            print(f"✅ Transaction d'enregistrement envoyée pour '{pseudo}'.")
            print(f"⏳ En attente de validation par le minage...")

    def send_chat(self, pseudo, content):
        # Vérifier si on est synchronisé
        if not self.synced:
            print("⏳ Synchronisation en cours... Veuillez patienter.")
            return

        with self.lock:
            if pseudo not in self.private_keys:
                print("❌ Vous ne possédez pas ce pseudo localement.")
                print("   Utilisez /register d'abord.")
                return
            
            users = self.get_users()
            if pseudo not in users:
                print("❌ Ce pseudo n'est pas encore validé dans la blockchain.")
                print("   Attendez que votre enregistrement soit miné.")
                return

            private_key = self.private_keys[pseudo]

            tx = Transaction("chat", {"sender": pseudo, "content": content})
            tx.sign(private_key)

            self.seen_tx.add(tx.txid)
            self.blockchain.add_transaction(tx)
            self.broadcast(tx)

            print(f"💬 {pseudo}: {content}")

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
    print("\n" + "="*50)
    print("   🔗 BLOCKCHAIN CHAT P2P 🔗")
    print("="*50)
    print("\n⏳ Recherche de pairs sur le réseau...")
    print("   (Patientez 5 secondes pour la synchronisation)\n")
    
    # Attendre la synchronisation initiale
    for i in range(5):
        time.sleep(1)
        if node.synced:
            break
    
    print("\nCommandes disponibles:")
    print("  /register <pseudo>       - S'enregistrer")
    print("  /msg <pseudo> <texte>    - Envoyer un message")
    print("  /users                   - Liste des utilisateurs")
    print("  /peers                   - Liste des pairs connectés")
    print("  /chain                   - Afficher la blockchain")
    print("  /mempool                 - Transactions en attente")
    print("  /stats                   - Statistiques")
    print("  /exit                    - Quitter")
    print("\n" + "="*50 + "\n")

    while True:
        try:
            cmd = input(">> ").strip()

            if not cmd:
                continue

            if cmd.startswith("/register "):
                parts = cmd.split(" ", 1)
                if len(parts) == 2:
                    node.register_user(parts[1])
                else:
                    print("Usage : /register <pseudo>")

            elif cmd.startswith("/msg "):
                parts = cmd.split(" ", 2)
                if len(parts) < 3:
                    print("Usage : /msg <pseudo> <texte>")
                else:
                    node.send_chat(parts[1], parts[2])

            elif cmd == "/users":
                with node.lock:
                    users = node.get_users()
                    if users:
                        print(f"\n👥 Utilisateurs enregistrés ({len(users)}):")
                        for pseudo in sorted(users.keys()):
                            local = " 🔑" if pseudo in node.private_keys else ""
                            print(f"  • {pseudo}{local}")
                    else:
                        print("Aucun utilisateur enregistré.")

            elif cmd == "/peers":
                with node.lock:
                    if node.peers:
                        print(f"\n🌐 Pairs connectés ({len(node.peers)}):")
                        for ip, port in sorted(node.peers):
                            print(f"  • {ip}:{port}")
                    else:
                        print("Aucun pair connecté.")

            elif cmd == "/mempool":
                with node.lock:
                    if node.blockchain.mempool:
                        print(f"\n⏳ Mempool ({len(node.blockchain.mempool)} transactions):")
                        for tx in node.blockchain.mempool:
                            if tx.tx_type == "register":
                                print(f"  • REGISTER: {tx.payload['pseudo']}")
                            elif tx.tx_type == "chat":
                                print(f"  • CHAT: {tx.payload['sender']} → {tx.payload['content'][:30]}...")
                    else:
                        print("Mempool vide.")

            elif cmd == "/stats":
                with node.lock:
                    users = node.get_users()
                    sync_status = "✅ Synchronisé" if node.synced else "⏳ En cours..."
                    print(f"\n📊 Statistiques:")
                    print(f"  • Statut: {sync_status}")
                    print(f"  • Blocs: {len(node.blockchain.chain)}")
                    print(f"  • Mempool: {len(node.blockchain.mempool)} transactions")
                    print(f"  • Utilisateurs: {len(users)}")
                    print(f"  • Pairs: {len(node.peers)}")
                    print(f"  • Pseudos locaux: {len(node.private_keys)}")

            elif cmd == "/chain":
                with node.lock:
                    chain = node.blockchain.chain
                    if not chain:
                        print("La blockchain est vide.")
                        continue

                    print(f"\n{'='*60}")
                    print(f"   BLOCKCHAIN ({len(chain)} blocs)")
                    print(f"{'='*60}\n")

                    for b in chain:
                        print(f"┌─ Bloc #{b.index} " + "─"*45)
                        print(f"│ Mineur      : {b.miner_id}")
                        print(f"│ Timestamp   : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(b.timestamp))}")
                        print(f"│ Prev Hash   : {b.previous_hash[:16]}...")
                        print(f"│ Merkle Root : {b.merkle_root[:16]}...")
                        print(f"│ Hash        : {b.current_hash[:16]}...")
                        print(f"│ Transactions: {len(b.transactions)}")

                        if b.transactions:
                            print("│")
                            for i, tx in enumerate(b.transactions, 1):
                                print(f"│  [{i}] {tx.tx_type.upper()}")
                                print(f"│      TXID: {tx.txid[:16]}...")
                                
                                if tx.tx_type == "register":
                                    print(f"│      User: {tx.payload['pseudo']}")
                                elif tx.tx_type == "chat":
                                    print(f"│      From: {tx.payload['sender']}")
                                    print(f"│      Msg : {tx.payload['content']}")
                                
                                if i < len(b.transactions):
                                    print("│")

                        print(f"└{'─'*58}\n")

            elif cmd == "/exit":
                print("\n👋 Au revoir!")
                break

            else:
                print("❌ Commande inconnue.")

        except KeyboardInterrupt:
            print("\n\n👋 Au revoir!")
            break
        except Exception as e:
            print(f"Erreur: {e}")


# ======================
# MAIN
# ======================
if __name__ == "__main__":
    node = Node()
    node.start()
    time.sleep(0.5)  # Laisser le temps au serveur TCP de démarrer
    repl(node)