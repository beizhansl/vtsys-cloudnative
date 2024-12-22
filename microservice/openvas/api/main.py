from fastapi import FastAPI, Depends
import uvicorn
from config import settings
from routers import gvm_task

app = FastAPI()

# #限制访问地址
# @app.middleware("http")
# async def add_ip_filter_middleware(request: Request, call_next):
#     # 获取访问的IP地址
#     client_ip = request.client.host
#     # 检查IP地址是否在允许列表中
#     if client_ip not in  settings.manager_ips:
#         raise HTTPException(status_code=403, detail="IP地址未授权")
#     return await call_next(request)

app.include_router(gvm_task.router)

if __name__ == "__main__":
    uvicorn.run(app='main:app', host="0.0.0.0", port=settings.clientport, reload=True)
