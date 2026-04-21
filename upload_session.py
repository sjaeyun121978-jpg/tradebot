import base64

with open('session.session', 'rb') as f:
    data = base64.b64encode(f.read()).decode()

print(f"SESSION_STRING={data}")
