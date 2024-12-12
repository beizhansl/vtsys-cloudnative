# 使用官方的Python基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 将应用程序代码复制到容器中
COPY . .

# 指定启动命令
CMD ["kopf", "run", "init_node_controller.py"]