"""CLI: python -m geoptimiser.app serve | audit | compare | list.

The serve command starts the local API and UI. It is permanently bound to 127.0.0.1
because the API has no authentication or user isolation.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from geoptimiser.app.config import LOOPBACK_HOSTS, AppConfig
from geoptimiser.app.models import AuditOptions, AuditSubmission
from geoptimiser.app.service import AuditService, ServiceError

DEFAULT_DATA_DIR = Path("data")


def _service(args: argparse.Namespace, **extra: object) -> AuditService:
    return AuditService(AppConfig(data_dir=args.data_dir, **extra))  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m geoptimiser.app")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the local API and UI")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--no-agent", action="store_true", help="disable the optional LLM agent"
    )
    serve.add_argument(
        "--max-agent-audits-per-hour",
        type=int,
        default=AppConfig.model_fields["max_agent_audits_per_hour"].default,
        help="server-side cap on LLM-agent audits accepted per hour (0 forbids them)",
    )
    serve.add_argument(
        "--cors-origin",
        action="append",
        default=[],
        help="allow a local browser origin to call the API (repeatable)",
    )

    audit = sub.add_parser("audit", help="run one audit now and print its summary")
    audit.add_argument("url")
    audit.add_argument("--brand")
    audit.add_argument("--max-pages", type=int, default=AuditOptions().max_pages)
    audit.add_argument("--max-depth", type=int, default=AuditOptions().max_depth)
    audit.add_argument(
        "--retrieval", choices=["off", "lexical", "semantic"], default="lexical"
    )
    audit.add_argument("--agent", action="store_true", help="also run the LLM agent")
    audit.add_argument(
        "--confirm-authorized",
        action="store_true",
        help="attest that you own or are authorized to audit the site",
    )

    compare = sub.add_parser("compare", help="compare two completed audits of one URL")
    compare.add_argument("before")
    compare.add_argument("after")
    sub.add_parser("list", help="list stored audits")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.command == "serve":
        try:
            service = _service(
                args,
                allowed_hosts=LOOPBACK_HOSTS,
                agent_enabled=not args.no_agent,
                cors_origins=tuple(args.cors_origin),
                max_agent_audits_per_hour=args.max_agent_audits_per_hour,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if service.recovered:
            print(
                f"marked {len(service.recovered)} unfinished audit(s) as interrupted",
                file=sys.stderr,
            )
        try:
            import uvicorn

            from geoptimiser.app.api import create_app
        except ImportError:
            print("the API needs: pip install 'geoptimiser[api]'", file=sys.stderr)
            return 2
        uvicorn.run(
            create_app(service), host="127.0.0.1", port=args.port, log_level="warning"
        )
        return 0

    service = _service(args)
    try:
        if args.command == "audit":
            if not args.confirm_authorized:
                parser.error("--confirm-authorized is required")
            record = service.submit(
                AuditSubmission(
                    url=args.url,
                    brand_name=args.brand,
                    authorization_confirmed=True,
                    options=AuditOptions(
                        max_pages=args.max_pages,
                        max_depth=args.max_depth,
                        retrieval=args.retrieval,
                        use_agent=args.agent,
                    ),
                )
            )
            service.runner.wait_idle()
            done = service.get(record.audit_id)
            print(
                json.dumps(
                    {
                        "audit_id": done.audit_id,
                        "status": done.status,
                        "error_category": done.error_category,
                        "error_message": done.error_message,
                        "summary": done.summary,
                    },
                    indent=2,
                    default=str,
                )
            )
            return {"completed": 0, "incomplete": 1}.get(done.status, 2)
        if args.command == "compare":
            result = service.compare(args.before, args.after)
            print(result.model_dump_json(indent=2))
            return 0
        for record in service.list_audits(100):
            print(
                f"{record.audit_id}  {record.status:11s} {record.domain}  {record.created_at:%Y-%m-%d %H:%M}"
            )
        return 0
    except ServiceError as exc:
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
