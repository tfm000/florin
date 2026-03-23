# Phase 10: Documentation Update

## Objective

Update all documentation to reflect the Florin branding, new features, and restructured navigation.

## Files to Update

### 1. `README.md` — Full rewrite

- New project name: Florin
- Updated feature list reflecting all changes
- New architecture diagram
- Updated prerequisites
- Updated installation instructions (entry point is now `florin` not `sentinel`)
- Updated configuration section (no Polygon, no scanner settings)
- New navigation structure documentation
- Updated Telegram bot commands
- Updated Docker instructions
- Screenshots (if applicable)
- Remove all "penny stock" framing — present as general financial terminal

### 2. `agent.md` — Update project references

- Update "Bloomberg Terminal Clone" to reflect Florin branding
- Update any Sentinel references
- Update any penny-stock specific guidance

### 3. `CLAUDE_CODE_BRIEFING.md`

- Update or remove if redundant with `agent.md`
- Update all references

### 4. `plan.md` / `new_plan.md`

- Archive or remove — these are superseded by `major_updates/`

### 5. `dashboard_ui/README.md`

- Update project name
- Update available scripts

### 6. `setup.sh` / `setup.bat`

- Update entry point from `sentinel` to `florin`
- Update any echo/print messages

### 7. Inline docstrings

Review and update docstrings in all modified modules to ensure they:
- Reference "Florin" not "Sentinel"
- Don't mention "penny stocks" where the code is now general-purpose
- Accurately describe current behavior (not pre-refactor behavior)

### 8. `pyproject.toml`

- Verify description is updated
- Verify all dependencies are current
- Remove `polygon-api-client` if not already done

### 9. `major_updates/master_plan.md`

- Update all phase statuses to "Complete"
- Add any final notes

## Quality Checklist

- [ ] No remaining "Sentinel" references in docs
- [ ] No remaining "penny stock" references in docs
- [ ] Installation instructions work from scratch
- [ ] Docker build and run instructions work
- [ ] All API endpoints are documented or discoverable via `/api/docs`
- [ ] Telegram bot commands are documented
- [ ] Environment variables are documented
- [ ] Navigation structure is documented
