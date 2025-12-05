import hashlib

class Block :
    
    def __init__(self, index, previous_hash, timestamp, data, hash) :
        self.index = index
        self.previous_hash = previous_hash
        self.timestamp = timestamp
        self.data = data
        self.hash = hash
        
    def calculate_hash(self) :
        value = str(self.index) + str(self.previous_hash) + str(self.timestamp) + str(self.data)
        self.hash = hashlib.sha256(value.encode('utf-8')).hexdigest()

    def __str__(self) :
        return f"Block(index={self.index}, previous_hash='{self.previous_hash}', timestamp={self.timestamp}, data='{self.data}', hash='{self.hash}')"
    
    