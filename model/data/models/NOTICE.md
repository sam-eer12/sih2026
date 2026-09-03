# Exported models — provenance and licence

Four files, all derived from the pretrained **SqueezeSegV2** SemanticKITTI
checkpoint published by
[lidar-bonnetal](https://github.com/PRBonn/lidar-bonnetal).

| File | Size | Produced by | Used |
|---|---:|---|---|
| `squeezesegV2_fp32.onnx` | 3.5 MB | [`tools/export_onnx.py`](../../../tools/export_onnx.py) | **Yes** — `perception.model` in `config.yaml` points here |
| `squeezesegV2_int8.onnx` | 1.1 MB | `tools/export_onnx.py` | No — kept as the evidence for the measurement below, and exercised by `tests/test_onnx_infer.py` |
| `squeezesegV2_5class.pt` | 3.6 MB | [`tools/finetune.py`](../../../tools/finetune.py) | **No** — see *The fine-tuned weights* below |
| `squeezesegV2_5class.uniform.pt` | 3.6 MB | `tools/finetune.py --uniform-weights` | **No** — the control for the same |

They are committed because they are small and because a fresh clone should be
able to run the network path without first downloading a checkpoint and
installing PyTorch. Nothing else under `data/` is committed except the fine-tune
split manifest and its two evaluation reports: the KITTI subset is 1.8 GB and
the label cache is 96 MB, and both are regenerable.

## Regenerating them

```bash
curl -O http://www.ipb.uni-bonn.de/html/projects/bonnetal/lidar/semantic/models/squeezesegV2.tar.gz
tar xzf squeezesegV2.tar.gz -C ../checkpoints/
python ../../../tools/export_onnx.py
```

The export verifies itself: the released weights load with `strict=True`, and
the exported graph must reproduce the PyTorch reference's argmax. Measured on
KITTI scan `00/000008`:

| | Size | Latency | Argmax agreement with PyTorch |
|---|---:|---:|---:|
| fp32 | 3.71 MB | 86.0 ms | 100.000% |
| int8 | 1.11 MB | 86.2 ms | 95.058% |

## The fine-tuned weights

`squeezesegV2_5class.pt` and its `.uniform` control are the Day 10 experiment
(`docs/progress/sameer.md`), kept as **evidence of a negative result**. The
backbone is frozen and the decoder and a new 5-output head were fine-tuned on
sequences 00 and 05, then scored on 04, which neither was trained on:

| | pretrained | inverse-freq | uniform |
|---|---:|---:|---:|
| mIoU | **0.8454** | 0.8303 | 0.8384 |
| point accuracy | **0.9409** | 0.9339 | 0.9286 |
| object recall | 0.9145 | **0.9427** | 0.8978 |

**Neither beats the pretrained network on mIoU, so neither is loaded by
anything.** `config.yaml` still points at `squeezesegV2_fp32.onnx`. They are
here so that "we tried fine-tuning and it did not help" is a claim a judge can
check rather than take on trust, and so that the two weightings can be compared
without a 10-minute rerun. Their provenance is
`../splits/finetune_5class.json` (which sequences trained and which validated)
and `../finetune_report*.json` (what the answer was).

They load with `torch.load(..., weights_only=False)` because the checkpoint
carries the architecture dict alongside the state dict. That flag executes
pickle, so it is safe only for files you produced yourself — which these are.

## Licence

The network architecture and the pretrained weights these files are derived from
are the work of the Photogrammetry and Robotics Lab at the University of Bonn,
released under the MIT License, reproduced in full below as that licence
requires. The exported ONNX graphs **and the fine-tuned `.pt` checkpoints** are
derived forms of that work and carry the same notice: fine-tuning changes the
weights, not their provenance, and the frozen backbone in the `.pt` files is
bit-for-bit the released one.

```
The MIT License

Copyright (c) 2019 Andres Milioto, Jens Behley, Cyrill Stachniss, Photogrammetry and Robotics Lab, University of Bonn.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

**Cite the work if you use it:**

> A. Milioto, I. Vizzo, J. Behley, C. Stachniss.
> *RangeNet++: Fast and Accurate LiDAR Semantic Segmentation.*
> IROS 2019.

## A note on the training data

The weights were trained on **SemanticKITTI**, which is licensed
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) —
attribution, share-alike, and **non-commercial**. That is fine for a hackathon
and it constrains what may be claimed: no statement in the deck or the report
may imply a commercial product built on these weights.

This applies with less indirection to the `.pt` files than to the ONNX exports.
The exports inherited SemanticKITTI only through Bonn's training run; we trained
the `.pt` checkpoints on the dataset ourselves, on sequences 00 and 05 of the
subset under `data/kitti/`. Same conclusion, shorter chain — and the share-alike
term is the reason this NOTICE travels with the files.
