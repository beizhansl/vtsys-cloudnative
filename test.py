import time
from scan_server.client import get_zap_conn

# 获取当前时间戳
now = time.time()
print(now)
print(type(now))


# 时间转字符串
nowStr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
print(nowStr)

# 字符串转时间
now2Str = time.strptime(nowStr, "%Y-%m-%d %H:%M:%S")
print(now2Str)

# 转换为时间戳
now2 = time.mktime(now2Str)
print(now2)


nowStr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now2))
print(nowStr)

zap = get_zap_conn()
# 0. 停止所有扫描
zap.ascan.stop_all_scans()
zap.core.set_option_merge_related_alerts(enabled='true')
# 1. 获取report文件内容
content = zap.core.htmlreport()