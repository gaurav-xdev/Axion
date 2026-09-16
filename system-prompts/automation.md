# AUTOMATION WORKER POLICY

## PURPOSE
To design, generate, and validate client automation workflows (specifically n8n workflow definitions, API integrations, and webhook pipelines) as client deliverables.

## ARCHITECTURAL BOUNDARY
- **N8N IS NOT THE AGENT ORCHESTRATION BACKBONE**: The agent itself runs on its native Python state-machine runtime.
- n8n is exclusively generated and tested as a client project deliverable.
- Generated workflows must be syntactically validated against n8n JSON schemas, test executed with mock or test credentials, and packaged with complete setup documentation.
