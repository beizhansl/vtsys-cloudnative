### 科技云漏扫系统客户端
主要工作内容：
1. 提供openvpn连接接口
2. 提供漏扫任务接口
3. 提供node状态接口
4. 主动向master注册自己

注意点：
1. 本身无状态，状态在openvas中
2. 仅使用FastAPI提供restful api
