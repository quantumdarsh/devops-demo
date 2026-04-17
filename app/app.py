from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter
from datetime import datetime, date
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lib-secret-2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'library.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
metrics = PrometheusMetrics(app)
metrics.info("app_info", "Library Rental System", version="1.0.0")

rentals_counter = Counter("rentals_total", "Total rentals created")
returns_counter = Counter("returns_total", "Total books returned")


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default="customer")
    rentals = db.relationship("Rental", backref="user", lazy=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role}


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(200), nullable=False)
    genre = db.Column(db.String(100), default="General")
    description = db.Column(db.Text, default="")
    total_copies = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    rental_price_per_day = db.Column(db.Float, default=5.0)
    rentals = db.relationship("Rental", backref="book", lazy=True)

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "author": self.author,
            "genre": self.genre, "description": self.description,
            "total_copies": self.total_copies,
            "available_copies": self.available_copies,
            "rental_price_per_day": self.rental_price_per_day,
        }


class Rental(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey("book.id"), nullable=False)
    rented_on = db.Column(db.Date, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    returned_on = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="active")

    def to_dict(self):
        b = Book.query.get(self.book_id)
        u = User.query.get(self.user_id)
        days = (self.due_date - self.rented_on).days
        cost = days * b.rental_price_per_day if b else 0
        return {
            "id": self.id, "user_id": self.user_id,
            "user_name": u.name if u else "",
            "book_id": self.book_id,
            "book_title": b.title if b else "",
            "rented_on": str(self.rented_on),
            "due_date": str(self.due_date),
            "returned_on": str(self.returned_on) if self.returned_on else None,
            "status": self.status,
            "cost": round(cost, 2),
        }


@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))


def seed():
    if not User.query.filter_by(email="admin@library.com").first():
        admin = User(name="Admin", email="admin@library.com",
                     password=bcrypt.generate_password_hash("admin123").decode(), role="admin")
        db.session.add(admin)
    if not Book.query.first():
        books = [
            Book(title="The Alchemist", author="Paulo Coelho", genre="Fiction",
                 description="A journey of dreams and destiny.", total_copies=3,
                 available_copies=3, rental_price_per_day=8),
            Book(title="Sapiens", author="Yuval Noah Harari", genre="History",
                 description="A brief history of humankind.", total_copies=2,
                 available_copies=2, rental_price_per_day=10),
            Book(title="Clean Code", author="Robert C. Martin", genre="Technology",
                 description="A handbook of agile software craftsmanship.", total_copies=4,
                 available_copies=4, rental_price_per_day=12),
            Book(title="To Kill a Mockingbird", author="Harper Lee", genre="Fiction",
                 description="A story of justice and moral growth.", total_copies=2,
                 available_copies=2, rental_price_per_day=7),
            Book(title="A Brief History of Time", author="Stephen Hawking", genre="Science",
                 description="Exploring the universe from the Big Bang.", total_copies=3,
                 available_copies=3, rental_price_per_day=9),
        ]
        db.session.add_all(books)
    db.session.commit()


with app.app_context():
    db.create_all()
    seed()


@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard") if current_user.role == "admin" else url_for("customer_dashboard"))
    if request.method == "POST":
        data = request.get_json() or request.form
        user = User.query.filter_by(email=data.get("email")).first()
        if user and bcrypt.check_password_hash(user.password, data.get("password", "")):
            login_user(user)
            return jsonify({"role": user.role, "name": user.name})
        return jsonify({"error": "Invalid email or password"}), 401
    return render_template("login.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    if User.query.filter_by(email=data.get("email")).first():
        return jsonify({"error": "Email already registered"}), 409
    if not all(k in data for k in ["name", "email", "password"]):
        return jsonify({"error": "Name, email and password are required"}), 400
    user = User(
        name=data["name"], email=data["email"],
        password=bcrypt.generate_password_hash(data["password"]).decode(),
        role="customer"
    )
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify({"role": user.role, "name": user.name}), 201

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/health")
def health():
    return "OK", 200

@app.route("/dashboard")
@login_required
def customer_dashboard():
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    return render_template("customer.html")

@app.route("/api/books")
@login_required
def api_books():
    q = request.args.get("q", "").strip()
    genre = request.args.get("genre", "")
    query = Book.query
    if q:
        query = query.filter((Book.title.ilike(f"%{q}%")) | (Book.author.ilike(f"%{q}%")))
    if genre:
        query = query.filter_by(genre=genre)
    return jsonify([b.to_dict() for b in query.all()])

@app.route("/api/rent", methods=["POST"])
@login_required
def rent_book():
    if current_user.role == "admin":
        return jsonify({"error": "Admins cannot rent books"}), 403
    data = request.get_json() or {}
    book_id = data.get("book_id")
    days = int(data.get("days", 7))
    if days < 1 or days > 30:
        return jsonify({"error": "Days must be between 1 and 30"}), 400
    book = Book.query.get(book_id)
    if not book:
        return jsonify({"error": "Book not found"}), 404
    if book.available_copies < 1:
        return jsonify({"error": "No copies available"}), 409
    existing = Rental.query.filter_by(user_id=current_user.id, book_id=book_id, status="active").first()
    if existing:
        return jsonify({"error": "You already have this book rented"}), 409
    from datetime import timedelta
    rental = Rental(
        user_id=current_user.id, book_id=book_id,
        rented_on=date.today(),
        due_date=date.today() + timedelta(days=days),
        status="active"
    )
    book.available_copies -= 1
    db.session.add(rental)
    db.session.commit()
    rentals_counter.inc()
    return jsonify(rental.to_dict()), 201

@app.route("/api/my-rentals")
@login_required
def my_rentals():
    rentals = Rental.query.filter_by(user_id=current_user.id).order_by(Rental.rented_on.desc()).all()
    return jsonify([r.to_dict() for r in rentals])

@app.route("/api/return/<int:rental_id>", methods=["POST"])
@login_required
def return_book(rental_id):
    rental = Rental.query.get_or_404(rental_id)
    if rental.user_id != current_user.id and current_user.role != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    if rental.status != "active":
        return jsonify({"error": "Book already returned"}), 409
    book = Book.query.get(rental.book_id)
    rental.returned_on = date.today()
    rental.status = "returned"
    book.available_copies += 1
    db.session.commit()
    returns_counter.inc()
    return jsonify(rental.to_dict())

@app.route("/api/me")
@login_required
def me():
    return jsonify(current_user.to_dict())

@app.route("/api/genres")
def api_genres():
    return jsonify(["Fiction", "Non-Fiction", "Science", "Biography",
                    "Technology", "History", "Romance", "Mystery", "General"])

@app.route("/admin")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        return redirect(url_for("customer_dashboard"))
    return render_template("admin.html")

@app.route("/api/admin/books", methods=["GET"])
@login_required
def admin_books():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    return jsonify([b.to_dict() for b in Book.query.all()])

@app.route("/api/admin/books", methods=["POST"])
@login_required
def admin_add_book():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json() or {}
    if not all(f in data for f in ["title", "author", "rental_price_per_day"]):
        return jsonify({"error": "Missing required fields"}), 400
    copies = int(data.get("total_copies", 1))
    book = Book(
        title=data["title"], author=data["author"],
        genre=data.get("genre", "General"),
        description=data.get("description", ""),
        total_copies=copies, available_copies=copies,
        rental_price_per_day=float(data["rental_price_per_day"]),
    )
    db.session.add(book)
    db.session.commit()
    return jsonify(book.to_dict()), 201

@app.route("/api/admin/books/<int:bid>", methods=["PUT"])
@login_required
def admin_edit_book(bid):
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    book = Book.query.get_or_404(bid)
    data = request.get_json() or {}
    for f in ["title", "author", "genre", "description"]:
        if f in data:
            setattr(book, f, data[f])
    if "rental_price_per_day" in data:
        book.rental_price_per_day = float(data["rental_price_per_day"])
    if "total_copies" in data:
        diff = int(data["total_copies"]) - book.total_copies
        book.total_copies = int(data["total_copies"])
        book.available_copies = max(0, book.available_copies + diff)
    db.session.commit()
    return jsonify(book.to_dict())

@app.route("/api/admin/books/<int:bid>", methods=["DELETE"])
@login_required
def admin_delete_book(bid):
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    book = Book.query.get_or_404(bid)
    Rental.query.filter_by(book_id=bid).delete()
    db.session.delete(book)
    db.session.commit()
    return "", 204

@app.route("/api/admin/rentals")
@login_required
def admin_rentals():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    status = request.args.get("status")
    query = Rental.query
    if status:
        query = query.filter_by(status=status)
    return jsonify([r.to_dict() for r in query.order_by(Rental.rented_on.desc()).all()])

@app.route("/api/admin/users")
@login_required
def admin_users():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    return jsonify([u.to_dict() for u in User.query.filter_by(role="customer").all()])

@app.route("/api/admin/stats")
@login_required
def admin_stats():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({
        "total_books": Book.query.count(),
        "total_users": User.query.filter_by(role="customer").count(),
        "active_rentals": Rental.query.filter_by(status="active").count(),
        "total_rentals": Rental.query.count(),
        "overdue": Rental.query.filter(Rental.status == "active", Rental.due_date < date.today()).count(),
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)