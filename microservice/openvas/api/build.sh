# 构建镜像
docker build -t cloudnative-vt/openvas-scanner-api:v1.0 .

# # 标记镜像（如果你不是推送到默认的 Docker Hub）
# docker tag yourusername/periodic-task:latest yourregistry.com/yourusername/periodic-task:latest

# # 推送镜像到容器注册表
# docker push yourusername/periodic-task:latest