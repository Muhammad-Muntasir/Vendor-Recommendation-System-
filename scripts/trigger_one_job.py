"""
trigger_one_job.py — Trigger scoring for ONE job at a time with a delay.

Triggers each job 30 seconds apart to avoid Gemini API rate limits.
Usage:
    python scripts/trigger_one_job.py
"""
import json, time, boto3
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
    jobs = table.scan().get('Items', [])
    pending = [j for j in jobs if j.get('status') == 'Pending']

    if not pending:
        print("No pending jobs found.")
        return

    print(f"Found {len(pending)} pending jobs. Triggering one at a time (30s apart)...")

    for i, job in enumerate(pending):
        detail = json.dumps(dict(job), cls=DecimalEncoder)
        resp = eb.put_events(Entries=[{
            'Source': 'retailfixit.jobs',
            'DetailType': 'JobCreated',
            'Detail': detail,
            'EventBusName': 'default'
        }])
        failed = resp.get('FailedEntryCount', 0)
        print(f"  {'OK' if not failed else 'FAILED'} - Job {str(job['jobId'])[:8]}... ({job.get('type')} @ {job.get('location')})")

        if i < len(pending) - 1:
            print(f"  Waiting 35 seconds before next job...")
            time.sleep(35)

    print("\nAll jobs triggered. Check the Recommendations page.")

if __name__ == '__main__':
    main()
