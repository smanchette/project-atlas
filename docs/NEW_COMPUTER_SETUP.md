\# Project Atlas New Computer Setup



This guide is for moving Project Atlas to another Windows computer.



\## Required software



Install these first:



\- Docker Desktop

\- Git

\- Node.js LTS

\- VS Code



\## Confirm tools



Open PowerShell and run:



docker --version

git --version

node -v

npm -v



If node or npm is not recognized, install Node.js LTS and reopen PowerShell.



\## Project location



Current known project path:



C:\\Users\\offic\\Documents\\Codex\\2026-06-29\\project-name-project-atlas-build-goal



On a new computer, the path may be different. Keep it simple and avoid spaces if possible.



\## Start Atlas



From the project root:



docker compose up -d



\## Local URLs



Frontend: http://localhost:5173

Backend: http://localhost:8000

Generated Pages: http://localhost:5173/generated-pages

Approval Queue: http://localhost:5173/approval-queue



WordPress Sandbox, Draft Queue, and Draft Review are also part of the platform.



\## Verify containers



docker ps



Expected containers:



\- atlas\_frontend

\- atlas\_backend

\- atlas\_postgres



\## Verify frontend build



docker exec -it atlas\_frontend npm run build



\## Verify backend tests



docker exec -it atlas\_backend sh -lc "PYTHONPATH=/app pytest"



Expected backend result as of v0.13:



119 passed



\## Protected paths



Do not delete, move, rename, clean up, or modify:



\- backend/backups

\- backend/media

\- frontend/public/media



\## Basic Git check



git status



A safe checkpoint should show:



nothing to commit, working tree clean

