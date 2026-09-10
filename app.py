import os
import json
import sqlite3
import uuid
from io import BytesIO
import qrcode
from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response, send_file

app = Flask(__name__)

DB_PATH = 'poll.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    # Enable WAL mode for better concurrency
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id TEXT NOT NULL,
            voter_id TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            UNIQUE(question_id, voter_id)
        )
    ''')
    
    # Store the current active question index in the DB
    conn.execute('''
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.execute('INSERT OR IGNORE INTO state (key, value) VALUES ("active_question", "0")')
    conn.commit()
    conn.close()

init_db()

# Load questions
with open('questions.json', 'r') as f:
    QUESTIONS = json.load(f)

def get_active_question_index():
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM state WHERE key="active_question"').fetchone()
    conn.close()
    return int(row['value']) if row else 0

def set_active_question_index(idx):
    conn = get_db_connection()
    conn.execute('UPDATE state SET value=? WHERE key="active_question"', (str(idx),))
    conn.commit()
    conn.close()

@app.route('/')
def index():
    # Public URL for voters
    active_idx = get_active_question_index()
    if active_idx >= len(QUESTIONS):
        return render_template('voter.html', question=None, message="Poll has ended!")
    
    question = QUESTIONS[active_idx]
    return render_template('voter.html', question=question, q_idx=active_idx)

@app.route('/vote', methods=['POST'])
def vote():
    data = request.json
    question_id = data.get('question_id')
    option_index = data.get('option_index')
    voter_id = data.get('voter_id')
    
    if not voter_id:
        return jsonify({'error': 'No voter ID found'}), 400

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO votes (question_id, voter_id, option_index) VALUES (?, ?, ?)',
                     (question_id, voter_id, option_index))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        # User already voted for this question
        return jsonify({'error': 'You have already voted for this question.'}), 409
    finally:
        conn.close()

@app.route('/results')
def results_page():
    return render_template('results.html')

@app.route('/api/results')
def api_results():
    active_idx = get_active_question_index()
    if active_idx >= len(QUESTIONS):
        return jsonify({'status': 'ended', 'question': None})
    
    question = QUESTIONS[active_idx]
    
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT option_index, COUNT(*) as count FROM votes WHERE question_id=? GROUP BY option_index',
        (question['id'],)
    ).fetchall()
    conn.close()
    
    counts = {row['option_index']: row['count'] for row in rows}
    results = [counts.get(i, 0) for i in range(len(question['options']))]
    
    return jsonify({
        'status': 'active',
        'question_text': question['text'],
        'labels': question['options'],
        'data': results
    })

@app.route('/admin')
def admin_page():
    active_idx = get_active_question_index()
    host = request.host_url
    return render_template('admin.html', 
                           questions=QUESTIONS, 
                           active_idx=active_idx, 
                           host=host)

@app.route('/admin/next', methods=['POST'])
def next_question():
    active_idx = get_active_question_index()
    set_active_question_index(active_idx + 1)
    return redirect(url_for('admin_page'))

@app.route('/admin/reset', methods=['POST'])
def reset_question():
    set_active_question_index(0)
    conn = get_db_connection()
    conn.execute('DELETE FROM votes')
    conn.commit()
    conn.close()
    return redirect(url_for('admin_page'))

@app.route('/qr.png')
def qr_code():
    url = request.host_url
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
