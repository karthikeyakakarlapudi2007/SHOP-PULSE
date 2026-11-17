| Case | Rotation (expected → applied) | Quality before → after | Variant | CER before → after | WER before → after | Word recall before → after | Critical tokens before → after |
|---|---|---|---|---|---|---|---|
| Clear portrait invoice | 0 → 0 | EXCELLENT → EXCELLENT | enhanced | 0.224 → 0.131 | 0.218 → 0.100 | 0.864 → 0.982 | 0.903 → 1.000 |
| Landscape invoice (correctly oriented, wider than tall) | 0 → 0 | EXCELLENT → EXCELLENT | enhanced | 0.224 → 0.156 | 0.213 → 0.124 | 0.854 → 0.989 | 0.955 → 1.000 |
| Invoice rotated 90 degrees clockwise | 270 → 270 | GOOD → EXCELLENT | enhanced | 0.216 → 0.207 | 0.209 → 0.173 | 0.873 → 0.909 | 0.935 → 1.000 |
| Invoice upside down (180 degrees) | 180 → 180 | GOOD → EXCELLENT | enhanced | 0.833 → 0.209 | 1.000 → 0.182 | 0.009 → 0.900 | 0.000 → 0.968 |
| Invoice rotated 90 degrees anticlockwise (270) | 90 → 90 | GOOD → EXCELLENT | enhanced | 0.831 → 0.129 | 1.000 → 0.100 | 0.009 → 0.982 | 0.000 → 1.000 |
| Slightly tilted invoice (4 degrees) | 0 → 0 | GOOD → EXCELLENT | corrected | 0.216 → 0.129 | 0.200 → 0.100 | 0.891 → 0.973 | 0.935 → 0.968 |
| Perspective-distorted photograph on a table | 0 → 0 | NEEDS_ENHANCEMENT → EXCELLENT | corrected | 0.221 → 0.131 | 0.409 → 0.109 | 0.718 → 0.973 | 0.677 → 1.000 |
| Shadow-heavy photograph | 0 → 0 | NEEDS_ENHANCEMENT → EXCELLENT | enhanced | 0.207 → 0.129 | 0.273 → 0.091 | 0.809 → 0.982 | 0.806 → 0.968 |
| Low-light photograph | 0 → 0 | NEEDS_ENHANCEMENT → EXCELLENT | enhanced | 1.000 → 0.128 | 1.000 → 0.091 | 0.000 → 0.991 | 0.000 → 1.000 |
| Blurry photograph (moderate defocus) | 0 → 0 | NEEDS_ENHANCEMENT → NEEDS_ENHANCEMENT | binarized | 0.249 → 0.128 | 0.482 → 0.282 | 0.591 → 0.764 | 0.452 → 0.839 |
| Low-resolution photograph (45% scale) | 0 → 0 | NEEDS_ENHANCEMENT → EXCELLENT | enhanced | 0.136 → 0.138 | 0.136 → 0.136 | 0.946 → 0.946 | 0.968 → 0.968 |
| Two-page invoice (second page sideways) | 0 → 0, 270 | EXCELLENT → EXCELLENT, GOOD → EXCELLENT | enhanced, corrected | 0.239 → 0.201 | 0.245 → 0.182 | 0.849 → 0.917 | 0.878 → 0.939 |
| Small decimal values at reduced print size | 0 → 0 | GOOD → EXCELLENT | enhanced | 0.207 → 0.134 | 0.182 → 0.118 | 0.891 → 0.964 | 0.968 → 1.000 |
| Faint printed text | 0 → 0 | NEEDS_ENHANCEMENT → EXCELLENT | binarized | 0.209 → 0.129 | 0.182 → 0.100 | 0.900 → 0.982 | 1.000 → 1.000 |
| Bordered table, tilted 7 degrees, sideways photo | 90 → 90 | GOOD → EXCELLENT | corrected | 0.811 → 0.128 | 0.991 → 0.091 | 0.027 → 0.991 | 0.000 → 1.000 |
| Paper on a background close to the paper colour | 0 → 0 | EXCELLENT → EXCELLENT | corrected | 0.647 → 0.138 | 0.791 → 0.127 | 0.764 → 0.955 | 0.968 → 0.968 |
| Severely blurred, low-resolution capture (should ask for retake) | 0 → 0 | UNREADABLE → POOR | enhanced | 1.000 → 0.959 | 1.000 → 0.991 | 0.000 → 0.009 | 0.000 → 0.000 |
