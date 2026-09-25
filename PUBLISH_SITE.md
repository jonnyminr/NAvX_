# Publish ANTARCTIC NAV-X without a tunnel

This build does **not** require any local tunneling software. The FastAPI backend serves the frontend itself, so deploy the project as one Python **Web Service**. The recommended beginner-friendly option is **Render**.

## What stays real

NAV-X does not add fake vessels, iceberg observations, weather, current, route, CPA/TCA, or forecast values when a source is unavailable. The bundled official/cached scientific datasets remain available. Live AIS is enabled only when you provide a valid server-side AIS provider credential.

## Before publishing

1. Keep `.env` private. Do not upload it to GitHub.
2. `.env.example` contains variable names only and is safe to commit.
3. If an API key was ever committed to GitHub, rotate/revoke that key before publishing.
4. The public site will use HTTPS automatically, so browser GPS can work after the user grants location permission.

## Recommended deployment: Render

### 1. Put the project on GitHub

Open PowerShell in the project folder:

```powershell
git init
git add .
git commit -m "Prepare ANTARCTIC NAV-X for deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/antarctic-nav-x.git
git push -u origin main
```

If the repository already exists, use your existing remote and just commit/push the updated files.

### 2. Create a Render Web Service

1. Sign in to Render.
2. Choose **New > Web Service**.
3. Connect the GitHub repository containing this project.
4. Use these values:
   - Runtime: **Python 3**
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT`
5. Choose the instance size you want and create the service.

A ready-to-use `render.yaml` is included at the repository root, so you can also create the service as a Render Blueprint.

### 3. Add environment variables in Render

Open your Render service > **Environment** and add only the credentials/providers you actually use.

For AISStream:

```text
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=YOUR_REAL_AISSTREAM_KEY
```

Other supported real AIS options:

```text
AISHUB_USERNAME=
DATALASTIC_API_KEY=
```

Optional legacy Mappls compatibility:

```text
MAPPLS_STATIC_KEY=
```

Optional Copernicus credentials, only if your workflow needs them:

```text
COPERNICUS_USERNAME=
COPERNICUS_PASSWORD=
```

Do **not** add `PORT`; Render provides it automatically.

### 4. Deploy

Click **Deploy latest commit** if Render has not already started automatically. Wait for the deploy log to show that Uvicorn is running.

Your site will be available at a URL similar to:

```text
https://your-service-name.onrender.com/
```

The same site is also available at:

```text
https://your-service-name.onrender.com/app/
```

### 5. Verify real-data endpoints

Open these paths on your deployed domain:

```text
/api/system/health
/api/config/realtime
/api/data/icebergs
/api/data/vessels
```

Expected behavior:

- `/api/system/health` reports dataset/provider status.
- `/api/data/icebergs` returns the verified USNIC-based iceberg dataset available to the server.
- `/api/data/vessels` returns genuine AIS messages only. Zero vessels is valid when no provider message is currently available.
- No secret API key should appear in any browser response.

## GPS on the published site

The deployed Render URL uses HTTPS. Browser geolocation can therefore work without a tunnel. The user must still allow Location permission in the browser/phone settings.

## Important note about live AIS and free hosting

A free web service can sleep after inactivity. When it sleeps, a persistent AIS WebSocket is disconnected and reconnects after the service wakes. For continuous operational AIS reception, use an always-on service instance instead of a sleeping free instance.

## Local development still works

You can still run the project locally without any tunnel:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.api.main
```

Then open:

```text
http://localhost:8000/
```

or:

```text
http://localhost:8000/app/
```
