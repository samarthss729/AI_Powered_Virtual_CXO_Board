# Design Write-Up — AI Powered Virtual CXO Board

## 1. Persona Modeling and Multi-Agent Interaction

The system models a virtual executive board consisting of a CEO, CFO, CMO, COO, and CSO. The CEO is represented by the human user, while the other executives are AI agents with distinct responsibilities and decision-making lenses.

Each persona is designed to focus on a different aspect of the business:

- **CFO — Arjun Mehta:** profitability, margins, cash, ROI, working capital, and financial risk.
- **CMO — Riya Sharma:** customer growth, CAC, retention, LTV, market share, and demand.
- **COO — Vikram Nair:** capacity, throughput, cost-to-serve, operational feasibility, and execution risk.
- **CSO — Aditya Iyer:** competitive positioning, market dynamics, strategic trade-offs, and long-term implications.
- **CEO — Ananya Kapoor:** represented by the human user, who asks the business question and receives the final board recommendation.

The discussion is orchestrated in two rounds.

**Round 1 — Independent analysis:** Each executive receives the current business question and relevant company data and provides an independent assessment from their functional perspective.

**Round 2 — Cross-challenge:** Executives receive the other executives' Round 1 views and can challenge, refine, or agree with those positions. This allows genuine trade-offs to emerge rather than producing one generic response.

A separate board synthesizer then evaluates the current discussion and produces a structured recommendation containing the decision, supporting evidence, disagreements, risks, recommended actions, monitoring metrics, and confidence.

The system is intentionally designed so that each question is treated as an isolated board decision. Previous questions are not fed back into the reasoning for a new question, preventing recommendations or metrics from leaking between unrelated business decisions.

## 2. Data Grounding and Assumptions

The prototype supports CSV/JSON company data uploads. Uploaded metrics are parsed and normalized by the backend and used as structured context for the executive agents.

The system selects metrics relevant to the current question rather than automatically providing the entire dataset to every executive. This reduces irrelevant evidence and helps prevent an executive from using unrelated metrics simply because they are available.

Agents are instructed to use evidence from the uploaded dataset and avoid inventing figures. When a requested metric is not available, the system should explicitly indicate that the metric cannot be verified rather than treating a related metric as proof.

Key assumptions:

- The uploaded company data is assumed to be accurate and representative of the business.
- CSV/JSON structured metrics are sufficient for this prototype; unstructured documents such as PDFs are outside the current scope.
- The AI executives provide decision support rather than autonomous decision-making.
- Different executives may reach different conclusions because their objectives and risk tolerances differ.
- The final recommendation is a synthesis of the available evidence and executive debate, not a guarantee of the correct business decision.

## 3. Production Extension

The current implementation is intentionally lightweight and suitable for a hiring-assignment prototype. For production, I would extend it in several areas.

**Data and retrieval:** Add support for larger datasets and unstructured sources such as financial reports, board decks, contracts, and operational documents. A retrieval layer could select relevant evidence while preserving source references and traceability.

**Reliability and evaluation:** Introduce automated evaluation datasets for factual grounding, metric relevance, persona consistency, cross-question isolation, and recommendation quality. Production monitoring would track hallucinations, latency, cost, and model failures.

**Security and governance:** Add authentication, role-based access control, tenant isolation, encryption, audit logs, and appropriate controls around sensitive company information.

**Scalability:** Move beyond SQLite to a production database and introduce background job processing and streaming responses for longer board discussions.

**Decision quality:** Add configurable decision criteria, thresholds, scenario analysis, and historical outcome tracking so the board can compare recommendations with subsequent business results.

The core orchestration model would remain: **question → relevant evidence → independent executive analysis → cross-challenge → board synthesis → actionable recommendation**.

## 4. Design Trade-offs

The prototype deliberately favors clarity and explainability over architectural complexity. A controlled orchestrator was chosen instead of a free-form multi-agent conversation so that the number of rounds, context passed between agents, and final synthesis remain predictable.

SQLite and structured CSV/JSON inputs keep the prototype easy to run locally and demonstrate. The architecture separates the frontend, API, board orchestration, agents, data processing, and synthesis layers so these components can later be replaced or scaled independently.

The goal is not simply to generate an AI answer to a business question, but to simulate how different C-suite functions would analyze the same evidence, challenge each other, and arrive at a board-level decision.