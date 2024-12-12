# 指定监听的地址和端口
bind = "0.0.0.0:9394"
# 启动的工作进程数
workers = 4  
threads = 1
# 使用 UvicornWorker 工作器
worker_class = "uvicorn.workers.UvicornWorker"  
# 请求超时时间，根据需要进行调整
timeout = 30  
# 日志级别
loglevel = "info" 
# 最大并发量
worker_connections = 4
# 进程文件目录
pidfile = '/home/gunicorn/pid/gunicorn.pid'
# 访问日志文件路径
accesslog = "/home/gunicorn/log/access.log"
# 错误日志文件路径
errorlog = "/home/gunicorn/log/error.log"
