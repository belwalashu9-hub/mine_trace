"""Ingestion service orchestrating data extraction, raw persistence, cleaning, and storage."""
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.repository import MineTraceRepository
from app.ingestion.comtrade_client import ComtradeClient, ComtradeAPIError
from app.ingestion.ofac_client import OfacClient, OfacAPIError
from app.ingestion.cleaning import clean_comtrade_record, clean_ofac_record

settings = get_settings()


class IngestionService:
    """Service orchestrating ingestion runs with audit logging, deduplication, and quality tracking."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = MineTraceRepository(db)
        self.comtrade_client = ComtradeClient()
        self.ofac_client = OfacClient()

    def ingest_trade_data(
        self,
        commodity_codes: Optional[List[str]] = None,
        periods: Optional[List[str]] = None,
        fixture_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs the UN Comtrade trade data ingestion pipeline."""
        codes = commodity_codes or settings.default_commodity_codes
        source_name = "UN_COMTRADE"
        source_url = self.comtrade_client.base_url

        self.repo.get_or_create_data_source(
            source_name=source_name,
            source_url=source_url,
            description="United Nations Comtrade Database - Critical Mineral Flows",
        )

        params_summary = json.dumps({"commodity_codes": codes, "periods": periods, "fixture": fixture_path})
        run = self.repo.create_ingestion_run(
            source_name=source_name,
            run_type="FIXTURE" if fixture_path else "API",
            parameters=params_summary,
        )

        raw_count = 0
        clean_count = 0
        error_count = 0
        warning_count = 0

        try:
            # 1. Fetch raw payload (from live API or fixture)
            if fixture_path:
                fetch_res = self.comtrade_client.load_from_fixture(fixture_path)
            else:
                fetch_res = self.comtrade_client.fetch_trade_data(
                    commodity_codes=codes,
                    periods=periods,
                )

            records = fetch_res.get("data", [])
            retrieval_ts = fetch_res.get("retrieval_timestamp", datetime.now(timezone.utc))

            # 2. Process each raw record
            for raw_rec in records:
                raw_count += 1
                rec_id = str(raw_rec.get("id") or raw_rec.get("refId") or "") or None

                # Store unaltered raw record
                raw_db_rec = self.repo.save_raw_trade_record(
                    ingestion_run_id=run.id,
                    source_record_id=rec_id,
                    commodity_code=str(raw_rec.get("cmdCode") or raw_rec.get("commodity_code") or ""),
                    period=str(raw_rec.get("period") or ""),
                    reporter_code=str(raw_rec.get("reporterCode") or ""),
                    partner_code=str(raw_rec.get("partnerCode") or ""),
                    raw_payload=json.dumps(raw_rec),
                    retrieval_timestamp=retrieval_ts,
                )

                # Clean and validate
                norm_data, issues = clean_comtrade_record(
                    raw=raw_rec,
                    retrieval_timestamp=retrieval_ts,
                    source_record_id=rec_id,
                )

                # Log quality issues
                for issue in issues:
                    if issue["severity"] == "ERROR":
                        error_count += 1
                    else:
                        warning_count += 1

                    self.repo.log_quality_issue(
                        ingestion_run_id=run.id,
                        source_record_id=rec_id,
                        table_name="raw_trade_records",
                        severity=issue["severity"],
                        issue_type=issue["issue_type"],
                        column_name=issue.get("column_name"),
                        raw_value=issue.get("raw_value"),
                        message=issue["message"],
                    )

                # Deduplicate and store normalized record if valid
                if norm_data is not None:
                    norm_data["raw_record_id"] = raw_db_rec.id
                    norm_data["ingestion_run_id"] = run.id
                    _, created = self.repo.save_normalized_trade_record(norm_data)
                    if created:
                        clean_count += 1
                    else:
                        warning_count += 1
                        self.repo.log_quality_issue(
                            ingestion_run_id=run.id,
                            source_record_id=rec_id,
                            table_name="normalized_trade_records",
                            severity="INFO",
                            issue_type="DUPLICATE_RECORD",
                            message=f"Duplicate trade record skipped (hash: {norm_data['record_hash'][:12]}...)",
                        )

            # Mark run success
            self.repo.finish_ingestion_run(
                run_id=run.id,
                status="COMPLETED",
                raw_count=raw_count,
                clean_count=clean_count,
                error_count=error_count,
                warning_count=warning_count,
            )
            self.repo.update_data_source_status(
                source_name=source_name,
                status="COMPLETED",
                successful=True,
                records_added=clean_count,
            )

            # Phase 5: Audit Event
            try:
                from app.audit.service import AuditEventService
                from app.evidence.rules import EVENT_TRADE_INGESTION_COMPLETED
                AuditEventService(self.db).record_event(
                    event_type=EVENT_TRADE_INGESTION_COMPLETED,
                    related_record_id=str(run.id),
                    operation_status="SUCCESS",
                    metadata={"clean_count": clean_count, "raw_count": raw_count, "source": source_name},
                )
            except Exception:
                pass

            return {
                "run_id": run.id,
                "source_name": source_name,
                "status": "COMPLETED",
                "raw_records_count": raw_count,
                "clean_records_count": clean_count,
                "error_count": error_count,
                "warning_count": warning_count,
                "message": f"Successfully ingested {clean_count} new trade records ({raw_count} raw inspected).",
            }

        except Exception as exc:
            logger.error(f"Trade ingestion failed: {exc}", exc_info=True)
            self.repo.finish_ingestion_run(
                run_id=run.id,
                status="FAILED",
                raw_count=raw_count,
                clean_count=clean_count,
                error_count=error_count + 1,
                warning_count=warning_count,
                error_message=str(exc),
            )
            self.repo.update_data_source_status(
                source_name=source_name,
                status="FAILED",
                successful=False,
            )
            raise

    def ingest_sanctions_data(
        self,
        fixture_path: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs the OFAC Sanctions data ingestion pipeline."""
        source_name = "OFAC_SDN"
        target_url = source_url or self.ofac_client.sdn_url

        self.repo.get_or_create_data_source(
            source_name=source_name,
            source_url=target_url,
            description="US Treasury OFAC Specially Designated Nationals (SDN) List",
        )

        params_summary = json.dumps({"source_url": target_url, "fixture": fixture_path})
        run = self.repo.create_ingestion_run(
            source_name=source_name,
            run_type="FIXTURE" if fixture_path else "LIVE",
            parameters=params_summary,
        )

        raw_count = 0
        clean_count = 0
        error_count = 0
        warning_count = 0

        try:
            if fixture_path:
                fetch_res = self.ofac_client.load_from_fixture(fixture_path)
            else:
                fetch_res = self.ofac_client.fetch_sdn_list(custom_url=target_url)

            rows = fetch_res.get("data", [])
            retrieval_ts = fetch_res.get("retrieval_timestamp", datetime.now(timezone.utc))

            for row in rows:
                raw_count += 1
                norm_data, issues = clean_ofac_record(raw_row=row, retrieval_timestamp=retrieval_ts)

                for issue in issues:
                    if issue["severity"] == "ERROR":
                        error_count += 1
                    else:
                        warning_count += 1

                    self.repo.log_quality_issue(
                        ingestion_run_id=run.id,
                        source_record_id=str(row.get("Ent_num") or ""),
                        table_name="ofac_sanctions_records",
                        severity=issue["severity"],
                        issue_type=issue["issue_type"],
                        column_name=issue.get("column_name"),
                        raw_value=issue.get("raw_value"),
                        message=issue["message"],
                    )

                if norm_data is not None:
                    norm_data["ingestion_run_id"] = run.id
                    _, created = self.repo.save_ofac_sanction_record(norm_data)
                    if created:
                        clean_count += 1
                    else:
                        warning_count += 1

            self.repo.finish_ingestion_run(
                run_id=run.id,
                status="COMPLETED",
                raw_count=raw_count,
                clean_count=clean_count,
                error_count=error_count,
                warning_count=warning_count,
            )
            self.repo.update_data_source_status(
                source_name=source_name,
                status="COMPLETED",
                successful=True,
                records_added=clean_count,
            )

            # Phase 5: Audit Event
            try:
                from app.audit.service import AuditEventService
                from app.evidence.rules import EVENT_SANCTIONS_INGESTION_COMPLETED
                AuditEventService(self.db).record_event(
                    event_type=EVENT_SANCTIONS_INGESTION_COMPLETED,
                    related_record_id=str(run.id),
                    operation_status="SUCCESS",
                    metadata={"clean_count": clean_count, "raw_count": raw_count, "source": "OFAC_SDN"},
                )
            except Exception:
                pass

            return {
                "run_id": run.id,
                "source_name": source_name,
                "status": "COMPLETED",
                "raw_records_count": raw_count,
                "clean_records_count": clean_count,
                "error_count": error_count,
                "warning_count": warning_count,
                "message": f"Successfully ingested {clean_count} new OFAC sanction records ({raw_count} parsed).",
            }

        except Exception as exc:
            logger.error(f"OFAC ingestion failed: {exc}", exc_info=True)
            self.repo.finish_ingestion_run(
                run_id=run.id,
                status="FAILED",
                raw_count=raw_count,
                clean_count=clean_count,
                error_count=error_count + 1,
                warning_count=warning_count,
                error_message=str(exc),
            )
            self.repo.update_data_source_status(
                source_name=source_name,
                status="FAILED",
                successful=False,
            )
            raise
