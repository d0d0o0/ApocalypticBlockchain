from abc import ABC, abstractmethod

class transaction(ABC):
    @property
    @abstractmethod
    def tx_id(self):
        pass

    @property
    @abstractmethod
    def timestamp(self):
        pass

    @property
    @abstractmethod
    def signature(self):
        pass

    @abstractmethod
    def sign(privKey):
        pass

    @abstractmethod
    def checkTransaction():
        pass