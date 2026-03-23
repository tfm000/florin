# Agent Guidelines — Bloomberg Terminal Clone

## Project Overview

This is a **production-grade Bloomberg terminal clone**. Every contribution must meet the standard of software that handles real financial data, serves real users, and cannot afford silent failures or numerical inaccuracies.

---

## Core Principles

1. **No silent failures.** If something breaks, stop and report it — never work around an error quietly. This includes errors from seemingly unrelated processes.
2. **No partial implementations.** Every file touched must receive a full implementation. Do not leave stubs, placeholders, or `# TODO` markers in committed code.
3. **No summarising.** Provide complete code for every file changed. Never truncate, abbreviate, or paraphrase implementation details.
4. **No mathematical changes without approval.** Models, formulas, pricing engines, risk calculations, and statistical methods must not be modified without first: (a) explaining what is currently wrong with evidence, (b) proposing the exact replacement with derivation or reference, and (c) receiving explicit user approval before writing any code.
5. **No unverified data paths.** Every API integration, data fetch, and pipeline stage must be verified end-to-end — a 200 status code is not proof that data was returned, is non-empty, and conforms to the expected schema. If you cannot prove data flows correctly from source to consumer, the implementation is incomplete.

---

## Workflow — Before Writing Any Code

For every task, follow this sequence **strictly**:

1. **Understand scope.** Read the full task description. Identify every file, module, and interface boundary that will be affected.
2. **Generate a TODO list.** Produce a complete, ordered checklist of every change needed across all scripts and modules before touching any code. Present this for review.
3. **Identify risks.** Flag any changes that touch: pricing models, risk engines, data pipelines, authentication, or database schemas. These require extra scrutiny.
4. **Implement.** Work through the TODO list item by item. Write full implementations — no diffs, no snippets, no summaries.
5. **Test.** Write and run tests covering all new functionality (see Testing section below).
6. **Verify data paths.** If the task involves any API or data integration, trace at least one record end-to-end from source to UI. Log and inspect the raw response, validated model, stored state, and rendered output. Do not skip this step (see API & Data Verification section below).
7. **Build.** Rebuild the frontend after any edits to frontend code.
8. **Verify.** Run the full CI/CD test suite before declaring the task complete.

---

## Environment & Tooling

- **Virtual environment:** Always activate and use the project `venv` for running and testing code.
- **Frontend builds:** Rebuild the frontend (`npm run build` or equivalent) after every frontend edit. Never assume a stale build is acceptable.
- **Dependencies:** If a new dependency is required, add it to the appropriate manifest (`requirements.txt`, `pyproject.toml`, `package.json`) and document why it was added.

---

## Testing Requirements

### Coverage Expectations

- **API endpoints:** Every endpoint must have tests covering success cases, expected error cases, edge cases, and authentication/authorisation.
- **UI components:** Component tests for rendering, user interaction, and state management.
- **Data pipelines:** Tests for ingestion, transformation, and output correctness — including malformed input handling.
- **Mathematical models:** Property-based tests and regression tests against known-good reference values. Include numerical stability checks where relevant.

### CI/CD

- All tests must pass in CI before any merge. No exceptions, no skipping.
- CI must run: linting, type checking, unit tests, integration tests, and the frontend build.
- If a test fails, fix the root cause. Do not disable or skip the test.

---

## API & Data Verification

**Implementing an API call is not the same as verifying it works.** This is a critical distinction. Every data integration must be validated at three levels:

### 1. Response Validation — Did We Get Anything?

After every external or internal API call, immediately verify:

- **HTTP status is as expected** (not just "not 500" — check for the specific expected code).
- **Response body is non-empty.** A 200 with an empty body, `null`, `[]`, or `{}` is a failure — treat it as one.
- **Content-Type matches expectations** (e.g., `application/json`, not an HTML error page masquerading as success).

Do not proceed past this step if any check fails. Log the raw response and raise an explicit error.

### 2. Schema Validation — Is the Data Shaped Correctly?

Every API response must be validated against the expected schema before use:

- **Required fields exist.** Check that all fields the downstream code depends on are present — do not let a `KeyError` be the first sign of a schema mismatch.
- **Types are correct.** A price that arrives as a string `"124.50"` instead of a float `124.50` will silently corrupt calculations if not caught. Parse and validate types explicitly.
- **Nested structures are intact.** If the API returns nested objects or arrays, validate depth and structure — not just top-level keys.
- **Enums and categorical values are within expected sets.** A status field returning `"HALTED"` when the code only handles `"OPEN"` and `"CLOSED"` must be caught at ingestion, not in a rendering function three layers down.

Use Pydantic models (or equivalent) to enforce schemas at API boundaries. Raw `dict` access on unvalidated API responses is not acceptable.

### 3. Semantic Validation — Does the Data Make Sense?

Data can be structurally valid but financially nonsensical. After schema validation, apply domain-aware sanity checks:

- **Prices:** Must be positive (or zero for specific instruments). A stock price of `-5.00` or `0.0001` should trigger an alert, not flow into a portfolio valuation.
- **Volumes:** Must be non-negative integers. Fractional or negative volumes indicate a parsing or API issue.
- **Timestamps:** Must be within a plausible range (not in the future for historical data, not years stale for "live" data). Timezone must be explicit and consistent.
- **Percentage values:** Verify whether the source returns `0.05` (decimal) or `5.0` (percentage). This is the single most common source of off-by-100x errors in financial applications. Document the convention and convert at ingestion.
- **Currency consistency:** If a response mixes currencies or omits currency codes, flag it immediately.
- **Staleness:** For any data labelled as live or real-time, verify the timestamp is within an acceptable recency window. Serving a stale quote as current is a critical defect.

### 4. End-to-End Verification

After implementing any new data path, **trace a single record from source to UI**:

1. Make the API call and log the raw response.
2. Validate it passes schema checks.
3. Verify it passes semantic checks.
4. Confirm it is stored/cached correctly.
5. Confirm it renders correctly in the frontend with the right format, units, and precision.

This end-to-end trace must be documented in the PR or task completion notes. "It works" without evidence is not acceptable — show the data at each stage.

### 5. Tests for Data Paths

Every API integration must include:

- **Contract tests:** Mock the external API and assert the code handles the documented response format correctly.
- **Empty/null response tests:** Verify graceful failure when the API returns no data.
- **Malformed response tests:** Feed garbage, partial JSON, HTML error pages, and unexpected field types. Assert the code fails loudly with a clear error, not silently with corrupt state.
- **Stale/duplicate data tests:** Verify the system handles repeated data and out-of-order delivery correctly.
- **Live smoke tests (where feasible):** A lightweight integration test that hits the real API and verifies the response conforms to expectations. This catches upstream API changes that mocks will miss.

---

### Style & Structure

- Follow existing project conventions for naming, file structure, and module boundaries.
- Keep functions short and single-purpose. If a function exceeds ~40 lines, it likely needs decomposition.
- Use type hints everywhere in Python. Use TypeScript (not JavaScript) for all frontend code.
- Docstrings on all public functions and classes — include parameter types, return types, and a brief description of behaviour.

### Error Handling

- Use explicit, typed exceptions. Never catch bare `Exception` unless re-raising.
- API errors must return structured error responses with appropriate HTTP status codes.
- Log errors with sufficient context to diagnose without reproducing (timestamp, input summary, stack trace).

### Performance

- Financial data paths are latency-sensitive. Avoid unnecessary allocations, redundant computations, and blocking I/O in hot paths.
- Profile before optimising. Do not introduce complexity for speculative performance gains.

---

## Financial / Mathematical Code

This section carries the highest bar for correctness.

- **Reference everything.** Cite the paper, textbook, or specification for any formula implemented (e.g., Black-Scholes, Hull-White, GARCH). Include the reference in a docstring or comment adjacent to the implementation.
- **Units and conventions.** Be explicit about day-count conventions, compounding frequency, annualisation factors, and currency. Never assume — document.
- **Numerical stability.** Prefer log-space computations for products of probabilities. Guard against division by zero, overflow, and catastrophic cancellation. Use appropriate tolerances in floating-point comparisons.
- **Validation.** Validate all inputs to pricing and risk functions (e.g., non-negative volatility, valid maturity dates, reasonable strike ranges). Fail loudly on invalid inputs.

---

## Git & Version Control

- Commit messages must be descriptive: `fix(pricing): correct accrued interest calc for ACT/360 convention` — not `fix bug`.
- One logical change per commit. Do not bundle unrelated fixes.
- Never commit commented-out code, debug print statements, or hardcoded secrets/keys.

---

## When Something Goes Wrong

1. **Stop.** Do not continue building on top of a broken state.
2. **Diagnose.** Read the full error trace. Identify the root cause, not just the symptom.
3. **Report.** Explain the error clearly: what failed, why, and what the fix options are.
4. **Fix.** Apply the fix, add a test that would have caught the issue, and verify the full suite still passes.
