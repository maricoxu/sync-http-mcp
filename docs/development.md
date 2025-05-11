# 开发指南

本文档详细说明了Sync-HTTP-MCP项目的开发计划、阶段划分和技术实现细节。

## 开发阶段详解

### 阶段一：核心功能实现 (2周)

#### 目标
实现基础架构和关键功能，完成端到端的文件同步和构建流程。

#### 任务细分

##### 周1: 基础架构
1. **设置项目结构**
   - 创建目录结构和配置系统
   - 实现日志和错误处理机制
   - 搭建开发环境和测试框架

2. **MCP服务器基础框架**
   - 实现FastAPI应用框架
   - 设计数据模型和存储机制
   - 创建基本API路由和中间件

3. **relay-cli自动化**
   - 实现relay-cli的pexpect封装
   - 创建自动化登录和命令执行
   - 处理会话管理和超时机制

##### 周2: 基本功能
1. **文件传输系统**
   - 实现文件上传/下载API
   - 创建文件版本和缓存管理
   - 完成文件传输到远程服务器功能

2. **构建系统**
   - 实现构建触发API
   - 创建构建任务队列和执行
   - 完成日志收集和状态管理

3. **测试与集成**
   - 单元测试主要组件
   - 集成测试端到端流程
   - 修复bug和性能问题

#### 里程碑评估标准
- 能通过HTTP API上传文件到远程服务器
- 能触发远程构建并获取日志
- 所有核心API测试通过率100%
- 端到端测试成功率≥90%

### 阶段二：功能完善 (2周)

#### 目标
完善实时通知和差量同步，提高系统的实用性和效率。

#### 任务细分

##### 周3: 实时功能
1. **WebSocket实现**
   - 创建WebSocket服务和连接管理
   - 实现事件发布和订阅系统
   - 完成客户端实时通知机制

2. **文件监控改进**
   - 实现文件差量计算算法
   - 优化文件传输效率
   - 添加文件冲突检测和解决

3. **构建状态改进**
   - 实现构建状态实时更新
   - 创建构建日志流式传输
   - 添加构建取消和重试功能

##### 周4: 体验提升
1. **多会话管理**
   - 实现多用户和多项目支持
   - 创建会话恢复和超时机制
   - 完成资源隔离和权限控制

2. **并发控制**
   - 实现任务队列和调度系统
   - 优化并发连接和请求处理
   - 完成资源限制和公平分配

3. **错误处理增强**
   - 实现详细错误诊断和报告
   - 创建自动重试和恢复机制
   - 完善日志和监控系统

#### 里程碑评估标准
- WebSocket连接稳定性≥99%
- 文件同步效率提升≥50% (通过差量传输)
- 实时通知延迟≤500ms
- 多用户并发支持≥10个同时活动会话

### 阶段三：客户端集成 (2周)

#### 目标
开发Cursor插件，提供完整的用户体验和界面。

#### 任务细分

##### 周5: 插件基础
1. **插件架构**
   - 设计Cursor插件结构
   - 实现插件激活和配置
   - 创建与MCP服务器的通信层

2. **文件监控**
   - 实现本地文件变化监控
   - 创建文件状态管理
   - 完成变更队列和批处理

3. **用户界面基础**
   - 实现状态栏和通知
   - 创建设置页面
   - 添加项目配置界面

##### 周6: 插件完善
1. **同步功能**
   - 实现自动和手动同步控制
   - 创建同步冲突解决UI
   - 完成同步状态可视化

2. **构建集成**
   - 实现构建触发和控制
   - 创建构建输出面板
   - 添加错误导航和链接

3. **用户体验优化**
   - 实现进度指示和通知
   - 创建文件状态徽章
   - 完善快捷键和命令

#### 里程碑评估标准
- 插件稳定性≥99%
- 用户操作延迟≤100ms
- 文件同步成功率≥99.9%
- 用户界面元素完整度100%

### 阶段四：优化和测试 (2周)

#### 目标
全面测试、优化性能，并完善文档和部署流程。

#### 任务细分

##### 周7: 性能优化
1. **性能分析**
   - 进行性能基准测试
   - 识别瓶颈和优化机会
   - 实施关键优化

2. **资源使用优化**
   - 优化内存和CPU使用
   - 减少网络带宽消耗
   - 改进缓存策略

3. **并发和扩展性**
   - 测试高并发场景
   - 优化数据库和缓存
   - 实现负载均衡支持

##### 周8: 测试和文档
1. **全面测试**
   - 进行功能全面测试
   - 执行压力和性能测试
   - 进行安全和渗透测试

2. **文档完善**
   - 更新API文档
   - 创建用户指南
   - 编写开发者文档

3. **部署优化**
   - 创建容器化部署方案
   - 实现自动化部署脚本
   - 完善监控和维护工具

#### 里程碑评估标准
- 性能优化目标：文件同步延迟≤200ms
- 资源使用减少≥30%
- 测试覆盖率≥90%
- 文档完整度100%

## 技术实现细节

### 文件差量同步算法

我们使用基于rsync算法的思想实现高效文件同步：

1. **分块处理**
   - 将文件分割成固定大小的块（默认4KB）
   - 为每个块计算强弱校验和（滚动校验和和MD5）

2. **差异检测**
   - 客户端计算本地文件的块校验和
   - 服务器比较校验和识别变更的块
   - 仅传输变更的块数据

3. **文件重建**
   - 服务器使用相同的块和新块重建文件
   - 验证完整性后替换原始文件

**代码示例**:
```python
def compute_file_signature(file_path, block_size=4096):
    """计算文件的块签名列表"""
    signatures = []
    with open(file_path, 'rb') as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            weak_checksum = adler32(block)
            strong_checksum = md5(block).hexdigest()
            signatures.append((weak_checksum, strong_checksum))
    return signatures

def find_diff_blocks(local_signatures, remote_signatures):
    """找出需要传输的块"""
    diff_blocks = []
    remote_dict = {weak: (i, strong) for i, (weak, strong) in enumerate(remote_signatures)}
    
    for i, (weak, strong) in enumerate(local_signatures):
        if weak in remote_dict:
            _, remote_strong = remote_dict[weak]
            if strong != remote_strong:
                diff_blocks.append(i)
        else:
            diff_blocks.append(i)
    
    return diff_blocks
```

### relay-cli自动化

使用`pexpect`库自动化与relay-cli的交互：

1. **自动登录**
   - 启动relay-cli进程
   - 匹配登录提示并输入凭据
   - 处理各种可能的交互模式

2. **命令执行**
   - 连接成功后发送SSH命令
   - 处理命令输出和错误
   - 维护命令超时和终止

**代码示例**:
```python
async def connect_through_relay(server, username, command=None):
    """通过relay-cli连接到服务器并执行命令"""
    # 启动relay-cli
    child = pexpect.spawn('relay-cli')
    
    # 等待登录提示
    i = await child.expect(['Please input user\'s password:', 'Connection refused', pexpect.EOF, pexpect.TIMEOUT], timeout=30)
    if i != 0:
        raise ConnectionError(f"Failed to connect to relay: {child.before.decode()}")
    
    # 输入密码（从安全存储获取）
    child.sendline(get_secure_password())
    
    # 等待连接成功
    i = await child.expect(['-bash-baidu-ssl', 'Login failed', pexpect.EOF, pexpect.TIMEOUT], timeout=30)
    if i != 0:
        raise AuthenticationError(f"Failed to authenticate: {child.before.decode()}")
    
    # 如果需要执行命令
    if command:
        # 发送SSH命令
        child.sendline(f"ssh {username}@{server} '{command}'")
        
        # 收集输出直到命令完成
        output = ""
        while True:
            i = await child.expect([f'{username}@{server}.*$', pexpect.EOF, pexpect.TIMEOUT], timeout=120)
            output += child.before.decode()
            if i != 0:
                break
    
    return child, output
```

### 实时WebSocket通信

使用`websockets`库实现实时双向通信：

1. **连接管理**
   - 维护客户端WebSocket连接池
   - 实现心跳检测和超时处理
   - 处理断线重连和会话恢复

2. **事件分发**
   - 基于发布-订阅模式的事件系统
   - 支持特定会话的事件过滤
   - 实现事件优先级和批处理

**代码示例**:
```python
class WebSocketManager:
    def __init__(self):
        self.connections = {}  # session_id -> [websocket connections]
        self.lock = asyncio.Lock()
    
    async def register(self, session_id, websocket):
        """注册新的WebSocket连接"""
        async with self.lock:
            if session_id not in self.connections:
                self.connections[session_id] = []
            self.connections[session_id].append(websocket)
    
    async def unregister(self, session_id, websocket):
        """注销WebSocket连接"""
        async with self.lock:
            if session_id in self.connections:
                if websocket in self.connections[session_id]:
                    self.connections[session_id].remove(websocket)
                if not self.connections[session_id]:
                    del self.connections[session_id]
    
    async def broadcast(self, session_id, message):
        """广播消息到指定会话的所有连接"""
        if session_id in self.connections:
            websockets = self.connections[session_id].copy()
            await asyncio.gather(*[ws.send(json.dumps(message)) for ws in websockets], return_exceptions=True)
```

### 安全认证实现

使用JWT（JSON Web Tokens）实现安全认证：

1. **令牌管理**
   - 生成短期访问令牌和长期刷新令牌
   - 实现令牌验证和过期检查
   - 支持令牌撤销和黑名单

2. **安全存储**
   - 使用安全密钥存储用户凭据
   - 实现密码加盐和哈希
   - 支持临时凭据和会话密钥

**代码示例**:
```python
def create_access_token(data: dict, expires_delta: timedelta = None):
    """创建JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    """验证JWT令牌"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise InvalidCredentialsError("Invalid authentication credentials")
        return payload
    except JWTError:
        raise InvalidCredentialsError("Invalid authentication credentials")
```

## 代码结构

```
sync-http-mcp/
├── sync_http_mcp/
│   ├── __init__.py
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py         # FastAPI主应用
│   │   ├── auth.py        # 认证相关
│   │   ├── config.py      # 配置管理
│   │   ├── utils.py       # 工具函数
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── sessions.py    # 会话API
│   │   │   ├── files.py       # 文件API
│   │   │   └── builds.py      # 构建API
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── session.py     # 会话数据模型
│   │   │   ├── file.py        # 文件数据模型
│   │   │   └── build.py       # 构建数据模型
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── relay.py       # relay-cli服务
│   │   │   ├── file_sync.py   # 文件同步服务
│   │   │   └── build.py       # 构建服务
│   │   └── websocket/
│   │       ├── __init__.py
│   │       ├── manager.py     # WebSocket管理
│   │       └── events.py      # 事件定义
│   ├── client/
│   │   ├── __init__.py
│   │   ├── api.py         # 客户端API库
│   │   ├── file_watcher.py # 文件监控
│   │   └── sync.py        # 同步逻辑
│   └── executor/
│       ├── __init__.py
│       ├── app.py         # Flask应用
│       └── runner.py      # 命令执行器
├── tests/
│   ├── __init__.py
│   ├── conftest.py        # 测试配置
│   ├── test_server/
│   │   ├── __init__.py
│   │   ├── test_api.py
│   │   └── test_websocket.py
│   └── test_client/
│       ├── __init__.py
│       └── test_sync.py
├── docs/
│   ├── design.md          # 设计文档
│   ├── architecture.md    # 架构文档
│   └── development.md     # 开发指南
├── requirements.txt       # 依赖列表
├── setup.py               # 安装脚本
└── README.md              # 项目说明
```