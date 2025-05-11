#!/bin/bash
# Sync-HTTP-MCP 服务器启动脚本
# 在Docker容器中自动启动服务

# 配置
SERVER_DIR="/home/sync-http-mcp"
SERVER_SCRIPT="remote_server.py"
PORT=8081
HOST="0.0.0.0"  # 使用0.0.0.0允许外部访问，移除端口转发需求
LOG_FILE="server.log"

# 确保目录存在
mkdir -p $SERVER_DIR
cd $SERVER_DIR

# 检查服务脚本是否存在
if [ ! -f "$SERVER_SCRIPT" ]; then
    echo "服务脚本不存在，尝试从BOS下载"
    bcecmd bos cp bos:/klx-pytorch-work-bd-bj/xuyehua/scripts/remote_server.py .
    bcecmd bos cp bos:/klx-pytorch-work-bd-bj/xuyehua/scripts/requirements.txt .
    
    # 安装依赖
    pip install -r requirements.txt
fi

# 检查是否已有实例在运行
PID=$(ps -ef | grep "$SERVER_SCRIPT" | grep -v grep | awk '{print $2}')
if [ ! -z "$PID" ]; then
    echo "服务已在运行，PID: $PID"
    echo "如需重启，请先终止现有进程: kill $PID"
    exit 0
fi

# 启动服务
echo "启动服务，端口: $PORT, 主机: $HOST"
nohup python $SERVER_SCRIPT --port $PORT --host $HOST > $LOG_FILE 2>&1 &

# 显示服务信息
NEW_PID=$!
echo "服务已启动，PID: $NEW_PID"
echo "查看日志: tail -f $LOG_FILE"

# 等待服务启动
sleep 2
if ps -p $NEW_PID > /dev/null; then
    echo "服务运行状态: 正常"
    echo "可通过 http://$HOST:$PORT 访问"
else
    echo "服务启动失败，请检查日志: $LOG_FILE"
    exit 1
fi 