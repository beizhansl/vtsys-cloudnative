import sqlite3
import time
import os
from config import logger
data_path = '/home/gunicorn/data.db'

def create_task_table():
    try:
        con = sqlite3.connect(data_path)
        cur = con.cursor()
        cur.execute("CREATE TABLE vara(id, running_id, finished_time)")
        cur.execute("INSERT INTO vara VALUES(0, NULL, NULL)")    
        con.commit()
        cur.close()
        con.close()
    except sqlite3.OperationalError:
        return True
    except Exception as e:
        logger.error("Create sql data Error: " + str(e))
    return True

def create_splite_task_table():
    try:
        con = sqlite3.connect(data_path)
        cur = con.cursor()
        cur.execute("CREATE TABLE tasks(id, scanner, task_id)")
        cur.execute("INSERT INTO tasks VALUES(0, NULL, NULL)")    
        con.commit()
        cur.close()
        con.close()
    except sqlite3.OperationalError:
        return True
    except Exception as e:
        logger.error("Create sql tasks Error: " + str(e))
    return True

def insert_splite_task(id:str, task_id:str, scanner:str):
    try:
        con = sqlite3.connect(data_path)
        cur = con.cursor()
        cur.execute(f"INSERT INTO tasks VALUES('{id}', '{scanner}', '{task_id}')")    
        con.commit()
        cur.close()
        con.close()
    except Exception as e:
        logger.error("insert sql tasks Error: " + str(e))
    return True

def get_splite_task(id:str):
    try:
        con = sqlite3.connect(data_path)
        cur = con.cursor()
        res = cur.execute(f"SELECT scanner,task_id FROM tasks WHERE id = '{id}'")
        task_list = res.fetchall()
        cur.close()
        con.close()
        return True, task_list
    except Exception as e:
        logger.error("Get sql tasks Error: " + str(e))
        return False, None

def get_data():
    try:
        con = sqlite3.connect(data_path)
        cur = con.cursor()
        res = cur.execute("SELECT running_id, finished_time FROM vara WHERE id=0")
        data = res.fetchone()
        running_id = data[0]
        finished_time = data[1]
        cur.close()
        con.close()
        return True, running_id, finished_time
    except Exception as e:
        logger.error("Get sql data Error: " + str(e))
        return False, None, None


def update_date(running_id, finished_time):
    try:
        con = sqlite3.connect(data_path)
        cur = con.cursor()
        sql = "UPDATE vara SET "
        if running_id is None:
            sql += "running_id=NULL, "
        else:
            sql += "running_id='%s', " % running_id 
        if finished_time is None:
            sql += "finished_time=NULL "
        else:
            sql += "finished_time=%s " % finished_time
        sql += "WHERE id=0"
        #sql = "UPDATE vara SET running_id='%s' ,finished_time=%s WHERE id=0"% (running_id, finished_time)
        cur.execute(sql)
        con.commit()
        cur.close()
        con.close()
        return True
    except Exception as e:
        logger.error("Update sql data Error: " + str(e))
        return False


if not os.path.exists(data_path):
    create_task_table()
    create_splite_task_table()

if __name__ == '__main__':
    y = 122
    ok = update_date(None, None)
    #create_db()
    o0, a1, a2 = get_data()
    print(ok)
    print(a1)
    print(a2)
    
