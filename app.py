import os
from datetime import datetime, timedelta
import pytz
from flask import (
    Flask, render_template, redirect, url_for,
    flash, request, send_from_directory
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename

from config import Config
from models import db, User, Ticket, Comment

from apscheduler.schedulers.background import BackgroundScheduler

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx"}

PK_TZ = pytz.timezone("Asia/Karachi")
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    def make_naive(dt):
        """Convert any datetime (aware or naive) into naive PKT time for comparison."""
        if dt is None:
            return None
        if dt.tzinfo is not None:
            # convert aware datetime to PKT and strip tzinfo
            return dt.astimezone(PK_TZ).replace(tzinfo=None)
        return dt  # already naive

    # DB
    db.init_app(app)

    # Login
    login_manager = LoginManager(app)
    login_manager.login_view = "login"

    # Mail
    mail = Mail(app)

    # Uploads
    upload_folder = os.path.join(app.root_path, "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder

    # Scheduler for SLA reminders
    scheduler = BackgroundScheduler(daemon=True)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    def allowed_file(filename: str) -> bool:
        return "." in filename and \
               filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

    def calculate_due_time(priority: str):
        now = datetime.now(PK_TZ).replace(tzinfo=None)
        if priority == "Urgent":
            return now + timedelta(hours=2)
        elif priority == "7 Days":
            return now + timedelta(days=7)
        elif priority == "15 Days":
            return now + timedelta(days=15)
        return now + timedelta(days=7)


    def ensure_pk_time(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Assume the naive datetime is UTC and convert to PK time
            dt = pytz.utc.localize(dt)
        return dt.astimezone(PK_TZ)

    def send_email(subject: str, recipients, body: str):
        if not recipients:
            return
        if isinstance(recipients, str):
            recipients = [recipients]
        try:
            msg = Message(subject=subject, recipients=recipients, body=body)
            mail.send(msg)
        except Exception as e:
            # For debugging on RDP console
            print("Email error:", e)

    def check_ticket_deadlines():
        """Reminder for tickets past due_time (based on their own SLA)."""
        with app.app_context():
            now = datetime.utcnow()
            pending_statuses = ["Open", "In Progress", "Solved"]
            overdue = Ticket.query.filter(
                Ticket.status.in_(pending_statuses),
                Ticket.due_time <= now
            ).all()

            for t in overdue:
                subject = f"[Reminder] Ticket #{t.id} overdue ({t.priority})"
                body = (
                    f"Hello,\n\n"
                    f"Ticket #{t.id} is still '{t.status}' and has passed its SLA.\n\n"
                    f"Staff: {t.staff.username} ({t.staff.email})\n"
                    f"Practice: {t.practice_name}\n"
                    f"Provider: {t.provider_name}\n"
                    f"Subject: {t.subject}\n"
                    f"Priority: {t.priority}\n\n"
                    f"Please log in to the Credentialing Helpdesk Portal.\n\n"
                    f"Regards,\nCredentialing Helpdesk System"
                )
                send_email(subject, [t.staff.email, app.config["MAIL_USERNAME"]], body)

    # run every 30 minutes
    scheduler.add_job(func=check_ticket_deadlines, trigger="interval", minutes=720)
    scheduler.start()


    # ---------------- ROUTES ----------------

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            if current_user.role == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("staff_dashboard"))
        return redirect(url_for("login"))
    
    # ---------- Auth ----------

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password")
            confirm = request.form.get("confirm")

            if not email or not username or not password:
                flash("All fields are required.", "danger")
                return redirect(url_for("register"))
            if password != confirm:
                flash("Passwords do not match.", "danger")
                return redirect(url_for("register"))
            if User.query.filter_by(email=email).first():
                flash("Email already registered.", "danger")
                return redirect(url_for("register"))

            user = User(username=username, email=email, role="staff")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email")
            password = request.form.get("password")

            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user)
                if user.role == "admin":
                    return redirect(url_for("admin_dashboard"))
                return redirect(url_for("staff_dashboard"))

            flash("Invalid email or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("Logged out successfully.", "success")
        return redirect(url_for("login"))

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email")
            user = User.query.filter_by(email=email).first()
            if user:
                subject = "[Credentialing Helpdesk] Password Reset Instructions"
                body = (
                    f"Hello {user.username},\n\n"
                    "Please contact your administrator to reset your password.\n\n"
                    "Regards,\nCredentialing Helpdesk"
                )
                send_email(subject, [user.email], body)
            flash("If that email exists, reset instructions have been sent.", "info")
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    # ---------- Staff views ----------
    @app.route("/staff/dashboard")
    @login_required
    def staff_dashboard():
        if current_user.role != "staff":
            return redirect(url_for("admin_dashboard"))

        selected_status = request.args.get("status", "All")

        query = Ticket.query.filter_by(staff_id=current_user.id)
        if selected_status != "All":
            query = query.filter_by(status=selected_status)
        tickets = query.order_by(Ticket.created_at.desc()).all()

        # Use Pakistan time directly
        now = make_naive(datetime.now(PK_TZ))

        total_tickets = len(tickets)
        closed_tickets = sum(1 for t in tickets if t.status.lower() in ["closed", "approved"])
        overdue_tickets = sum(
            1 for t in tickets
            if t.due_time and make_naive(t.due_time) < now and t.status.lower() not in ["closed", "approved"]
        )


        flashed = request.args.get("new_ticket", False)
        return render_template(
            "staff_dashboard.html",
            tickets=tickets,
            selected_status=selected_status,
            now=now,
            flashed=flashed,
            total_tickets=total_tickets,
            closed_tickets=closed_tickets,
            overdue_tickets=overdue_tickets
        )


    @app.route("/ticket/create", methods=["GET", "POST"])
    @login_required
    def create_ticket():
        # ✅ Only staff can create tickets
        if current_user.role != "staff":
            flash("Only staff can create tickets.", "danger")
            return redirect(url_for("staff_dashboard"))

        if request.method == "POST":
            # Collect form data
            practice_name = request.form.get("practice_name")
            provider_name = request.form.get("provider_name")
            subject_text = request.form.get("subject")
            description = request.form.get("description")
            priority = request.form.get("priority")

            # Validate all fields
            if not all([practice_name, provider_name, subject_text, description, priority]):
                flash("All fields including priority are required.", "danger")
                return redirect(url_for("create_ticket"))

            # ✅ Always use Pakistan time directly (no UTC)
            from datetime import datetime, timedelta
            import pytz
            PK_TZ = pytz.timezone("Asia/Karachi")
            created_at = datetime.now(PK_TZ)

            # Calculate due time based on priority (in PKT)
            if priority == "Urgent":
                due_time = created_at + timedelta(hours=2)
            elif priority == "7 Days":
                due_time = created_at + timedelta(days=7)
            else:
                due_time = created_at + timedelta(days=3)

            # ✅ Handle attachment upload
            attachment_file = request.files.get("attachment")
            filename = None
            if attachment_file and attachment_file.filename:
                if allowed_file(attachment_file.filename):
                    filename = secure_filename(attachment_file.filename)
                    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    attachment_file.save(path)
                else:
                    flash("Invalid attachment type.", "danger")
                    return redirect(url_for("create_ticket"))

            # ✅ Create and save ticket (PKT time)
            ticket = Ticket(
                staff_id=current_user.id,
                practice_name=practice_name,
                provider_name=provider_name,
                subject=subject_text,
                description=description,
                priority=priority,
                created_at=created_at,
                due_time=due_time,
                attachment_filename=filename,
                status="Open",
            )
            db.session.add(ticket)
            db.session.commit()

            # ✅ Email logic (will work later when you enable)
            body_admin = (
                f"Hello Credentialing Team,\n\n"
                f"A new ticket has been submitted.\n\n"
                f"Ticket ID: #{ticket.id}\n"
                f"Staff: {current_user.username} ({current_user.email})\n"
                f"Practice: {practice_name}\n"
                f"Provider: {provider_name}\n"
                f"Priority: {priority}\n"
                f"Subject: {subject_text}\n\n"
                f"Regards,\nCredentialing Helpdesk System"
            )
            send_email(
                f"[New Ticket Created] #{ticket.id} | Priority: {priority}",
                [app.config["MAIL_USERNAME"]],
                body_admin,
            )

            body_staff = (
                f"Hello {current_user.username},\n\n"
                f"Your ticket #{ticket.id} has been submitted.\n\n"
                f"Priority: {priority}\n"
                f"Subject: {subject_text}\n\n"
                f"Regards,\nCredentialing Helpdesk System"
            )
            send_email(
                f"[Ticket Confirmation] Ticket #{ticket.id} Submitted",
                [current_user.email],
                body_staff,
            )

            flash(f"Ticket #{ticket.id} created successfully.", "success")
            return redirect(url_for("staff_dashboard", new_ticket=True))

        # Render ticket creation form
        return render_template("create_ticket.html")


    # ---------- Admin views ----------

    @app.route("/admin/dashboard")
    @login_required
    def admin_dashboard():
        if current_user.role != "admin":
            return redirect(url_for("staff_dashboard"))

        status_filter = request.args.get("status", "All")
        query = Ticket.query
        if status_filter != "All":
            query = query.filter_by(status=status_filter)
        tickets = query.order_by(Ticket.created_at.desc()).all()

        # Use Pakistan time directly
        now = make_naive(datetime.now(PK_TZ))

        total_tickets = len(tickets)
        closed_tickets = sum(1 for t in tickets if t.status.lower() in ["closed", "approved"])
        overdue_tickets = sum(
            1 for t in tickets
            if t.due_time and make_naive(t.due_time) < now and t.status.lower() not in ["closed", "approved"]
        )


        return render_template(
            "admin_dashboard.html",
            tickets=tickets,
            selected_status=status_filter,
            now=now,
            total_tickets=total_tickets,
            closed_tickets=closed_tickets,
            overdue_tickets=overdue_tickets
        )

    @app.route("/admin/ticket/<int:ticket_id>/status", methods=["POST"])
    @login_required
    def admin_update_status(ticket_id):
        if current_user.role != "admin":
            flash("Not authorized.", "danger")
            return redirect(url_for("index"))

        ticket = Ticket.query.get_or_404(ticket_id)
        new_status = request.form.get("status")

        if new_status not in ["Open", "In Progress", "Solved"]:
            flash("Invalid status.", "danger")
            return redirect(url_for("admin_dashboard"))

        ticket.status = new_status
        db.session.commit()

        # Notify staff
        subject = f"[Ticket Update] Ticket #{ticket.id} is now {new_status}"
        body = (
            f"Hello {ticket.staff.username},\n\n"
            f"Your ticket #{ticket.id} status is now: {new_status}.\n\n"
            f"Subject: {ticket.subject}\n"
            f"Priority: {ticket.priority}\n\n"
            f"Regards,\nCredentialing Helpdesk System"
        )
        send_email(subject, [ticket.staff.email, app.config["MAIL_USERNAME"]], body)


        flash("Ticket status updated.", "success")
        return redirect(url_for("admin_dashboard"))

    # ---------- Shared ticket views ----------

    @app.route("/ticket/<int:ticket_id>")
    @login_required
    def view_ticket(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)

        # PKT conversion for consistency
        if ticket.created_at:
            ticket.created_at = ticket.created_at.replace(tzinfo=pytz.utc).astimezone(PK_TZ)
        if ticket.due_time:
            if ticket.due_time.tzinfo is None:
                ticket.due_time = ticket.due_time.replace(tzinfo=pytz.utc).astimezone(PK_TZ)
            else:
                ticket.due_time = ticket.due_time.astimezone(PK_TZ)

        if current_user.role == "staff" and ticket.staff_id != current_user.id:
            flash("You are not allowed to view this ticket.", "danger")
            return redirect(url_for("staff_dashboard"))

        return render_template("view_ticket.html", ticket=ticket)


    @app.route("/ticket/<int:ticket_id>/attachment")
    @login_required
    def download_attachment(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if not ticket.attachment_filename:
            flash("No attachment for this ticket.", "info")
            return redirect(url_for("view_ticket", ticket_id=ticket_id))
        if current_user.role == "staff" and ticket.staff_id != current_user.id:
            flash("Not authorized.", "danger")
            return redirect(url_for("staff_dashboard"))
        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            ticket.attachment_filename,
            as_attachment=True
        )

    # ---------- Comments (Two-Way Chat) ----------
    @app.route("/ticket/<int:ticket_id>/comment", methods=["POST"])
    @login_required
    def add_comment(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        message = request.form.get("message", "").strip()

        if not message:
            flash("Comment cannot be empty.", "danger")
            return redirect(url_for("view_ticket", ticket_id=ticket_id))

        comment = Comment(
            ticket_id=ticket.id,
            user_id=current_user.id,
            message=message
        )
        db.session.add(comment)
        db.session.commit()

        flash("Comment posted successfully.", "success")
        return redirect(url_for("view_ticket", ticket_id=ticket.id))


    # ---------- Staff Approve / Reopen ----------

    @app.route("/ticket/<int:ticket_id>/staff-action", methods=["POST"])
    @login_required
    def staff_action(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if current_user.role != "staff" or ticket.staff_id != current_user.id:
            flash("Not authorized.", "danger")
            return redirect(url_for("index"))

        action = request.form.get("action")
        cred_email = app.config["MAIL_USERNAME"]

        if action == "approve_close" and ticket.status in ["Solved", "In Progress", "Open"]:
            ticket.status = "Closed"
            db.session.commit()
            subject = f"[Ticket Closed] #{ticket.id} Approved & Closed"
            body = (
                f"Hello Credentialing Team,\n\n"
                f"Ticket #{ticket.id} has been approved & closed by {current_user.username}.\n\n"
                f"Subject: {ticket.subject}\n"
                f"Priority: {ticket.priority}\n\n"
                f"Regards,\nCredentialing Helpdesk System"
            )
            send_email(subject, [cred_email], body)
            flash("Ticket closed.", "success")

        elif action == "reopen" and ticket.status in ["Solved", "Closed"]:
            ticket.status = "In Progress"
            ticket.due_time = calculate_due_time(ticket.priority)
            db.session.commit()
            subject = f"[Ticket Reopened] #{ticket.id}"
            body = (
                f"Hello Credentialing Team,\n\n"
                f"Ticket #{ticket.id} has been reopened by {current_user.username}.\n\n"
                f"Subject: {ticket.subject}\n"
                f"Priority: {ticket.priority}\n\n"
                f"Regards,\nCredentialing Helpdesk System"
            )
            send_email(subject, [cred_email], body)
            flash("Ticket reopened and set to In Progress.", "success")

        else:
            flash("Invalid action for current status.", "danger")

        return redirect(url_for("view_ticket", ticket_id=ticket.id))
    
    @app.route("/admin/ticket/<int:ticket_id>/assign", methods=["POST"])
    @login_required
    def admin_update_assigned(ticket_id):
        if current_user.role != "admin":
            flash("Not authorized.", "danger")
            return redirect(url_for("index"))

        ticket = Ticket.query.get_or_404(ticket_id)
        assigned_to = request.form.get("assigned_to", "").strip()

        ticket.assigned_to = assigned_to
        db.session.commit()

        flash(f"Ticket #{ticket.id} assigned to '{assigned_to}'.", "success")
        return redirect(url_for("admin_dashboard", status=request.args.get("status", "All")))

    # ---------- CLI: init-db ----------

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        admin_email = os.environ.get("ADMIN_EMAIL", "credentialing@docsmedicalbilling.com")
        admin = User.query.filter_by(email=admin_email).first()
        if not admin:
            admin = User(
                username="CredentialingAdmin",
                email=admin_email,
                role="admin"
            )
            admin.set_password(os.environ.get("ADMIN_PASSWORD", "Admin@123"))
            db.session.add(admin)
            db.session.commit()
            print(f"Created default admin: {admin_email} / Admin@123")
        print("Database initialized.")

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)
