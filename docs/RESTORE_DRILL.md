\# Project Atlas Restore Drill



\## v0.15 Restore Drill / New Computer Simulation



Date: 2026-07-08



Purpose:



Prove that Project Atlas can be checked, rebuilt, and verified using documented commands before attempting a real computer transfer.



\## Commands tested



Docker Compose configuration:



docker compose config



Frontend production build:



docker exec -it atlas\_frontend npm run build



Backend test suite:



docker exec -it atlas\_backend sh -lc "PYTHONPATH=/app pytest"



\## Results



Docker Compose configuration loaded successfully.



Frontend build passed.



Backend tests passed:



119 passed



\## Notes



The backend pytest command may need PYTHONPATH=/app inside the Docker backend container.



The protected paths remain:



\- backend/backups

\- backend/media

\- frontend/public/media



These paths must not be deleted, moved, renamed, cleaned up, or modified unless Shawn explicitly asks.

