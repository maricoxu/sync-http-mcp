#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Git同步状态管理测试脚本

用于测试GitStateManager集成到remote_server.py的功能
"""

import os
import sys
import json
import time
import hashlib
import requests
import tempfile
import shutil
import base64
from pathlib import Path

# 导入项目模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.git_file_state import GitFileState, GitStateManager

# 测试配置
TEST_SERVER_URL = "http://localhost:8081"
TEST_REPO_PATH = None  # 将在测试中创建


def setup_test_repo():
    """创建测试仓库"""
    global TEST_REPO_PATH
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp(prefix="git_sync_test_")
    TEST_REPO_PATH = temp_dir
    
    print(f"创建测试仓库: {TEST_REPO_PATH}")
    return TEST_REPO_PATH


def cleanup_test_repo():
    """清理测试仓库"""
    if TEST_REPO_PATH and os.path.exists(TEST_REPO_PATH):
        shutil.rmtree(TEST_REPO_PATH)
        print(f"已清理测试仓库: {TEST_REPO_PATH}")


def test_init_repo():
    """测试初始化仓库"""
    print("\n--- 测试初始化仓库 ---")
    
    # 创建初始化请求
    response = requests.post(
        f"{TEST_SERVER_URL}/api/v1/sync/init",
        json={
            "path": TEST_REPO_PATH,
            "force": True
        }
    )
    
    # 检查响应
    if response.status_code == 200:
        result = response.json()
        print(f"状态: {result['status']}")
        print(f"消息: {result['message']}")
        print(f"路径: {result['path']}")
        print(f"HEAD提交: {result.get('head_commit', '')}")
        
        assert result["status"] == "success", "初始化仓库失败"
        return True
    else:
        print(f"错误: {response.status_code}")
        print(response.text)
        return False


def test_get_sync_status():
    """测试获取同步状态"""
    print("\n--- 测试获取同步状态 ---")
    
    response = requests.get(
        f"{TEST_SERVER_URL}/api/v1/sync/status",
        params={"path": TEST_REPO_PATH}
    )
    
    # 检查响应
    if response.status_code == 200:
        result = response.json()
        print(f"状态: {result['status']}")
        print(f"最后同步提交: {result.get('last_sync_commit', '')}")
        print(f"最后同步时间: {result.get('last_sync_time', '')}")
        
        assert result["status"] == "success", "获取同步状态失败"
        return True
    else:
        print(f"错误: {response.status_code}")
        print(response.text)
        return False


def test_apply_patch():
    """测试应用补丁"""
    print("\n--- 测试应用补丁 ---")
    
    # 创建测试文件
    test_file_content = "这是一个测试文件\n用于测试Git补丁功能\n"
    
    # 创建补丁内容
    patch_content = f"""diff --git a/test_file.txt b/test_file.txt
new file mode 100644
index 0000000..9daeafb
--- /dev/null
+++ b/test_file.txt
@@ -0,0 +1,2 @@
+这是一个测试文件
+用于测试Git补丁功能
"""
    
    # 发送补丁请求
    response = requests.post(
        f"{TEST_SERVER_URL}/api/v1/sync/patch",
        json={
            "base_commit": None,  # 使用当前HEAD
            "patch_content": base64.b64encode(patch_content.encode()).decode(),
            "binary_files": []
        }
    )
    
    # 检查响应
    if response.status_code == 200:
        result = response.json()
        print(f"状态: {result['status']}")
        print(f"消息: {result['message']}")
        print(f"提交: {result.get('commit', '')}")
        print(f"受影响的文件: {result.get('affected_files', [])}")
        
        assert result["status"] == "success", "应用补丁失败"
        assert "test_file.txt" in result.get("affected_files", []), "补丁未正确标识受影响的文件"
        return True
    else:
        print(f"错误: {response.status_code}")
        print(response.text)
        return False


def main():
    """主测试函数"""
    try:
        # 设置测试环境
        setup_test_repo()
        
        # 运行测试
        tests = [
            test_init_repo,
            test_get_sync_status,
            test_apply_patch
        ]
        
        all_passed = True
        for test_func in tests:
            try:
                if not test_func():
                    all_passed = False
                    print(f"测试失败: {test_func.__name__}")
            except Exception as e:
                all_passed = False
                print(f"测试异常: {test_func.__name__} - {str(e)}")
        
        # 报告结果
        if all_passed:
            print("\n所有测试通过！")
        else:
            print("\n测试失败！")
            sys.exit(1)
    
    finally:
        # 清理测试环境
        cleanup_test_repo()


if __name__ == "__main__":
    main() 