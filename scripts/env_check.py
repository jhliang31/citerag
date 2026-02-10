import os
import torch

def main():
    print("=== System ===")
    print("HOSTNAME:", os.uname().nodename)

    print("\n=== PyTorch & CUDA ===")
    print("Torch version:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())

    if torch.cuda.is_available():
        print("Torch CUDA version:", torch.version.cuda)
        print("GPU count:", torch.cuda.device_count())
        print("GPU name:", torch.cuda.get_device_name(0))

        x = torch.randn(1024, 1024, device="cuda")
        y = torch.randn(1024, 1024, device="cuda")
        z = x @ y
        torch.cuda.synchronize()

        print("GPU matmul OK. z shape:", tuple(z.shape))
        print("Allocated (MB):", round(torch.cuda.memory_allocated() / 1024 / 1024, 2))
        print("Reserved  (MB):", round(torch.cuda.memory_reserved() / 1024 / 1024, 2))
    else:
        print("CUDA not available.")

if __name__ == "__main__":
    main()
