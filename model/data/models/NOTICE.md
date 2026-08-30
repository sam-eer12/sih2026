# Exported models — provenance and licence

Two ONNX files, both exported by [`../../../tools/export_onnx.py`](../../../tools/export_onnx.py)
from the pretrained **SqueezeSegV2** SemanticKITTI checkpoint published by
[lidar-bonnetal](https://github.com/PRBonn/lidar-bonnetal).

| File | Size | Used |
|---|---:|---|
| `squeezesegV2_fp32.onnx` | 3.5 MB | **Yes** — `perception.model` in `config.yaml` points here |
| `squeezesegV2_int8.onnx` | 1.1 MB | No — kept as the evidence for the measurement below, and exercised by `tests/test_onnx_infer.py` |

They are committed because they are small and because a fresh clone should be
able to run the network path without first downloading a checkpoint and
installing PyTorch. Nothing else under `data/` is committed: the KITTI subset is
1.8 GB and the label cache is 96 MB, and both are regenerable.

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

## Licence

The network architecture and the pretrained weights these files are derived from
are the work of the Photogrammetry and Robotics Lab at the University of Bonn,
released under the MIT License, reproduced in full below as that licence
requires. The exported ONNX graphs are a derived form of that work and carry the
same notice.

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
