# SmartAttend — Real-Time Smart Attendance Management System

SmartAttend is a complete, production-quality, real-time smart attendance management web application built with **Python**, **Flask**, **SQLite**, **OpenCV** (Haar Cascade & LBPH Face Recognizer), and **QR Code Detection**.

SmartAttend provides real-time attendance tracking via two contactless methods:
1. **Biometric Face Recognition** (OpenCV LBPH Face Recognizer with configurable threshold)
2. **Instant QR Code Scanning** (Unique student ID passes decoded via OpenCV QRCodeDetector)

---

## Key Features

- **Real-Time Live Dashboard**: Auto-updating KPI cards (Total Students, Present Today, Absent Today, Turnout %, Total Records, Method counts), interactive Chart.js graphs, and recent attendance streams without page refreshes.
- **Student Lifecycle Management**: Registration with unique roll number constraints, automatic QR generation upon enrollment, face dataset management, profile view, editing, and cascading deletion.
- **Biometric Face Recognition**:
  - 30-sample facial dataset capture with Haar Cascade detection, grayscale conversion, and histogram equalization.
  - LBPH model training yielding a persistent `trainer.yml` classifier.
  - Live video stream with face bounding boxes, match confidence overlays, and recognition cooldown.
- **QR Code Attendance**:
  - Automatically generated unique QR passes for every enrolled student.
  - Downloadable and print-friendly student ID passes.
  - Missing QR files auto-regenerated on-the-fly.
  - Live video QR scanner with bounding polygon highlighting and instant recognition.
- **Strict Duplicate Attendance Prevention**: Enforced at application and database layers — a student can only be marked PRESENT once per calendar day (`YYYY-MM-DD`).
- **Comprehensive Reporting**:
  - **Daily Attendance**: Filter by date, search student, filter by method (Face/QR), presence/absence breakdown, and instant record deletion with audit updates.
  - **Monthly Reports**: Full calendar matrix for any selected student and month, calculating exact turnout percentage and day-by-day status.
  - **Attendance History Log**: Filterable by student, date range, method, and searchable by keywords.
- **Configurable Settings**: In-app configuration for face confidence threshold, camera index, recognition cooldown, and application branding.
- **Enterprise-Grade UI/UX**: Clean SaaS design system with dark-neutral surfaces, glass cards, toast alerts, confirmation dialogs, and responsive layouts.

---

## Technology Stack

- **Backend**: Python 3.10+, Flask 3.x
- **Database**: SQLite with parameterized queries, foreign keys, and indexes
- **Computer Vision**: OpenCV (`opencv-contrib-python`), Haar Cascade Frontal Face Classifier, LBPH Face Recognizer
- **QR Generation & Decoding**: `qrcode[pil]`, Pillow, OpenCV `QRCodeDetector`
- **Frontend**: HTML5, CSS3 (Custom SaaS Design System), Vanilla JavaScript, Chart.js

---

## Project Structure

```
smart-attend/
│
├── app.py                             # Main Flask application and REST API endpoints
├── config.py                          # Paths, constants, and default configurations
├── database.py                        # SQLite schema, migrations, and data access layer
├── face_engine.py                     # Face detection, dataset capture, LBPH training & inference
├── qr_engine.py                       # QR generation, auto-recovery, and scanning
├── camera.py                          # Thread-safe video capture and MJPEG streaming
├── haarcascade_frontalface_default.xml # Haar Cascade XML model for face detection
├── requirements.txt                   # Application dependencies
├── setup_assets.py                    # Database and directory initialization helper
├── README.md                          # Documentation
│
├── data/                              # Persistent storage (auto-created)
│   ├── attendance.db                  # SQLite database
│   ├── qr/                            # Generated QR code image files
│   ├── faces/                         # Face dataset folders (data/faces/<student_id>/)
│   └── model/
│       └── trainer.yml                # Trained LBPH model weights
│
├── templates/                         # Jinja2 HTML templates
│   ├── base.html                      # Layout, sidebar, top header, toast system
│   ├── dashboard.html                 # Real-time analytics, charts, and activity feeds
│   ├── students.html                  # Student list, search, modals for edit/delete
│   ├── register.html                  # Student registration form
│   ├── student_detail.html            # Profile, QR card, biometric status, monthly summary
│   ├── print_qr.html                  # Printable student QR pass
│   ├── capture.html                   # Interactive face dataset capture interface
│   ├── train.html                     # Model training control and dataset audit
│   ├── face_attendance.html           # Live face recognition attendance scanner
│   ├── qr_attendance.html             # Live QR code attendance scanner
│   ├── daily_attendance.html          # Date-specific attendance audit & deletion
│   ├── monthly_attendance.html        # Monthly student calendar matrix
│   ├── attendance.html                # Searchable attendance history log
│   └── settings.html                  # System settings configuration
│
├── static/                            # Static assets
│   ├── css/
│   │   └── style.css                  # Custom SaaS stylesheet & print styles
│   └── js/
│       ├── app.js                     # Global utilities, live clock, toasts, modals
│       ├── dashboard.js               # Real-time polling & Chart.js controllers
│       ├── attendance.js              # Table filtering and search
│       └── qr.js                      # QR scanner client helpers
│
├── scripts/                           # Standalone CLI tools
│   ├── capture_faces.py               # CLI tool to capture face samples
│   ├── train_model.py                 # CLI tool to train LBPH model
│   ├── face_attendance.py             # CLI tool to run face attendance scanner
│   └── qr_attendance.py               # CLI tool to run QR attendance scanner
│
└── tests/
    └── test_smartattend.py            # Automated unit and integration test suite
```

---

## Installation & Setup

### 1. Clone or Open the Workspace
Ensure you are inside the `smart-attend` directory:
```bash
cd smart-attend
```

### 2. Create and Activate a Virtual Environment (Optional but Recommended)
**Windows (PowerShell / Command Prompt):**
```bash
python -m venv venv
.\venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
```bash
python app.py
```
Open your web browser and navigate to:
```
http://127.0.0.1:5000
```

---

## End-to-End Workflow Guide

### Step 1: Register a Student
1. Go to **Register Student** (`/register`) or click **Add Student** on the Students page.
2. Enter the student's **Full Name** and unique **Roll Number** (e.g. `Jane Doe`, `CS2026-001`).
3. Click **Register & Generate QR**.
4. The student is created in SQLite and their unique QR code is automatically generated in `data/qr/student_<id>.png`.

### Step 2: View / Download / Print QR Code
1. From the student's profile page, view their centered QR pass.
2. Click **Download QR** to save `student_<id>_qr.png`.
3. Click **Print QR Card** to open a print-optimized version and use `Ctrl+P` / `Cmd+P` to print.

### Step 3: Capture Face Dataset
1. On the student's profile or students list, click **Capture Face** (`/capture/<student_id>`).
2. Position the student in front of the camera.
3. Click **Start Automatic Capture (30 Samples)**.
4. The system collects and normalizes 30 facial crops, saving them to `data/faces/<student_id>/sample_XXX.jpg`.

### Step 4: Train Face Recognition Model
1. Go to **Train Model** (`/train`).
2. Review the list of enrolled datasets and total sample count.
3. Click **Train Face Recognition Model**.
4. The system trains the LBPH model and outputs `data/model/trainer.yml`.

### Step 5: Start Face Attendance
1. Click **Face Scanner** (`/face-attendance`).
2. When the student steps in front of the camera:
   - Green bounding box appears with student name, roll number, and confidence score.
   - Attendance is recorded in SQLite with method `face`.
   - If the student is detected again on the same calendar day, the system displays **Already Marked Today** and prevents duplicate entries.

### Step 6: Start QR Attendance
1. Click **QR Scanner** (`/qr-attendance`).
2. Hold the printed student QR pass or display it on a phone screen to the camera.
3. The system decodes the student ID, verifies the record in SQLite, and marks attendance with method `qr`.
4. Repeated scans on the same day display **Already Marked Today**.

### Step 7: View Daily & Monthly Reports
- **Daily Attendance** (`/daily-attendance`): Select any date to see all registered students, their PRESENT / ABSENT status, check-in times, and method badges. Delete records with one click if needed.
- **Monthly Reports** (`/monthly-attendance`): Select a student and month to view a calendar-day matrix with attendance percentage.
- **Dashboard** (`/dashboard`): Observe real-time updates of statistics and charts.

---

## Standalone CLI Scripts

For headless or desktop terminal workflows, standalone CLI utilities are provided in `scripts/`:

```bash
# Capture face dataset for a student
python scripts/capture_faces.py --roll CS2026-001 --samples 30

# Train LBPH face recognizer
python scripts/train_model.py

# Run face attendance in a desktop window (press 'q' to exit)
python scripts/face_attendance.py

# Run QR attendance in a desktop window (press 'q' to exit)
python scripts/qr_attendance.py
```

---

## REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/dashboard` | `GET` | Returns live counters, recent records, 7-day trends, and last detection event. |
| `/api/students` | `GET` | Returns list of registered students and dataset status (`?search=query`). |
| `/api/attendance` | `GET` | Search and filter attendance logs (`?method=face&start_date=YYYY-MM-DD`). |
| `/api/attendance/today` | `GET` | Returns today's daily attendance breakdown. |
| `/api/attendance/<date_str>` | `GET` | Returns daily attendance breakdown for `<date_str>` (`YYYY-MM-DD`). |
| `/api/attendance/scan-qr` | `POST` | Scan raw QR payload (`{"qr_data": "<student_id>"}`). |
| `/api/capture/start/<student_id>` | `POST` | Starts automated 30-sample face capture session. |
| `/api/capture/status/<student_id>` | `GET` | Returns face sample collection count and status. |
| `/api/train` | `POST` | Triggers LBPH model compilation and returns metrics. |
| `/api/stream` | `GET` | Server-Sent Events (SSE) stream for live updates. |

---

## Running Automated Tests

Execute the test suite covering database schema, student registration, duplicate prevention, QR recovery, face model training, and API routes:

```bash
python -m unittest tests/test_smartattend.py
```

---

## Troubleshooting

- **Camera Unavailable / Cannot open camera**:
  - Verify your webcam is connected and not occupied by another app (Zoom, Teams, etc.).
  - Change the **Camera Index** in **Settings** (`/settings`) from `0` to `1` or `2`.
- **Model Missing Error**:
  - Ensure you have registered at least one student, captured their face dataset, and clicked **Train Face Recognition Model** at `/train`.
- **Duplicate Attendance Warning**:
  - SmartAttend strictly enforces one attendance record per student per calendar day. To re-test on the same day, delete the existing record from `/daily-attendance` or `/attendance-history`.
- **Missing QR Image**:
  - Accessing the QR view or download route automatically regenerates missing QR files.
