import time
import onnxruntime as ort
from transformers import AutoTokenizer

# ------------ Load tokenizer & quantized ONNX model ------------
tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
session = ort.InferenceSession(
    r"models\distilfinbert_onnx_q8\model_quantized.onnx",
    providers=["CPUExecutionProvider"],
)

# ------------ Example text (represents one filing paragraph) ------------
text = "The company reported an increase in revenue but a decline in net income."

# Tokenize → NumPy (int64 is required for ORT)
inputs = tokenizer(
    text, return_tensors="np", padding="max_length", truncation=True, max_length=128
)
onnx_inputs = {k: v.astype("int64") for k, v in inputs.items()}

# Warm-up run (jit caches, memory paging, etc.)
session.run(None, onnx_inputs)

# Timed benchmark
runs = 10
start = time.time()
for _ in range(runs):
    session.run(None, onnx_inputs)
avg = (time.time() - start) / runs
print(f"Average CPU latency per filing: {avg:.3f} seconds")
