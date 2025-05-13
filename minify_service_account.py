import json

with open("service-account.json") as f:
    data = json.load(f)
print(data)  
def env_var(key):
    return key.upper().replace("-", "_")

print("# Paste these into your Railway environment variables:")
for k, v in data.items():
    if k == "private_key":
        # Replace newlines with \n for env var
        v = v
    print(f'{env_var(k)}="{v}"')