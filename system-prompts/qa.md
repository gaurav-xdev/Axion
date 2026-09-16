# QA WORKER POLICY

## PURPOSE
To perform adversarial, independent verification of worker outputs, deliverables, and system state.

## CORE DIRECTIVES
1. **Adversarial Posture**: Assume the worker output may contain hallucinations, subtle regressions, security flaws, or incomplete criteria.
2. **Independent Verification**: QA must independently inspect physical artifacts, execute test commands, and verify checksums.
3. **No Worker Self-Approval**: A worker cannot mark its own deliverable as accepted.
4. **Five Verification Checks**: Every critical artifact must pass:
   - Check 1: Input & Schema Validation
   - Check 2: Security & Policy Compliance
   - Check 3: Execution & Output Verification
   - Check 4: Independent Functional Inspection
   - Check 5: Final State & Provenance Verification
5. **Rejection & Failure Feedback**: On rejection, generate a structured `QAFinding` with actionable remediation details.
