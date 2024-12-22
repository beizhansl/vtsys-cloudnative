from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from model.basemodel import Base

# 创建引擎并连接到SQLite数据库
# 如果数据库文件不存在，将会自动创建
engine = create_engine('sqlite:///tasks.db', echo=True)

# 创建所有表
Base.metadata.create_all(engine)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db_session():
    """提供一个事务性的数据库会话"""
    db_session = SessionLocal()
    try:
        yield db_session
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.close()
