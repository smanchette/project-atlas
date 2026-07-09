\# Project Atlas Machine Setup



\## Purpose



This document records the Windows machine setup required to work on Project Atlas without depending only on Docker.



\## Required tools



Install:



\- Docker Desktop

\- Git

\- Node.js

\- npm

\- VS Code



\## Verified on current machine



Project path:



C:\\Users\\offic\\Documents\\Codex\\2026-06-29\\project-name-project-atlas-build-goal



Verified commands:



node -v

npm -v

git --version

docker --version



Current verified versions:



\- Node: v24.18.0

\- npm: 11.16.0

\- Git: 2.55.0.windows.2

\- Docker: 29.5.3



\## PowerShell npm issue



If npm fails with a message saying scripts are disabled, run:



Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned



Then close PowerShell, reopen it, and try:



npm -v



\## Frontend setup on Windows



From the project root:



cd frontend

npm install

npm run build

cd ..



Expected result:



Frontend production build passes.



\## Docker frontend verification



From the project root:



docker exec -it atlas\_frontend npm run build



Expected result:



Frontend production build passes inside Docker.



\## Backend verification



From the project root:



docker exec atlas\_backend sh -lc "PYTHONPATH=/app pytest"



Expected result as of v0.15:



119 passed



\## Git verification



From the project root:



git status



Expected safe result:



nothing to commit, working tree clean



\## Protected paths



Never delete, move, rename, clean up, or modify these folders unless Shawn explicitly asks:



\- backend/backups

\- backend/media

\- frontend/public/media

