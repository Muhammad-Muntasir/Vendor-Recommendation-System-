import pathlib

cors_old = '"Access-Control-Allow-Origin": "*",'
cors_new = (
    '"Access-Control-Allow-Origin": "*",\n'
    '            "Access-Control-Allow-Headers": "Authorization,Content-Type",\n'
    '            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",'
)

files = [
    'backend/lambda/handlers/query.py',
    'backend/lambda/handlers/override.py',
]

for fp in files:
    p = pathlib.Path(fp)
    txt = p.read_text(encoding='utf-8')
    if cors_old in txt and 'Access-Control-Allow-Headers' not in txt:
        p.write_text(txt.replace(cors_old, cors_new), encoding='utf-8')
        print('Fixed CORS in', fp)
    else:
        print('Skipped (already fixed or not found):', fp)
