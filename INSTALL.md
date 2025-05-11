# Sync-HTTP-MCP 安装指南

本文档提供了Sync-HTTP-MCP系统的详细安装和使用说明，包括服务器端和客户端的配置。

## 系统要求

### 服务器端
- Python 3.7+
- 运行在百度内网服务器上
- 建议至少4GB内存和10GB硬盘空间

### 客户端
- Python 3.7+
- 安装了PyQt5（如果需要GUI界面）
- 支持的操作系统：Windows、macOS、Linux

## 安装步骤

### 1. 服务器端安装

1. **登录到百度内网服务器**
   ```bash
   # 使用relay-cli连接到跳板机
   relay-cli
   
   # 连接到目标服务器
   ssh username@server-address
   ```

2. **创建工作目录**
   ```bash
   mkdir -p ~/sync-http-mcp
   cd ~/sync-http-mcp
   ```

3. **下载或上传项目文件**
   ```bash
   # 方法1: 克隆仓库(如果服务器可以访问代码仓库)
   git clone https://path/to/repo.git .
   
   # 方法2: 从本地上传(使用scp或其他方式)
   # 在本地执行:
   scp -r /path/to/sync-http-mcp/* username@server-address:~/sync-http-mcp/
   ```

4. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

5. **启动服务器**
   ```bash
   # 前台运行(仅用于测试)
   python src/remote_server.py --port 8081 --host 127.0.0.1
   
   # 或者使用nohup后台运行
   nohup python src/remote_server.py --port 8081 --host 127.0.0.1 > server.log 2>&1 &
   ```

### 2. 端口转发设置

为了从本地访问内网服务器，需要设置SSH端口转发：

1. **手动设置端口转发**
   ```bash
   # 打开新终端
   relay-cli
   
   # 在跳板机上设置端口转发
   ssh -N -L 8081:localhost:8081 username@server-address
   ```

2. **或者使用自动脚本**
   ```bash
   # 在本地执行
   ./scripts/setup-tunnel.sh server-address 8081
   ```

### 3. 客户端安装

1. **安装依赖**
   ```bash
   # 安装基本依赖
   pip install -r requirements.txt
   
   # 如果需要GUI界面，还需安装PyQt5
   pip install PyQt5
   ```

2. **验证连接**
   ```bash
   # 测试连接是否成功
   python src/mcp_cli.py ls /
   ```

## 使用说明

### 命令行工具使用

命令行工具(`mcp_cli.py`)提供了多种功能：

```bash
# 显示帮助信息
python src/mcp_cli.py --help

# 列出远程目录内容
python src/mcp_cli.py ls /path/to/dir

# 同步本地文件或目录到远程
python src/mcp_cli.py sync /local/path /remote/path

# 获取远程文件内容
python src/mcp_cli.py get /remote/file.txt --output local_file.txt

# 上传本地文件到远程
python src/mcp_cli.py put local_file.txt /remote/file.txt

# 执行远程命令
python src/mcp_cli.py exec "ls -la" --dir /remote/dir

# 执行远程构建
python src/mcp_cli.py build --dir /path/to/project --build-command "make" --target clean
```

### GUI界面使用

GUI界面提供了更直观的操作方式：

```bash
# 启动GUI客户端
python src/cursor_integration.py
```

GUI界面包含以下功能：
- 浏览远程文件系统
- 同步本地文件到远程
- 远程命令执行
- 文件编辑
- 实时监控文件变化

## 故障排除

### 常见问题

1. **无法连接到服务器**
   - 确认端口转发是否正确设置
   - 检查服务器是否正在运行
   - 验证防火墙设置是否允许连接

2. **同步文件失败**
   - 检查远程路径是否存在
   - 确认远程路径的写入权限
   - 检查文件大小是否超过限制

3. **命令执行卡住或超时**
   - 增加命令执行的超时时间
   - 检查命令是否需要交互式输入

### 日志查看

- 服务器日志默认保存在启动目录
- 客户端错误会显示在控制台输出中

## 高级配置

### 服务器参数

`remote_server.py`接受以下参数：

```
--host HOST          监听地址(默认:127.0.0.1)
--port PORT          监听端口(默认:8081)
--log-level LEVEL    日志级别(DEBUG, INFO, WARNING, ERROR)
--max-upload SIZE    最大上传文件大小(MB)
--workspace DIR      工作目录根路径
```

### 客户端配置

可以创建配置文件`~/.mcp_config.json`来存储默认参数：

```json
{
  "server": "http://localhost:8081",
  "workspace": "/path/to/local/workspace",
  "default_remote_dir": "/path/to/remote/dir"
}
```

## 安全注意事项

1. 服务器仅绑定到`127.0.0.1`，不对外暴露
2. 所有连接通过SSH隧道加密
3. 建议定期更换SSH密钥
4. 限制访问敏感目录和命令执行权限 