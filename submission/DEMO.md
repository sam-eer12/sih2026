# Demo — Team KANVSS

## Live deployment

**https://nexa-drdo.duckdns.org**

Public HTTPS. Sign in with email/password or Google to reach the dashboard.

## Demo video

<!-- Replace with the actual link once recorded. -->

    Link: <YOUTUBE_OR_DRIVE_LINK>

Set sharing to "anyone with the link can view" and verify it in a private window.

## What the demo shows

| Time | Beat |
|---|---|
| 0:00–0:10 | Raw KITTI point cloud — 120,000 points, 10 times a second |
| 0:10–0:22 | Adaptive grid with the ring overlay — cells visibly coarsen with range |
| 0:22–0:34 | A/B wipe against the uniform 5 cm grid — 16,000,000 cells vs 705,771 |
| 0:34–0:48 | Overhang scene — road stays drivable, gantry flagged with measured clearance |
| 0:48–0:58 | Pothole scene — negative obstacle flagged with measured depth |
| 0:58–1:10 | Crossing truck — track, velocity estimate, predicted trajectory |
| 1:10–1:22 | Reroute fires; alternative route drawn with its reason string |
| 1:22–1:30 | HUD — FPS, per-stage latency, memory both sides, conservation at 100% |

## Running it locally

The live demo streams over `wss://`. To run the same thing on your own machine, see
§12 of the [README](../README.md).
