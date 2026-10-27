import json
import time
from datetime import timedelta
import pytest
from sqlalchemy import text
from app.database.models import *
from app.database.connection import init_db
from app.geospatial.routes_seed import seed_transport_routes
from app.geospatial.haversine import point_to_linestring_distance_km
from app.geopolitical.location_extractor import LocationExtractor
from app.geopolitical.event_classifier import EventClassifier
from app.geopolitical.normalizer import normalize_gdelt_article,parse_gdelt_seendate
from app.geopolitical.ingestion_service import GDELTIngestionService
from app.geopolitical.scheduler import Model2MonitoringScheduler as Scheduler
from app.routing.feasibility_engine import RouteFeasibilityEngine
from app.routing.network_graph import TransportNetworkGraph

@pytest.mark.parametrize('coords',[[[179,0],[-179,0]], [[-179,0],[179,0]]])
def test_dateline(coords):
    assert point_to_linestring_distance_km(0,180,coords) < 0.001
    assert point_to_linestring_distance_km(0,0,coords) > 19000

@pytest.mark.parametrize('coords',[[],[[0,0]],[[181,0],[0,0]],[[0,91],[0,0]],[[float('nan'),0],[0,0]],[[0],[0,0]]])
def test_bad_geometry(coords):
    with pytest.raises(ValueError):point_to_linestring_distance_km(0,0,coords)

def test_segment_interior_not_sampling():
    assert point_to_linestring_distance_km(0,0.123,[[0,0],[1,0]]) < .0001

@pytest.mark.parametrize('title',['Mining strike reported','China condemns conflict in Ukraine','News from Russia and Chile'])
def test_ambiguous_country(title):
    assert LocationExtractor.extract_location(title=title,source_country='United States')['affected_country'] is None

def test_headline_not_official():
    event=EventClassifier.classify_article({'title':'Official statement: port closed in Durban','source_url':'https://example.org/news'})
    assert event['verification_status']=='REPORTED'
    assert event['publication_date'] is None
    assert event['event_date'] is None

@pytest.mark.parametrize('url',['javascript:alert(1)','file:///etc/passwd','ftp://example.org/x'])
def test_untrusted_link(url):
    assert normalize_gdelt_article({'title':'test','url':url}) is None

def test_timestamp_utc():
    assert parse_gdelt_seendate('2026-10-27T12:00:00+05:30')=='2026-10-27T06:30:00Z'

def test_lease_prevents_duplicate(test_db):
    test_db.add(MonitoringLease(name='pipeline',owner='other',expires_at=time.time()+100));test_db.commit()
    assert Scheduler.execute_full_pipeline(source='offline',db=test_db)['status']=='BUSY'

def test_pipeline_does_not_contact_live_offline(test_db,monkeypatch):
    monkeypatch.setattr(GDELTIngestionService,'ingest_from_live',lambda *a,**k:pytest.fail('Offline made network call'))
    assert Scheduler.execute_full_pipeline(source='offline',db=test_db)['status']=='COMPLETED'
    assert test_db.query(MonitoringLease).count()==0

def test_ingestion_failure_preserves_cache(test_db,monkeypatch):
    from types import SimpleNamespace
    class Failure:
        status='FAILED'
        def model_dump(self,**kwargs):return {'status':'FAILED'}
    monkeypatch.setattr(GDELTIngestionService,'ingest_from_live',lambda *a,**k:Failure())
    result=Scheduler.execute_full_pipeline(db=test_db)
    assert result['status']=='DEGRADED_CACHED'
    assert Scheduler.get_status()['is_online_mode'] is False

def test_advisory_expiry_and_closure(test_db):
    seed_transport_routes(test_db)
    route=test_db.query(TransportRoute).filter_by(route_id='route_red_sea_suez_minerals').one()
    advice=RouteOperationalEvidence(route_id=route.id,source_url='https://authority.example/advisory',authority='TEST AUTHORITY',
        statement='SYNTHETIC: passage closed',status='CLOSED',verified_by='TEST reviewer',affected_hubs='["Bab el-Mandeb"]',valid_until=utc_now()+timedelta(hours=1))
    test_db.add(advice);test_db.commit()
    result=RouteFeasibilityEngine(test_db).assess_route_feasibility(route)
    assert result.operability_status=='CONFIRMED_CLOSED'
    assert 'cape_of_good_hope' in result.alternative_route_name
    assert result.shipment_feasibility!='VERIFIED_OPTION_AVAILABLE'
    advice.valid_until=utc_now()-timedelta(seconds=1);test_db.commit()
    assert RouteFeasibilityEngine(test_db).assess_route_feasibility(route).operability_status=='NO_IDENTIFIED_ALERT'

def test_same_endpoint_alternative():
    alternative=TransportNetworkGraph().find_candidate_alternative('route_red_sea_suez_minerals',blocked_hubs=['Bab el-Mandeb Strait'])
    assert alternative['waypoints'][0]=='gulf_of_aden'
    assert alternative['waypoints'][-1]=='europe_med_hub'
    assert 'bab_el_mandeb' not in alternative['waypoints']

def test_no_alternative_to_closed_destination():
    assert TransportNetworkGraph().find_candidate_alternative('route_cod_durban_cobalt',blocked_hubs=['Port of Durban']) is None

def test_migration_twice_preserves_model1(test_db):
    test_db.add(OfacSanctionRecord(record_hash="preserve",source_record_id="123",primary_name="SYNTHETIC TEST"));test_db.commit()
    before={t:test_db.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in ['normalized_trade_records','ofac_sanctions_records']}
    init_db(test_db.bind);init_db(test_db.bind)
    assert before=={t:test_db.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in before}

@pytest.mark.asyncio
async def test_end_to_end_api(async_client,test_db,tmp_path,monkeypatch):
    from scripts.model2_demo import run_demo
    result=run_demo(tmp_path/'isolated.sqlite')
    assert result['synthetic'] and result['operability']=='AT_RISK'
    article={'url':'https://synthetic.example/attack','title':'SYNTHETIC: maritime security incident at Bab el-Mandeb affects cobalt shipping','seendate':'20261027T120000Z'}
    service=GDELTIngestionService(test_db)
    assert service.ingest_articles([article],category='TEST').inserted_count==1
    assert service.ingest_articles([article],category='TEST2').duplicate_count==1
    response=await async_client.post('/api/v1/live/sync?source=offline')
    assert response.status_code==200 and response.json()['result']['status']=='COMPLETED'
    route='route_red_sea_suez_minerals'
    for suffix in ['events','routes',f'routes/{route}/impact',f'routes/{route}/feasibility',f'routes/{route}/alternatives',f'routes/{route}/explanation','dashboard/summary']:
        r=await async_client.get('/api/v1/live/'+suffix)
        assert r.status_code==200,(suffix,r.text)
    assert (await async_client.post('/api/v1/live/routes/import',json={})).status_code==403

@pytest.mark.asyncio
async def test_llm_output_cannot_invent_claim(async_client,test_db,monkeypatch):
    from app.rag.ollama_service import OllamaService
    seed_transport_routes(test_db)
    monkeypatch.setattr(OllamaService,'generate',lambda *a,**k:'Shipment guaranteed: $10')
    result=(await async_client.get('/api/v1/live/routes/route_cod_durban_cobalt/explanation?use_llm=true')).json()
    assert result['mode']=='DETERMINISTIC'
    assert '$10' not in str(result)

def test_fixture_excluded_from_live_classification(test_db):
    from app.geopolitical.classification_service import EventClassificationService
    GDELTIngestionService(test_db).ingest_articles([{'url':'https://synthetic.example/fixture','title':'SYNTHETIC: war in Yemen'}],run_type='FIXTURE')
    assert EventClassificationService(test_db).process_pending_articles().articles_processed==0
    assert EventClassificationService(test_db).process_pending_articles(include_synthetic=True).articles_processed==1

@pytest.mark.asyncio
async def test_new_route_never_verified_by_default(async_client):
    rows=(await async_client.get('/api/v1/live/routes')).json()['routes']
    assert rows and all(r['shipment_feasibility']=='UNKNOWN' for r in rows)

def test_scheduler_lifecycle(monkeypatch):
    import threading
    hit=threading.Event()
    monkeypatch.setenv('MODEL2_AUTO_SYNC','true')
    monkeypatch.setattr(Scheduler,'execute_full_pipeline',lambda **kwargs:hit.set())
    Scheduler.start();first=Scheduler._thread;Scheduler.start()
    assert Scheduler._thread is first and hit.wait(2)
    Scheduler.stop();assert not first.is_alive()

@pytest.mark.parametrize('value',['[70,45,25]','[0,45,70]','[25,45]','[25,45,101]'])
def test_invalid_risk_policy(monkeypatch,value):
    from app.risk.model2_policy import thresholds
    monkeypatch.setenv('MODEL2_RISK_THRESHOLDS',value)
    with pytest.raises(ValueError): thresholds()

@pytest.mark.asyncio
async def test_route_import_and_review_api(async_client,test_db,monkeypatch):
    monkeypatch.setenv('MODEL2_REVIEW_TOKEN','test-only-secret')
    headers={'X-Model2-Token':'test-only-secret'}
    body=dict(route_id='test_import',name='SYNTHETIC test corridor',origin='A',destination='B',mineral_relevance='cobalt',transport_mode='MARITIME',coordinates=[[179,0],[-179,0]],source='Synthetic acceptance fixture')
    assert (await async_client.post('/api/v1/live/routes/import',json=body,headers=headers)).status_code==200
    body['coordinates']=[[190,0],[0,0]]
    assert (await async_client.post('/api/v1/live/routes/import',json=body,headers=headers)).status_code==422
    advisory=dict(authority='SYNTHETIC authority',source_url='https://authority.example/closure',statement='SYNTHETIC corridor closure verified for test',verified_by='test reviewer',status='CLOSED',valid_until=(utc_now()+timedelta(hours=1)).isoformat(),affected_hubs=[])
    result=await async_client.post('/api/v1/live/routes/test_import/advisories',json=advisory,headers=headers)
    assert result.status_code==200 and result.json()['operability']=='CONFIRMED_CLOSED'

def test_second_periodic_worker_skips_recent_run(test_db,monkeypatch):
    test_db.add(Model2SyncStatus(source_mode='live',status='COMPLETED',metrics='{}'));test_db.commit()
    monkeypatch.setattr(GDELTIngestionService,'ingest_from_live',lambda *a,**k:pytest.fail('Repeated periodic fetch'))
    assert Scheduler.execute_full_pipeline(db=test_db,periodic=True)['status']=='SKIPPED_FRESH'
    assert test_db.query(Model2SyncStatus).count()==1
