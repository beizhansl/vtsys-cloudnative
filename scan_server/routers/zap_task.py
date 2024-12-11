import time
from fastapi import APIRouter
from client import get_zap_conn, handle_zap_task
from config import logger
from sqlctrl import get_data, update_date

router = APIRouter(
    prefix="/zap",  # 前缀只在这个模块中使用
    tags=["zaptasks"],
)

@router.get("/hello")
async def helloworld():
    return {'ok': True}

@router.get("/get_task")
async def get_task(running_status: str, target:str, task_id:str):
    try:
        ok, running_id, finished_time = get_data()
        if not ok:
            raise Exception("get sql error.")
        if finished_time and time.time() - finished_time > 10*60:
            finished_time = None
            running_id = None
        if task_id != running_id:
            raise Exception("Not the running task.")
        zap = get_zap_conn()
        running_status, errmsg = handle_zap_task(zap=zap, running_status=running_status, target=target)
        if running_status in ['failed', 'done']:
            finished_time = time.time()
        ok = update_date(running_id=running_id, finished_time=finished_time)
        if not ok:
            raise Exception("update sql error.")
        return {'ok': True, 'running_status': running_status, 'errmsg':errmsg}
    except Exception as e:
        logger.error('Faild to get zap task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
        

@router.post("/create_task")
async def create_task(target: str, task_id:str):
    try:
        ok, running_id, finished_time = get_data()
        if not ok:
            raise Exception("get sql error.")
        if finished_time and time.time() - finished_time > 10*60:
            finished_time = None
            running_id = None
        if running_id is not None:
            raise Exception("Parallel excution is not supported.")
        zap = get_zap_conn()
        running_status = None
        # 0. 开启新的session
        zap.core.run_garbage_collection()
        if zap.core.new_session(overwrite=True) != 'OK':
            raise Exception("New session failed.")
        # 1. 开始任务，即进入传统爬虫阶段
        zap.pscan.set_max_alerts_per_rule(20)
        zap.spider.set_option_max_depth(5)
        zap.spider.set_option_max_duration(10)
        zap.spider.set_option_thread_count(8)
        res = zap.spider.scan(target)
        if int(res) != 0:
            raise Exception(f"Spider scan failed.")
        else:
            running_id = task_id
            finished_time = None
            running_status = 'spider'
            logger.info(f"New task {target} started.")
        ok = update_date(running_id=running_id, finished_time=finished_time)
        if not ok:
            raise Exception("update sql error.")
        return {'ok': True, 'running_status': running_status}
    except Exception as e:
        logger.error('Faild to create zap task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}


@router.delete("/delete_task")
async def delete_task(task_id: str):
    try:
        ok, running_id, finished_time = get_data()
        if not ok:
            raise Exception("get sql error.")
        if running_id != task_id:
            raise Exception("Not the running task.")
        running_id = None
        finished_time = None
        ok = update_date(running_id=running_id, finished_time=finished_time)
        if not ok:
            raise Exception("sql error.")
        # zap = get_zap_conn()
        # # 0. 停止任务
        # zap.spider.stop_all_scans()
        # zap.ajaxSpider.stop()
        # zap.ascan.stop_all_scans()
        # # 1. 开启新的session
        # zap.core.run_garbage_collection()
        # if zap.core.new_session(overwrite=True) != 'OK':
        #     raise Exception("New session failed.")
        return {'ok': True}
    except Exception as e:
        logger.error('Faild to create zap task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}



@router.get("/get_report")
async def get_report(task_id: str):
    try:
        ok, running_id, finished_time = get_data()
        if not ok:
            raise Exception("get sql error.")
        if running_id != task_id:
            raise Exception("Not the running task.")
        zap = get_zap_conn()
        # 0. 停止所有扫描
        zap.ascan.stop_all_scans()
        zap.core.set_option_merge_related_alerts(enabled='true')
        # 1. 获取report文件内容
        content = zap.core.htmlreport()
        content = content.encode('utf-8')
        return {'ok': True, 'content': content}
    except Exception as e:
        logger.error('Faild to get zap report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
