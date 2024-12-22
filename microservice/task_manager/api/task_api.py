import base64
import logging
import structlog
from ..model import task as Task
from ..tidb_sql import get_db_session
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from fastapi import FastAPI, Request, Depends, status as Status, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
import schemas
from sqlalchemy.future import select
from exception import UnauthorizedException, NotFoundException
import io

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

@app.exception_handler(UnauthorizedException)
async def unauthorized_exception_handler(request: Request, exc: UnauthorizedException):
    return JSONResponse(
        status_code=Status.HTTP_401_UNAUTHORIZED,
        content={"message": exc.detail},
        headers=exc.headers if hasattr(exc, 'headers') else {"WWW-Authenticate": "Bearer"}
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

@app.get("/list_tasks", response_model=schemas.VtTaskListResponse)
async def list_tasks(
    user_id: int = Query(..., description="Filter tasks by user ID"),
    page_num: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    db_session: Session = Depends(get_db_session)
):
    """
    Http Code: 状态码200,返回数据:
            {
              "count": 5,
              "page_num": 3,
              "page_size": 2,
              "results": [
                {
                  "id": "1",
                  "name": "name-string",
                  "type": "web",
                  "target": "https://baidu.com:8888/",
                  "task_status": "queued",
                  "remark": "string",
                  "creation": "2023-01-29T01:01:22.403887Z",
                  "modification": "2023-01-29T01:01:00Z",
                  "user": {     #关联用户属于用户的监控任务
                    "id": "1",
                    "username": "shun"
                  },
                }
              ]
            }
            http code 400:
            {
                "code": "xxx",
                "message": "xxx"
            }
            500:
                DatabaseError
    """
    offset = (page_num - 1) * page_size
    query = (
        db_session.query(Task.VtTask).filter(Task.VtTask.user_id == user_id)
        .order_by(desc(Task.VtTask.create_time))
        .offset(offset).limit(page_size)
    )
    tasks = query.all()
    total = db_session.execute(
                select(func.count()).select_from(Task.VtTask).filter(Task.VtTask.user_id == user_id)
            ).scalar_one()
    return schemas.VtTaskListResponse(
        count=len(tasks),
        total=total,
        results=tasks,
        page_num=page_num,
        page_size=page_size,
    )

@app.post("/create_task", response_model=schemas.VtTaskCreateResponse, status_code=Status.HTTP_201_CREATED)
async def create_task(
    task: schemas.VtTaskCreateRequest,
    user_id: int = Query(..., description="Filter tasks by user ID"),
    db_session: Session = Depends(get_db_session)
):
    # 创建新的任务实例
    new_task = Task.VtTask(
        target=task.target,
        type=task.type,
        scanner_type=task.engine,
        name=task.name,
        user_id=user_id,
        remark=task.remark,
        parallel=task.parallel
    )
    db_session.add(new_task)
    return schemas.VtTaskCreateResponse(
        success= True,
        task= new_task
    )

# 报告下载接口，下发文件数据流
@app.get("/download_report", response_model=StreamingResponse)
async def get_report(
    user_id: str = Query(..., description="Filter tasks by user ID"),
    task_id: int = Query(..., description="Task ID"),
    db_session: Session = Depends(get_db_session)
):
    task = db_session.query(Task.VtTask).filter(Task.VtTask.id == task_id).first()
    if task == None:
        raise NotFoundException(detail="Task Not Found")
    if task.user_id != user_id:
        raise UnauthorizedException(detail="Not The Owner Of Task")
    if task.task_status != Task.Status.DONE:
        raise Exception("Task Not Done")
    if task.report == None:
        raise Exception("Unknown Error")
    # report = db_session.query(Report.VtReport).filter(Report.VtReport.id == task_id).first()
    report = task.report
    file_like = io.BytesIO(report.content)
    headers = {
        'Content-Disposition': f'attachment; filename="{report.filename}.{report.type}"',
        'Content-Length': str(report.size),
    }
    return StreamingResponse(file_like, media_type='application/octet-stream', headers=headers)

# 报告获取接口，返回文件内容
@app.get("/get_report", response_model=schemas.VtReportResponse)
async def get_report(
    user_id: str = Query(..., description="Filter tasks by user ID"),
    task_id: int = Query(..., description="Task ID"),
    db_session: Session = Depends(get_db_session)
):
    task = db_session.query(Task.VtTask).filter(Task.VtTask.id == task_id).first()
    if task == None:
        raise NotFoundException(detail="Task Not Found")
    if task.user_id != user_id:
        raise UnauthorizedException(detail="Not The Owner Of Task")
    if task.task_status != Task.Status.DONE:
        raise Exception("Task Not Done")
    if task.report == None:
        raise Exception("Unknown Error")
    # report = db_session.query(Report.VtReport).filter(Report.VtReport.id == task_id).first()
    return task.report

# 提供给资源管理器进行伸缩的接口
@app.get("/list_engine_tasks_num", response_model=schemas.VtTaskCountResponse)
async def get_report(
    db_session: Session = Depends(get_db_session)
):
    query =(
        db_session.query(
            Task.VtTask.scanner_type, 
            # Task.VtTask.task_status, 
            func.count(Task.VtTask.id).label('count')  # 使用func.count来统计每个分组的数量
        )
        .filter(Task.VtTask.task_status.in_([Task.Status.QUEUED, Task.Status.RUNNING]))  # 筛选状态为'running'或'queued'的任务
        .group_by(Task.VtTask.scanner_type)  # 按照扫描器类型分组
    )
    results = query.all()
    type_num = len(results)
    task_count = []
    for result in results:
        task_count.append(schemas.VtTaskCountSchema(scanner_type=result[0], num=result[1]))
    return schemas.VtTaskCountResponse(
        type_num=type_num,
        task_count=task_count
    )
    
# 提供给资源管理器进行伸缩的接口
@app.get("/list_running_tasks_num", response_model=schemas.VtTaskCountResponse)
async def get_report(
    engines: schemas.VtRunningTaskCountRequest,
    db_session: Session = Depends(get_db_session)
):
    query =(
        db_session.query(
            Task.VtTask.scanner_id, 
            # Task.VtTask.task_status, 
            func.count(Task.VtTask.id).label('count')  # 使用func.count来统计每个分组的数量
        )
        .filter(Task.VtTask.task_status == Task.Status.RUNNING)  # 筛选状态为'running'的任务
        .filter(Task.VtTask.scanner_type.in_(engines))
        .group_by(Task.VtTask.scanner_id)  # 按照扫描器分组
    )
    results = query.all()
    scanner_num = len(results)
    task_count = []
    for result in results:
        task_count.append(schemas.VtRunningTaskCountSchema(scanner_id=result[0], num=result[1]))
    return schemas.VtRunningTaskCountResponse(
        scanner_num=scanner_num,
        task_count=task_count
    )

# 提供给资源管理器控制删除pod的接口
@app.get("/get_running_task_num", response_model=schemas.VtTaskCountResponse)
async def get_report(
    scanner_id: int = Query(..., description="Scanner Name"),
    db_session: Session = Depends(get_db_session)
):
    query =(
        db_session.query(
            # Task.VtTask.task_status, 
            func.count(Task.VtTask.id).label('count')  # 使用func.count来统计数量
        )
        .filter(Task.VtTask.task_status == Task.Status.RUNNING)  # 筛选状态为'running'的任务
        .filter(Task.VtTask.scanner_id == scanner_id)
    )
    running_task_num = query.scalar()
    return {
        "running_task_num": running_task_num
    }

# 健康检查接口
@app.get("/healthz")
async def healthz(
    db_session: Session = Depends(get_db_session)
):
    return {"status": "ok"}
