"""Isolated synthetic demonstration. Never opens the main application database."""
import argparse
import json
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from app.database.connection import get_engine, init_db
from app.database.models import TransportRoute, GeopoliticalEvent, R6RiskAssessment
from app.geospatial.routes_seed import seed_transport_routes
from app.geopolitical.ingestion_service import GDELTIngestionService
from app.geopolitical.classification_service import EventClassificationService
from app.geospatial.matching_engine import GeographicMatchingEngine
from app.risk.r6_engine import R6GeopoliticalRiskEngine
from app.routing.feasibility_engine import RouteFeasibilityEngine

def run_demo(path):
    engine=get_engine('sqlite:///'+str(path.resolve()));init_db(engine)
    with sessionmaker(bind=engine)() as db:
        seed_transport_routes(db)
        route=db.query(TransportRoute).filter_by(route_id='route_red_sea_suez_minerals').one()
        baseline=RouteFeasibilityEngine(db).assess_route_feasibility(route).operability_status
        article={'url':'https://synthetic.example/demo-red-sea','title':'SYNTHETIC DEMO: Maritime security incident at Bab el-Mandeb affects cobalt shipping','seendate':'20261027T120000Z','domain':'synthetic.example'}
        ingestion=GDELTIngestionService(db).ingest_articles([article],run_type='FIXTURE',category='SYNTHETIC_DEMO')
        classification=EventClassificationService(db).process_pending_articles(include_synthetic=True)
        matched=GeographicMatchingEngine(db).evaluate_all_active_events()
        R6GeopoliticalRiskEngine(db).assess_all_exposure_matches()
        feas=RouteFeasibilityEngine(db).assess_route_feasibility(route)
        scores=db.query(R6RiskAssessment).all()
        return {'synthetic':True,'baseline':baseline,'ingestion':ingestion.model_dump(mode='json'),
            'classification':classification.model_dump(mode='json'),'matches':matched,
            'assessments':[{'level':s.risk_level,'score':s.heuristic_score,'explanation':s.calculation_explanation,'sources':json.loads(s.source_evidence)} for s in scores],
            'operability':feas.operability_status,'feasibility':feas.shipment_feasibility,
            'alternative':feas.alternative_route_name,'limitations':feas.limitations_disclaimer}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--reset',action='store_true');args=parser.parse_args()
    path=Path('data/model2_demo.sqlite')
    if args.reset and path.exists(): path.unlink()
    output=run_demo(path)
    Path('docs').mkdir(exist_ok=True)
    Path('docs/demo-output.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(output,indent=2))
