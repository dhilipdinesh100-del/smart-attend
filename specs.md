PROJECT NAME
SmartAttend — Real-Time Smart Attendance Management System


PROJECT GOAL
Build a complete, production-quality, real-time attendance management web application.

The application must manage students and attendance using two attendance methods:

1. Face Recognition
2. QR Code

The application must provide real-time attendance updates, daily attendance, monthly reports, student management, QR generation/download, face capture/training, dashboard analytics, and attendance history.

Do NOT create a basic demo or static mockup.

All displayed statistics and attendance records must come from the actual database.

Do NOT use fake/sample attendance data.


==================================================
TECHNOLOGY
==================================================

Backend:
- Python
- Flask

Database:
- SQLite for the initial version
- SQL queries must be parameterized

Frontend:
- HTML5
- CSS3
- JavaScript
- Jinja2 templates

Face Recognition:
- OpenCV
- Haar Cascade
- LBPH Face Recognizer

QR:
- Python qrcode library
- OpenCV QRCodeDetector for scanning

Charts:
- Chart.js

Real-time updates:
- JavaScript polling or Server-Sent Events
- Dashboard attendance counts should update without manually refreshing the page

Project must run locally with:

python app.py


==================================================
DESIGN REQUIREMENTS
==================================================

The UI must look like a premium modern SaaS application.

Do NOT make it look like a school project or a basic HTML website.

Use:

- clean white/dark-neutral interface
- rounded cards
- subtle shadows
- modern typography
- consistent spacing
- responsive layout
- professional navigation
- dashboard cards
- status badges
- icons
- hover effects
- loading states
- empty states
- success/error notifications
- responsive tables
- mobile-friendly design

Use one consistent design system throughout the entire application.

The application name is:

SmartAttend

Tagline:

Real-Time Smart Attendance Management


==================================================
MAIN NAVIGATION
==================================================

Create a professional sidebar/navigation containing:

Dashboard
Students
Register Student
Face Capture
Train Model
Face Attendance
QR Attendance
Daily Attendance
Monthly Reports
Attendance History
Settings


==================================================
DASHBOARD
==================================================

Create a real-time dashboard.

Display:

Total Students
Today's Present
Today's Absent
Today's Attendance %
Total Attendance Records
Face Attendance
QR Attendance

Also display:

Recent Attendance
Today's Attendance
Attendance by Method
Attendance Trend
Quick Actions


Quick actions:

Register Student
Capture Face
Train Model
Start Face Attendance
Start QR Attendance
Daily Attendance
Monthly Report


The dashboard must update automatically when new attendance is recorded.

Do not require the user to refresh the browser.


==================================================
STUDENT MANAGEMENT
==================================================

Create a Students page.

Display:

Student ID
Name
Roll Number
QR Code
Face Dataset Status
Registration Date
Actions


Actions:

View
Edit
Delete
View QR
Download QR
Capture Face


Add search:

Search by name
Search by roll number


Add filtering and pagination if required.


==================================================
REGISTER STUDENT
==================================================

Create a professional student registration form.

Fields:

Full Name
Roll Number


Validation:

- Name is required
- Roll number is required
- Roll number must be unique
- Trim whitespace
- Prevent duplicate students


After successful registration:

1. Create student database record
2. Generate QR code automatically
3. Save QR code in:

data/qr/student_<student_id>.png

4. Display success message
5. Provide buttons:

View QR
Download QR
Capture Face


==================================================
QR CODE
==================================================

Every student must have a unique QR code.

QR content should contain the student ID.

Example:

123


QR generation must happen automatically when registering a student.

Provide:

View QR
Download QR


The download filename should be:

student_<student_id>_qr.png


If a QR file is missing, automatically regenerate it.


Do NOT create duplicate Flask endpoints.

There must be exactly one route for viewing a QR and exactly one route for downloading a QR.


==================================================
QR ATTENDANCE
==================================================

Create a real-time QR attendance scanner.

Use:

OpenCV QRCodeDetector


Workflow:

1. Start QR Attendance
2. Open camera
3. Detect QR code
4. Decode student ID
5. Find student in database
6. Verify student exists
7. Check whether attendance is already recorded today
8. If not recorded:
   insert attendance
9. Display:

Attendance Marked
Student Name
Roll Number
Time
Method = QR

If already recorded:

Display:

Already Marked Today

Do not create duplicate attendance records.


Unknown QR:

Display:

Student Not Found


The scanner must continue running until the user exits it.


==================================================
FACE ATTENDANCE
==================================================

Use:

OpenCV
Haar Cascade
LBPHFaceRecognizer


Face attendance workflow:

1. Start camera
2. Detect faces
3. Recognize student
4. Check confidence threshold
5. Find student in database
6. Check today's attendance
7. Record attendance if not already recorded
8. Display student name
9. Display attendance status


Important:

Lower LBPH confidence means a better match.

Use a configurable recognition threshold.

Example configuration:

FACE_CONFIDENCE_THRESHOLD = 60


Do not hard-code this in multiple places.


Prevent repeated processing of the same detected student.


==================================================
FACE CAPTURE
==================================================

Create a Face Capture page.

Select student.

Display:

Student Name
Roll Number
Capture Status


When capture starts:

Open camera.

Capture multiple face samples.

Save them under:

data/faces/<student_id>/


Display capture progress.

Example:

Samples captured: 12 / 30


After completion:

Display:

Face dataset captured successfully.


==================================================
MODEL TRAINING
==================================================

Create a Train Model page.

Button:

Train Face Recognition Model


When clicked:

Read datasets from:

data/faces/


Train LBPH model.


Save:

data/model/trainer.yml


Display:

Training started
Training completed
Number of students
Number of images
Training status


If there are no face datasets:

Display a clear error.


==================================================
ATTENDANCE DATABASE
==================================================

Use an attendance table containing at minimum:

id
student_id
method
date_time


method values:

face
qr


Use foreign-key relationships where appropriate.


Attendance must be stored permanently in SQLite.


==================================================
DUPLICATE ATTENDANCE
==================================================

A student can only be marked PRESENT once per day.

This rule must be enforced at the database/application level.

Example:

Student ID = 5
Date = 2026-08-21

If already present:

Do not insert another record.


The system must prevent duplicates even if:

- face scanner sees the same person repeatedly
- QR is scanned repeatedly
- browser refreshes
- scanner restarts


==================================================
DAILY ATTENDANCE
==================================================

Create:

/daily-attendance


The page must show today's attendance.

Display:

Student
Roll Number
Status
Method
Date
Time


Provide:

Search
Filter by method
Present count
Absent count
Attendance percentage


Add date selector so the user can view attendance for any selected date.


Important:

"Absent" should be calculated from registered students who do not have an attendance record for that date.

Do not store fake absent records unless explicitly needed.


==================================================
MONTHLY ATTENDANCE
==================================================

Create:

/monthly-attendance


Allow selecting:

Student
Month


Display:

Student Name
Roll Number
Selected Month
Present Days
Absent Days
Attendance Percentage
Face Count
QR Count


Display a complete calendar/date-based attendance table.


For each date:

Date
Day
Status
Method
Time


Status:

PRESENT
ABSENT


Attendance percentage should be calculated from actual attendance data.


Do not calculate attendance using total database records.


==================================================
ATTENDANCE HISTORY
==================================================

Create an attendance history page.

Display all attendance records.

Columns:

#
Student
Roll Number
Date
Time
Method


Add:

Search
Date filter
Student filter
Method filter


Sort newest first.


==================================================
RECENT ATTENDANCE
==================================================

Dashboard must show recent attendance.

Example:

John Doe
Roll: 23
Present
Face
09:32 AM


Jane Smith
Roll: 24
Present
QR
09:35 AM


Only display actual records from the database.


If an attendance record is deleted, it must disappear from Recent Attendance immediately.


==================================================
DELETE ATTENDANCE
==================================================

Allow authorized users to delete attendance records.

Before deleting:

Show confirmation.


After deletion:

Update dashboard statistics immediately.


Do not show deleted records anywhere.


==================================================
DELETE STUDENT
==================================================

Allow deleting students.

Before deletion:

Show confirmation.


When deleting a student:

- delete student attendance records
- delete face dataset
- delete QR code
- remove student database record


Do NOT renumber student IDs after deletion.

Student IDs should remain stable.

This is important because QR codes and face models depend on stable student IDs.


==================================================
REAL-TIME SYSTEM
==================================================

The application must feel real-time.

When attendance is recorded:

Dashboard should automatically update.

Recent Attendance should update.

Today's attendance count should update.

Attendance percentage should update.


Use one of:

Server-Sent Events
OR
short-interval JavaScript polling


Prefer Server-Sent Events if practical.

Create an endpoint such as:

/api/dashboard


Return JSON containing current statistics.


The frontend should periodically request/update the data without a full page reload.


==================================================
API ENDPOINTS
==================================================

Create clean API endpoints where useful.

Examples:

GET /api/dashboard
GET /api/students
GET /api/attendance
GET /api/attendance/today
GET /api/attendance/<date>


Return JSON.


Do not duplicate endpoint function names.


Every Flask endpoint must have a unique endpoint/function name.


==================================================
SECURITY
==================================================

Use:

Parameterized SQL queries
Input validation
Safe file paths
Safe subprocess execution
Error handling


Do not expose internal Python exceptions to users.


Show friendly error messages.


==================================================
ERROR HANDLING
==================================================

Handle:

Camera unavailable
Camera permission failure
Model missing
Haar Cascade missing
Face model unavailable
QR scanner failure
Database errors
Invalid student ID
Duplicate roll number
Missing QR file
Missing face dataset
No students registered


Display user-friendly messages.


==================================================
PROJECT STRUCTURE
==================================================

Create a clean structure similar to:

smart-attendence/

    app.py

    requirements.txt

    README.md

    haarcascade_frontalface_default.xml

    data/
        attendance.db

        qr/

        faces/

        model/
            trainer.yml

    templates/
        base.html
        index.html
        dashboard.html
        students.html
        register.html
        capture.html
        train.html
        face_attendance.html
        qr_attendance.html
        daily_attendance.html
        monthly_attendance.html
        attendance.html
        settings.html

    static/
        css/
            style.css

        js/
            dashboard.js
            attendance.js
            qr.js
            app.js

        images/
        icons/


    scripts/
        capture_faces.py
        train_model.py
        face_attendance.py
        qr_attendance.py


Keep responsibilities separated.

Do not put the entire application into one huge Python file if separate modules improve maintainability.


==================================================
DATABASE INITIALIZATION
==================================================

The application must automatically create the database if it doesn't exist.

Create:

students

attendance


students:

id INTEGER PRIMARY KEY
name TEXT NOT NULL
roll_no TEXT UNIQUE NOT NULL
created_at TEXT


attendance:

id INTEGER PRIMARY KEY
student_id INTEGER NOT NULL
method TEXT NOT NULL
date_time TEXT NOT NULL

FOREIGN KEY(student_id)
REFERENCES students(id)
ON DELETE CASCADE


Add appropriate indexes for:

attendance.student_id
attendance.date_time
attendance.method


==================================================
TIME AND DATE
==================================================

Use the server's local date/time consistently.

Store timestamps in:

YYYY-MM-DD HH:MM:SS


For date filtering use:

YYYY-MM-DD


Do not mix incompatible date formats.


==================================================
PREMIUM UX
==================================================

Add:

Toast notifications
Loading indicators
Confirmation dialogs
Empty states
Error states
Success states
Responsive tables
Responsive cards
Smooth hover effects
Modern buttons
Professional badges


Example attendance badge:

PRESENT


Example methods:

FACE
QR


Use icons consistently.


==================================================
DASHBOARD CHARTS
==================================================

Add Chart.js charts:

1. Attendance by Method

Face
QR


2. Attendance Trend

Last 7 days


3. Student Attendance

Top attendance students


Charts must use real database data.

Do not hard-code chart values.


==================================================
STUDENT QR CARD
==================================================

On student details page display:

Student Name
Roll Number
Student ID
QR Code


Buttons:

Download QR
Print QR


The QR should be visually centered.


==================================================
PRINT QR
==================================================

Provide a print-friendly QR page.

The printed page should contain:

SmartAttend
Student Name
Roll Number
Student ID
QR Code


==================================================
RESPONSIVE DESIGN
==================================================

Desktop:
Sidebar + main content


Tablet:
Collapsible sidebar


Mobile:
Mobile navigation


Tables should scroll horizontally when necessary.


==================================================
SETTINGS
==================================================

Create settings page.

Allow configuration of:

Face confidence threshold
Camera index
Recognition cooldown
Application name


Store configurable values in a simple settings table or configuration file.


==================================================
README
==================================================

Create a complete README.

Include:

Project overview
Features
Requirements
Installation
Virtual environment setup
Package installation
Database setup
How to register students
How to capture faces
How to train model
How to use face attendance
How to use QR attendance
How to generate/download QR
How to view daily attendance
How to view monthly reports
Troubleshooting


==================================================
REQUIREMENTS.TXT
==================================================

Include required packages, such as:

Flask
opencv-contrib-python
qrcode
Pillow


Use compatible versions where necessary.


==================================================
IMPORTANT DEVELOPMENT RULES
==================================================

1. Do not generate fake data.

2. Do not use placeholder statistics.

3. Do not duplicate Flask routes.

4. Every endpoint must have a unique function name.

5. Do not renumber student IDs after deletion.

6. QR codes must contain the actual student ID.

7. Attendance must use the actual SQLite database.

8. Attendance must be unique per student per day.

9. Deleted attendance must immediately disappear from reports and dashboard.

10. Deleted students must have their QR and face data removed.

11. Missing QR files should be regenerated automatically.

12. Do not silently ignore database errors.

13. Do not expose stack traces to users.

14. Do not create unnecessary duplicate Python files.

15. Keep frontend and backend logic organized.

16. The application must actually work when run locally.

17. Test every route after implementation.

18. Test registration.

19. Test QR generation.

20. Test QR download.

21. Test QR scanning.

22. Test face capture.

23. Test face training.

24. Test face recognition.

25. Test duplicate attendance prevention.

26. Test daily attendance.

27. Test monthly attendance.

28. Test student deletion.

29. Test attendance deletion.

30. Test dashboard real-time updates.


==================================================
FINAL ACCEPTANCE TEST
==================================================

The application is considered complete only when this workflow works:

REGISTER STUDENT
        ↓
QR AUTOMATICALLY GENERATED
        ↓
DOWNLOAD QR
        ↓
CAPTURE FACE
        ↓
TRAIN MODEL
        ↓
START FACE ATTENDANCE
        ↓
STUDENT RECOGNIZED
        ↓
ATTENDANCE SAVED
        ↓
DASHBOARD UPDATES
        ↓
DAILY ATTENDANCE UPDATES
        ↓
MONTHLY REPORT UPDATES


Also test:

DOWNLOAD QR
        ↓
OPEN QR
        ↓
START QR ATTENDANCE
        ↓
SCAN QR
        ↓
STUDENT IDENTIFIED
        ↓
ATTENDANCE SAVED
        ↓
DASHBOARD UPDATES


If the same student is scanned again on the same day:

DO NOT CREATE DUPLICATE RECORD


==================================================
FINAL REQUIREMENT
==================================================

Generate the complete working project.

Do not only provide snippets.

Do not leave TODO placeholders for core functionality.

Do not say "implement this later."

All core functionality must be implemented.

After generating the project, provide:

1. Project structure
2. Installation commands
3. Run command
4. Default URL
5. Testing checklist
6. Any required system dependencies

The final application should look and behave like a professional real-time attendance management product called:

SmartAttend