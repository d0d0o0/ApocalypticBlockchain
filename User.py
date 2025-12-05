from Crypto.PublicKey import RSA
from hashlib import hash

class User :
    def __init__(self):
        key = RSA.generate(2048)
        self.secretKey = key.export_key()
        self.publicKey = key.public_key().export_key
        self.addressID = hash.sha256(self.publicKey)

    def getPseudo(self):
        return hash.sha256(self.publicKey)