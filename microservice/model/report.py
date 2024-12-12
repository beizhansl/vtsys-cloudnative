from sqlalchemy import Column, Integer, String, DateTime, Enum, LargeBinary, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
# from enum import Enum as PyEnum
from datetime import datetime, timezone
from sqlalchemy.orm import relationship

Base = declarative_base()

class FileType(Enum):
    HTML = 'html'
    PDF = 'pdf'

class VtReport(Base):
    __tablename__ = 'vt_report'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), unique=True, nullable=False)  # Assuming UuidModel adds a UUID field

    filename = Column(String(255), nullable=False)
    type = Column(Enum(FileType), default=FileType.HTML.value)
    content = Column(LargeBinary, nullable=True)
    size = Column(Integer, default=0)
    create_time = Column(DateTime, default=datetime.now(timezone.utc))

    # Assuming there is a relationship with VtTask model
    task_id = Column(Integer, ForeignKey('vt_task.id'), nullable=True)
    task = relationship("VtTask", back_populates="report")

    def __repr__(self):
        return f'<VtReport(filename={self.filename}, type={self.type})>'

    def __str__(self):
        return f'{self.filename}.{self.type}'

# Note: The ordering and verbose_name attributes from Django's Meta class are not directly applicable in SQLAlchemy.
# If you want to order query results, you should do it explicitly when querying the database.