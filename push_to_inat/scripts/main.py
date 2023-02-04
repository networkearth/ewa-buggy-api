"""
Batch Job Definition
"""

import os
import json
import click
import boto3
import requests

from gluon.inaturalist import client as inaturalist_client
from gluon.kobo import client as kobo_client

# pylint: disable=invalid-name
def get_job_data(email, s3, bucket):
    """
    Grabs the data on the job stored in s3
    """
    bucket = s3.Bucket(bucket)
    objects = list(bucket.objects.filter(Prefix=email))
    if not objects:
        return tuple([None] * 9)

    instances = set()

    objects_to_delete = []
    # pylint: disable=redefined-builtin
    for object in objects:
        objects_to_delete.append(object)
        content = json.loads(object.get()['Body'].read().decode('utf-8'))
        kobo_username = content['kobo_username']
        kobo_password = content['kobo_password']
        kobo_uid = content['kobo_uid']
        inat_username = content['inaturalist_email']
        inat_password = content['inaturalist_password']
        inat_client_id = content['client_id']
        inat_client_secret = content['client_secret']
        instances.update(content['instances'])

    return (
        kobo_username, kobo_password, kobo_uid, inat_username, inat_password,
        inat_client_id, inat_client_secret, instances, objects_to_delete
    )

def get_submissions(api_url, username, password, uid, email, instances):
    """
    Gets the relevant submissions from the API
    """
    payload = {
        'kobo_username': username,
        'kobo_password': password,
        'kobo_uid': uid,
        'email': email,
    }
    api_url = '/'.join([
        api_url,
        'submissions'
    ])
    response = requests.get(api_url, json=payload, timeout=60)
    submissions = [
        submission for submission in response.json()
        if submission['instance'] in instances
    ]
    return submissions

def get_clients(
    kobo_username, kobo_password, inat_username,
    inat_password, inat_client_id, inat_client_secret,
    inat_api, inat_webapp
):
    """
    Builds the kobo and iNaturalist clients
    """
    kobo = kobo_client.KoboClient(kobo_username, kobo_password)
    inaturalist = inaturalist_client.iNaturalistClient(
        inat_username, inat_password, inat_client_id,
        inat_client_secret, api_url=inat_api,
        app_url=inat_webapp
    )
    return kobo, inaturalist

def pull_images(kobo, kobo_uid, record):
    """
    Pulls the image data for a specific submission
    and stores it to disc
    """
    image_paths = []
    instance = record['instance']
    for image in record['images']:
        image_path = f'{kobo_uid}_{instance}_{image}'
        kobo.pull_image(
            image_path, kobo_uid, instance, image
        )
        image_paths.append(image_path)
    return image_paths

# pylint: disable=invalid-name
def backup_record(kobo, kobo_uid, record, image_paths, s3, backup_bucket):
    """
    Backs up the kobo record to s3
    """
    instance = record['instance']
    kobo_record = kobo.pull_instance(kobo_uid, instance)
    s3.put_object(
        Body=json.dumps(kobo_record, indent=4, sort_keys=True),
        Bucket=backup_bucket,
        Key='/'.join([str(kobo_uid), str(instance) + '.json'])
    )

    for image_path in image_paths:
        with open(image_path, 'rb') as file:
            s3.put_object(
                Body=file.read(),
                Bucket=backup_bucket,
                Key='/'.join([str(kobo_uid), str(instance), image_path.split('_')[-1] + '.jpg'])
            )

def upload_to_inat(inaturalist, record, image_paths):
    """
    Runs the upload to iNaturalist
    """
    observation_id = inaturalist.upload_base_observation(
        record['taxa'],
        record['longitude'],
        record['latitude'],
        record['ts'],
        record['positional_accuracy'],
        record['notes']
    )

    # attach the images
    for image_path in image_paths:
        inaturalist.attach_image(
            observation_id, image_path
        )

    # attach the observation field values
    for field_id, value in record['observation_fields'].items():
        inaturalist.attach_observation_field(
            observation_id, int(field_id), value
        )


@click.command()
@click.option('-e', '--email', required=True, help='email to do uploads for')
@click.option('-b', '--bucket', required=True, help='bucket to look for jobs in')
@click.option('-bb', '--backup_bucket', required=True, help='bucket to backup kobo records to')
@click.option('-ia', '--inat_api', required=True, help='inat api url')
@click.option('-iw', '--inat_webapp', required=True, help='inat webapp url')
def main(email, bucket, backup_bucket, inat_api, inat_webapp):
    """
    Batch Job Click Function
    """
    api_url = os.environ['API_URL']

    # pylint: disable=invalid-name
    s3 = boto3.resource('s3')

    (
        kobo_username, kobo_password, kobo_uid, inat_username, inat_password,
        inat_client_id, inat_client_secret, instances, objects_to_delete
    ) = get_job_data(email, s3, bucket)

    if kobo_username is None:
        return

    submissions = get_submissions(
        api_url,
        kobo_username,
        kobo_password,
        kobo_uid,
        email,
        instances
    )

    kobo, inaturalist = get_clients(
        kobo_username, kobo_password, inat_username,
        inat_password, inat_client_id, inat_client_secret,
        inat_api, inat_webapp
    )

    # pylint: disable=invalid-name
    s3 = boto3.client('s3')
    for record in submissions:
        #if not record['is_valid']: continue

        # start by downloading the images
        image_paths = pull_images(
            kobo, kobo_uid, record
        )

        # backup the record
        backup_record(
            kobo, kobo_uid, record,
            image_paths, s3, backup_bucket
        )

        # upload the record
        upload_to_inat(
            inaturalist, record, image_paths
        )

        # delete the record
        kobo.delete_instance(kobo_uid, record['instance'])

    # delete the jobs
    # pylint: disable=redefined-builtin
    for object in objects_to_delete:
        object.delete()

if __name__ == '__main__':
    # pylint: disable=no-value-for-parameter
    main()
