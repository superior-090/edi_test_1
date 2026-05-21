# ProctorAI

Clean project map:

- `backend/` - the single FastAPI backend for local development and Render deployment.
- `backend/models/` - YOLO model files used by the unified backend.
- `backend/legacy_ai/` - archived old standalone AI scripts kept for reference only.
- `edi_project/` - the Flutter proctoring app.
- Root Flutter files are leftovers from the starter project; run the app from `edi_project/`.

Current flow:

- Students choose an exam and enter a side-camera IP like `192.168.0.103:8080`.
- The backend validates that side camera before starting the exam.
- Proctors can filter the dashboard by subject, then open a student to see front camera, side camera, score, cheat type, and malpractice events.
- If the side-camera feed stops during an exam, the backend terminates that session.
- If a student tries to rejoin the same exam, the session waits for proctor approval.

## Run locally

Terminal 1:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd edi_project
flutter pub get
flutter run -d chrome --dart-define=API_URL=http://127.0.0.1:8000
```

Demo users:

- Candidate: `candidate` / `student123`
- Admin: `admin` / `admin123`
