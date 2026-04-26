# Model Versioning — AI Vendor Recommendation System

## Version Format

Model versions follow **Semantic Versioning**: `MAJOR.MINOR.PATCH`

| Component | Meaning | Example change |
|---|---|---|
| MAJOR | Breaking change to scoring algorithm or output schema | Removing a scoring dimension |
| MINOR | New scoring dimension or significant weight change | Adding a new dimension |
| PATCH | Minor weight tuning or prompt adjustment | Adjusting a weight by <5% |

Examples: `1.0.0`, `1.1.0`, `2.0.0`

## Storage Location

The current model version is stored as a plain text file in S3:

```
s3://ai-vrs-lambda-zip/model-version.txt
```

Content: a single line containing the version string, e.g. `1.0.0`

## Propagation Flow

```
S3 (model-version.txt)
        │
        │ Read on Lambda cold start
        ▼
utils/model_version.py
  get_model_version()
        │
        │ Cached in module-level variable
        │ (reused for all warm invocations)
        ▼
handlers/vendor_scoring.py
  normalize() → ScoreFactors.modelVersion
        │
        ├─→ DynamoDB ai-vrs-recommendations
        │     Recommendation.modelVersion
        │
        └─→ DynamoDB ai-vrs-audit-log
              AuditLog.modelVersion
```

## Update Process

To deploy a new model version:

1. **Update the version file in S3:**
   ```bash
   echo -n "1.1.0" | aws s3 cp - s3://ai-vrs-lambda-zip/model-version.txt
   ```

2. **Verify the upload:**
   ```bash
   aws s3 cp s3://ai-vrs-lambda-zip/model-version.txt -
   # Should print: 1.1.0
   ```

3. **Force Lambda cold start** (new version takes effect on next cold start):
   ```bash
   aws lambda update-function-configuration \
     --function-name ai-vrs \
     --description "Model version 1.1.0 deployed $(date -u +%Y-%m-%dT%H:%M:%SZ)"
   ```

4. **Verify in CloudWatch logs** — look for log entries showing the new version being read from S3.

5. **Monitor** — watch `RecommendationConfidenceDistribution` and `HighOverrideRate` metrics for 24–48 hours after deployment.

## Querying by Version

To find all recommendations produced by a specific model version, use the `modelVersion-index` GSI on the `ai-vrs-recommendations` table:

```python
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('ai-vrs-recommendations')

response = table.query(
    IndexName='modelVersion-index',
    KeyConditionExpression=Key('modelVersion').eq('1.0.0')
)
recommendations = response['Items']
```

Similarly, audit logs can be queried by `modelVersion` using a scan with a filter expression.

## Rollback Procedure

If a new model version produces unexpected results:

1. **Revert the S3 file** to the previous version:
   ```bash
   echo -n "1.0.0" | aws s3 cp - s3://ai-vrs-lambda-zip/model-version.txt
   ```

2. **Force Lambda cold start** (same as step 3 in Update Process above).

3. **Verify** — new recommendations should show the previous `modelVersion`.

4. **Investigate** — use the `modelVersion-index` GSI to compare recommendation quality between versions.

Note: Existing recommendations in DynamoDB retain their original `modelVersion` — rollback only affects new recommendations. Both versions coexist in the audit log, which is the intended behavior (Requirement 14.5).

## Fallback Version

If the S3 read fails for any reason (network error, missing file, invalid format), `utils/model_version.py` falls back to `"0.0.0"` and logs a warning to CloudWatch. This ensures the scoring pipeline never fails due to a missing version file.
