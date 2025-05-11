# Sync-HTTP-MCP 使用指南

本文档提供了Sync-HTTP-MCP简化版客户端的详细使用说明，包括安装、配置和使用方法。

## 特性

简化版客户端具有以下特点：

- **极简依赖**: 仅依赖`requests`和`websocket-client`两个库
- **同步操作**: 提供同步调用API
- **命令行工具**: 支持命令行方式使用
- **易于配置**: 最小化配置要求
- **可靠性**: 专注于稳定性和兼容性
- **增量同步**: 只传输变更的数据块，显著提高效率

## 安装步骤

### 1. 依赖安装

简化版客户端只需要非常基础的依赖：

```bash
# 安装基本依赖
pip install requests>=2.25.0 websocket-client>=1.0.0

# 可选：使用国内镜像加速安装
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests>=2.25.0 websocket-client>=1.0.0

# 可选：如需文件监控功能
pip install watchdog>=2.1.0

# 可选：如需图形界面
pip install PyQt5>=5.12.0
```

### 2. 验证安装

```bash
# 测试是否可以正常导入
python -c "import requests, websocket; print('依赖安装成功')"
```

### 3. 服务器端安装配置

#### 3.1 登录并配置服务器初始环境

```bash
# 通过webrelay或其他方式登录服务器
webrelay

# 或者使用传统登录方式
relay-cli
ssh bjhw-sys-rpm0221.bjhw.baidu.com
```

#### 3.2 配置Docker环境

在服务器上创建Docker容器:

```bash
# 创建并启动Docker容器
docker run \
    --privileged \
    --name=xuyehua_torch \
    --ulimit core=-1 \
    --security-opt seccomp=unconfined \
    -dti \
    --net=host --uts=host --ipc=host \
    --security-opt=seccomp=unconfined \
    -v /home:/home \
    -v /data1:/data1 \
    -v /data2:/data2 \
    -v /data3:/data3 \
    -v /data4:/data4 \
    --shm-size=256g \
    --restart=always \
    iregistry.baidu-int.com/xmlir/xmlir_ubuntu_2004_x86_64:v0.32

# 进入容器环境
docker exec -it xuyehua_torch bash
```

#### 3.3 在Docker中安装并启动服务

在Docker容器内执行以下操作:

```bash
# 创建工作目录
mkdir -p /home/sync-http-mcp
cd /home/sync-http-mcp

# 下载服务器启动脚本
wget https://raw.githubusercontent.com/user/sync-http-mcp/main/scripts/start_server.sh -O start_server.sh
# 或从BOS下载
bcecmd bos cp bos:/klx-pytorch-work-bd-bj/xuyehua/scripts/start_server.sh .

# 添加执行权限
chmod +x start_server.sh

# 启动服务
./start_server.sh
```

启动脚本会自动下载所需文件并安装依赖，然后后台启动服务。

#### 3.4 多台设备访问同一服务器

由于服务器配置为监听所有网络接口（0.0.0.0），多台设备可以直接访问相同的服务器：

1. **获取服务器IP地址**：
   ```bash
   # 在服务器上执行
   hostname -I | awk '{print $1}'
   ```

2. **配置客户端**：
   - 在家里的电脑上：使用服务器的IP地址，例如 `http://10.20.30.40:8081`
   - 在公司的电脑上：同样使用相同的IP地址，访问相同的服务器实例

这种设置允许多台设备同时操作相同的远程环境，确保工作一致性。您可以：
- 在公司开始工作，同步文件到服务器
- 回到家中继续相同的工作，访问同一服务器
- 两地的操作都会应用到相同的服务器环境中

## 使用方法

### 命令行工具使用

命令行工具(`client.py`)提供了多种功能，现在支持更多默认值：

```bash
# 显示帮助信息
python src/client.py --help

# 列出远程目录内容 (默认路径: /home)
python src/client.py list
# 或指定路径
python src/client.py list /data1/projects

# 获取远程文件内容
python src/client.py get /home/myfile.txt

# 上传本地文件到远程 (默认远程路径: /home/文件名)
python src/client.py put local_file.txt
# 或指定远程路径
python src/client.py put local_file.txt /data1/projects/file.txt

# 同步本地目录到远程 (默认本地目录: 当前目录, 默认远程目录: /home)
python src/client.py sync
# 或指定本地和远程路径
python src/client.py sync ./myproject /data1/projects/myproject

# 执行远程命令 (默认工作目录: /home)
python src/client.py --command "ls -la"
# 或指定工作目录
python src/client.py --command "make" --dir /data1/projects/mycode
```

### 增量同步功能

Sync-HTTP-MCP实现了高效的增量同步机制，显著提高传输效率：

```bash
# 默认启用增量同步
python src/client.py sync ./your_project /home/your_project

# 如需禁用增量同步
python src/client.py --no-delta sync ./your_project /home/your_project

# 清理增量同步缓存
python src/client.py clean --local ./your_project
```

#### 增量同步工作原理

1. **文件分块**：系统将文件分割成固定大小块（默认4KB），计算每块的哈希值
2. **缓存机制**：`.mcp_cache.json`文件保存本地和远程文件的元数据信息
3. **差异识别**：比较本地文件与缓存中的远程文件，识别变更的块
4. **智能传输**：只传输变更的块，未变更的块不会重复传输

#### 性能特点

- **首次同步**：首次同步会相对较慢，因为：
  - 所有文件需要完整传输（无现有缓存）
  - 需要计算所有文件的哈希值并创建元数据
  - 缓存需要初始化并存储到本地

- **后续同步**：之后的同步会显著加快：
  - 只传输修改过的文件
  - 对于修改过的文件，只传输变更的块
  - 系统会维护文件状态缓存，加速比较过程

- **适用场景**：
  - 大型代码库的频繁小修改
  - 网络带宽受限环境
  - 需要快速同步的开发工作流

#### 故障排除

如果遇到缓存问题或同步异常，可以清理缓存：

```bash
# 清理特定目录相关的缓存
python src/client.py clean --local ./your_project

# 清理远程路径相关的缓存
python src/client.py clean --remote /home/your_project
```

### 自定义服务器连接

客户端默认连接到`http://localhost:8081`，您可以通过以下方式连接到不同的服务器：

```bash
# 连接到指定服务器
python src/client.py --server http://10.20.30.40:8081 list

# 连接到指定服务器并设置工作区
python src/client.py --server http://10.20.30.40:8081 --workspace /path/to/workspace sync
```

### 在Python代码中使用

您也可以在自己的Python代码中导入并使用客户端库：

```python
from client import SimplifiedMCPClient

# 创建客户端实例
client = SimplifiedMCPClient(
    server_url="http://10.20.30.40:8081",
    workspace_path="/path/to/local/workspace"
)

# 连接服务器
client.connect()

try:
    # 列出远程文件
    files = client.list_files("/remote/path")
    for item in files:
        print(f"{item['type']} - {item['path']}")
    
    # 获取文件内容
    content = client.get_file_content("/remote/file.txt")
    if content:
        print(f"文件内容: {content.decode('utf-8')}")
    
    # 上传文件
    with open("local_file.txt", "rb") as f:
        content = f.read()
    result = client.update_file_content("/remote/file.txt", content)
    print(f"上传结果: {result}")
    
    # 执行命令
    cmd_result = client.execute_command("ls -la", "/remote/dir")
    cmd_id = cmd_result.get("command_id")
    
    # 轮询获取命令状态和输出
    import time
    while True:
        status = client.get_command_status(cmd_id)
        if status.get("status") in ["completed", "failed", "timeout"]:
            output = client.get_command_output(cmd_id)
            print(output.get("output", ""))
            break
        time.sleep(1)
    
    # 同步整个目录
    sync_result = client.sync_local_to_remote("/local/dir", "/remote/dir")
    print(f"同步结果: {sync_result}")
    
finally:
    # 断开连接
    client.disconnect()
```

## WebSocket通知

如果需要接收实时通知，可以使用WebSocket连接：

```python
def handle_notification(data):
    print(f"收到通知: {data}")

# 在新线程中启动WebSocket连接
import threading
ws_thread = threading.Thread(
    target=client.connect_websocket,
    args=(handle_notification,)
)
ws_thread.daemon = True
ws_thread.start()
```

## 最佳实践

1. **建立可靠连接**：
   - 总是使用try-finally结构确保连接被正确关闭
   - 在脚本开始处检查连接状态

2. **高效文件同步**：
   - 利用增量同步功能提高性能
   - 对于首次同步，预留足够时间完成初始化
   - 定期清理不需要的缓存，保持元数据干净

3. **命令执行**：
   - 为长时间运行的命令提供足够的超时时间
   - 总是检查命令执行状态和出错信息

4. **错误处理**：
   - 包装API调用在try-except块中
   - 实现重试逻辑处理临时网络问题

5. **多设备协作**：
   - 使用相同的服务器URL确保在不同设备上操作一致性
   - 可以设置一个配置文件存储常用服务器地址

## 常见问题解决

### 连接问题

1. **无法连接到服务器**:
   ```
   # 检查服务器是否正在运行
   # 在服务器上执行
   ps aux | grep remote_server.py
   
   # 检查网络连接
   ping 10.20.30.40
   ```

2. **连接超时**:
   ```
   # 检查防火墙设置
   # 尝试使用curl测试连接
   curl http://10.20.30.40:8081
   ```

### 文件操作问题

1. **文件上传失败**:
   - 检查远程目录权限
   - 验证文件大小是否超过服务器限制

2. **同步操作卡住**:
   - 对于大文件或大量文件，增加超时参数
   - 考虑将大型目录分成多次同步操作

3. **增量同步问题**:
   - 如果元数据缓存损坏，清理缓存并重新同步
   - 检查是否有足够磁盘空间存储缓存
   - 确保本地和远程路径在缓存中匹配

## 定制与扩展

简化版客户端设计为易于扩展。如需添加新功能，编辑`client.py`文件，添加新的方法到`SimplifiedMCPClient`类。

### 示例：添加文件监控功能

```python
# 需要先安装watchdog库
# pip install watchdog

import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, client, local_path, remote_path):
        self.client = client
        self.local_path = Path(local_path)
        self.remote_path = remote_path
        
    def on_modified(self, event):
        if event.is_directory:
            return
            
        rel_path = Path(event.src_path).relative_to(self.local_path)
        remote_file_path = f"{self.remote_path}/{rel_path}"
        
        with open(event.src_path, "rb") as f:
            content = f.read()
        
        self.client.update_file_content(remote_file_path, content)
        print(f"自动同步文件: {event.src_path} -> {remote_file_path}")

def start_file_monitoring(client, local_path, remote_path):
    event_handler = FileChangeHandler(client, local_path, remote_path)
    observer = Observer()
    observer.schedule(event_handler, local_path, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join() 