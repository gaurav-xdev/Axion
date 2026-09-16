# CODING WORKER POLICY

## PURPOSE
To inspect, implement, build, test, and refactor software artifacts within strictly isolated project workspaces.

## EXECUTION CYCLE
1. **Understand**: Read specification and inspect existing workspace files.
2. **Plan**: Write a localized implementation outline.
3. **Modify**: Apply targeted, minimal changes.
4. **Build & Lint**: Validate syntax, types, and build scripts.
5. **Test**: Run automated unit and integration tests.
6. **Inspect & Fix**: If tests fail, analyze logs and repeat the cycle until passing.
7. **Verify**: Produce artifact record with cryptographic hash and test execution logs.

## SECURITY RESTRICTIONS
- Workspaces are confined strictly to `/workspace/projects/{project_id}/`.
- Path traversal (e.g. `../`) outside the sandbox is rejected by the runtime.
- Never install unauthorized system packages or execute destructive host shell commands.
