# Forgis Robotics Hackathon – Context

## Challenge Overview

Build working software that makes factory machines smarter by programming them through intelligent skill composition.

You are building an **agentic intelligence layer** on top of the Forgis Skill Engine.

High-level goal (natural language) → reasoning → skill selection → executable flow → real robot execution.

No manual robot programming. The system must dynamically compose skills.

---

## What Forgis Provides

* Skill Engine (robot behaviors as reusable blocks)
* Unified cross-vendor machine abstraction layer
* 8 real robotics workstations (on-site hardware)
* Mock hackathon platform for development/testing
* Access to Google DeepMind models

---

## What Is Expected

Your system should:

1. Accept high-level goals (plain English)
2. Decompose goals into atomic robot skills
3. Compose executable skill graphs or flows
4. Execute on real hardware
5. Adapt to changing conditions
6. Demonstrate real reasoning (not simple formatting)

Judging Criteria:

* Working end-to-end pipeline
* Real task reasoning
* Creative and smart use of skill engine
* Adaptability to changes
* Clean system architecture

---

## Example Scope

User goal:
"Assemble part A onto B, then label and place in output bin."

System should:

* Parse intent
* Select relevant skills (pick, place, convey, label)
* Order them logically
* Handle constraints (missing part, different robot, bin full)
* Deploy to robot cell

---

## Available Repositories

Dobot / UR Robot Cell:
[https://github.com/ForgisX/Hackathon_Forgis_Dobot_URR](https://github.com/ForgisX/Hackathon_Forgis_Dobot_URR)

ABB YuMi Cell:
[https://github.com/ForgisX/Hackathon__FORGIS_YUMI](https://github.com/ForgisX/Hackathon__FORGIS_YUMI)

These repos contain:

* Docker-based robot drivers
* ROS 2 interfaces
* Pick-and-place pipelines
* IO triggers
* URScript integration (for UR robots)

---

## Using Google DeepMind Gemini

Recommended components:

* Gemini 3 (Vision-Language reasoning)
* Gemini Robotics ER (task orchestration)
* Agentic Vision (zoom/localize industrial objects)
* Live API (voice + real-time perception)

Use Gemini for:

* Task decomposition
* Perception understanding
* Conditional branching
* Skill graph planning
* Failure handling logic

Best Practice:

* Separate reasoning layer from execution layer
* Validate generated plans before execution
* Keep skill schema structured (JSON/tool format)
* Add guardrails for safety and constraints

---

## Suggested Architecture

User Input → Gemini Reasoning Layer → Skill Graph Builder → Forgis Skill Engine → Robot Execution

Optional modules:

* Perception node (camera + VLM)
* State monitor
* Execution validator
* Recovery planner

---

## Goal for a Strong Demo

Demonstrate:

* Natural language goal
* Dynamic skill composition
* Conditional logic
* Real hardware execution
* Visible adaptability

The more autonomous the reasoning and composition, the stronger the demo.
