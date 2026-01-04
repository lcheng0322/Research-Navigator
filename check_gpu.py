# check_gpu.py
import torch
import subprocess
import sys

print("=== 系统环境检查 ===")
print(f"Python 版本: {sys.version}")
print(f"PyTorch 版本: {torch.__version__}")
print(f"CUDA 可用: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    cuda_version = torch.version.cuda
    print(f"CUDA 版本: {cuda_version}")
    print(f"GPU 数量: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        gpu_name = torch.cuda.get_device_name(i)
        print(f"GPU {i}: {gpu_name}")
else:
    print("❌ 未检测到 CUDA 设备")
    print("CUDA 版本: N/A")

# 检查 NVIDIA 驱动
try:
    result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ NVIDIA 驱动已安装")
        # 解析 nvidia-smi 输出获取驱动版本
        for line in result.stdout.split('\n'):
            if 'Driver Version' in line:
                print(f"🎯 {line.strip()}")
    else:
        print("❌ 未找到 nvidia-smi，可能没有安装 NVIDIA 驱动")
except FileNotFoundError:
    print("❌ nvidia-smi 未找到，请安装 NVIDIA 驱动")