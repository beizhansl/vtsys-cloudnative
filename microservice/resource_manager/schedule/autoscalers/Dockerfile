# 使用官方 Python 基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制当前目录下的所有文件到容器内的 /app 目录
COPY . /app

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露任何必要的端口（如果需要）
# EXPOSE 8080

# 设置入口点，指定启动时运行的命令
CMD ["python", "openvas_autoscaler.py"]