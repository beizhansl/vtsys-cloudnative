from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Table, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from basemodel import Base
from scanner import ScannerEngine

# Assuming these are the translation of the Django model's verbose names to descriptions for SQLAlchemy
# from enum import Enum as PyEnum

class TaskType(Enum):
    WEB = 'web'
    HOST = 'host'

class Status(Enum):
    QUEUED = 'Queued'
    RUNNING = 'Running'
    DONE = 'Done'
    FAILED = 'Failed'

# class RunningStatus(PyEnum):
#     SPIDER = 'spider'
#     AJAXSPIDER = 'ajaxspider'
#     ACTIVE = 'active'
#     PASSIVE = 'passive'
#     DONE = 'done'
#     FAILED = 'failed'

class VtTask(Base):
    __tablename__ = 'vt_task'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    priority = Column(Integer, default=2)
    target = Column(String(255), nullable=False)
    type = Column(Enum(TaskType), nullable=False)
    scanner_type = Column(Enum(ScannerEngine), default=ScannerEngine.OPENVAS, nullable=False)
    task_status = Column(Enum(Status), default=Status.QUEUED.value)
    scanner_id = Column(String, ForeignKey('vt_scanner.id'), nullable=True)
    user_id = Column(String, nullable=True)
    create_time = Column(DateTime, default=datetime.now(timezone.utc))
    finish_time = Column(DateTime, nullable=True)
    update_time = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    errmsg = Column(String(255), default='')
    report_id = Column(String, ForeignKey('vt_report.id'), nullable=True)
    remark = Column(String(255), default='')
    # running_status = Column(Enum(RunningStatus), nullable=True)
    # running_id = Column(String(36), nullable=True, default='')
    # Relationships
    scanner = relationship("VtScanner", back_populates="tasks")
    # user = relationship("User", back_populates="tasks")
    report = relationship("VtReport", back_populates="tasks")
    except_num = Column(Integer, default=0)
    parallel = Column(Integer, default=1, nullable=True)
    
    def __repr__(self):
        return f"<VtTask(name={self.name}, target={self.target}, status={self.task_status})>"

# Assuming that VtScanner, User, and VtReport models exist and have a relationship defined.