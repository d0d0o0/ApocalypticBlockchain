import hashlib
from typing import List, Tuple


class MerkleTree:
    """
    Implémentation simple d'un arbre de Merkle avec SHA-256.
    """
#Gestion des nombres impairs de feuilles en dupliquant la dernière feuille si nécessaire.
    def __init__(self, transactions: List[bytes] or List[str], duplicate_odd: bool = True):
        """
        transactions : liste de chaînes ou bytes représentant les transactions.
        """
        self.duplicate_odd = duplicate_odd

        # Normalisation : toutes les transactions en bytes
        self.leaves = [
            t if isinstance(t, bytes) else str(t).encode()
            for t in transactions
        ]

        # Liste des niveaux de l'arbre, chaque niveau contenant des hashs
        self.levels: List[List[bytes]] = []

        if len(self.leaves) > 0:
            self._build_tree()


    @staticmethod
    def _hash(data: bytes) -> bytes:
        """
        Hachage SHA-256 d'une donnée en bytes.
        """
        return hashlib.sha256(data).digest()

    def _build_tree(self):
        """
        Construit l'arbre de Merkle du bas vers le haut.
        """

        # Hachage des feuilles
        current_level = [self._hash(leaf) for leaf in self.leaves]

        # Stockage du niveau des feuilles
        self.levels = [current_level]

        # Construction des niveaux supérieurs
        while len(current_level) > 1:

            next_level = []
            n = len(current_level)

            i = 0
            while i < n:
                left = current_level[i]

                # Si pas de paire, on gère le impair
                if i + 1 < n:
                    right = current_level[i + 1]
                else:
                    right = left if self.duplicate_odd else self._hash(b"")

                # Parent = SHA256(left + right)
                parent = self._hash(left + right)
                next_level.append(parent)

                i += 2

            current_level = next_level
            self.levels.append(current_level)


    def get_root(self) -> str:
        """
        Retourne la racine de Merkle en hexadécimal.
        """
        if not self.levels:
            return ""
        return self.levels[-1][0].hex()

    # ----------------------------------------------------------------------

    def get_leaf_hash(self, index: int) -> str:
        """
        Retourne le hash d'une feuille en hexadécimal.
        """
        return self.levels[0][index].hex()

    # ----------------------------------------------------------------------

    def get_proof(self, index: int) -> List[Tuple[str, str]]:
        """
        Génère une preuve de Merkle (Merkle proof) pour la feuille donnée.

        Retourne une liste de tuples :
            (hash_sibling_en_hex, position)
        où position ∈ {"left", "right"}.
        """
        if index < 0 or index >= len(self.levels[0]):
            return []

        proof = []
        idx = index

        for level in range(len(self.levels) - 1):
            current_level = self.levels[level]

            # Si idx pair → le nœud est à gauche
            if idx % 2 == 0:
                sibling_idx = idx + 1 if idx + 1 < len(current_level) else idx
                position = "right"
            else:
                sibling_idx = idx - 1
                position = "left"

            sibling_hash_hex = current_level[sibling_idx].hex()
            proof.append((sibling_hash_hex, position))

            # Parent pour niveau suivant
            idx //= 2

        return proof

    # ----------------------------------------------------------------------

    @staticmethod
    def verify_proof(leaf: bytes or str, proof: List[Tuple[str, str]], root_hex: str) -> bool:
        """
        Vérifie une preuve de Merkle.

        leaf : la feuille brute (bytes ou string)
        proof : liste des (hash_sibling, position)
        root_hex : hash de la racine attendu
        """
        current = leaf if isinstance(leaf, bytes) else str(leaf).encode()
        current_hash = hashlib.sha256(current).digest()

        for sibling_hex, position in proof:
            sibling = bytes.fromhex(sibling_hex)

            if position == "right":
                current_hash = hashlib.sha256(current_hash + sibling).digest()
            else:
                current_hash = hashlib.sha256(sibling + current_hash).digest()

        return current_hash.hex() == root_hex



