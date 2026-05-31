# INTERVIEW Q&A — defend-your-decisions prep

> Standing practice: **after every slice, add 5 likely interview questions + simple answers here.**
> The challenge ends with 5 follow-up questions about *your own code* (async video, <2 min each) —
> these must be answerable from genuine understanding, not generic filler ([[SPEC]] §5.3, §6).
> Keep answers short, honest, and specific to what we built. Newest slices at the bottom.

---

## Slice 2.0 — Entrance line calibration + frame reader

**Q1. Why do you sample ~5 frames per second instead of processing every frame?**
A 30 fps clip has 30 near-identical frames each second — a person barely moves between them. Running
the detector on all of them wastes ~6× the compute for no extra accuracy. 5 fps is plenty to catch
someone crossing the entrance, so we sample (take every 6th frame). It's a deliberate
cost-vs-accuracy trade; the sample rate is configurable if we ever need finer timing.

**Q2. How does the system decide "inside" vs "outside", and why is the line diagonal?**
We draw one straight line and use a simple geometry test (the sign of a cross-product) to tell which
side a point falls on; we tagged which side is the shop (`inside_sign`). The line is diagonal because
the camera looks down at an angle — the boundary between the wooden retail floor (inside) and the
dark threshold tiles (the mall side) runs diagonally across the frame, so a horizontal line wouldn't
match the real floor edge.

**Q3. Why use the bottom-centre ("foot point") of a person's box, not its centre?**
Because where a person *stands* is what tells us which zone/side they're in. With an overhead-angled
camera, the centre of the box can sit over a different zone than their feet. The foot point is the
ground contact, so it's the honest position for line-crossing and zone assignment.

**Q4. How do you know the line is calibrated correctly?**
Right now it's a visual best-effort: we overlaid a coordinate grid + the line on a real frame and
confirmed it sits on the wood/threshold edge with INSIDE/OUTSIDE on the right sides. The real proof
comes in Slice 2.2 — we'll track actual people, count how many cross the line, and compare to a
manual eye-count of the clip. If it's off, we nudge the coordinates. So: plausible now, *validated*
against live movement next.

**Q5. What's the weakness of this calibration approach?**
It's manual and per-camera — if the camera is moved or we add a new store, someone has to recalibrate
the line. It's a single-frame hypothesis until validated, and a fixed straight line can't perfectly
capture a curved doorway. We accept this because calibration is a one-time setup per fixed CCTV
camera; a more automated approach (homography from a floor plan) would be the next step if needed.

---

## Slice 2.1 — YOLO person detection + structured events

**Q1. Why YOLOv8-nano, and how would you defend that choice?**
We're scored on system quality and edge-case handling, not raw detection accuracy, and the demo must
run on a normal CPU via `docker compose up`. YOLOv8n is small, fast on CPU, and ships with tracking
support we need next. It trades some accuracy for speed/portability — an acceptable trade here, and
the model path is a config value, so swapping to a larger model (or RT-DETR) is a one-line change if
accuracy matters more than latency.

**Q2. Why pre-bake the model weights into the Docker image instead of downloading at runtime?**
The acceptance gate requires `docker compose up` to work with no manual steps, possibly offline. If
the container downloaded the model on first run, a flaky network would break the demo. Baking it in at
build time makes startup deterministic and reliable — a small image-size cost for a big reliability win.

**Q3. Why is the box-filtering logic a separate pure function from the model call?**
So we can unit-test the logic (keep persons, drop low-confidence, convert box format) without loading
a multi-hundred-MB model or a GPU. The model call stays thin; the decision logic is tested offline and
fast. It also keeps the code honest — the filtering is verifiable, not a black box.

**Q4. Detection runs per-frame and doesn't know it's the same person across frames — isn't that double counting?**
Yes — on its own, per-frame detection would count one shopper many times. That's exactly why detection
is only the foundation. Slice 2.2 adds tracking (ByteTrack) to give each person a stable ID across
frames, and Re-ID (Slice 2.4) links them across cameras and re-entries. Counting happens on *tracks*,
never raw detections.

**Q5. How do you handle partial occlusion and low-confidence detections?**
We do **not** silently drop low-confidence boxes — we keep them and carry the real confidence value on
the event, so downstream can weigh or flag them ("degrade gracefully, not fail silently"). For
occlusion, the tracker helps bridge short gaps where a person is briefly hidden behind a shelf. We set
a threshold for *acting* on a detection but never fabricate or suppress — that's both correct and what
the rubric rewards (confidence calibration).

*(Bonus — scale question they may ask: "At 40 live stores in real time, what breaks first?" → The
CPU-bound YOLO inference. Each store's feeds are independent, so we'd scale horizontally (one detector
worker per store/camera), use GPU or a smaller model, and/or sample fewer fps. The API/ingest is
lighter and scales separately.)*
