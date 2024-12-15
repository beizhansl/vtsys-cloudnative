from sqlalchemy import Column, Integer, String, Enum, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
# from enum import Enum as PyEnum
from datetime import datetime
from sqlalchemy.orm import relationship
from basemodel import Base
from datetime import timezone

class ScannerType(Enum):
    WEB = 'web'
    HOST = 'host'

class Status(Enum):
    ENABLE = 'enable'
    WAITING = 'waiting'
    DISABLE = 'disable'
    DELETED = 'deleted'
    DELETING = 'deleting'

class ScannerEngine(Enum):
    ZAP = 'zaproxy'
    OPENVAS = 'openvas'

class FileType(Enum):
    HTML = 'html'
    PDF = 'pdf'
    XML = 'xml'

class VtScanner(Base):
    __tablename__ = 'vt_scanner'

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(255), unique=True, nullable=False)
    type = Column(Enum(ScannerType), nullable=False)
    engine = Column(Enum(ScannerEngine), nullable=False)
    ipaddr = Column(String(16), nullable=False)
    port = Column(String, nullable=False)
    filetype = Column(Enum(ScannerType), nullable=False)
    status = Column(Enum(Status), default=Status.ENABLE.value, nullable=False)
    max_concurrency = Column(Integer, nullable=False)
    except_num = Column(Integer, default=0)
    create_time = Column(DateTime, default=datetime.now(timezone.utc))
    update_time = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    # Relationships
    tasks = relationship("VtTask", back_populates="scanner")

    def __repr__(self):
        return f'<VtScanner(name={self.name}, type={self.type})>'

    def __str__(self):
        return f'[{self.type.value}]{self.name}'  # Use .value to get the string representation of the enum

# Note: The ordering attribute from Django's Meta class is not directly applicable in SQLAlchemy.
# If you want to order query results, you should do it explicitly when querying the database.