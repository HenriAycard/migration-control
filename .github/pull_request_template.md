## What and why

## How it was tested
- [ ] `ruff check .` and `pytest -q` pass
- [ ] If prompts, rubrics or schemas changed: `mig validate` on the petclinic example, and (if you can) one real run
- [ ] If the dashboard changed: `mig dashboard --offline` on the petclinic example, checked in a browser

## Safety
- [ ] No token or key can reach a prompt, a log, `.mig/`, argv or the dashboard page
- [ ] Agents still get no write credential; publishing still requires a human approval
