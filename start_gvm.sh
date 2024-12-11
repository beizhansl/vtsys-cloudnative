FASTAPI_PROJECT_PATH="/home/gunicorn/scan_server"
GUNICORN_CONFIG="$FASTAPI_PROJECT_PATH/gunicorn_config.py"

export PYTHONPATH=$FASTAPI_PROJECT_PATH:$PYTHONPATH

# 进入工作目录
cd $FASTAPI_PROJECT_PATH

# 启动 Gunicorn
GUNICORN_PROCESS_COUNT=$(pgrep -c -f "gunicorn")
if [ $GUNICORN_PROCESS_COUNT -eq 0 ]; then
	# 如果Gunbicorn未开启则开启
	nohup gunicorn -c $GUNICORN_CONFIG main:app > /home/gunicorn/log/nohup.txt &
fi

sleep 5
GUNICORN_PROCESS_COUNT=$(pgrep -c -f "gunicorn")
if [ $GUNICORN_PROCESS_COUNT -eq 0 ]; then
	echo "Gunicorn start failed"
else
	echo "Gunicorn start succeed"
fi
