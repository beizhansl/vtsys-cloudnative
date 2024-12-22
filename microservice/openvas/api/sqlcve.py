import sqlite3
import logging
import structlog

data_path = '/mnt/cve/cve.db'       # 必须挂载进来

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = structlog.wrap_logger(logging.getLogger())

class CveSql:
    def __init__(self) -> None:
        self._sql = sqlite3.connect(data_path)
    
    def find_vul(self, cve_id: str):
        try:
            cur = self._sql.cursor()
            sql = "SELECT * FROM cves WHERE cve='%s'" % cve_id
            res = cur.execute(sql)
            data = res.fetchone()
            self._sql.commit()
            cur.close()
            if data == None:
                return False, None
            return True, data
        except Exception as e:
            logger.error("Find vul Error: " + str(e))
            return False, None
