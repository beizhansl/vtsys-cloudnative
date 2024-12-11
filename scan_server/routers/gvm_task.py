from fastapi import APIRouter
from client import get_gvm_conn
from config import logger
from zh.zh_generate import gvm_zh_report
from client import check_splited_configs, map_to_scanners, reduce_splite_task, get_splite_task_status, delete_splite_task_with_id
import uuid


router = APIRouter(
    prefix="/gvm",  # 前缀只在这个模块中使用
    tags=["gvmtasks"],
)


@router.get("/hello")
async def helloworld():
    return {'ok': True}


@router.get("/get_task")
async def get_task(running_id: str):
    try:
        pygvm = get_gvm_conn()
        task = pygvm.get_task(task_id=running_id)
        progress = task['progress']
        status = task['status']
        return {'ok': True, 'progress': progress, 'running_status': status}
    except Exception as e:
        logger.error('Faild to get gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.get("/get_splite_task")
async def get_task(running_id: str):
    try:
        pygvm = get_gvm_conn()
        ok, unfinished, num = get_splite_task_status(id=running_id)
        if ok:
            if unfinished == 0:
                progress = 100
                status = 'Done'
            else:
                progress = unfinished // num
                status = 'Running'
            return {'ok': True, 'progress': progress, 'running_status': status}
        else:
            logger.error('Faild to get gvm task: ' + unfinished)
            return {'ok': False, 'errmsg': unfinished}
    except Exception as e:
        logger.error('Faild to get gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.get("/get_task_num")
async def get_task_num():
    try:
        pygvm = get_gvm_conn()
        task_num = 0
        tasks = pygvm.list_tasks(status="Running")
        task_num += len(tasks.data)
        tasks = pygvm.list_tasks(status="Queued")
        task_num += len(tasks.data)
        tasks = pygvm.list_tasks(status="Requested")
        task_num += len(tasks.data)
        logger.info("Get task num succeed, task_num:", task_num)
        return {'ok': True, 'task_num': task_num}
    except Exception as e:
        logger.error('Faild to get gvm task num: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.post("/create_task")
async def create_task(id:str, target:str):
    try:
        pygvm = get_gvm_conn()
        # 0. 获取目标
        target_host = [target]
        # 1. 创建目标
        target = pygvm.create_target('target_'+id, hosts=target_host, port_list_id='33d0cd82-57c6-11e1-8ed1-406186ea4fc5')
        target_id = target['@id']
        # 2. 创建任务
        task = pygvm.create_task(name=f"task_{id}",target_id=target_id, 
                          config_id='daba56c8-73ec-11df-a475-002264764cea', 
                          scanner_id='08b69003-5fc2-4037-a479-93b440211c73',
                            preferences={'assets_min_qod' : 30})
        task_id = task['@id']
        # 3. 开始任务
        pygvm.start_task(task_id=task_id)
        return {'ok': True, 'running_id': task_id}
    except Exception as e:
        logger.error('Faild to create gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.post("/create_splite_task")
async def create_splite_task(target:str, splite_num:int):
    try:
        pygvm = get_gvm_conn()
        id = uuid.uuid1()
        logger.info("Creating splite task...")
        ok, msg = map_to_scanners(splite_num=splite_num, target=target, id=id)
        if ok:
            return {'ok': True, 'running_id': id}
        else:
            return {'ok': False, 'errmsg': msg}
    except Exception as e:
        logger.error('Faild to create gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.post("/create_task_with_config")
async def create_task_with_config(id:str, target:str, num:int, splite_num:int):
    try:
        pygvm = get_gvm_conn()
        logger.info("Creating splite task with config...")
        # 0. 获取目标
        target_host = [target]
        # 1. 创建目标
        try:
            target = pygvm.create_target('target_'+id, hosts=target_host, port_list_id='33d0cd82-57c6-11e1-8ed1-406186ea4fc5')
        except Exception as e:
            if "exists already" in str(e):
                target = pygvm.list_targets(kwargs={'name':'target_'+id})[0]
        
        target_id = target['@id']
        # 2. 获取配置id
        ok, msg, config_dict = check_splited_configs(pyg=pygvm, splite_num=splite_num)
        if not ok:
            logger.error('Faild to create gvm task, check splited configs error: ' + msg)
            return {'ok': False, 'errmsg': str(e)}
        config_name = "FF"+str(splite_num)+"_"+str(num)
        config_id = config_dict[config_name]
        # 3. 创建任务
        task = pygvm.create_task(name=f"task_{id}",target_id=target_id, 
                          config_id=config_id, 
                          scanner_id='08b69003-5fc2-4037-a479-93b440211c73',
                            preferences={'assets_min_qod' : 50})
        task_id = task['@id']
        # 4. 开始任务
        pygvm.start_task(task_id=task_id)
        return {'ok': True, 'running_id': task_id}
    except Exception as e:
        logger.error('Faild to create gvm task: ' + e.with_traceback)
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()

    
@router.get("/get_task_result")
async def get_task_result(running_id: str):
    try:
        pygvm = get_gvm_conn()
        # 0. 获取task对应results
        vuls = pygvm.list_results(task_id=running_id, filter_str="apply_overrides=0 levels=hml rows=100 min_qod=70 first=1 sort-reverse=severity")
        return {'ok':True, 'vuls': vuls.data}
    except Exception as e:
        logger.error('Faild to get gvm results: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.delete("/delete_task")
async def delete_task(running_id: str):
    try:
        pygvm = get_gvm_conn()
        # 1. 停止task
        pygvm.stop_task(task_id=running_id)
        # 2. 删除task
        pygvm.delete_task(task_id=running_id)
        return {'ok': True}
    except Exception as e:
        logger.error('Faild to delete gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.delete("/delete_splite_task")
async def delete_splite_task(running_id: str):
    try:
        pygvm = get_gvm_conn()
        ok, msg = delete_splite_task_with_id(id=running_id)
        if not ok:
            return {'ok': False, 'errmsg': msg}
        return {'ok': True}
    except Exception as e:
        logger.error('Faild to delete gvm task: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.get("/get_report")
async def get_report(running_id: str):
    try:
        pygvm = get_gvm_conn()
        # 0. 获取task对应report
        report = pygvm.list_reports(task_id=running_id)[0]
        report_id = report['@id']
        # 1. 获取report文件内容
        content = pygvm.get_report(report_id=report_id, report_format_name='PDF', 
                       filter_str='apply_overrides=0 levels=hml rows=1000 min_qod=50 first=1 sort-reverse=severity')
        return {'ok': True, 'content': content}
    except Exception as e:
        logger.error('Faild to get gvm report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.get("/get_splite_task_report")
async def get_splite_task_report(running_id: str):
    try:
        pygvm = get_gvm_conn()
        ok, vuls = reduce_splite_task(id=running_id)
        if not ok:
            return {'ok': False, 'errmsg': vuls}
        content = gvm_zh_report(vuls)
        return {'ok': True, 'content': content}
    except Exception as e:
        logger.error('Faild to get gvm report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()


@router.get("/get_report_zh")
async def get_report_zh(running_id: str):
    try:
        pygvm = get_gvm_conn()
        # 0. 获取task对应results
        vuls = pygvm.list_results(task_id=running_id, filter_str="apply_overrides=0 levels=hml rows=100 min_qod=70 first=1 sort-reverse=severity")
        # 1. 对所有结果做中文化
        html_report = gvm_zh_report(vuls.data)
        content = html_report.encode('utf-8')
        return {'ok':True, 'content': content}
    except Exception as e:
        logger.error('Faild to get gvm report: ' + str(e))
        return {'ok': False, 'errmsg': str(e)}
    finally:
        pygvm.disconnect()