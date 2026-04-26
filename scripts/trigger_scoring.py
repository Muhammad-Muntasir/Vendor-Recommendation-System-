"""
trigger_scoring.py — Manually trigger the scoring pipeline for all pending jobs.

Publishes a JobCreated_Event to EventBridge for each Pending job in DynamoDB.
EventBridge routes it to SQS → Lambda → vendor scoring pipeline.

Usage:
    python scripts/trigger_scoring.py
"""
import json
import boto3
from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def main():
    region = 'us-east-1'
    dynamodb = boto3.resource('dynamodb', region_name=region)
    eb = boto3.client('events', region_name=region)

    table = dynamodb.Table('ai-vrs-jobs')
    response = table.scan()
    jobs = response.get('Items', [])

    pending = [j for j in jobs if j.get('status') == 'Pending']
    print(f"Found {len(pending)} pending jobs. Triggering scoring pipeline...")

    for job in pending:
        detail = json.dumps(dict(job), cls=DecimalEncoder)
        resp = eb.put_events(Entries=[{
            'Source': 'retailfixit.jobs',
            'DetailType': 'JobCreated',
            'Detail': detail,
            'EventBusName': 'default'
        }])
        failed = resp.get('FailedEntryCount', 0)
        status = 'OK' if failed == 0 else 'FAILED'
        print(f"  {status} - Job {str(job['jobId'])[:8]}... ({job.get('type', '?')} @ {job.get('location', '?')})")

    print("\nDone. Wait ~10 seconds then refresh the Recommendations page.")

if __name__ == '__main__':
    main()
