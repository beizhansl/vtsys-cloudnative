import base64
import logging
from typing import Dict
from pydantic import BaseModel
import structlog
from ..model import scanner as Scanner
from tidb_sql import get_db_session
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from fastapi import FastAPI, HTTPException, Request, Depends, status as Status, Query
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

@app.get("/list_scanner_resource", response_model=schemas.VtScannerListResponse)
async def list_scanner_resource(
    db_session: Session = Depends(get_db_session)
):
    """
    Http Code: 状态码200,返回数据:
            {
              "ok": True,
              "scanners": [
                {
                  "id": "1",
                  "name": "name-string",
                  "type": "host",
                  "engine": "openvas",
                  "ipaddr": "127.0.0.1",
                  "port": "8080",
                  "filetype": "PDF",
                  "max_concurrency": "2",
                  "except_num": "0",
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
    query = (
        db_session.query(Scanner.VtScanner).filter(Scanner.VtScanner.status==Scanner.Status.ENABLE)
    )
    scanners = query.all()
    return schemas.VtScannerListResponse(
        count=len(scanners),
        scanners=scanners
    )

@app.post("/update_resource_scanner")
async def update_resource_scanner(
    scanner_dict: Dict[int, int],
    db_session: Session = Depends(get_db_session)
):
    for scanner_id in scanner_dict:
        scanner = db_session.query(Scanner.VtScanner).filter(Scanner.VtScanner.id == scanner_id).first()
        if scanner == None:
            logger.error(f"Scanner not found: {scanner.id}")
            raise HTTPException(status_code=404, detail=f"Scanner with id {scanner_id} not found")
        scanner.max_concurrency = scanner_dict[scanner_id]
        db_session.add(scanner)
    return {
        "ok": True,
        "errmsg": ""
    }

# 健康检查接口
@app.get("/healthz")
async def healthz(
    db_session: Session = Depends(get_db_session)
):
    db_session.close()
    return {"status": "ok"}
