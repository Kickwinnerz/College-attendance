from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash, jsonify
import sqlite3
from datetime import date
import csv
import io
import os

APP_SECRET = os.environ.get("APP_SECRET", "change_this_secret")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "12345")

app = Flask(__name__)
app.secret_key = APP_SECRET
DB = "attendance.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        roll_no TEXT
    );
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        year INTEGER NOT NULL,
        status TEXT NOT NULL,
        UNIQUE(student_id, date),
        FOREIGN KEY(student_id) REFERENCES students(id)
    );
    """)
    conn.commit()
    conn.close()

@app.before_first_request
def setup():
    init_db()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("teacher_logged"):
            return f(*args, **kwargs)
        return redirect(url_for("login"))
    return wrapped

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password","")
        if pw == TEACHER_PASSWORD:
            session["teacher_logged"] = True
            return redirect(url_for("index"))
        flash("Password wrong", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students ORDER BY roll_no, name")
    students = cur.fetchall()
    today = date.today().isoformat()
    return render_template("index.html", students=students, today=today)

@app.route("/students/add", methods=["POST"])
@login_required
def add_student():
    name = request.form.get("name","").strip()
    roll = request.form.get("roll_no","").strip()
    if not name:
        flash("Name required", "error")
        return redirect(url_for("index"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO students (name, roll_no) VALUES (?, ?)", (name, roll))
    conn.commit()
    return redirect(url_for("index"))

@app.route("/attendance/mark", methods=["POST"])
@login_required
def mark_attendance():
    data = request.json
    when = data.get("date")
    year = int(data.get("year"))
    marks = data.get("marks")
    conn = get_db()
    cur = conn.cursor()
    for sid, status in marks.items():
        cur.execute("""
            INSERT INTO attendance (student_id, date, year, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(student_id, date) DO UPDATE SET status=excluded.status
        """, (int(sid), when, year, status))
    conn.commit()
    return jsonify({"ok": True})

@app.route("/attendance/view")
@login_required
def view_attendance():
    qdate = request.args.get("date")
    year = request.args.get("year")
    conn = get_db()
    cur = conn.cursor()
    if qdate:
        cur.execute("""
            SELECT a.*, s.name, s.roll_no FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE a.date=?
            ORDER BY s.roll_no, s.name
        """, (qdate,))
        rows = cur.fetchall()
        return render_template("view_date.html", rows=rows, qdate=qdate)
    if year:
        cur.execute("""
            SELECT s.id as student_id, s.name, s.roll_no,
            SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as presents,
            COUNT(a.id) as total_marks
            FROM students s
            LEFT JOIN attendance a ON a.student_id = s.id AND a.year=?
            GROUP BY s.id ORDER BY s.roll_no, s.name
        """, (int(year),))
        rows = cur.fetchall()
        return render_template("view_year.html", rows=rows, year=year)
    flash("Select date or year to view", "info")
    return redirect(url_for("index"))

@app.route("/export/year/<int:year>")
@login_required
def export_year(year):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, roll_no FROM students ORDER BY roll_no, name")
    students = cur.fetchall()
    cur.execute("SELECT DISTINCT date FROM attendance WHERE year=? ORDER BY date", (year,))
    dates = [r["date"] for r in cur.fetchall()]
    output = io.StringIO()
    writer = csv.writer(output)
    header = ["Student ID", "Name", "Roll No"] + dates
    writer.writerow(header)
    for s in students:
        row = [s["id"], s["name"], s["roll_no"]]
        for d in dates:
            cur.execute("SELECT status FROM attendance WHERE student_id=? AND date=?", (s["id"], d))
            r = cur.fetchone()
            row.append(r["status"] if r else "")
        writer.writerow(row)
    output.seek(0)
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8"))
    mem.seek(0)
    filename = f"attendance_{year}.csv"
    return send_file(mem, mimetype="text/csv", download_name=filename, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)