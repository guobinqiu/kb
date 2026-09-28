# Office MinerU Flash Implementation Plan

**Goal:** Route new and legacy Office documents through self-hosted MinerU Flash. Keep native TXT/Markdown parsing only.

**Architecture:** Office requests always use the existing MinerU API endpoint, timeout and retry configuration, with a separate Flash parser client. PDF routing and native TXT/Markdown behavior stay unchanged.

**Tech Stack:** Python, httpx, MinerU V1 API, pytest.

## Global Constraints

- Remove native Office implementations, their tests and dependencies.
- Support DOC/DOCX, XLS/XLSX and PPT/PPTX.
- Always submit Office jobs with `tier: flash` and the correct MIME type.
- Do not change PDF tier or inference configuration.

### Task 1: Routing Tests

- Add six-format routing tests, Office URL cleanup, and an HTTP transport test for upload MIME and Flash jobs.
- Verify the tests fail before implementing the new route.

### Task 2: Implementation

- Remove the Office provider switch from ParserConfig and its loader.
- Route Office through a MinerU client configured for Flash; start/close it with ParserService.
- Derive API upload MIME from the original filename.
- Document that the shared YAML tier applies only to PDF; Office always uses Flash.

### Task 3: Verification

- Run Indexer/Parser/Inference regression tests and KB shared configuration tests.
- Parse generated Word, Excel and PowerPoint samples through the actual 233 API, checking text and tables.
- Rebuild the local Indexer and verify health and MQ subscription.
