from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
PK_TZ = pytz.timezone("Asia/Karachi")
db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="staff")  # 'staff' or 'admin'

    tickets = db.relationship("Ticket", backref="staff", lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    practice_name = db.Column(db.String(255), nullable=False)
    provider_name = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)

    priority = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(50), default="Open")
    attachment_filename = db.Column(db.String(255))

    assigned_to = db.Column(db.String(255), nullable=True, default="")
    # store as local Pakistan time (naive)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(PK_TZ).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(PK_TZ).replace(tzinfo=None),
                           onupdate=lambda: datetime.now(PK_TZ).replace(tzinfo=None))

    due_time = db.Column(db.DateTime, nullable=False)


    def __repr__(self):
        return f"<Ticket #{self.id} - {self.subject} ({self.status})>"



class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(PK_TZ))

    # Relationships
    ticket = db.relationship("Ticket", backref="comments", lazy=True)
    user = db.relationship("User", backref="comments", lazy=True)

    def __repr__(self):
        return f"<Comment {self.id} by {self.user.username} on Ticket {self.ticket_id}>"
