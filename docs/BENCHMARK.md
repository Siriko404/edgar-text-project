\# DistilFinBERT Latency Benchmarks

| Model variant | File size | Avg CPU latency (s) | Notes |

|--------------|-----------|---------------------|-------|

| PyTorch (HF) | 438 MB    | 1.062              | baseline on 10× loop, Intel i5-10th |

| ONNX INT8    | 110 MB    | 0.842              | quantized, AVX-2, same machine |



