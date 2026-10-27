"""Periodic monitoring with a SQLite lease shared by API and scheduler workers."""
import os
import json
import time
import uuid
import threading
from sqlalchemy import text
from app.database.connection import SessionLocal
from app.database.models import utc_now, Model2SyncStatus
from app.geopolitical.ingestion_service import GDELTIngestionService
from app.geopolitical.classification_service import EventClassificationService
from app.geospatial.routes_seed import seed_transport_routes
from app.geospatial.matching_engine import GeographicMatchingEngine
from app.risk.r6_engine import R6GeopoliticalRiskEngine
from app.routing.feasibility_engine import RouteFeasibilityEngine

def enabled(name, default='false'):
    return os.getenv(name, default).lower() == 'true'

class Model2MonitoringScheduler:
    _stop = threading.Event()
    _thread = None
    _last_sync_status = 'NEVER_RUN'
    _last_sync_timestamp = None
    _last_success = None
    _is_online = None
    _last_sync_metrics = {}
    _is_running = False

    @classmethod
    def get_status(cls):
        return dict(model2_enabled=enabled('MODEL2_ENABLED','true'),
                    auto_sync_enabled=enabled('MODEL2_AUTO_SYNC'),
                    sync_interval_minutes=max(1,int(os.getenv('MODEL2_SYNC_INTERVAL_MINUTES','15'))),
                    last_sync_status=cls._last_sync_status, last_sync_timestamp=cls._last_sync_timestamp,
                    last_successful_sync=cls._last_success, is_online_mode=cls._is_online,
                    is_syncing_now=cls._is_running,last_metrics=cls._last_sync_metrics)

    @classmethod
    def execute_full_pipeline(cls, source='live', fixture_path=None, category=None, max_records=25, db=None, periodic=False):
        if source not in ('live','offline','fixture'): raise ValueError('Unsupported source')
        if source == 'fixture' and not enabled('MODEL2_ALLOW_DEMO_MODE'): raise ValueError('Demo requires isolated demo configuration')
        owned = db is None
        db = db or SessionLocal()
        owner = uuid.uuid4().hex
        now = time.time()
        # Atomic UPSERT permits one active sync across processes sharing the same SQLite DB.
        result = db.execute(text('''INSERT INTO model2_monitoring_lease(name,owner,expires_at)
            VALUES ('pipeline',:owner,:expires) ON CONFLICT(name) DO UPDATE SET
            owner=:owner,expires_at=:expires WHERE expires_at < :now'''),
            dict(owner=owner,expires=now+900,now=now))
        db.commit()
        if result.rowcount == 0:
            if owned: db.close()
            return {'status':'BUSY'}
        cls._is_running = True
        metrics = {'started_at':utc_now().isoformat(),'source_mode':source}
        try:
            if periodic:
                last = db.query(Model2SyncStatus).filter_by(source_mode='live').order_by(Model2SyncStatus.id.desc()).first()
                if last:
                    from datetime import timezone
                    age = (utc_now()-last.completed_at.replace(tzinfo=timezone.utc)).total_seconds()
                    if age < max(60,float(os.getenv('MODEL2_SYNC_INTERVAL_MINUTES','15'))*60):
                        metrics['status'] = 'SKIPPED_FRESH'
                        return metrics
            seed_transport_routes(db)
            failed = False
            if source != 'offline':
                ingest = GDELTIngestionService(db)
                if source == 'fixture':
                    if not fixture_path: raise ValueError('Fixture path is required')
                    summary = ingest.ingest_from_fixture(fixture_path, category)
                else:
                    summary = ingest.ingest_from_live(category=category,max_records=max_records,custom_query=os.getenv("GDELT_QUERY") or None)
                metrics['ingestion'] = summary.model_dump(mode='json')
                failed = summary.status == 'FAILED'
                if source == 'live':
                    cls._is_online = not failed
                    if not failed: cls._last_success = utc_now().isoformat()
            classified = EventClassificationService(db).process_pending_articles(limit=1000, include_synthetic=(source == "fixture"))
            if classified.status == 'FAILED': raise RuntimeError(classified.error_message)
            metrics['classification'] = classified.model_dump(mode='json')
            metrics['route_matches'] = GeographicMatchingEngine(db).evaluate_all_active_events()
            metrics['r6_assessments'] = R6GeopoliticalRiskEngine(db).assess_all_exposure_matches()
            metrics['routes_evaluated'] = RouteFeasibilityEngine(db).assess_all_routes()
            metrics['status'] = 'DEGRADED_CACHED' if failed else 'COMPLETED'
        except Exception as exc:
            db.rollback()
            metrics.update(status='FAILED',error_message=str(exc))
        finally:
            db.execute(text("DELETE FROM model2_monitoring_lease WHERE name='pipeline' AND owner=:owner"),{'owner':owner})
            if metrics["status"] != "SKIPPED_FRESH":
                db.add(Model2SyncStatus(source_mode=source,status=metrics["status"],metrics=json.dumps(metrics)))
            db.commit()
            if owned: db.close()
            cls._is_running = False
            cls._last_sync_status = metrics['status']
            cls._last_sync_timestamp = utc_now().isoformat()
            metrics['completed_at'] = cls._last_sync_timestamp
            cls._last_sync_metrics = metrics
        return metrics

    @classmethod
    def start(cls):
        if not enabled('MODEL2_ENABLED','true') or not enabled('MODEL2_AUTO_SYNC'): return
        if cls._thread and cls._thread.is_alive(): return
        cls._stop.clear()
        def loop():
            interval = max(60,float(os.getenv('MODEL2_SYNC_INTERVAL_MINUTES','15'))*60)
            while not cls._stop.is_set():
                try: cls.execute_full_pipeline(periodic=True,max_records=min(250,max(1,int(os.getenv('MODEL2_MAX_ARTICLES_PER_RUN','100')))))
                except Exception:
                    from app.core.logging import logger
                    logger.exception('Monitoring iteration failed')
                cls._stop.wait(interval)
        cls._thread = threading.Thread(target=loop,name='minetrace-monitor',daemon=True)
        cls._thread.start()

    @classmethod
    def stop(cls):
        cls._stop.set()
        if cls._thread: cls._thread.join()
