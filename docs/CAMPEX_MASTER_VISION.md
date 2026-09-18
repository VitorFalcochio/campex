# CAMPEX
## Master Vision & Product Architecture

> Status: Long-Term Product Vision
> Current Stage: MVP / Foundation
> Product Category: Physical Intelligence
> Scope: Vision, principles, architecture and long-term direction
>
> IMPORTANT:
> This document describes both the current product and the long-term vision.
> Features described here are NOT necessarily implemented.
> Always consult CAMPEX_MVP.md to determine what should be built now.

---

# 1. What is CAMPEX?

CAMPEX is a Physical Intelligence platform.

Its purpose is to transform cameras, sensors and existing physical infrastructure into a digital intelligence layer capable of perceiving, understanding and eventually helping operate the physical world.

Today, companies have thousands of cameras.

Most of them simply record video.

CAMPEX aims to transform those cameras from passive recording devices into sensors capable of producing structured information about what is happening inside a physical operation.

Instead of storing only video, CAMPEX can eventually understand:

- what happened;
- where it happened;
- when it happened;
- which entities were involved;
- how long it lasted;
- what happened before;
- what happened afterwards;
- whether the situation was expected;
- whether the situation requires attention;
- how it relates to the rest of the operation.

The long-term idea is simple:

> Give physical operations a digital nervous system.

CAMPEX should allow a company to understand its physical operation with the same level of visibility that modern software companies have over their digital systems.

---

# 2. The Fundamental Idea

CAMPEX begins with a camera.

A camera produces video.

CAMPEX transforms that video into information.

The fundamental pipeline is:

Camera
↓
Frame
↓
Detection
↓
Tracking
↓
Observation
↓
Event
↓
Evidence
↓
Memory
↓
Intelligence
↓
World
↓
Prediction
↓
Action

Not every stage exists in the MVP.

This pipeline represents the long-term architecture of the product.

---

# 3. Where CAMPEX Starts

The first CAMPEX MVP is intentionally small.

The objective is NOT to build the complete vision.

The objective is to prove that the fundamental technological loop works reliably.

The first proof is:

REAL CAMERA
↓
VIDEO
↓
CAMPEX
↓
DETECTION
↓
TRACKING
↓
OBSERVATION
↓
EVENT
↓
EVIDENCE
↓
INTERFACE

Example:

A camera observes an entrance.

A person appears.

CAMPEX detects the person.

CAMPEX tracks the person.

The person enters a configured restricted zone.

CAMPEX creates an observation.

A rule recognizes the situation.

CAMPEX generates an event.

Evidence is stored.

The event appears in the operator interface.

The operator can inspect what happened.

If this works reliably with a real camera in a real environment, the foundation of CAMPEX exists.

---

# 4. MVP Philosophy

CAMPEX has a very large vision.

The MVP must remain very small.

This distinction is fundamental.

Long-term vision must NOT become short-term scope.

The MVP should prove:

1. Camera connectivity.
2. Video processing.
3. Object detection.
4. Object tracking.
5. Zones.
6. Structured observations.
7. Operational rules.
8. Events.
9. Evidence.
10. Real-time operator interface.

The first version does NOT need:

- CAMPEX World;
- AR;
- advanced prediction;
- simulation;
- autonomous actions;
- cross-camera identity;
- ERP integrations;
- WMS integrations;
- complex reports;
- mobile application;
- dozens of AI models;
- facial recognition;
- microservices;
- massive cloud infrastructure.

Build the smallest system capable of proving the core idea.

---

# 5. Core Product Principle

CAMPEX should not be designed as another analytics dashboard.

It is operational software.

The primary user may keep CAMPEX open for an entire work shift.

The experience should therefore resemble a professional operations center rather than a traditional SaaS dashboard.

The product workflow is:

MONITOR
↓
DETECT
↓
UNDERSTAND
↓
INVESTIGATE
↓
RESPOND

Different parts of CAMPEX should have interfaces appropriate to their purpose.

Not every page should be a collection of cards and charts.

---

# 6. CAMPEX Operations

CAMPEX Operations is the real-time operational interface.

Its primary experience is a Video Wall.

Possible layouts:

1x1
2x2
3x3
4x4
Smart Grid
Fullscreen

The operator can monitor multiple cameras simultaneously.

The interface should prioritize video.

Permanent UI elements should remain minimal.

Example camera header:

CAM 03 · Entrada
● LIVE

Optional Vision Overlay:

Vision ON
Vision OFF

When Vision is enabled, CAMPEX can visualize detected entities such as:

PERSON #18
VEHICLE #07
FORKLIFT #04

The intelligence continues operating even when the visual overlay is disabled.

---

# 7. Smart Monitoring

CAMPEX should eventually help decide what deserves human attention.

Instead of forcing an operator to watch 16 equally sized camera feeds continuously, CAMPEX can prioritize relevant feeds.

Example:

Normal operation:

CAM01 | CAM02
CAM03 | CAM04

Critical event detected on CAM03:

CAM03 becomes the primary feed.

Other cameras become secondary.

This concept is called Smart Grid.

The goal is not to replace the operator.

The goal is to reduce the amount of irrelevant visual information the operator must process.

---

# 8. CAMPEX Vision

CAMPEX Vision is the perception layer.

Its responsibility is to transform visual information into machine-readable detections.

Possible future detection capabilities include:

- people;
- cars;
- trucks;
- motorcycles;
- forklifts;
- pallets;
- packages;
- PPE;
- machinery;
- doors;
- gates;
- smoke;
- objects;
- operational equipment.

Vision must remain modular.

Different models may be used for different environments.

A generic model should not be expected to solve every industrial problem.

---

# 9. Tracking

Detection answers:

"What exists in this frame?"

Tracking answers:

"Is this the same entity observed in the previous frame?"

Example:

PERSON #24

The tracking system maintains temporary entity identity while the entity remains observable.

This enables:

- trajectory;
- movement;
- dwell time;
- zone entry;
- zone exit;
- proximity;
- direction;
- interaction analysis.

Initial tracking may operate within a single camera.

Cross-camera tracking is a future capability.

---

# 10. Observations

Observations are one of the fundamental concepts of CAMPEX.

Raw AI detections should not directly control business behavior.

Example raw detection:

class: person
confidence: 0.94
bbox: [...]

CAMPEX transforms this into a structured observation.

Example:

type: person_presence
camera: CAM03
track: PERSON_18
zone: RESTRICTED_ZONE
state: PRESENT
confidence: 0.94

Observations represent facts or structured interpretations of sensor data.

Possible observation types include:

- person_presence;
- person_track;
- vehicle_presence;
- zone_occupancy;
- machine_activity;
- lighting_state;
- operational_activity;
- person_vehicle_proximity;
- object_presence;
- asset_movement.

Observations create a stable layer between computer vision and business logic.

---

# 11. Rules

Rules interpret observations.

Example:

WHEN
person_presence

AND
zone = restricted_zone

AND
duration > 5 seconds

THEN
create critical event

Rules should eventually allow organizations to configure CAMPEX without changing application code.

Future rule concepts may include:

WHEN
CONDITION
DURATION
THEN
ACTION

---

# 12. Events

Events represent meaningful operational situations.

Examples:

person.entered_restricted_zone

vehicle.arrived

vehicle.departed

machine.stopped

machine.resumed

camera.offline

camera.obstructed

zone.congested

object.moved

object.removed

Events are not raw detections.

They represent situations that matter to the organization.

---

# 13. Evidence

Every important CAMPEX event should be explainable.

An event should ideally include visual evidence.

CAMPEX can maintain a rolling memory buffer.

Example:

-10 seconds
↓
EVENT
↓
+10 seconds

Instead of permanently recording every processed frame, CAMPEX can preserve relevant evidence when events occur.

Evidence may include:

- image;
- video clip;
- before-event frames;
- event frames;
- after-event frames;
- related camera footage;
- observations;
- timestamps;
- metadata.

---

# 14. Investigations

Events can become investigations.

An investigation workspace should allow operators to understand an incident without manually searching through hours of video.

Example:

INVESTIGATION #EV-2841

Person in restricted zone

Main video

Timeline

10:13:58 Person detected
10:14:02 Entered Zone B
10:14:07 Event triggered
10:14:18 Exited Zone B

Related cameras

Evidence

Observations

Operator notes

Responsible operator

Status

Severity

CAMPEX should evolve from "showing an alert" to "helping explain what happened."

---

# 15. CAMPEX Memory

Most camera systems remember video.

CAMPEX should eventually remember events and operational context.

CAMPEX Memory is the historical intelligence layer.

Instead of asking:

"Which recording contains the event?"

A user should eventually ask:

"What happened at Loading Dock B yesterday afternoon?"

Memory can connect:

video
+
observations
+
events
+
entities
+
locations
+
business context

This creates searchable operational history.

---

# 16. Ask CAMPEX

CAMPEX should eventually provide a natural-language interface to physical operations.

Example:

"What happened at the main entrance between 22:00 and midnight?"

CAMPEX can search its operational memory and return:

- relevant events;
- observations;
- patterns;
- evidence;
- related cameras;
- unknown information.

Answers must remain grounded in evidence.

CAMPEX should distinguish:

FACT
HYPOTHESIS
UNKNOWN

The system must not invent explanations when evidence is insufficient.

---

# 17. Physical Entities

CAMPEX should gradually evolve from detecting object classes to understanding operational entities.

Computer vision might detect:

PALLET

Tracking might create:

PALLET_TRACK_31

Additional systems may identify:

PALLET PLT-9381

Business systems may provide:

Order #48291
Product XYZ
Destination Dock 04

This creates a connection between:

VISUAL ENTITY
↓
PHYSICAL ENTITY
↓
BUSINESS ENTITY

Potential identification technologies include:

- barcode;
- QR code;
- OCR;
- RFID;
- visual embeddings;
- spatial association;
- ERP;
- WMS;
- IoT.

---

# 18. Existing Infrastructure

CAMPEX should be software-first.

Companies should not be forced to replace existing cameras just to use CAMPEX.

The ideal architecture is:

Existing Camera
↓
RTSP / ONVIF / DVR / NVR
↓
CAMPEX Edge
↓
CAMPEX Intelligence

Possible environments include:

- IP cameras;
- analog cameras connected through DVR/NVR;
- existing enterprise CCTV systems;
- new CAMPEX-ready installations.

The camera acts primarily as a sensor.

The intelligence belongs to CAMPEX.

---

# 19. CAMPEX Edge

CAMPEX Edge processes information close to the physical environment.

Possible responsibilities:

- camera connection;
- RTSP ingestion;
- frame processing;
- computer vision;
- tracking;
- local event detection;
- buffering;
- evidence capture;
- camera health;
- synchronization with cloud services.

Benefits include:

- lower latency;
- lower bandwidth usage;
- greater privacy;
- resilience;
- local processing;
- reduced cloud inference cost.

Long-term architecture:

CAMERAS
↓
CAMPEX EDGE
↓
EVENTS / METADATA / EVIDENCE
↓
CAMPEX CLOUD

---

# 20. Camera Compatibility

CAMPEX should aim to work with a broad range of existing infrastructure.

Possible manufacturers include:

- Intelbras;
- Hikvision;
- Dahua;
- Axis;
- Bosch;
- Hanwha;
- Uniview;
- others.

CAMPEX may eventually maintain a Camera Compatibility Database containing:

- manufacturer;
- model;
- firmware;
- protocol;
- resolution;
- FPS;
- RTSP compatibility;
- ONVIF compatibility;
- audio capability;
- PTZ capability;
- known limitations.

---

# 21. Capability Engine

Not every camera can provide the same quality of intelligence.

CAMPEX should eventually analyze each camera and determine what capabilities are reliable.

Example:

CAM 01

Person Detection        Excellent
Vehicle Detection       Excellent
Pallet Detection        Good
OCR                     Limited
Face Detail             Insufficient
Low-light               Good

This prevents CAMPEX from promising intelligence that the physical sensor cannot reliably provide.

---

# 22. CAMPEX Vision Grade

A future camera quality system may classify camera suitability for different workloads.

Example:

CAMPEX Vision Grade: A

Possible factors:

- resolution;
- field of view;
- lighting;
- angle;
- pixel density;
- obstruction;
- compression;
- FPS;
- stability;
- night performance.

CAMPEX could recommend:

- reposition camera;
- improve lighting;
- increase resolution;
- reduce compression;
- add additional camera.

---

# 23. CAMPEX Privacy Layer

Privacy must be architectural, not an afterthought.

CAMPEX may process sensitive physical environments.

The platform should support:

- tenant isolation;
- RBAC;
- audit logs;
- encryption;
- retention policies;
- anonymization;
- access control;
- evidence permissions;
- signed URLs;
- secure Edge communication;
- LGPD-oriented controls.

Biometric identification should never become an assumed default capability.

---

# 24. CAMPEX World

CAMPEX World represents the long-term spatial evolution of the platform.

The objective is to create a living digital representation of a physical operation.

Instead of only seeing camera feeds, users could see the operation spatially.

Example:

Warehouse
↓
Digital representation
↓
Racks
Pallets
Machines
Vehicles
People
Zones
Cameras
Events

The World should not look like a videogame.

It should behave like an operational digital twin.

---

# 25. Building CAMPEX World

Possible inputs include:

- floor plans;
- CAD;
- BIM;
- mobile scanning;
- LiDAR;
- depth sensors;
- camera calibration;
- computer vision;
- IoT;
- ERP;
- WMS.

Initial geometry may be created through scans or imported plans.

Cameras then maintain live operational state.

Business systems add context.

Sensors add non-visual information.

---

# 26. Spatial Intelligence

Future CAMPEX entities should support spatial coordinates.

Example:

entity_id
x
y
z
confidence
timestamp
last_seen

Cameras should eventually store:

x
y
z
rotation
field_of_view

This enables visual observations to be projected into a common spatial environment.

---

# 27. CAMPEX Time Machine

CAMPEX World should eventually support historical reconstruction.

A user could move through time:

08:00
09:00
10:00
11:00

and inspect the known operational state.

Example:

"Where was pallet PLT-9381 at 09:42?"

CAMPEX could reconstruct its last known location and supporting evidence.

This concept is called Time Machine.

---

# 28. CAMPEX Lens

CAMPEX Lens represents the future augmented-reality interface.

A manager or operator could walk through the facility using a mobile device.

The camera could overlay operational information.

Example:

Point at pallet:

PALLET PLT-9381
Order #48291
Destination: Dock 04

Point at machine:

MACHINE #12
RUNNING
Last stop: 08:42
Duration: 4m 12s

Point at shelf:

ZONE B14
Expected: Product XYZ
Detected: Product ABC
WARNING: possible incorrect placement

Lens connects CAMPEX World to the real physical environment.

---

# 29. CAMPEX Mobile

A future CAMPEX application may provide:

- alerts;
- investigations;
- live cameras;
- operational status;
- CAMPEX World;
- AR / Lens;
- manager communication;
- evidence review.

React Native may be considered for initial cross-platform development.

Deep AR capabilities may eventually use:

iOS:
ARKit / RealityKit

Android:
ARCore

---

# 30. CAMPEX Trace

CAMPEX Trace represents future cross-camera trajectory intelligence.

Example:

CAM 01 detects ENTITY #31

ENTITY leaves field of view.

CAM 04 detects a visually compatible entity.

CAMPEX estimates that both observations represent the same physical entity.

This enables trajectories across large environments.

Trace must account for uncertainty.

Identity should never be presented as fact when confidence is insufficient.

---

# 31. CAMPEX Predict

Once CAMPEX has sufficient operational memory, it may identify patterns and anomalies.

Examples:

- unusual congestion;
- abnormal machine inactivity;
- recurring delays;
- unusual access patterns;
- increased dwell time;
- operational bottlenecks.

Prediction should be introduced only after reliable observation and memory exist.

Prediction without reliable data is not intelligence.

---

# 32. CAMPEX Simulate

CAMPEX World may eventually allow operational simulations.

Examples:

"What happens if this loading area is moved?"

"What happens if another production line is added?"

"What happens if traffic is redirected?"

"What happens if this rack is relocated?"

Simulation requires reliable spatial and operational models and therefore belongs to the long-term roadmap.

---

# 33. CAMPEX Action

CAMPEX should eventually evolve from:

SEE

to:

UNDERSTAND

to:

RECOMMEND

and eventually:

ACT

Possible actions may include:

- notify operator;
- open workflow;
- create ticket;
- trigger business integration;
- request confirmation;
- update operational system;
- control authorized equipment.

Human approval and permission boundaries must be fundamental.

---

# 34. CAMPEX Autonomy

The highest level of the vision is controlled operational autonomy.

CAMPEX observes the physical environment.

CAMPEX understands context.

CAMPEX predicts potential problems.

CAMPEX recommends actions.

For explicitly authorized workflows, CAMPEX may eventually execute actions.

Autonomy must always consider:

- permissions;
- confidence;
- risk;
- reversibility;
- auditability;
- human escalation.

---

# 35. Intelligence Architecture

CAMPEX should not use expensive AI reasoning for every frame.

Principle:

Use deterministic software whenever deterministic software is sufficient.

Possible hierarchy:

Camera
↓
Computer Vision
↓
Tracking
↓
Deterministic Observations
↓
Rules
↓
Events
↓
AI Reasoning only when necessary

Large multimodal models should be used selectively.

This reduces:

- latency;
- cost;
- hallucination risk;
- infrastructure requirements.

---

# 36. CAMPEX Intelligence Principles

CAMPEX should distinguish between:

OBSERVED

INFERRED

UNKNOWN

INSUFFICIENT DATA

SENSOR UNAVAILABLE

This distinction is essential.

CAMPEX should never transform uncertainty into fake certainty.

Example:

Good:

"Person #18 remained in Zone B for approximately 14 seconds."

Bad:

"Employee #18 was wasting time."

CAMPEX observes operations.

It should not invent motivations.

---

# 37. Product Areas

Long-term CAMPEX may be organized into three conceptual layers.

## PERCEIVE

CAMPEX sees the physical environment.

Possible capabilities:

Vision
Sight
Trace
Sense
Scan
Edge
Observations

## UNDERSTAND

CAMPEX turns observations into knowledge.

Possible capabilities:

Memory
Recall
Intelligence
Ask CAMPEX
Context
Patterns
Prediction

## OPERATE

CAMPEX transforms intelligence into operational interfaces and actions.

Possible capabilities:

World
Lens
Simulation
Actions
Automation

Names remain subject to brand evolution.

Architecture matters more than current naming.

---

# 38. Main Markets

CAMPEX should initially focus on environments where physical visibility creates measurable operational value.

Potential markets include:

- industry;
- warehouses;
- distribution centers;
- logistics;
- manufacturing;
- physical security;
- retail operations;
- infrastructure;
- large facilities.

The first market should remain narrow.

CAMPEX should solve one expensive problem extremely well before expanding horizontally.

---

# 39. CAMPEX Is Not Just Security

Security may be an excellent entry point.

But CAMPEX's long-term opportunity is larger.

The same physical intelligence infrastructure used to detect:

"person entered restricted zone"

can eventually understand:

"forklift is blocking loading area"

"pallet is in the wrong location"

"machine has unexpectedly stopped"

"loading dock has unusual congestion"

"order has physically reached dispatch"

Security is one application of Physical Intelligence.

Operations are the larger platform opportunity.

---

# 40. Product Experience

CAMPEX should feel like professional operational software.

Not another generic SaaS dashboard.

Different workflows require different interfaces.

OPERATIONS
→ Video Wall / Command Center

EVENTS
→ Operational timeline

INVESTIGATIONS
→ Evidence workspace

INTELLIGENCE
→ AI + operational evidence

CAMERAS
→ Infrastructure management

AREAS
→ Spatial configuration

WORLD
→ Digital twin

SETTINGS
→ Administrative interface

---

# 41. Visual Direction

CAMPEX should communicate:

precision
technology
trust
operational seriousness
simplicity
intelligence

Primary visual system:

black
white
gray

Color should primarily communicate operational meaning.

Green:
normal / connected / active

Yellow:
attention

Red:
critical

The product should avoid excessive decorative color.

Video and operational information should remain the visual protagonists.

---

# 42. Technical Direction

Initial recommended stack:

Frontend:
HTML
CSS
JavaScript

Backend:
Python
FastAPI

Vision:
Python
OpenCV
Ultralytics YOLO

Tracking:
ByteTrack or equivalent

Database:
PostgreSQL

Development database:
SQLite may be used temporarily

Realtime:
WebSocket

Camera protocols:
RTSP
ONVIF where appropriate

Future:

ONNX Runtime
TensorRT
PostGIS
pgvector
Redis
NATS/Kafka
S3/R2/MinIO
React Native
Three.js
React Three Fiber
OpenUSD
ARKit
ARCore

Future technologies must only be introduced when justified by product requirements.

---

# 43. Architectural Direction

CAMPEX should begin as a modular monolith.

Do not start with microservices.

Initial architecture:

Frontend
↓
FastAPI
↓
CAMPEX Core
├── Cameras
├── Vision
├── Tracking
├── Observations
├── Rules
├── Events
├── Evidence
└── Realtime
↓
Database

As scale grows, components may become independent services.

Possible future separation:

Cloud API
Vision Workers
Edge Runtime
Event Bus
Memory Service
Intelligence Service
World Service

But only when operational scale requires it.

---

# 44. Multi-Tenant Future

CAMPEX is intended to become a platform serving multiple organizations.

Future data models should consider:

organization
site
unit
area
camera
edge_node
zone
entity
observation
event
evidence
investigation
user

Even when the MVP is simple, avoid architectural choices that make multi-tenant evolution impossible.

---

# 45. Future Enterprise Architecture

A mature CAMPEX deployment may resemble:

PHYSICAL WORLD

Cameras
Sensors
Machines
IoT

↓

CAMPEX EDGE

Stream ingestion
Vision
Tracking
Local observations
Local rules
Buffer
Evidence
Health

↓

SECURE CONNECTION

↓

CAMPEX CLOUD

API
Events
Memory
Intelligence
Search
Integrations
World

↓

EXPERIENCES

Operations Center
Web
Mobile
World
Lens
API
Enterprise Integrations

---

# 46. Business Vision

CAMPEX should not aim to become merely a camera software company.

The long-term ambition is to become infrastructure for Physical Intelligence.

The platform can potentially sit between:

the physical world

and

enterprise software.

Modern companies have systems that understand:

finance
customers
sales
inventory
software infrastructure

CAMPEX aims to help them understand:

their physical reality.

---

# 47. Long-Term Company Vision

CAMPEX should be designed with the ambition to become a global technology company.

The long-term opportunity is not limited to one city, one country, one camera manufacturer or one industry.

CAMPEX should eventually be capable of operating across:

factories
warehouses
distribution centers
logistics networks
commercial environments
large physical infrastructure

The company should grow through technological depth, reliability and measurable operational value.

The objective is not to become large because the document says so.

The objective is to build technology valuable enough that global scale becomes possible.

---

# 48. Competitive Moat

The long-term moat should not simply be:

"we use YOLO."

Object detection will increasingly become commoditized.

Potential CAMPEX differentiation includes:

Operational Observations
+
Physical Memory
+
Spatial Context
+
Business Context
+
Cross-Camera Understanding
+
Evidence
+
Physical World Model
+
Operational Intelligence

The system should understand not only pixels, but the operational meaning behind them.

---

# 49. Development Principle

The project must always remember:

VISION ≠ CURRENT SCOPE

The roadmap may describe years of possibilities.

Development should focus only on the current milestone.

Before implementing a feature, ask:

1. Does this help prove the current product hypothesis?
2. Does the customer need this now?
3. Does this improve reliability of the core pipeline?
4. Can we validate it in a real environment?

If the answer is no, the feature probably belongs in the roadmap rather than the current sprint.

---

# 50. The First Mission

Before CAMPEX World.

Before AR.

Before Prediction.

Before autonomous operations.

Before global scale.

CAMPEX must prove one thing exceptionally well:

A real camera can become an intelligent operational sensor.

The first mission is therefore:

REAL CAMERA
↓
RELIABLE VIDEO
↓
RELIABLE DETECTION
↓
RELIABLE TRACKING
↓
RELIABLE OBSERVATION
↓
RELIABLE EVENT
↓
RELIABLE EVIDENCE
↓
USEFUL OPERATOR EXPERIENCE

This is CAMPEX MVP.

Everything else grows from this foundation.

---

# 51. North Star

CAMPEX begins by understanding a camera.

Then a room.

Then a warehouse.

Then a factory.

Then an entire physical operation.

Eventually, CAMPEX should be capable of maintaining a living digital understanding of the physical world around an organization.

See.

Remember.

Understand.

Predict.

Act.

That is the long-term direction of CAMPEX.