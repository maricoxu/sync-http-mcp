# Sync-HTTP-MCP 开发阶段与测试计划

## 概述

本文档详细说明了Sync-HTTP-MCP项目的分阶段开发计划，每个阶段都包含明确的实现目标、测试方法和完成标准。

## 阶段一：基础服务器设置与测试 (1周)

### 目标
搭建基本的HTTP服务器框架，实现简单API，验证端口转发隧道的可行性。

### 核心任务
1. 实现基础HTTP服务器
2. 创建端口转发脚本
3. 验证本地到内网服务器的通信

### 详细步骤

#### 1.1 实现最小可行服务器
- 创建简化版remote_server.py，仅包含:
  - 根路由"/"返回服务器信息
  - 健康检查endpoint"/health"
  - 简单文件列表endpoint"/api/v1/files"（仅当前目录）

#### 1.2 端口转发设置
- 完善setup-tunnel.sh脚本
- 验证隧道建立和维护逻辑

#### 1.3 测试方法

**服务器端测试:**
```bash
# 登录到内网服务器
relay-cli
ssh bjhw-sys-rpm0221.bjhw.baidu.com

# 启动简化版服务器
cd ~/sync-http-mcp
python src/remote_server.py --port 8081 --host 127.0.0.1
```

**本地测试:**
```bash
# 在新终端设置端口转发
./scripts/setup-tunnel.sh bjhw-sys-rpm0221.bjhw.baidu.com 8081

# 测试API连通性
curl http://localhost:8081
curl http://localhost:8081/health
curl http://localhost:8081/api/v1/files
```

### 完成标准
- 服务器可以在内网成功启动
- 端口转发隧道可以成功建立
- 本地请求能够通过隧道到达服务器并得到正确响应

## 阶段二：文件操作功能实现与测试 (2周)

### 目标
实现完整的文件操作API，包括文件读取、写入和同步功能。

### 核心任务
1. 实现文件内容读取API
2. 实现文件内容写入API
3. 实现批量文件同步API
4. 编写命令行测试工具

### 详细步骤

#### 2.1 实现文件内容API
- 完善"/api/v1/files/content" GET和PUT endpoints
- 实现文件读写逻辑，包括base64编码/解码
- 添加校验和验证

#### 2.2 实现批量同步API
- 实现"/api/v1/files/sync" POST endpoint
- 支持多文件同时上传
- 处理同步错误和状态报告

#### 2.3 创建测试工具
- 编写simple_client.py命令行工具:
  - 支持上传单个文件
  - 支持下载单个文件
  - 支持目录同步

#### 2.4 测试方法

**服务器端:**
```bash
# 启动更新后的服务器
python src/remote_server.py --port 8081
```

**本地测试:**
```bash
# 设置端口转发
./scripts/setup-tunnel.sh

# 测试文件读取
curl "http://localhost:8081/api/v1/files/content?path=/home/user/test.txt"

# 测试文件写入 (示例curl命令)
curl -X PUT http://localhost:8081/api/v1/files/content \
  -H "Content-Type: application/json" \
  -d '{"path":"/home/user/test.txt","content":"SGVsbG8gV29ybGQ=","checksum":"b10a8db164e0754105b7a99be72e3fe5"}'

# 使用测试工具
python scripts/simple_client.py upload local_file.txt /home/user/remote_file.txt
python scripts/simple_client.py download /home/user/remote_file.txt local_copy.txt
python scripts/simple_client.py sync ./local_dir /home/user/remote_dir
```

### 完成标准
- 所有文件操作API正常工作
- 能够成功上传和下载不同类型的文件
- 批量同步功能正确处理多个文件
- 错误情况（如文件不存在、权限不足）能够被正确处理

## 阶段三：命令执行功能实现与测试 (1周)

### 目标
实现远程命令执行API，支持长时间运行的命令和实时日志获取。

### 核心任务
1. 实现命令执行API
2. 实现命令状态查询
3. 实现命令输出获取
4. 创建命令执行测试工具

### 详细步骤

#### 3.1 实现命令API
- 实现"/api/v1/commands" POST endpoint
- 实现后台命令执行逻辑
- 支持工作目录和环境变量设置

#### 3.2 实现状态和输出API
- 实现"/api/v1/commands/{id}" GET endpoint
- 实现"/api/v1/commands/{id}/output" GET endpoint
- 支持长时间运行命令的状态跟踪

#### 3.3 创建测试工具
- 扩展simple_client.py:
  - 添加命令执行功能
  - 添加实时日志查看功能

#### 3.4 测试方法

**服务器端:**
```bash
# 启动更新后的服务器
python src/remote_server.py --port 8081
```

**本地测试:**
```bash
# 执行命令
curl -X POST http://localhost:8081/api/v1/commands \
  -H "Content-Type: application/json" \
  -d '{"command":"ls -la","working_directory":"/home/user"}'

# 获取命令状态 (使用返回的命令ID)
curl http://localhost:8081/api/v1/commands/cmd_1234567890

# 获取命令输出
curl http://localhost:8081/api/v1/commands/cmd_1234567890/output

# 使用测试工具
python scripts/simple_client.py exec "make all" /home/user/project
python scripts/simple_client.py status cmd_1234567890
python scripts/simple_client.py logs cmd_1234567890 --follow
```

### 完成标准
- 命令可以在服务器端成功执行
- 状态和退出码正确返回
- 输出内容完整无缺失
- 长时间运行的命令能够正确处理

## 阶段四：WebSocket实时通知实现与测试 (1周)

### 目标
实现WebSocket服务，提供文件变更和命令状态实时通知。

### 核心任务
1. 实现WebSocket服务器
2. 实现文件变更事件通知
3. 实现命令状态实时更新
4. 创建WebSocket测试客户端

### 详细步骤

#### 4.1 实现WebSocket服务器
- 实现"/ws" WebSocket endpoint
- 创建连接管理器和广播机制

#### 4.2 实现事件通知
- 在文件变更时发送通知
- 在命令状态变化时发送通知
- 命令输出流式传输

#### 4.3 创建测试工具
- 编写ws_client.py:
  - 连接WebSocket服务
  - 接收和显示事件
  - 简单的GUI监控界面

#### 4.4 测试方法

**服务器端:**
```bash
# 启动更新后的服务器
python src/remote_server.py --port 8081
```

**本地测试:**
```bash
# 启动WebSocket测试客户端
python scripts/ws_client.py --url ws://localhost:8081/ws

# 同时在另一个终端执行文件操作和命令
python scripts/simple_client.py upload test.txt /home/user/test.txt
python scripts/simple_client.py exec "sleep 10 && echo done" /home/user
```

### 完成标准
- WebSocket连接可以成功建立
- 文件变更事件能实时推送
- 命令状态变更能实时推送
- 命令输出能够流式传输

## 阶段五：客户端工具与UI实现 (2周)

### 目标
开发完整的命令行客户端和简单的GUI界面。

### 核心任务
1. 实现功能完善的命令行客户端
2. 实现文件监控和自动同步
3. 开发简单的GUI界面
4. 集成测试所有功能

### 详细步骤

#### 5.1 完善命令行客户端
- 重构simple_client.py为完整功能的client.py:
  - 配置文件支持
  - 同步排除规则
  - 增量同步算法

#### 5.2 实现文件监控
- 添加文件系统监控功能:
  - 监控本地目录变更
  - 自动触发同步
  - 冲突检测和解决

#### 5.3 开发简单GUI
- 使用PyQt或Electron创建简单界面:
  - 文件同步状态显示
  - 命令执行面板
  - 日志查看器

#### 5.4 测试方法

**服务器端:**
```bash
# 启动完整服务器
python src/remote_server.py --port 8081
```

**本地测试:**
```bash
# 配置客户端
python src/client.py configure

# 启动监控和同步
python src/client.py watch ./local_project /home/user/remote_project

# 执行远程命令
python src/client.py exec "make test" /home/user/remote_project

# 启动GUI
python src/gui_client.py
```

### 完成标准
- 命令行客户端功能完整可用
- 文件监控能够准确检测变更
- 增量同步算法能够提高效率
- GUI界面能够正常工作且提供良好用户体验

## 阶段六：性能优化和文档完善 (1周)

### 目标
优化系统性能，完善文档，准备发布。

### 核心任务
1. 性能测试和优化
2. 安全性审查
3. 完善文档
4. 打包和发布准备

### 详细步骤

#### 6.1 性能优化
- 分析和优化性能瓶颈:
  - 文件传输效率
  - 命令执行开销
  - WebSocket消息处理

#### 6.2 安全审查
- 检查和加强安全措施:
  - API认证
  - 数据验证
  - 错误处理

#### 6.3 文档完善
- 更新所有文档:
  - 用户指南
  - API参考
  - 开发者文档
  - 示例和教程

#### 6.4 测试方法

**性能测试:**
```bash
# 文件传输性能测试
python scripts/performance_test.py file_transfer

# 命令执行性能测试
python scripts/performance_test.py command_exec

# 并发连接测试
python scripts/performance_test.py connections
```

**安全测试:**
```bash
# 运行安全检查脚本
python scripts/security_check.py
```

### 完成标准
- 性能指标满足预期:
  - 大文件传输速度 > 10MB/s
  - 命令启动延迟 < 500ms
  - 支持并发连接 > 10
- 所有已知安全问题已修复
- 文档完整且易于理解
- 系统准备好进行发布