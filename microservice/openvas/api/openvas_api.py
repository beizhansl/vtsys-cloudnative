from datetime import datetime
from enum import Enum
from typing import List
from fastapi import APIRouter, Depends, FastAPI, Query, Request, status as Status
from fastapi.responses import JSONResponse
from gvm_client import get_gvm_conn
import logging
import structlog
from zh.zh_generate import gvm_zh_report
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
from sqllite_sql import get_db_session
from model.openvas_task import VtOpenvasTask, TaskStatus
from sqlalchemy.orm import Session
from sqlalchemy import desc

# 日志相关
# 设置结构化日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SQLAlchemyError)
async def sql_alchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Database error: {exc}")
    return JSONResponse(
        status_code=Status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"message": "An error occurred while processing the database operation."},
    )
    
# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=Status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "message": "An unexpected error occurred",
            "detail": str(exc),
        },
    )
    
class OpenvasStatus(Enum):
    REQUESTED = 'Requested'
    QUEUED = 'Queued'
    RUNNING = 'Running'
    DONE = 'Done'
    FAILED = 'Failed'
    INTERAPTED = 'Interapted'


@app.get("/healthz")
async def healthz(db_session: Session = Depends(get_db_session)):
    return {'ok': True}

def get_db_openvas_task(id: int, db_session: Session) -> VtOpenvasTask:
    task = db_session.query(VtOpenvasTask).filter_by(id=id).first()
    if task == None:
        raise Exception(f"{id} task not found")
    return task

def get_db_running_task(db_session: Session) -> List[VtOpenvasTask]:
    tasks = db_session.query(VtOpenvasTask).filter(VtOpenvasTask.status==TaskStatus.RUNNING).order_by(desc(VtOpenvasTask.create_time)).all()
    return tasks

@app.get("/get_task")
async def get_task(task_id: str = Query(..., description="Global task id"),
                   db_session: Session = Depends(get_db_session)):
    try:
        task: VtOpenvasTask = get_db_openvas_task(task_id, db_session)
        running_id = task.running_id
        pygvm = get_gvm_conn()
        task = pygvm.get_task(task_id=running_id)
        progress = task['progress']
        status = task['status']
        task_status = TaskStatus.RUNNING
        if status in [OpenvasStatus.FAILED.value, OpenvasStatus.INTERAPTED.value]:
            task_status = TaskStatus.ERROR
        if status in [OpenvasStatus.DONE]:
            task_status = TaskStatus.DONE
        if status in [OpenvasStatus.QUEUED, OpenvasStatus.RUNNING, OpenvasStatus.REQUESTED]:
            task_status = TaskStatus.RUNNING
        if task_status != task.status:
            task.status = task_status
            if task.status == TaskStatus.DONE:
                task.finish_time = datetime.now()
            db_session.add(task)
            db_session.flush()
        return {'ok': True, 'progress': progress, 'status': task_status}
    except Exception as e:
        logger.error('Failed to get gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

@app.post("/create_task")
async def create_task(task_id:str = Query(..., description="Global task id"),
                      target:str = Query(...,  description="Task target"),
                      db_session: Session = Depends(get_db_session)):
    try:
        pygvm = get_gvm_conn()
        # 0. 获取目标
        target_host = [target]
        # 1. 创建目标
        target = pygvm.create_target('target_'+task_id, hosts=target_host, port_list_id='33d0cd82-57c6-11e1-8ed1-406186ea4fc5')
        target_id = target['@id']
        # 2. 创建任务
        task = pygvm.create_task(name=f"task_{task_id}",target_id=target_id, 
                          config_id='daba56c8-73ec-11df-a475-002264764cea', 
                          scanner_id='08b69003-5fc2-4037-a479-93b440211c73',
                            preferences={'assets_min_qod' : 30})
        running_id = task['@id']
        # 3. 开始任务
        pygvm.start_task(task_id=running_id)
        task = VtOpenvasTask(
            id=task_id,
            running_id=running_id,
            finish_time=None
        )
        db_session.add(task)
        db_session.flush()
        return {'ok': True, 'running_id': running_id}
    except Exception as e:
        logger.error('Failed to create gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

@app.get("/get_task_result")
async def get_task_result(task_id:str = Query(..., description="Global task id"),
                      db_session: Session = Depends(get_db_session)):
    try:
        pygvm = get_gvm_conn()
        task:VtOpenvasTask = get_db_openvas_task(id=task_id, db_session=db_session)
        running_id = task.running_id
        # 0. 获取task对应results
        vuls = pygvm.list_results(task_id=running_id, filter_str="apply_overrides=0 levels=hml rows=100 min_qod=70 first=1 sort-reverse=severity")
        return {'ok':True, 'vuls': vuls.data}
    except Exception as e:
        logger.error('Failed to get gvm results: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

@app.delete("/delete_task")
async def delete_task(task_id:str = Query(..., description="Global task id"),
                      db_session: Session = Depends(get_db_session)):
    try:
        pygvm = get_gvm_conn()
        task:VtOpenvasTask = get_db_openvas_task(id=task_id, db_session=db_session)
        running_id = task.running_id
        # 1. 停止task
        pygvm.stop_task(task_id=running_id)
        # 2. 删除task
        pygvm.delete_task(task_id=running_id)
        return {'ok': True}
    except Exception as e:
        logger.error('Failed to delete gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

@app.get("/get_report")
async def get_report(task_id:str = Query(..., description="Global task id"),
                      db_session: Session = Depends(get_db_session)):
    try:
        pygvm = get_gvm_conn()
        task:VtOpenvasTask = get_db_openvas_task(id=task_id, db_session=db_session)
        running_id = task.running_id
        # 0. 获取task对应report
        report = pygvm.list_reports(task_id=running_id)[0]
        report_id = report['@id']
        # 1. 获取report文件内容
        content = pygvm.get_report(report_id=report_id, report_format_name='PDF', 
                       filter_str='apply_overrides=0 levels=hml rows=1000 min_qod=50 first=1 sort-reverse=severity')
        return {'ok': True, 'content': content}
    except Exception as e:
        logger.error('Failed to get gvm report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

@app.get("/get_report_zh")
async def get_report_zh(task_id:str = Query(..., description="Global task id"),
                        db_session: Session = Depends(get_db_session)):
    try:
        pygvm = get_gvm_conn()
        task:VtOpenvasTask = get_db_openvas_task(id=task_id, db_session=db_session)
        running_id = task.running_id
        # 0. 获取task对应results
        vuls = pygvm.list_results(task_id=running_id, filter_str="apply_overrides=0 levels=hml rows=100 min_qod=70 first=1 sort-reverse=severity")
        # 1. 对所有结果做中文化
        html_report = gvm_zh_report(vuls.data)
        content = html_report.encode('utf-8')
        return {'ok':True, 'content': content}
    except Exception as e:
        logger.error('Failed to get gvm report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

# 缩容接口
@app.get("/scale_in_with_num")
async def scale_in_with_num(num:str = Query(..., description="task num to scale in"),
                        db_session: Session = Depends(get_db_session)):
    try:
        pygvm = get_gvm_conn()
        tasks:List[VtOpenvasTask] = get_db_running_task(db_session=db_session)
        for task in tasks:
            if num <= 0:
                break
            running_id = task.running_id
            pygvm.stop_task(task_id=running_id)
            task.status = TaskStatus.ERROR
            db_session.add(task)
            num -= 1
        return {'ok':True}
    except Exception as e:
        logger.error('Failed to scale in: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()