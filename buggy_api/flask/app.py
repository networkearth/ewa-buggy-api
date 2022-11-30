import os
import boto3
import json

from flask import Flask
from flask_restful import Api

from resources.submissions import Submissions
from resources.image import Image
from resources.jobs import Job

app = Flask(__name__)
api = Api(app)

app.config['ENVIRONMENT'] = os.environ['APP_ENVIRONMENT']
app.config['NAMESPACE'] = os.environ['APP_NAMESPACE']
app.config['ACCOUNT'] = os.environ['APP_ACCOUNT']
app.config['REGION'] = os.environ['APP_REGION']

SECRETS = {
    'INATURALIST_API': {
         'secret_id': 'inaturalist',
         'key': 'api'
    },
    'INATURALIST_WEBAPP': {
         'secret_id': 'inaturalist',
         'key': 'webapp'
    }
}

session = boto3.session.Session()
client = session.client(
   service_name='secretsmanager',
   region_name=app.config['REGION']
)
for key, info in SECRETS.items():
   secret_id = f'{app.config["NAMESPACE"]}-{app.config["ENVIRONMENT"]}-{info["secret_id"]}'
   response = client.get_secret_value(
      SecretId=secret_id
   )
   app.config[key] = json.loads(response['SecretString'])[info['key']]

app.config['JOB_BUCKET'] = '-'.join([
   app.config['NAMESPACE'], app.config['ENVIRONMENT'], 'job'
])
app.config['BACKUP_BUCKET'] = '-'.join([
   app.config['NAMESPACE'], app.config['ENVIRONMENT'], 'backup'
])

api.add_resource(Submissions, '/submissions')
api.add_resource(Image, '/image')
api.add_resource(Job, '/job')

if __name__ == "__main__":
   app.run(host='0.0.0.0', port=5002)