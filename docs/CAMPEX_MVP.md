# CAMPEX MVP
## Technical Product Specification — MVP 0.1

> Status: Development Specification
> Stage: Foundation / MVP
> Product: CAMPEX
> Version: 0.1
>
> This document defines what must be built NOW.
>
> For the long-term vision, consult:
> `CAMPEX_MASTER_VISION.md`
>
> IMPORTANT:
> The Master Vision describes where CAMPEX may go.
> This document defines the current development scope.
>
> If a feature exists in the Master Vision but not here,
> DO NOT implement it.

---

# 1. MVP Objective

The CAMPEX MVP exists to prove one fundamental hypothesis:

> An existing real-world camera can become an intelligent operational sensor.

The first version must reliably transform a camera stream into:

VIDEO
↓
DETECTION
↓
TRACKING
↓
OBSERVATION
↓
RULE
↓
EVENT
↓
EVIDENCE
↓
OPERATOR INTERFACE

The MVP is successful when this complete flow works reliably in a real environment.

---

# 2. MVP Product Definition

CAMPEX MVP is an operational camera monitoring system with basic computer vision.

The system must allow an operator to:

1. Add a camera.
2. Watch the camera live.
3. Enable CAMPEX Vision.
4. Detect people.
5. Track detected people.
6. Configure zones over the camera image.
7. Detect when a person enters a zone.
8. Generate an operational event.
9. Save visual evidence.
10. Review the event.
11. Investigate what happened.
12. Monitor system and camera health.

The first use case is:

> Person enters a restricted zone.

This is the primary scenario that the entire MVP must prove.

---

# 3. MVP Success Scenario

The official MVP demonstration is:

1. CAMPEX connects to a real camera.
2. Video appears in CAMPEX Operations.
3. A real person enters the camera field of view.
4. CAMPEX detects the person.
5. CAMPEX assigns a temporary Track ID.
6. The person enters a configured restricted zone.
7. CAMPEX creates a structured Observation.
8. The Rule Engine evaluates the Observation.
9. CAMPEX creates a critical Event.
10. CAMPEX preserves evidence from before, during and after the event.
11. The Event appears in the interface in real time.
12. The operator opens the Event.
13. The operator reviews the evidence and timeline.
14. The operator marks the Event as reviewed.

Example:

CAM 03
↓
PERSON #18
↓
Restricted Zone B
↓
person_presence
↓
Rule triggered
↓
EVENT #2841
↓
Evidence
↓
Operator

If this works repeatedly and reliably, CAMPEX MVP 0.1 is validated.

---

# 4. What We Are Building

The MVP contains the following product areas:

## Operations

Real-time camera monitoring.

## Events

Operational events detected by CAMPEX.

## Investigations

Detailed review of individual events.

## Cameras

Camera connection and management.

## Areas & Zones

Camera zones and restricted areas.

## Rules

Basic event rules.

## System

Basic configuration and health information.

---

# 5. What We Are NOT Building

The following features are explicitly outside MVP 0.1:

- CAMPEX World
- 3D Digital Twin
- CAMPEX Lens
- Augmented Reality
- Mobile application
- CAMPEX Predict
- CAMPEX Simulate
- CAMPEX Autopilot
- advanced AI agents
- cross-camera tracking
- facial recognition
- biometric identification
- ERP integration
- WMS integration
- advanced IoT integration
- advanced reporting
- complex notification systems
- automatic business actions
- advanced natural-language search
- multi-site enterprise management
- microservices
- Kubernetes
- large-scale distributed processing
- dozens of detection models

Do not implement these features during MVP development.

---

# 6. Technology Stack

The MVP uses a deliberately simple stack.

## Frontend

HTML5
CSS3
JavaScript

Use native ES Modules.

Avoid frontend frameworks during MVP unless a concrete technical requirement appears.

## Backend

Python 3.12+
FastAPI

## Computer Vision

Python
OpenCV
Ultralytics YOLO

## Tracking

ByteTrack or an equivalent proven tracker.

Do not create a custom tracking algorithm unless necessary.

## Database

Development:

SQLite

Target:

PostgreSQL

Database access should be abstracted enough to allow migration without rewriting business logic.

## Realtime

WebSocket

## Camera Protocol

Initial:

RTSP

Development sources may also include:

- local webcam;
- local video file;
- test stream.

## Evidence Storage

Initial:

local filesystem

Example:

`storage/evidence/`

Future object storage is outside MVP.

---

# 7. Architecture Principle

CAMPEX MVP must begin as a modular monolith.

DO NOT create microservices.

Architecture:

FRONTEND
↓
REST + WEBSOCKET
↓
FASTAPI
↓
CAMPEX CORE
├── Cameras
├── Vision
├── Tracking
├── Observations
├── Zones
├── Rules
├── Events
├── Evidence
└── Realtime
↓
DATABASE

One repository.

One backend.

One frontend.

One database.

---

# 8. Fundamental Processing Pipeline

The most important architectural rule is:

CAMERA
↓
FRAME
↓
DETECTION
↓
TRACK
↓
OBSERVATION
↓
RULE
↓
EVENT
↓
EVIDENCE

Each layer must have a clear responsibility.

Do not mix these responsibilities.

---

# 9. Camera Layer

The Camera Layer is responsible for acquiring video.

It should NOT contain business rules.

Initial camera sources:

## RTSPSource

Connects to real IP cameras or DVR/NVR streams.

## WebcamSource

Used for local development.

## VideoFileSource

Used for repeatable automated/manual tests.

All sources should expose a similar internal interface.

Concept:

CameraSource

- connect()
- read()
- reconnect()
- close()
- health()

Implementations:

RTSPSource
WebcamSource
VideoFileSource

---

# 10. Camera Health

CAMPEX must know whether a camera is operational.

Minimum states:

CONNECTING
ONLINE
DEGRADED
OFFLINE

Track:

camera ID
connection status
last successful frame
last error
resolution
approximate FPS
reconnect attempts

The system must automatically attempt reconnection when an RTSP stream fails.

A camera failure must not crash the entire backend.

---

# 11. Vision Layer

Vision receives frames and returns detections.

The first mandatory detection class is:

PERSON

Optional COCO classes may remain available for development, but they must not increase MVP complexity.

The interface should conceptually return:

Detection

- class
- confidence
- bounding box
- timestamp
- camera ID

Example:

{
  "class": "person",
  "confidence": 0.94,
  "bbox": [x1, y1, x2, y2]
}

The detector must not create Events directly.

---

# 12. Detection Thresholds

Confidence thresholds must be configurable.

Example environment configuration:

VISION_PERSON_CONFIDENCE=0.50

Thresholds must not be hardcoded throughout the application.

Configuration should have one canonical source.

---

# 13. Tracking Layer

Tracking receives detections and maintains temporary identities.

Example:

PERSON #18

Minimum Track information:

track_id
class
bounding_box
confidence
first_seen
last_seen
camera_id
state

Tracking is initially camera-local.

The MVP does NOT attempt to recognize the same person across different cameras.

---

# 14. Track Lifecycle

Minimum lifecycle:

NEW
↓
ACTIVE
↓
LOST
↓
ENDED

Temporary loss for a few frames should not immediately create a new entity.

The tracker should tolerate short occlusions.

---

# 15. Zones

Operators must be able to configure zones over camera images.

A zone is represented by a polygon.

Example:

{
  "camera_id": "cam_03",
  "name": "Zona restrita",
  "type": "restricted",
  "points": [
    [0.22, 0.51],
    [0.71, 0.49],
    [0.83, 0.91],
    [0.18, 0.91]
  ]
}

Coordinates should be normalized between 0 and 1.

This allows zones to remain compatible with different display resolutions.

---

# 16. Zone Editor

The frontend must provide a basic zone editor.

Flow:

Camera
↓
Pause/reference frame
↓
Create Zone
↓
Click polygon points
↓
Name Zone
↓
Choose Zone Type
↓
Save

MVP zone types:

MONITORED
RESTRICTED

The operator must be able to:

- create;
- edit;
- enable/disable;
- delete.

---

# 17. Zone Presence

CAMPEX must determine whether a tracked entity is inside a configured zone.

For PERSON tracking, use a consistent reference point.

Recommended initial strategy:

bottom-center of the bounding box.

This approximates the person's ground position better than using the bounding box center.

Example:

bbox
↓
bottom-center point
↓
point-in-polygon
↓
zone membership

---

# 18. Observations

Observations are mandatory in MVP architecture.

Do NOT connect YOLO directly to Events.

Observation example:

{
  "type": "person_presence",
  "camera_id": "cam_03",
  "track_id": 18,
  "zone_id": "zone_b",
  "state": "present",
  "confidence": 0.94,
  "timestamp": "..."
}

Initial observation types:

person_detected
person_presence
person_entered_zone
person_exited_zone
camera_status

Observations describe what CAMPEX believes it observed.

---

# 19. Data Quality

Every relevant Observation should support uncertainty.

Minimum concepts:

OBSERVED
UNKNOWN
SENSOR_UNAVAILABLE

Do not infer information when the camera cannot reliably observe it.

---

# 20. Rules Engine

MVP rules remain intentionally simple.

Required rules:

## Rule 1

Person entered restricted zone.

WHEN:

person_entered_zone

AND:

zone.type == restricted

THEN:

create event

## Rule 2

Person remained inside restricted zone.

WHEN:

person_presence

AND:

zone.type == restricted

AND:

duration >= configured threshold

THEN:

create event

## Rule 3

Camera offline.

WHEN:

camera_status == OFFLINE

THEN:

create event

Do not create a complex visual workflow engine during MVP.

Rules may initially be configured through forms.

---

# 21. Events

Events represent meaningful situations.

Initial event types:

PERSON_RESTRICTED_ZONE

PERSON_RESTRICTED_ZONE_DWELL

CAMERA_OFFLINE

Each Event should contain at least:

id
type
camera_id
zone_id
track_id if applicable
severity
status
started_at
ended_at
duration
confidence
metadata
created_at

---

# 22. Event Severity

Initial severity levels:

INFO
ATTENTION
CRITICAL

Example:

CAMERA_OFFLINE
→ ATTENTION

PERSON_RESTRICTED_ZONE
→ CRITICAL

Severity should eventually be configurable.

---

# 23. Event Status

Minimum lifecycle:

OPEN
REVIEWED
CLOSED

MVP operator actions:

Mark as reviewed.

Add optional note.

Close event.

---

# 24. Event Deduplication

The same person remaining in the same restricted zone must NOT create a new event every frame.

Example:

BAD:

14:32:01 EVENT
14:32:02 EVENT
14:32:03 EVENT
14:32:04 EVENT

GOOD:

14:32:01 EVENT OPENED

person remains in zone...

14:32:18 EVENT CLOSED

duration = 17 seconds

Event identity should be tied to:

camera
track
zone
event type

when appropriate.

---

# 25. Evidence Buffer

Evidence is mandatory.

Each active camera pipeline should maintain a rolling frame buffer.

Initial target:

10 seconds before the event.

When an event starts:

preserve pre-event buffer.

Continue capturing during the event.

Capture approximately:

10 seconds after the event.

Final evidence:

BEFORE
+
EVENT
+
AFTER

---

# 26. Evidence Format

Initial implementation may use:

JPEG frames

and/or

MP4 clips.

Recommended MVP result:

event clip
+
representative snapshot

Storage example:

storage/
  evidence/
    EV-2841/
      snapshot.jpg
      event.mp4
      metadata.json

Do not store binary video data inside the relational database.

Store file references.

---

# 27. Evidence Metadata

Store:

event ID
camera ID
start timestamp
end timestamp
frame timestamps
snapshot path
video path
duration
related track
related zone

Evidence must remain traceable to the Event that created it.

---

# 28. Realtime Layer

WebSocket should be used for operational updates.

Possible messages:

camera.status

detection.update

track.update

observation.created

event.created

event.updated

event.closed

The frontend should not continuously poll the API for live operational information.

---

# 29. Vision Overlay

The live interface must support:

Vision ON
Vision OFF

When enabled, display:

bounding box
entity class
Track ID

Example:

PERSON #18

Optional:

confidence

Do not permanently burn overlays into the camera video.

Overlay data should be rendered separately by the frontend whenever practical.

---

# 30. Operations Interface

CAMPEX should open primarily as operational software.

Main MVP navigation:

OPERAR

Ao vivo
Eventos
Investigações

GERENCIAR

Câmeras
Áreas & zonas
Regras

SISTEMA

Configurações

Do not prioritize a traditional KPI dashboard.

---

# 31. Live / Video Wall

The Live page is the primary MVP experience.

Required layouts:

1x1
2x2
3x3

Optional if easy:

4x4

Required:

Fullscreen

Each camera tile displays:

camera name
area
live/offline status
video

Minimal controls appear on interaction.

Possible controls:

mute if audio exists
fullscreen
Vision ON/OFF
open camera
open events

---

# 32. Fullscreen Monitoring

Fullscreen mode should resemble professional surveillance software.

The screen should primarily contain camera feeds.

Minimal navigation.

Example:

CAM01 | CAM02
------|------
CAM03 | CAM04

A small collapsible toolbar may provide:

camera selection
layout
Vision
settings
exit fullscreen

The user should be able to keep this screen open for long periods.

---

# 33. Events Interface

The Events page should NOT be designed as a generic database table.

Use an operational timeline.

Required filters:

All
Critical
Attention
Reviewed
Unreviewed

Each event preview should show:

time
event type
camera
zone
severity
thumbnail
status

Clicking an event opens its details.

---

# 34. Event Detail

Event detail must show:

event title
camera
zone
timestamp
duration
severity
status
video evidence
snapshot
event timeline
observations
Track ID
confidence
operator note

Actions:

Mark reviewed
Close
Add note
Open investigation

---

# 35. Investigations

MVP Investigation may initially be a detailed Event workspace rather than a complex separate system.

The objective is to let an operator answer:

What happened?

When?

Where?

Which camera?

Which entity?

How long?

What evidence exists?

The interface should combine:

video
timeline
event metadata
observations
notes

---

# 36. Cameras Interface

Camera management is administrative.

This interface may use a lighter visual theme.

Required functionality:

List cameras.

Add camera.

Edit camera.

Delete camera.

Test connection.

Enable/disable camera.

View camera health.

Fields:

name
area
source type
RTSP URL
enabled
Vision enabled

Sensitive credentials must not be returned unnecessarily to the frontend.

---

# 37. Add Camera Flow

Minimum flow:

Add Camera
↓
Name
↓
RTSP URL
↓
Test Connection
↓
CAMPEX attempts connection
↓
Preview frame
↓
Save

If connection fails:

show useful diagnostic information.

Do not simply display:

"Error."

---

# 38. Areas

MVP supports basic areas.

Examples:

Entrada
Expedição
Produção
Estoque

A camera may belong to an area.

Areas help organize:

cameras
events
zones

Complex spatial hierarchy is outside MVP.

---

# 39. Rules Interface

Initial UI can be form-based.

Example:

Rule Name:
Restricted Zone Access

Entity:
Person

Condition:
Entered zone

Zone:
Zona Restrita

Severity:
Critical

Enabled:
Yes

Future visual rule builders are outside MVP.

---

# 40. Settings

Keep Settings minimal.

MVP settings:

general system information
Vision defaults
evidence retention
system health
database information
version

Authentication may be added when necessary for deployment.

Do not build a complete enterprise identity platform during the initial local prototype.

---

# 41. Frontend Visual System

CAMPEX should NOT look like a generic SaaS dashboard.

Visual direction:

black
white
gray

Operational colors:

GREEN
normal / online

YELLOW
attention

RED
critical

Dark interfaces:

Operations
Live
Events
Investigations

Light or neutral interfaces:

Cameras
Zones
Rules
Settings

Video is the primary visual element during monitoring.

---

# 42. Frontend Structure

Recommended:

frontend/
│
├── index.html
│
├── pages/
│   ├── live.html
│   ├── events.html
│   ├── investigation.html
│   ├── cameras.html
│   ├── zones.html
│   ├── rules.html
│   └── settings.html
│
├── css/
│   ├── tokens.css
│   ├── global.css
│   ├── layout.css
│   ├── components.css
│   └── pages/
│
├── js/
│   ├── app.js
│   ├── api.js
│   ├── websocket.js
│   ├── state.js
│   ├── components/
│   └── pages/
│
└── assets/

Avoid duplicating CSS and JavaScript between pages.

---

# 43. Backend Structure

Recommended initial structure:

backend/
│
├── main.py
│
├── config.py
│
├── api/
│   ├── cameras.py
│   ├── areas.py
│   ├── zones.py
│   ├── rules.py
│   ├── events.py
│   └── health.py
│
├── cameras/
│   ├── base.py
│   ├── rtsp.py
│   ├── webcam.py
│   ├── video_file.py
│   ├── manager.py
│   └── health.py
│
├── vision/
│   ├── detector.py
│   ├── tracker.py
│   ├── pipeline.py
│   └── overlay.py
│
├── observations/
│   ├── models.py
│   └── engine.py
│
├── zones/
│   ├── models.py
│   └── engine.py
│
├── rules/
│   ├── models.py
│   └── engine.py
│
├── events/
│   ├── models.py
│   ├── service.py
│   └── repository.py
│
├── evidence/
│   ├── buffer.py
│   ├── recorder.py
│   └── storage.py
│
├── realtime/
│   ├── manager.py
│   └── messages.py
│
└── database/
    ├── db.py
    ├── models.py
    └── migrations/

---

# 44. Repository Structure

Complete initial repository:

campex/
│
├── frontend/
├── backend/
├── storage/
│   └── evidence/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/
├── docs/
│   ├── CAMPEX_MASTER_VISION.md
│   └── CAMPEX_MVP.md
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md

Do not create unnecessary directories before they are required.

---

# 45. Database Entities

Initial database entities:

Camera
Area
Zone
Rule
Event
Evidence
OperatorNote

Observations may initially be:

persisted selectively

or

kept ephemeral depending on performance needs.

Do not store every frame.

Do not store every bounding box forever.

---

# 46. Camera Model

Minimum:

id
name
area_id
source_type
source_uri
enabled
vision_enabled
status
created_at
updated_at

Credentials must be handled securely.

Do not expose full RTSP credentials through normal API responses.

---

# 47. Zone Model

Minimum:

id
camera_id
name
type
points
enabled
created_at
updated_at

---

# 48. Rule Model

Minimum:

id
name
event_type
zone_id
condition
duration_threshold
severity
enabled

---

# 49. Event Model

Minimum:

id
type
camera_id
zone_id
track_id
severity
status
confidence
started_at
ended_at
duration
metadata
created_at
updated_at

---

# 50. Evidence Model

Minimum:

id
event_id
type
path
started_at
ended_at
metadata
created_at

---

# 51. API

Initial API prefix:

/api/v1

Minimum endpoints:

GET    /api/v1/health

GET    /api/v1/cameras
POST   /api/v1/cameras
GET    /api/v1/cameras/{id}
PATCH  /api/v1/cameras/{id}
DELETE /api/v1/cameras/{id}

POST   /api/v1/cameras/{id}/test
GET    /api/v1/cameras/{id}/health

GET    /api/v1/areas
POST   /api/v1/areas

GET    /api/v1/zones
POST   /api/v1/zones
PATCH  /api/v1/zones/{id}
DELETE /api/v1/zones/{id}

GET    /api/v1/rules
POST   /api/v1/rules
PATCH  /api/v1/rules/{id}

GET    /api/v1/events
GET    /api/v1/events/{id}
PATCH  /api/v1/events/{id}

GET    /api/v1/events/{id}/evidence

Avoid creating endpoints without a current product requirement.

---

# 52. WebSocket

Initial endpoint:

/ws

Possible message envelope:

{
  "type": "event.created",
  "timestamp": "...",
  "data": {}
}

Initial message types:

camera.status
vision.tracks
event.created
event.updated
event.closed

Message formats must be documented.

---

# 53. Configuration

Use environment variables.

Example:

CAMPEX_ENV=development

DATABASE_URL=...

VISION_MODEL=...

VISION_PERSON_CONFIDENCE=0.50

EVIDENCE_PRE_SECONDS=10

EVIDENCE_POST_SECONDS=10

CAMERA_RECONNECT_SECONDS=5

Never commit:

passwords
camera credentials
API keys
private URLs
production secrets

Provide:

.env.example

---

# 54. Logging

Logging is required from the beginning.

Log:

application startup
camera connection
camera disconnection
reconnect attempts
Vision model loading
pipeline start
pipeline stop
event creation
evidence creation
unexpected errors

Avoid excessive frame-by-frame logging.

Logs should help diagnose real camera problems.

---

# 55. Error Handling

One camera failure must not crash CAMPEX.

One corrupted frame must not crash the camera pipeline.

One failed evidence write must not crash Vision.

Errors must be isolated and logged.

The UI should display understandable operational states.

---

# 56. Performance Philosophy

Do not optimize prematurely.

But do measure.

Track basic metrics:

input FPS
processed FPS
Vision latency
camera reconnect count
active tracks
event count
WebSocket connections

The MVP does not need to process every camera frame.

Example:

camera = 30 FPS

Vision processing may operate at a lower effective FPS if adequate for the use case.

Reliability is more important than maximizing FPS.

---

# 57. Security Basics

Even MVP code must avoid obvious security problems.

Requirements:

validate API input
sanitize file paths
do not expose RTSP passwords
do not log secrets
restrict evidence paths
use environment variables
validate WebSocket messages
avoid arbitrary command execution
avoid arbitrary filesystem access

Full enterprise security comes later.

Basic security does not.

---

# 58. Privacy

The MVP should avoid unnecessary personal identification.

No facial recognition.

No employee identity inference.

Track IDs are temporary technical identifiers.

Example:

PERSON #18

does not mean:

Employee #18

This distinction is important.

---

# 59. Testing Strategy

CAMPEX requires more than unit tests.

Four test layers:

## Unit

Test isolated logic.

Examples:

point-in-polygon
rule evaluation
event deduplication
track state

## Integration

Test components together.

Example:

Observation
↓
Rule
↓
Event

## Recorded Video

Run the same known video repeatedly.

Expected events must remain deterministic enough for regression testing.

## Physical Test

Use a real camera and real person.

This is mandatory before MVP approval.

---

# 60. Official Physical Test

Test name:

CAMPEX MVP TEST 001
PERSON IN RESTRICTED ZONE

Environment:

real camera
real person
real configured zone

Procedure:

1. Start CAMPEX.
2. Confirm camera online.
3. Confirm live video.
4. Enable Vision.
5. Person enters frame.
6. Confirm detection.
7. Confirm Track ID.
8. Person enters restricted zone.
9. Confirm Observation.
10. Confirm Event.
11. Confirm evidence.
12. Person exits zone.
13. Confirm Event duration.
14. Open Event interface.
15. Review evidence.
16. Mark reviewed.
17. Restart CAMPEX.
18. Confirm Event and evidence remain available.

---

# 61. Repetition Requirement

One successful demonstration is not enough.

Repeat the primary physical scenario at least 30 times.

Vary:

distance
walking speed
entry angle
clothing
lighting
partial occlusion
time inside zone

Record failures.

Do not hide failed tests.

The objective is to understand system reliability.

---

# 62. MVP Metrics

Track:

Detection success rate

Track continuity

False event count

Missed event count

Event latency

Evidence success rate

Camera reconnect success

UI event delivery latency

These metrics matter more than adding features.

---

# 63. Development Phases

Development should happen incrementally.

Do not ask an AI coding agent to implement the entire MVP at once.

Each phase must end in a testable system.

---

# 64. Sprint 0 — Foundation

Objective:

Create a clean, stable project foundation.

Implement:

repository structure
Python environment
FastAPI application
frontend base
configuration
logging
database connection
health endpoint
basic tests
README
.gitignore
.env.example

Expected result:

Backend starts.

Frontend opens.

Frontend communicates with backend.

Database initializes.

Health endpoint responds.

No Vision yet.

---

# 65. Sprint 1 — Camera Source

Implement:

CameraSource abstraction

WebcamSource

VideoFileSource

RTSPSource

Camera Manager

basic camera health

reconnection

API camera CRUD

Expected result:

CAMPEX can connect to at least:

one local webcam or video

and

one RTSP stream.

---

# 66. Sprint 2 — Live Video

Implement:

live video delivery to frontend

camera tile

online/offline state

1x1 view

2x2 view

fullscreen

Expected result:

Operator can reliably monitor camera feeds.

Do not add AI before live video is stable.

---

# 67. Sprint 3 — Vision

Implement:

YOLO model loading

person detection

configurable confidence

Detection model

Vision pipeline

Vision overlay data

Expected result:

A real person appears with a detection bounding box.

---

# 68. Sprint 4 — Tracking

Implement:

ByteTrack

Track IDs

track lifecycle

temporary occlusion tolerance

WebSocket track updates

Expected result:

A moving person maintains a stable temporary ID.

---

# 69. Sprint 5 — Zones

Implement:

Zone model

Zone API

polygon editor

point-in-polygon

zone entry

zone exit

Expected result:

CAMPEX reliably determines when PERSON #X enters and exits a configured zone.

---

# 70. Sprint 6 — Observations & Rules

Implement:

Observation model

Observation Engine

basic Rules Engine

restricted-zone rule

dwell-time rule

camera-offline rule

Expected result:

Camera activity becomes structured operational information.

---

# 71. Sprint 7 — Events

Implement:

Event persistence

event lifecycle

event deduplication

severity

Events UI

WebSocket event updates

Expected result:

Restricted-zone activity generates one correct operational Event.

---

# 72. Sprint 8 — Evidence

Implement:

rolling buffer

pre-event capture

event capture

post-event capture

snapshot

evidence storage

Evidence API

Expected result:

Every relevant Event has usable visual evidence.

---

# 73. Sprint 9 — Investigation

Implement:

Event Detail

video playback

event timeline

observations

metadata

notes

review action

close action

Expected result:

Operator can understand and review an Event without searching manually through raw footage.

---

# 74. Sprint 10 — Operations UX

Refine:

Video Wall

1x1

2x2

3x3

fullscreen

Vision toggle

camera status

event indication

minimal controls

dark monitoring experience

Expected result:

CAMPEX feels like professional operational monitoring software.

---

# 75. Sprint 11 — Reliability

Do not add features.

Focus exclusively on:

camera reconnection
memory usage
Vision stability
tracking stability
event correctness
evidence correctness
database persistence
backend restart
frontend reconnect
WebSocket reconnect
error handling

Run recorded-video tests.

Run physical tests.

---

# 76. Sprint 12 — MVP Validation

Run:

CAMPEX MVP TEST 001

at least 30 times.

Document:

successes
failures
false positives
false negatives
latency
environment
camera model
lighting
distance
software version

Only after this should MVP 0.1 be considered technically validated.

---

# 77. Definition of Done — Sprint

A Sprint is NOT complete because:

"the code exists."

A Sprint is complete when:

implementation exists
tests pass
manual scenario works
errors are handled
logs are useful
documentation is updated
existing functionality remains working

---

# 78. Definition of Done — MVP

CAMPEX MVP 0.1 is complete when:

A real camera connects reliably.

Live video works.

Person detection works.

Tracking works.

Zones work.

Observations work.

Rules work.

Events work.

Evidence works.

The operator receives Events in real time.

The operator can investigate an Event.

Data survives application restart.

The complete scenario works repeatedly in a real environment.

---

# 79. AI Coding Agent Rules

When using Codex, Laguna or another coding agent:

DO NOT implement future roadmap features.

DO NOT create mock functionality and present it as working.

DO NOT create unnecessary abstractions.

DO NOT rewrite working modules without reason.

DO NOT introduce frameworks without justification.

DO NOT create microservices.

DO NOT silently change architecture.

DO NOT hardcode secrets.

DO NOT hide errors.

DO NOT declare physical functionality validated without a physical test.

Always:

read this document first
identify current Sprint
inspect existing code
make the smallest coherent change
run tests
report what changed
report what remains
report failures clearly

---

# 80. Current Development State

At the beginning of this project:

Current Stage:

SPRINT 0 — FOUNDATION

Current objective:

Create the project foundation.

Do NOT implement:

camera processing
YOLO
tracking
zones
events
evidence

until the Foundation is stable.

---

# 81. Sprint 0 Exact Deliverables

Create:

campex/
├── frontend/
├── backend/
├── storage/
├── tests/
├── scripts/
├── docs/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md

Backend:

FastAPI starts successfully.

Required route:

GET /api/v1/health

Example response:

{
  "status": "ok",
  "service": "campex",
  "version": "0.1.0"
}

Frontend:

Basic application shell.

It must successfully request:

GET /api/v1/health

and display system connectivity.

Database:

Initialize SQLite development database.

Configuration:

Central environment-based configuration.

Logging:

Application startup and errors.

Tests:

Health endpoint test.

Configuration test.

Database initialization test.

---

# 82. Sprint 0 UI

Do not build the final interface yet.

Create only the application shell:

CAMPEX logo

navigation structure

main content area

backend connectivity indicator

Navigation:

Ao vivo
Eventos
Investigações

Câmeras
Áreas & zonas
Regras

Configurações

Pages may initially display:

"Module not implemented."

This is acceptable during Foundation.

Do not fake functionality.

---

# 83. First Commit

Recommended first commit:

chore: initialize CAMPEX MVP foundation

The commit should contain only Foundation work.

---

# 84. First Development Milestone

After Sprint 0:

Frontend
↕
FastAPI
↕
Database

works.

After Sprint 1:

Camera
↓
CAMPEX

works.

After Sprint 3:

Camera
↓
CAMPEX
↓
Person Detection

works.

After Sprint 7:

Camera
↓
Detection
↓
Tracking
↓
Observation
↓
Rule
↓
Event

works.

After Sprint 9:

Camera
↓
Detection
↓
Tracking
↓
Observation
↓
Rule
↓
Event
↓
Evidence
↓
Investigation

works.

That is the MVP.

---

# 85. Final Principle

CAMPEX does not need to look enormous during MVP development.

It needs to work.

Do not measure progress by:

number of pages
number of features
number of models
number of integrations
lines of code

Measure progress by:

Can CAMPEX reliably understand something useful happening in front of a real camera?

The first goal is not to understand an entire factory.

The first goal is:

One camera.

One person.

One zone.

One event.

One piece of evidence.

Working reliably.

Then we expand.