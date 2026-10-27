"""Capture actual API outputs against a disposable synthetic database."""
import json
import tempfile
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.database.connection import get_engine, get_db
from app.main import app
from scripts.model2_demo import run_demo
if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'demo.sqlite';demo=run_demo(path)
        engine=get_engine('sqlite:///'+str(path));db=sessionmaker(bind=engine)()
        app.dependency_overrides[get_db]=lambda:db
        client=TestClient(app)
        route='route_red_sea_suez_minerals'
        samples={}
        for endpoint in ['status','news','events','routes','dashboard/summary',f'routes/{route}/impact',f'routes/{route}/feasibility',f'routes/{route}/alternatives',f'routes/{route}/explanation']:
            response=client.get('/api/v1/live/'+endpoint)
            if response.status_code != 200:raise RuntimeError(response.text)
            samples[endpoint]={'http_status':response.status_code,'body':response.json()}
        Path('docs/api-samples.json').write_text(json.dumps({'synthetic':True,'samples':samples},indent=2))
        app.dependency_overrides.clear();db.close();engine.dispose()
    print('Captured 9 API responses to docs/api-samples.json')
