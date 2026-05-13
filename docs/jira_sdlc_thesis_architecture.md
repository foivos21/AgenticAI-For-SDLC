# Jira-Driven SDLC Thesis Architecture

## Purpose

This implementation demonstrates a Jira-based software maintenance workflow in which Jira is the operational entry point and the application platform becomes the execution and observability layer.

The goal is not to present the most advanced architecture. The goal is to present an architecture that is:

- explainable
- structured
- traceable
- practical for a thesis demo

## Core Thesis Statement

An agent connected to Jira can be used to support software maintenance by:

1. collecting issues from Jira
2. analyzing whether those issues are executable by the platform
3. mapping issues into predefined system tasks
4. triggering a controlled improvement pipeline
5. tracking the lifecycle of the work back into Jira
6. exposing the full process in a monitoring UI

This creates a lightweight Software Development Life Cycle around Jira where Jira is not only a backlog tool, but also a control surface for operational maintenance work.

## Why This Approach Was Chosen

This codebase uses a deliberately bounded approach instead of free-form autonomous code generation.

Key design choice:
- Jira issues must map to a predefined `task_slug` using the label format `ai_task:<task_slug>`.

Reason:
- This keeps the system deterministic enough for a thesis.
- It makes the workflow easy to explain.
- It avoids the complexity of open-ended ticket interpretation.
- It makes failures easier to reason about because every issue either maps cleanly or fails validation.

This is a constraint by design, not a limitation by accident.

## System Components

### 1. Jira Integration Layer

Backend routes under `/api/jira` provide the integration boundary.

Implemented capabilities:
- list tracked Jira issues
- fetch one tracked Jira issue
- run one Jira issue through the pipeline
- receive Jira webhook events
- sync issues directly from Jira using JQL

Why this matters:
- It separates Jira integration concerns from the rest of the app.
- It gives the frontend one stable API surface for issue monitoring.

### 2. Issue Analysis Layer

Each Jira issue is normalized into an internal analysis object:

- `issue_key`
- `summary`
- `description`
- `labels`
- `priority`
- `reporter`
- `created_at`
- `updated_at`
- `task_slug`
- `analysis_notes`
- `validation_errors`

Why this matters:
- The thesis needs an explainable decision point.
- This object is that decision point.
- It makes it easy to show why a ticket is runnable or not runnable.

### 3. Mapping Contract

The current mapping contract is:

- exactly one Jira label with prefix `ai_task:`
- the value after the prefix must match an internal task slug

Example:
- `ai_task:book_flight`

Why this matters:
- It is simple enough for a thesis demonstration.
- It is auditable.
- It avoids ambiguous AI inference for v1.

### 4. Link Store

The system stores issue linkage in a file-backed JSON store under the existing testing pipeline artifact area.

Stored fields include:
- issue state
- pipeline id
- analysis payload
- timestamps
- sync metadata
- latest commit/deploy info

Why file-backed storage was chosen:
- no database migration needed
- easy to inspect during demos
- low implementation overhead
- aligns with thesis prototype goals

### 5. Pipeline Orchestration Layer

When an issue is runnable, the Jira service starts the existing bounded refinement pipeline with:

- one mapped `task_slug`
- manual approval enabled

Why manual approval was kept:
- safer for software maintenance demonstrations
- easier to justify academically
- avoids overstating full autonomy

The thesis argument becomes stronger because the system demonstrates controlled autonomy rather than unbounded autonomy.

### 6. Jira Status and Comment Sync

The platform mirrors important pipeline milestones back to Jira:

- pipeline started
- fix plan ready
- approval required
- iteration complete
- final success or failure

Why this matters:
- Jira remains the canonical project interface
- users can inspect progress without leaving Jira
- the integration becomes operational, not just observational

### 7. Frontend Monitoring Layer

The frontend Jira page is the observability surface of the thesis.

It lets the user:
- sync Jira issues with JQL
- select a tracked issue
- inspect mapping validity
- see pipeline linkage
- run or re-run an issue
- approve a waiting iteration
- inspect the process event stream

Why this matters:
- It turns the thesis into a demonstrable system rather than a backend-only prototype.
- It shows both control and visibility.

## Why ElevenLabs Was Removed

For the thesis, the ElevenLabs runtime dependency was removed from the active application flow.

Reason:
- voice-agent coupling was not central to the SDLC argument
- it added external complexity
- it made the platform harder to run and explain

Current thesis mode:
- Jira remains central
- chat remains available in local-only fallback mode
- ElevenLabs-dependent testing execution is intentionally disabled

This makes the thesis narrative cleaner:
- the focus is software maintenance through Jira-driven orchestration
- not voice conversation systems

## Operational Modes

### Mode A: Jira Sync and Showcase

Use case:
- collect tickets from Jira and visualize them in the platform

Flow:
1. sync issues from Jira using JQL
2. store them locally
3. analyze mapping validity
4. display them in the Jira monitor

This is the recommended thesis demo starting point.

### Mode B: Controlled Execution

Use case:
- take one mapped issue and process it through the internal improvement pipeline

Flow:
1. issue is selected
2. issue is run manually from the UI
3. pipeline is started
4. events are mirrored back to Jira
5. approval gate pauses before apply/push

This demonstrates agent-assisted maintenance with guardrails.

## Important Assumptions

The implementation intentionally assumes:

- Jira issues are not interpreted freely
- issue-to-task mapping is explicit
- not every issue is runnable
- manual approval is preferable to fully autonomous mutation
- file storage is acceptable for prototype state
- explainability is more important than maximum autonomy

These assumptions are appropriate for a thesis because they make the system easier to defend, reproduce, and analyze.

## Current Limitations

The system does not yet:

- infer tasks from arbitrary issue text
- comment on exact source lines in Jira
- integrate with GitHub PR review comments
- perform a full autonomous code-repair cycle without the disabled external testing path

These are valid next-step extensions, not defects in the current thesis scope.

## Recommended Thesis Narrative

A clear way to present this work is:

1. Jira is used as the intake and governance layer.
2. The platform synchronizes issues and determines which are executable.
3. Executable issues map into bounded maintenance workflows.
4. The workflow is observable in both Jira and the platform.
5. Manual approval preserves software engineering control.
6. This demonstrates a practical agent-driven SDLC for maintenance, not an unconstrained autonomous developer.

## Recommended Next Extensions

If this evolves beyond the thesis prototype, the next logical steps are:

- GitHub integration for PR and code review linkage
- richer Jira JQL filters and saved sync profiles
- issue templates for agent-ready tickets
- dynamic task inference for broader issue classes
- a more advanced execution engine replacing the currently disabled external conversation-based testing path
