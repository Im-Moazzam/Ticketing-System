Credentialing Helpdesk Portal (Flask + SQLite)

Steps (on your Remote Desktop):

1. Install Python 3.x
2. Extract this folder.
3. In Command Prompt:
   pip install flask flask_sqlalchemy flask_login flask_mail apscheduler werkzeug
4. Set environment (recommended):
   set MAIL_USERNAME=credentialing@docsmedicalbilling.com
   set MAIL_PASSWORD=your_app_password
   set ADMIN_EMAIL=credadmin@docsmedicalbilling.com
   set ADMIN_PASSWORD=Admin@123
5. Initialize DB:
   flask --app app.py init-db
6. Run:
   python app.py
7. Open:
   http://127.0.0.1:5000
