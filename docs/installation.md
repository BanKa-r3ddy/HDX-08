# Installation Guide

Use Python 3.13 or later. Create and activate a virtual environment, then run:

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

The server listens at `http://127.0.0.1:8000`; interactive API documentation is at `/docs`.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/analyze -ContentType 'application/json' -Body '{"symbol":"AAPL"}'
```
