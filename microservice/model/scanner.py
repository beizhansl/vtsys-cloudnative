from sqlalchemy import Column, Integer, String, Enum, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
# from enum import Enum as PyEnum
from datetime import datetime
from sqlalchemy.orm import relationship

Base = declarative_base()

class ScannerType(Enum):
    WEB = 'web'
    HOST = 'host'

class Status(Enum):
    ENABLE = 'enable'
    DISABLE = 'disable'
    DELETED = 'deleted'

class ScannerEngine(Enum):
    ZAP = 'zaproxy'
    GVM = 'gvm'

class VtScanner(Base):
    __tablename__ = 'vt_scanner'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), unique=True, nullable=False)  # Assuming UuidModel adds a UUID field

    name = Column(String(255), unique=True, nullable=False)
    type = Column(Enum(ScannerType), nullable=False)
    engine = Column(Enum(ScannerEngine), nullable=False)
    ipaddr = Column(String(16), nullable=False)
    port = Column(Integer, nullable=False)
    status = Column(Enum(Status), default=Status.ENABLE.value, nullable=False)
    key = Column(String(64), nullable=False)
    max_concurrency = Column(Integer, nullable=False)

    # Relationships
    tasks = relationship("VtTask", back_populates="scanner")

    def __repr__(self):
        return f'<VtScanner(name={self.name}, type={self.type})>'

    def __str__(self):
        return f'[{self.type.value}]{self.name}'  # Use .value to get the string representation of the enum

# Note: The ordering attribute from Django's Meta class is not directly applicable in SQLAlchemy.
# If you want to order query results, you should do it explicitly when querying the database.