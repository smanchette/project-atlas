"""Run the narrow automatic-CTA refresh only on an explicitly marked clone.

This is a disposable rehearsal entry point.  It intentionally has no active
database override and never obtains its database URL from the application
engine singleton.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, create_engine

from app.services.automatic_cta_refresh import (
    FAILURE_POINTS,
    InjectedAutomaticCTARefreshFailure,
    rehearse_automatic_cta_refresh,
)


EXPECTED_ALEMBIC_REVISION = "20260820_0048"
DATABASE_NAME_PATTERN = re.compile(
    r"^atlas_cta_refresh_[a-f0-9]{8,32}_(scratch|success|restore)$"
)
NONCE_PATTERN = re.compile(r"^[a-f0-9]{64}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
DATABASE_URL_ENV = "ATLAS_CTA_REFRESH_DATABASE_URL"
RUN_GUC = "atlas.cta_refresh_run_id"
NONCE_GUC = "atlas.cta_refresh_nonce_sha256"
MAX_CONCURRENCY_HOLD_SECONDS = 20.0


class RehearsalGuardError(RuntimeError):
    """The disposable database identity or runner contract failed closed."""


def require_disposable_database(
    session: Session,
    *,
    expected_database: str,
    run_id: str,
    nonce_sha256: str,
) -> dict[str, str]:
    """Bind the transaction to one PostgreSQL clone and its database GUCs."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise RehearsalGuardError("Automatic CTA rehearsal requires PostgreSQL.")
    if expected_database == "atlas" or not DATABASE_NAME_PATTERN.fullmatch(expected_database):
        raise RehearsalGuardError("Expected database is not an allowed disposable clone name.")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RehearsalGuardError("Task run identity is malformed.")
    if not NONCE_PATTERN.fullmatch(nonce_sha256):
        raise RehearsalGuardError("Task nonce fingerprint is malformed.")

    row = session.exec(
        text(
            "SELECT current_database(), "
            "current_setting('atlas.cta_refresh_run_id', true), "
            "current_setting('atlas.cta_refresh_nonce_sha256', true)"
        )
    ).one()
    observed_database, observed_run_id, observed_nonce = (str(value or "") for value in row)
    if observed_database == "atlas" or observed_database != expected_database:
        raise RehearsalGuardError("Connected database identity differs or is protected active Atlas.")
    if not DATABASE_NAME_PATTERN.fullmatch(observed_database):
        raise RehearsalGuardError("Connected database is outside the disposable rehearsal allowlist.")
    if observed_run_id != run_id or observed_nonce != nonce_sha256:
        raise RehearsalGuardError("Disposable database marker does not match this task run.")
    revision = session.exec(text("SELECT version_num FROM alembic_version")).one()
    if str(revision[0]) != EXPECTED_ALEMBIC_REVISION:
        raise RehearsalGuardError("Disposable clone Alembic revision differs.")
    return {
        "database": observed_database,
        "run_id": observed_run_id,
        "nonce_sha256": observed_nonce,
        "alembic_revision": str(revision[0]),
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise RehearsalGuardError(f"{DATABASE_URL_ENV} is required.")
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            guard = require_disposable_database(
                session,
                expected_database=args.expected_database,
                run_id=args.run_id,
                nonce_sha256=args.nonce_sha256,
            )
            try:
                if args.mode == "dry-run":
                    result = rehearse_automatic_cta_refresh(
                        session,
                        manifest,
                        dry_run=True,
                        lock_nowait=args.lock_nowait,
                    )
                    session.rollback()
                elif args.mode == "inject":
                    try:
                        rehearse_automatic_cta_refresh(
                            session,
                            manifest,
                            failure_point=args.failure_point,
                            lock_nowait=args.lock_nowait,
                        )
                    except InjectedAutomaticCTARefreshFailure as exc:
                        expected_suffix = f"{args.failure_point}."
                        if not str(exc).endswith(expected_suffix):
                            raise RehearsalGuardError(
                                "Injected failure identity differs from the requested point."
                            ) from exc
                        session.rollback()
                        result = {
                            "status": "EXPECTED_ROLLBACK",
                            "failure_point": args.failure_point,
                            "writes_committed": 0,
                        }
                    else:
                        session.rollback()
                        raise RehearsalGuardError("Requested failure point did not fire.")
                else:
                    result = rehearse_automatic_cta_refresh(
                        session,
                        manifest,
                        lock_nowait=args.lock_nowait,
                    )
                    if args.hold_before_commit_seconds:
                        time.sleep(args.hold_before_commit_seconds)
                    session.commit()
                return {
                    "schema": "project-atlas-automatic-cta-refresh-runner-result@1",
                    "mode": args.mode,
                    "database": guard["database"],
                    "run_id": guard["run_id"],
                    "nonce_sha256": guard["nonce_sha256"],
                    "alembic_revision": guard["alembic_revision"],
                    "result": result,
                }
            except Exception:
                session.rollback()
                raise
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--mode", choices=("dry-run", "apply", "inject"), required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--nonce-sha256", required=True)
    parser.add_argument("--failure-point", choices=sorted(FAILURE_POINTS))
    parser.add_argument("--lock-nowait", action="store_true")
    parser.add_argument("--hold-before-commit-seconds", type=float, default=0.0)
    parser.add_argument("--result-output")
    args = parser.parse_args()
    if args.mode == "inject" and not args.failure_point:
        parser.error("--failure-point is required for inject mode")
    if args.mode != "inject" and args.failure_point:
        parser.error("--failure-point is allowed only for inject mode")
    if not 0.0 <= args.hold_before_commit_seconds <= MAX_CONCURRENCY_HOLD_SECONDS:
        parser.error(
            "--hold-before-commit-seconds must be between 0 and "
            f"{MAX_CONCURRENCY_HOLD_SECONDS:g}"
        )
    if args.mode != "apply" and args.hold_before_commit_seconds:
        parser.error("--hold-before-commit-seconds is allowed only for apply mode")
    return args


def main() -> int:
    args = parse_args()
    result = execute(args)
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if args.result_output:
        output = Path(args.result_output)
        if output.exists():
            raise RehearsalGuardError("Runner result output already exists.")
        output.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
