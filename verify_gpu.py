import torch
print("=== GPU 安装验证 ===")
print(f"PyTorch 版本: {torch.__version__}")
print(f"CUDA 可用: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"CUDA 版本: {torch.version.cuda}")
    print(f"GPU 数量: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        print(f"GPU {i}: {torch.cuda.get_device_name(i)}")
    
    # 测试 GPU 计算
    print("\n=== GPU 性能测试 ===")
    device = torch.device("cuda")
    x = torch.randn(1000, 1000).to(device)
    y = torch.randn(1000, 1000).to(device)
    
    import time
    start = time.time()
    z = torch.matmul(x, y)
    end = time.time()
    
    print(f"GPU 矩阵乘法时间: {end-start:.4f} 秒")
    print(f"GPU 内存分配: {torch.cuda.memory_allocated()/1024**2:.2f} MB")
else:
    print("❌ GPU 仍然不可用")