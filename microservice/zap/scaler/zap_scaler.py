import logging
import structlog
from fastapi import FastAPI, Request, status as Status, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pod_create import create_pod_from_yaml, check_node_label

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

# 扩容接口
@app.get("/scale_out_with_node")
async def list_scanner_resource(
    node_name:str = Query(..., description="Node name"),
):
    """
    Http Code: 状态码200,返回数据:
    {
        "ok": True,
        "errmsg": ""
    }
    or
    {
        "ok": False,
        "errmsg": "xxx"
    }
    """
    success = create_pod_from_yaml(node_name=node_name)
    if not success:
        return {
            "ok": False,
            "errmsg": f"ZAP scale failed on node {node_name}"
        }
    return {
        "ok": True,
        "errmsg": ""
    }
    
# 健康检查接口
@app.get("/healthz")
async def healthz(
):
    return {"status": "ok"}
