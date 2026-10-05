# C-04 complete inspection image index

See the [investigation and disposition](c04-investigation-20260924.md) for methods,
numerical results, case observations and limitations. The final verification
receipt binds every original PNG and sheet to its exact case, role and seed.
All 172 generated images were inspected; repeated base images remain included.

## Training — 108 images

Each diagnostic sheet contains eight native 512px tiles: four roles in columns
(base/plain, base/trigger, adapter/plain, adapter/trigger) and two seeds in rows.
Every repetition was inspected, including the matching r2/r3 pairs. Repetitions
are independent training attempts, not continuation of the preceding checkpoint.

| Endpoint / repetition | Pears (11760922, 11760923) | Geometry (11860922, 11860923) |
| --- | --- | --- |
| Two updates / r1 | [Eight images](evidence/phase-c04-images/training-short-r1-vase-and-pears.png) | [Eight images](evidence/phase-c04-images/training-short-r1-paper-geometry.png) |
| Two updates / r2 | [Eight images](evidence/phase-c04-images/training-short-r2-vase-and-pears.png) | [Eight images](evidence/phase-c04-images/training-short-r2-paper-geometry.png) |
| Two updates / r3 | [Eight images](evidence/phase-c04-images/training-short-r3-vase-and-pears.png) | [Eight images](evidence/phase-c04-images/training-short-r3-paper-geometry.png) |
| Four updates / r1 | [Eight images](evidence/phase-c04-images/training-long-r1-vase-and-pears.png) | [Eight images](evidence/phase-c04-images/training-long-r1-paper-geometry.png) |
| Four updates / r2 | [Eight images](evidence/phase-c04-images/training-long-r2-vase-and-pears.png) | [Eight images](evidence/phase-c04-images/training-long-r2-paper-geometry.png) |
| Four updates / r3 | [Eight images](evidence/phase-c04-images/training-long-r3-vase-and-pears.png) | [Eight images](evidence/phase-c04-images/training-long-r3-paper-geometry.png) |

The [12 validation previews](evidence/phase-c04-images/training-validation-previews.png)
retain baseline/candidate pairs for all six attempts. They are diagnostic images,
not additional independent prompt-level acceptance cases.

## Deployed candidate — 64 images

Each sheet contains all four roles in a 2×2 grid: base/plain and base/trigger above,
adapter/plain and adapter/trigger below. 512px tiles are native; 1024px originals
are previewed at 768px using Lanczos. Original 1024px PNGs remain unmodified in
the workspace and are indexed by the receipt. Ambiguous red-object geometry was
additionally inspected at original resolution.

| Resolution / strength | Pears 11760922 | Pears 11760923 | Geometry 11860922 | Geometry 11860923 |
| --- | --- | --- | --- | --- |
| 512 / 0.25 | [Four images](evidence/phase-c04-images/diagnostic-512-250-vase-and-pears-11760922.png) | [Four images](evidence/phase-c04-images/diagnostic-512-250-vase-and-pears-11760923.png) | [Four images](evidence/phase-c04-images/diagnostic-512-250-paper-geometry-11860922.png) | [Four images](evidence/phase-c04-images/diagnostic-512-250-paper-geometry-11860923.png) |
| 512 / 1.0 | [Four images](evidence/phase-c04-images/diagnostic-512-1000-vase-and-pears-11760922.png) | [Four images](evidence/phase-c04-images/diagnostic-512-1000-vase-and-pears-11760923.png) | [Four images](evidence/phase-c04-images/diagnostic-512-1000-paper-geometry-11860922.png) | [Four images](evidence/phase-c04-images/diagnostic-512-1000-paper-geometry-11860923.png) |
| 1024 / 0.25 | [Four images](evidence/phase-c04-images/diagnostic-1024-250-vase-and-pears-11760922.png) | [Four images](evidence/phase-c04-images/diagnostic-1024-250-vase-and-pears-11760923.png) | [Four images](evidence/phase-c04-images/diagnostic-1024-250-paper-geometry-11860922.png) | [Four images](evidence/phase-c04-images/diagnostic-1024-250-paper-geometry-11860923.png) |
| 1024 / 1.0 | [Four images](evidence/phase-c04-images/diagnostic-1024-1000-vase-and-pears-11760922.png) | [Four images](evidence/phase-c04-images/diagnostic-1024-1000-vase-and-pears-11760923.png) | [Four images](evidence/phase-c04-images/diagnostic-1024-1000-paper-geometry-11860922.png) | [Four images](evidence/phase-c04-images/diagnostic-1024-1000-paper-geometry-11860923.png) |

The [source/prepared dataset sheet](evidence/phase-c04-data-source-prepared.png)
was audited separately; these six views are not part of the 172 generated images.
