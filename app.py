from __future__ import annotations

import json
import os
import sqlite3
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "studyai.sqlite3"
DATA_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                content TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER REFERENCES decks(id) ON DELETE SET NULL,
                kind TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                details TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def material_payload(conn: sqlite3.Connection, deck_id: int) -> dict[str, list[Any]]:
    result = {"flashcards": [], "quizzes": [], "tests": [], "questions": [], "summary": [], "key_terms": []}
    rows = conn.execute("SELECT kind, payload FROM materials WHERE deck_id = ?", (deck_id,)).fetchall()
    for row in rows:
        try:
            result.setdefault(row["kind"], []).extend(json.loads(row["payload"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def deck_view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    deck = dict(row)
    deck.update(material_payload(conn, row["id"]))
    return deck


def validate_study_json(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["De JSON moet een object zijn."]
    if value.get("format") != "study-ai":
        errors.append("Het veld format moet exact 'study-ai' zijn.")
    if value.get("version") != 1:
        errors.append("Het veld version moet het getal 1 zijn.")
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata ontbreekt of is geen object.")
    else:
        for key in ("title", "subject", "difficulty"):
            if not isinstance(metadata.get(key), str):
                errors.append(f"metadata.{key} moet tekst zijn.")
    for key in ("flashcards", "quizzes", "tests", "questions", "summary", "key_terms"):
        if not isinstance(value.get(key), list):
            errors.append(f"{key} moet een array zijn.")
    for index, card in enumerate(value.get("flashcards", []) if isinstance(value.get("flashcards"), list) else []):
        if not isinstance(card, dict) or not isinstance(card.get("front"), str) or not isinstance(card.get("back"), str):
            errors.append(f"Flashcard {index + 1} moet front en back als tekst bevatten.")
    for index, quiz in enumerate(value.get("quizzes", []) if isinstance(value.get("quizzes"), list) else []):
        if not isinstance(quiz, dict):
            errors.append(f"Quiz {index + 1} moet een object zijn.")
            continue
        if not isinstance(quiz.get("question"), str):
            errors.append(f"Quiz {index + 1} bevat geen geldige question.")
        options = quiz.get("options")
        if not isinstance(options, list) or len(options) < 2 or not all(isinstance(o, str) for o in options):
            errors.append(f"Quiz {index + 1} moet minimaal twee tekstuele options bevatten.")
        answer = quiz.get("correctAnswer")
        if not isinstance(answer, int) or isinstance(answer, bool):
            errors.append(f"Quiz {index + 1} bevat geen geldig correctAnswer.")
        elif isinstance(options, list) and not 0 <= answer < len(options):
            errors.append(f"correctAnswer van quiz {index + 1} verwijst naar een niet-bestaande optie.")
    for index, question in enumerate(value.get("questions", []) if isinstance(value.get("questions"), list) else []):
        if not isinstance(question, dict) or not isinstance(question.get("question"), str) or not isinstance(question.get("answer"), str):
            errors.append(f"Open vraag {index + 1} moet question en answer als tekst bevatten.")
    for index, test in enumerate(value.get("tests", []) if isinstance(value.get("tests"), list) else []):
        if not isinstance(test, dict):
            errors.append(f"Oefentoets {index + 1} moet een object zijn.")
        elif not isinstance(test.get("title"), str) or not isinstance(test.get("questions"), list):
            errors.append(f"Oefentoets {index + 1} moet title en questions bevatten.")
    return errors


def study_schema() -> dict[str, Any]:
    return {
        "format": "study-ai", "version": 1,
        "metadata": {"title": "", "subject": "", "difficulty": "gemengd"},
        "flashcards": [{"front": "", "back": "", "difficulty": "gemengd"}],
        "quizzes": [{"question": "", "options": ["", ""], "correctAnswer": 0, "explanation": "", "difficulty": "gemengd"}],
        "tests": [{"title": "Oefentoets", "questions": [{"type": "multiple_choice", "question": "", "options": ["", ""], "correctAnswer": 0, "explanation": ""}]}],
        "questions": [{"question": "", "answer": "", "explanation": ""}],
        "summary": [""], "key_terms": [{"term": "", "definition": ""}]
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    with db() as conn:
        subjects = []
        for subject in conn.execute("SELECT * FROM subjects ORDER BY name COLLATE NOCASE").fetchall():
            item = dict(subject)
            decks = [deck_view(conn, row) for row in conn.execute("SELECT * FROM decks WHERE subject_id = ? ORDER BY title COLLATE NOCASE", (subject["id"],)).fetchall()]
            item["decks"] = decks
            item["deck_count"] = len(decks)
            item["flashcard_count"] = sum(len(d["flashcards"]) for d in decks)
            subjects.append(item)
        results = [dict(r) for r in conn.execute("SELECT * FROM results ORDER BY created_at DESC LIMIT 12").fetchall()]
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings").fetchall()}
        stats = {
            "subjects": len(subjects), "decks": sum(s["deck_count"] for s in subjects),
            "flashcards": sum(s["flashcard_count"] for s in subjects), "results": len(results)
        }
        return jsonify({"subjects": subjects, "results": results, "settings": settings, "stats": stats})


@app.post("/api/subjects")
def create_subject():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 120:
        return jsonify(error="Geef een vaknaam van maximaal 120 tekens op."), 400
    with db() as conn:
        cur = conn.execute("INSERT INTO subjects(name, description, created_at) VALUES (?, ?, ?)", (name, str(data.get("description", ""))[:500], now()))
        return jsonify(id=cur.lastrowid, message="Vak opgeslagen.")


@app.patch("/api/subjects/<int:subject_id>")
def update_subject(subject_id: int):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify(error="Een vaknaam mag niet leeg zijn."), 400
    with db() as conn:
        if not conn.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone():
            return jsonify(error="Vak niet gevonden."), 404
        conn.execute("UPDATE subjects SET name = ?, description = ? WHERE id = ?", (name[:120], str(data.get("description", ""))[:500], subject_id))
    return jsonify(message="Vak bijgewerkt.")


@app.delete("/api/subjects/<int:subject_id>")
def delete_subject(subject_id: int):
    with db() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
    return jsonify(message="Vak verwijderd.")


@app.post("/api/decks")
def create_deck():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    subject_id = data.get("subject_id")
    if not title or not isinstance(subject_id, int):
        return jsonify(error="Een deck heeft een titel en een geldig vak nodig."), 400
    with db() as conn:
        if not conn.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone():
            return jsonify(error="Vak niet gevonden."), 404
        cur = conn.execute("INSERT INTO decks(subject_id,title,description,content,created_at,updated_at) VALUES(?,?,?,?,?,?)", (subject_id, title[:160], str(data.get("description", ""))[:600], str(data.get("content", "")), now(), now()))
    return jsonify(id=cur.lastrowid, message="Deck opgeslagen.")


@app.patch("/api/decks/<int:deck_id>")
def update_deck(deck_id: int):
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify(error="Een decktitel mag niet leeg zijn."), 400
    with db() as conn:
        if not conn.execute("SELECT id FROM decks WHERE id = ?", (deck_id,)).fetchone():
            return jsonify(error="Deck niet gevonden."), 404
        conn.execute("UPDATE decks SET title=?, description=?, content=?, updated_at=? WHERE id=?", (title[:160], str(data.get("description", ""))[:600], str(data.get("content", "")), now(), deck_id))
    return jsonify(message="Deck bijgewerkt.")


@app.delete("/api/decks/<int:deck_id>")
def delete_deck(deck_id: int):
    with db() as conn:
        conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    return jsonify(message="Deck verwijderd.")


@app.post("/api/import")
def import_material():
    data = request.get_json(silent=True) or {}
    value = data.get("data")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            return jsonify(errors=[f"Ongeldige JSON op regel {exc.lineno}, kolom {exc.colno}: {exc.msg}."]), 400
    errors = validate_study_json(value)
    if errors:
        return jsonify(errors=errors), 400
    return jsonify(valid=True, preview={
        "title": value["metadata"]["title"], "subject": value["metadata"]["subject"],
        "difficulty": value["metadata"]["difficulty"], "flashcards": len(value["flashcards"]),
        "quizzes": len(value["quizzes"]), "tests": len(value["tests"]), "questions": len(value["questions"]), "key_terms": len(value["key_terms"])
    })


@app.post("/api/import/commit")
def commit_import():
    data = request.get_json(silent=True) or {}
    value = data.get("data")
    if isinstance(value, str):
        try: value = json.loads(value)
        except json.JSONDecodeError: return jsonify(error="De JSON kan niet worden gelezen."), 400
    errors = validate_study_json(value)
    if errors: return jsonify(errors=errors), 400
    subject_name = value["metadata"]["subject"].strip() or "Ongeordend"
    deck_title = value["metadata"]["title"].strip() or "Geïmporteerd materiaal"
    with db() as conn:
        subject = conn.execute("SELECT id FROM subjects WHERE name = ?", (subject_name,)).fetchone()
        if not subject:
            cur = conn.execute("INSERT INTO subjects(name, created_at) VALUES (?, ?)", (subject_name, now()))
            subject_id = cur.lastrowid
        else: subject_id = subject["id"]
        cur = conn.execute("INSERT INTO decks(subject_id,title,description,content,created_at,updated_at) VALUES(?,?,?,?,?,?)", (subject_id, deck_title, "Geïmporteerd via AI Studio", "", now(), now()))
        deck_id = cur.lastrowid
        for kind in ("flashcards", "quizzes", "tests", "questions", "summary", "key_terms"):
            if value[kind]: conn.execute("INSERT INTO materials(deck_id,kind,payload,created_at) VALUES(?,?,?,?)", (deck_id, kind, json.dumps(value[kind], ensure_ascii=False), now()))
    return jsonify(message="Studiepakket geïmporteerd.", deck_id=deck_id)


@app.get("/api/export")
def export_data():
    with db() as conn:
        payload = {"format": "study-ai-workspace", "version": 1, "exportedAt": now(), "subjects": []}
        for subject in conn.execute("SELECT * FROM subjects ORDER BY id").fetchall():
            item = {"name": subject["name"], "description": subject["description"], "decks": []}
            for deck in conn.execute("SELECT * FROM decks WHERE subject_id = ?", (subject["id"],)).fetchall():
                d = deck_view(conn, deck); item["decks"].append({"title": d["title"], "description": d["description"], "content": d["content"], "materials": {k: d[k] for k in ("flashcards", "quizzes", "tests", "questions", "summary", "key_terms")} })
            payload["subjects"].append(item)
    out = DATA_DIR / "studyai-export.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return send_file(out, as_attachment=True, download_name="studyai-export.json", mimetype="application/json")


@app.post("/api/results")
def save_result():
    data = request.get_json(silent=True) or {}
    try:
        score, total = int(data.get("score")), int(data.get("total"))
    except (TypeError, ValueError):
        return jsonify(error="Score en totaal moeten getallen zijn."), 400
    if total < 1 or score < 0 or score > total: return jsonify(error="Ongeldig resultaat."), 400
    with db() as conn:
        conn.execute("INSERT INTO results(deck_id,kind,score,total,details,created_at) VALUES(?,?,?,?,?,?)", (data.get("deck_id"), str(data.get("kind", "quiz"))[:30], score, total, json.dumps(data.get("details", {}), ensure_ascii=False), now()))
    return jsonify(message="Resultaat opgeslagen.")


@app.post("/api/settings")
def save_settings():
    data = request.get_json(silent=True) or {}
    with db() as conn:
        for key, value in data.items():
            if key in ("theme", "confirmations"): conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    return jsonify(message="Instellingen opgeslagen.")


@app.post("/api/reset")
def reset_data():
    with db() as conn:
        conn.executescript("DELETE FROM results; DELETE FROM materials; DELETE FROM decks; DELETE FROM subjects; DELETE FROM settings;")
    return jsonify(message="Alle lokale data verwijderd.")


@app.post("/api/demo")
def demo_data():
    with db() as conn:
        cur = conn.execute("INSERT INTO subjects(name,description,created_at) VALUES(?,?,?)", ("Biologie", "Voorbeelddata — veilig te verwijderen.", now())); subject_id = cur.lastrowid
        cur = conn.execute("INSERT INTO decks(subject_id,title,description,content,created_at,updated_at) VALUES(?,?,?,?,?,?)", (subject_id, "Ademhaling", "Voorbeelddeck", "Gaswisseling vindt plaats in de longblaasjes.", now(), now())); deck_id = cur.lastrowid
        cards = [{"front":"Waar vindt gaswisseling plaats?","back":"In de longblaasjes.","difficulty":"basis"},{"front":"Wat is de functie van zuurstof?","back":"Zuurstof wordt gebruikt bij verbranding om energie vrij te maken.","difficulty":"basis"}]
        quiz = [{"question":"Waar vindt gaswisseling plaats?","options":["In de maag","In de longblaasjes","In de nieren"],"correctAnswer":1,"explanation":"De longblaasjes hebben een groot oppervlak voor gaswisseling.","difficulty":"basis"}]
        conn.execute("INSERT INTO materials(deck_id,kind,payload,created_at) VALUES(?,?,?,?)", (deck_id,"flashcards",json.dumps(cards),now()))
        conn.execute("INSERT INTO materials(deck_id,kind,payload,created_at) VALUES(?,?,?,?)", (deck_id,"quizzes",json.dumps(quiz),now()))
    return jsonify(message="Voorbeelddata geladen.")


init_db()

if __name__ == "__main__":
    if os.environ.get("STUDYAI_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    app.run(host="127.0.0.1", port=8000, debug=False)
