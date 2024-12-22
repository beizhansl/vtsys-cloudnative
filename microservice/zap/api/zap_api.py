import atexit
from typing import List
from fastapi import APIRouter, Depends, FastAPI, Query, Request, status as Status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
from sqllite_sql import get_db_session
from model.zap_task import VtZapTask, TaskStatus
from sqlalchemy.orm import Session
from sqlalchemy import desc
from zap_client import get_zap_conn
from zap_task_trace_schedule import scheduler, logger
import os

app = FastAPI()

# 启动周期任务, 追踪更新任务状态
scheduler.start()
# 注册退出处理程序以优雅地关闭调度器
atexit.register(lambda: scheduler.shutdown())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
max_task_parallel = int(os.getenv("MAX_TASK_PARALLEL", "1"))


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

def get_db_zap_task(id: int, db_session: Session) -> VtZapTask:
    task = db_session.query(VtZapTask).filter_by(id=id).first()
    if task == None:
        raise Exception(f"{id} task not found")
    return task

def get_db_running_task(db_session: Session) -> List[VtZapTask]:
    tasks = db_session.query(VtZapTask).filter(VtZapTask.status==TaskStatus.RUNNING).order_by(desc(VtZapTask.create_time)).all()
    return tasks

@app.get("/healthz")
async def healthz(db_session: Session = Depends(get_db_session)):
    return {'ok': True}

@app.get("/get_task")
async def get_task(task_id:int = Query(..., description="Global task id"),
                   db_session: Session = Depends(get_db_session)):
    try:
        task = get_db_zap_task(id=task_id, db_session=db_session)
        status = task.status
        return {'ok': True, 'status': status}
    except Exception as e:
        logger.error('Faild to get zap task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}

@app.post("/create_task")
async def create_task(task_id:int = Query(..., description="Global task id"),
                      target:str = Query(...,  description="Task target"),
                      db_session: Session = Depends(get_db_session)):
    try:
        running_tasks = get_db_running_task(db_session=db_session)
        if len(running_tasks) >= max_task_parallel:
            raise Exception("TaskNumLimit")
        zap = get_zap_conn()
        running_status = None
        # 0. 开启新的session
        zap.core.run_garbage_collection()
        if zap.core.new_session(overwrite=True) != 'OK':
            raise Exception("New session failed.")
        # 1. 开始任务，即进入传统爬虫阶段
        zap.pscan.set_max_alerts_per_rule(20)
        zap.spider.set_option_max_depth(5)
        zap.spider.set_option_max_duration(10)
        zap.spider.set_option_thread_count(8)
        res = zap.spider.scan(target)
        if int(res) != 0:
            raise Exception(f"Spider scan failed.")
        else:
            running_id = None
            finished_time = None
            task = VtZapTask(
                id=task_id,
                target=target,
                running_id=running_id,
                finished_time=finished_time,
            )
            logger.info(f"New task {target} started.")
            db_session.add(task)
            db_session.flush()
        return {'ok': True, 'running_status': running_status}
    except Exception as e:
        logger.error('Faild to create zap task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}

@app.delete("/delete_task")
async def delete_task(task_id:int = Query(..., description="Global task id"),
                   db_session: Session = Depends(get_db_session)):
    try:
        task = get_db_zap_task(id=task_id, db_session=db_session)
        task.status = TaskStatus.DONE
        db_session.add(task)
        db_session.flush()
        return {'ok': True}
        # zap = get_zap_conn()
        # # 0. 停止任务
        # zap.spider.stop_all_scans()
        # zap.ajaxSpider.stop()
        # zap.ascan.stop_all_scans()
        # # 1. 开启新的session
        # zap.core.run_garbage_collection()
        # if zap.core.new_session(overwrite=True) != 'OK':
        #     raise Exception("New session failed.")
    except Exception as e:
        logger.error('Faild to delete zap task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}

@app.get("/get_report")
async def get_report(task_id:int = Query(..., description="Global task id"),
                   db_session: Session = Depends(get_db_session)):
    try:
        task = get_db_zap_task(id=task_id, db_session=db_session)
        zap = get_zap_conn()
        # 0. 停止所有扫描
        zap.ascan.stop_all_scans()
        zap.core.set_option_merge_related_alerts(enabled='true')
        # 1. 获取report文件内容
        content = zap.core.htmlreport()
        content = content.encode('utf-8')
        return {'ok': True, 'content': content}
    except Exception as e:
        logger.error('Faild to get zap report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}

# 缩容
@app.delete("/scale_in_with_num")
async def scale_in_with_num(num:str = Query(..., description="task num to scale in"),
                        db_session: Session = Depends(get_db_session)):
    try:
        tasks:List[VtZapTask] = get_db_running_task(db_session=db_session)
        zap = get_zap_conn()
        for task in tasks:
            if num <= 0:
                break
            zap.ascan.stop_all_scans()
            zap.ajaxSpider.stop()
            zap.spider.stop_all_scans()
            task.status = TaskStatus.ERROR
            db_session.add(task)
            db_session.flush()
            num -= 1
        return {'ok': True}
    except Exception as e:
        logger.error('Faild to scale in: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
