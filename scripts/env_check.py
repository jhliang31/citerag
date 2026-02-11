import torch
import os

print("=== Day02 Environment Check (T4) ===")
print("Hostname:", os.uname().nodename)
print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    x = torch.randn(1024, 1024, device="cuda")
    y = torch.randn(1024, 1024, device="cuda")
    z = x @ y
    torch.cuda.synchronize()
    print("GPU matmul OK. shape:", z.shape)
    print("Allocated MB:", round(torch.cuda.memory_allocated()/1024/1024, 2))

