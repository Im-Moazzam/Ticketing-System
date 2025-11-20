import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production")

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "credentialing_helpdesk.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Gmail / Google Workspace setup
    MAIL_SERVER = "smtp.zoho.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "credentialing@docsmedicalbilling.com")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "b53qnU5maH9n")
    MAIL_DEFAULT_SENDER = (
        "Credentialing Helpdesk",
        os.environ.get("MAIL_USERNAME", "credentialing@docsmedicalbilling.com")
    )

    # Scheduler (for reminders)
    SCHEDULER_API_ENABLED = True
