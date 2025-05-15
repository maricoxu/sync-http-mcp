#!/bin/bash
# 设置端口转发隧道的自动化脚本

# 配置参数
TARGET_SERVER=${1:-"[default_hostname_or_ip]"}
LOCAL_PORT=${2:-8081}
REMOTE_PORT=${3:-$LOCAL_PORT}

echo "===== 百度内网HTTP服务端口转发工具 ====="
echo "目标服务器: $TARGET_SERVER"
echo "本地端口: $LOCAL_PORT -> 远程端口: $REMOTE_PORT"

# 检查端口是否已被占用
if lsof -i:$LOCAL_PORT > /dev/null 2>&1; then
    echo "警告: 本地端口 $LOCAL_PORT 已被占用"
    echo "可能已有转发隧道在运行，或其他程序正在使用该端口"
    echo "如需终止现有进程，请运行: kill \$(lsof -t -i:$LOCAL_PORT)"
    exit 1
fi

# 创建自动化脚本
RELAY_SCRIPT=$(mktemp)
cat > "$RELAY_SCRIPT" << EOF
#!/bin/bash
# 自动连接relay-cli并设置端口转发

echo "正在通过relay-cli连接到跳板机..."
# 使用expect自动化relay-cli
expect -c '
spawn relay-cli
expect "*$*"
sleep 2
send "ssh -N -L $LOCAL_PORT:localhost:$REMOTE_PORT $TARGET_SERVER\r"
expect {
    "password:" {
        interact
    }
    "*#*" {
        interact
    }
    timeout {
        send_user "连接超时\n"
        exit 1
    }
}
interact
'
EOF

chmod +x "$RELAY_SCRIPT"

# 在新的Terminal窗口中执行relay脚本
osascript -e "tell application \"Terminal\" to do script \"$RELAY_SCRIPT; rm $RELAY_SCRIPT\""

echo ""
echo "===== 操作指南 ====="
echo "1. 在新打开的Terminal窗口中，按照提示操作"
echo "2. 成功连接后，保持Terminal窗口打开以维持端口转发"
echo "3. 现在可以通过 http://localhost:$LOCAL_PORT 访问内网HTTP服务器"
echo ""
echo "端口转发隧道已设置。关闭上述Terminal窗口将终止转发。"