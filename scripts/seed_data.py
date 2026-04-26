#!/usr/bin/env python3
"""
seed_data.py — Populate DynamoDB with realistic test data for AI-VRS.

Usage:
    python scripts/seed_data.py [--region us-east-1] [--environment production]
                                [--vendors 10] [--jobs 5] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Seed data pools
# ---------------------------------------------------------------------------

LOCATIONS = [
    "Austin, TX", "Dallas, TX", "Houston, TX", "San Antonio, TX", "Phoenix, AZ",
]

SPECIALIZATIONS_POOL = ["plumbing", "electrical", "hvac", "carpentry", "roofing", "painting"]

JOB_TYPES = ["plumbing", "electrical", "hvac", "carpentry", "roofing", "painting"]

URGENCY_WEIGHTS = [
    ("Low", 0.40),
    ("Medium", 0.30),
    ("High", 0.20),
    ("Critical", 0.10),
]

AVAILABILITY_WEIGHTS = [
    ("available", 0.60),
    ("busy", 0.30),
    ("unavailable", 0.10),
]

VENDOR_NAMES = [
    "Acme Plumbing Co.", "Bright Spark Electric", "Cool Air HVAC", "Timber Craft Carpentry",
    "Summit Roofing", "ColorPro Painting", "FastFix Services", "ProTech Solutions",
    "Elite Contractors", "Reliable Repairs Inc.", "QuickFix Pros", "AllStar Services",
    "Premier Maintenance", "TrustWorthy Trades", "Expert Hands LLC",
]


def _weighted_choice(choices: list[tuple[str, float]]) -> str:
    """Pick a value from a weighted list."""
    values, weights = zip(*choices)
    return random.choices(values, weights=weights, k=1)[0]


def _generate_vendor(index: int) -> dict:
    """Generate a single VendorProfile dict."""
    availability = _weighted_choice(AVAILABILITY_WEIGHTS)
    num_specs = random.randint(1, 3)
    specializations = random.sample(SPECIALIZATIONS_POOL, num_specs)

    return {
        "vendorId": str(uuid.uuid4()),
        "name": VENDOR_NAMES[index % len(VENDOR_NAMES)],
        "completionRate": Decimal(str(round(random.uniform(0.70, 0.98), 2))),
        "availability": availability,
        "reworkRate": Decimal(str(round(random.uniform(0.02, 0.20), 2))),
        "location": random.choice(LOCATIONS),
        "specializations": specializations,
        "avgResponseTime": Decimal(str(round(random.uniform(0.5, 12.0), 1))),
        "slaBreachCount": random.randint(0, 8),
        "activeJobs": random.randint(0, 15),
    }


def _generate_job(index: int) -> dict:
    """Generate a single JobEvent dict."""
    urgency = _weighted_choice(URGENCY_WEIGHTS)
    job_type = random.choice(JOB_TYPES)
    location = random.choice(LOCATIONS)

    # SLA deadline: 2 hours to 7 days from now
    hours_ahead = random.uniform(2, 168)
    sla_deadline = (datetime.now(timezone.utc) + timedelta(hours=hours_ahead)).isoformat()
    created_at = datetime.now(timezone.utc).isoformat()

    descriptions = {
        "plumbing": "Burst pipe requiring immediate repair in commercial kitchen.",
        "electrical": "Electrical panel upgrade needed for new equipment installation.",
        "hvac": "HVAC system failure — building temperature control required.",
        "carpentry": "Custom shelving installation for retail display area.",
        "roofing": "Roof leak repair after recent storm damage.",
        "painting": "Interior repaint for newly renovated office space.",
    }

    return {
        "jobId": str(uuid.uuid4()),
        "type": job_type,
        "location": location,
        "urgency": urgency,
        "slaDeadline": sla_deadline,
        "description": descriptions.get(job_type, "General maintenance required."),
        "createdAt": created_at,
        "schemaVersion": "1.0",
        "status": "Pending",
    }


def seed(region: str, environment: str, num_vendors: int, num_jobs: int, dry_run: bool) -> None:
    """Seed DynamoDB with vendor and job records."""
    vendors_table = f"ai-vrs-vendors"
    jobs_table = f"ai-vrs-jobs"

    vendors = [_generate_vendor(i) for i in range(num_vendors)]
    jobs = [_generate_job(i) for i in range(num_jobs)]

    if dry_run:
        print("=== DRY RUN — no writes will be made ===\n")
        print(f"Would write {len(vendors)} vendors to '{vendors_table}':")
        for v in vendors:
            print(f"  {v['vendorId'][:8]}… {v['name']} [{v['availability']}] {v['location']}")
        print(f"\nWould write {len(jobs)} jobs to '{jobs_table}':")
        for j in jobs:
            print(f"  {j['jobId'][:8]}… {j['type']} [{j['urgency']}] {j['location']}")
        return

    import boto3
    from botocore.exceptions import ClientError

    dynamodb = boto3.resource("dynamodb", region_name=region)
    vendors_tbl = dynamodb.Table(vendors_table)
    jobs_tbl = dynamodb.Table(jobs_table)

    print(f"Seeding {len(vendors)} vendors into '{vendors_table}'...")
    for vendor in vendors:
        try:
            vendors_tbl.put_item(
                Item=vendor,
                ConditionExpression="attribute_not_exists(vendorId)",
            )
            print(f"  ✓ Created vendor {vendor['vendorId'][:8]}… {vendor['name']}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                print(f"  ↷ Skipped vendor {vendor['vendorId'][:8]}… (already exists)")
            else:
                print(f"  ✗ Error writing vendor {vendor['vendorId'][:8]}…: {e}")

    print(f"\nSeeding {len(jobs)} jobs into '{jobs_table}'...")
    for job in jobs:
        try:
            jobs_tbl.put_item(
                Item=job,
                ConditionExpression="attribute_not_exists(jobId)",
            )
            print(f"  ✓ Created job {job['jobId'][:8]}… [{job['urgency']}] {job['type']} @ {job['location']}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                print(f"  ↷ Skipped job {job['jobId'][:8]}… (already exists)")
            else:
                print(f"  ✗ Error writing job {job['jobId'][:8]}…: {e}")

    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed AI-VRS DynamoDB tables with test data.")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--environment", default="production", help="Environment name (default: production)")
    parser.add_argument("--vendors", type=int, default=10, help="Number of vendor records to create (default: 10)")
    parser.add_argument("--jobs", type=int, default=5, help="Number of job records to create (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Print records without writing to DynamoDB")
    args = parser.parse_args()

    seed(
        region=args.region,
        environment=args.environment,
        num_vendors=args.vendors,
        num_jobs=args.jobs,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
