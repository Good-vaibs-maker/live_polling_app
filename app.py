import os
import json
import sqlite3
import uuid
from io import BytesIO
import qrcode
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file

app = Flask(__name__)
DB_PATH = 'poll.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            options TEXT NOT NULL,
            sort_order INTEGER NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Check if questions table is empty, if so load from json
    count = conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    if count == 0:
        if os.path.exists('questions.json'):
            with open('questions.json', 'r') as f:
                questions_data = json.load(f)
                for i, q in enumerate(questions_data):
                    conn.execute('INSERT INTO questions (id, text, options, sort_order) VALUES (?, ?, ?, ?)',
                                 (q['id'], q['text'], json.dumps(q['options']), i))
    
    # Initialize active question to empty string if not set
    conn.execute('INSERT OR IGNORE INTO state (key, value) VALUES ("active_question_id", "")')
    
    # Migrate from old "active_question" (index) if it exists and active_question_id is empty
    old_active = conn.execute('SELECT value FROM state WHERE key="active_question"').fetchone()
    current_active = conn.execute('SELECT value FROM state WHERE key="active_question_id"').fetchone()
    
    if old_active and (not current_active or current_active['value'] == ""):
        try:
            idx = int(old_active['value'])
            q_at_idx = conn.execute('SELECT id FROM questions ORDER BY sort_order LIMIT 1 OFFSET ?', (idx,)).fetchone()
            if q_at_idx:
                conn.execute('UPDATE state SET value=? WHERE key="active_question_id"', (q_at_idx['id'],))
        except ValueError:
            pass

    conn.commit()
    conn.close()

init_db()

def get_active_question_id():
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM state WHERE key="active_question_id"').fetchone()
    conn.close()
    return row['value'] if row else ""

def set_active_question_id(q_id):
    conn = get_db_connection()
    conn.execute('UPDATE state SET value=? WHERE key="active_question_id"', (q_id,))
    conn.commit()
    conn.close()

def get_question(q_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM questions WHERE id=?', (q_id,)).fetchone()
    conn.close()
    if row:
        return {'id': row['id'], 'text': row['text'], 'options': json.loads(row['options']), 'sort_order': row['sort_order']}
    return None

def get_all_questions():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM questions ORDER BY sort_order').fetchall()
    conn.close()
    return [{'id': r['id'], 'text': r['text'], 'options': json.loads(r['options']), 'sort_order': r['sort_order']} for r in rows]

@app.route('/')
def index():
    return render_template('voter.html')

@app.route('/api/voter/current')
def api_voter_current():
    active_id = get_active_question_id()
    if not active_id:
        return jsonify({'status': 'ended', 'question': None})
    
    question = get_question(active_id)
    if not question:
        return jsonify({'status': 'ended', 'question': None})
        
    return jsonify({
        'status': 'active',
        'question': question
    })

@app.route('/vote', methods=['POST'])
def vote():
    data = request.json
    question_id = data.get('question_id')
    option_index = data.get('option_index')
    voter_id = data.get('voter_id')
    
    if not voter_id:
        return jsonify({'error': 'No voter ID found'}), 400

    active_id = get_active_question_id()
    if question_id != active_id:
        return jsonify({'error': 'Voting for this question is closed.'}), 400

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO votes (question_id, voter_id, option_index) VALUES (?, ?, ?)',
                     (question_id, voter_id, option_index))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'You have already voted for this question.'}), 409
    finally:
        conn.close()

@app.route('/results')
def results_page():
    return render_template('results.html')

@app.route('/join')
def join_page():
    return render_template('join.html')

@app.route('/api/results')
def api_results():
    active_id = get_active_question_id()
    if not active_id:
        return jsonify({'status': 'ended', 'question': None})
    
    question = get_question(active_id)
    if not question:
        return jsonify({'status': 'ended', 'question': None})
    
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

# --- Admin API Routes ---

@app.route('/admin')
def admin_page():
    host = request.host_url
    return render_template('admin.html', host=host)

@app.route('/api/questions', methods=['GET'])
def get_questions():
    questions = get_all_questions()
    active_id = get_active_question_id()
    return jsonify({
        'questions': questions,
        'active_question_id': active_id
    })

@app.route('/api/questions', methods=['POST'])
def create_question():
    data = request.json
    text = data.get('text', '').strip()
    options = [o.strip() for o in data.get('options', []) if o.strip()]
    
    if not text:
        return jsonify({'error': 'Question text cannot be empty'}), 400
    if len(options) < 2 or len(options) > 6:
        return jsonify({'error': 'Questions must have between 2 and 6 options'}), 400
        
    q_id = 'q_' + str(uuid.uuid4())[:8]
    
    conn = get_db_connection()
    max_sort = conn.execute('SELECT MAX(sort_order) FROM questions').fetchone()[0]
    next_sort = 0 if max_sort is None else max_sort + 1
    
    conn.execute('INSERT INTO questions (id, text, options, sort_order) VALUES (?, ?, ?, ?)',
                 (q_id, text, json.dumps(options), next_sort))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'id': q_id})

@app.route('/api/questions/<q_id>', methods=['PUT'])
def update_question(q_id):
    data = request.json
    text = data.get('text', '').strip()
    options = [o.strip() for o in data.get('options', []) if o.strip()]
    
    if not text:
        return jsonify({'error': 'Question text cannot be empty'}), 400
    if len(options) < 2 or len(options) > 6:
        return jsonify({'error': 'Questions must have between 2 and 6 options'}), 400
        
    conn = get_db_connection()
    conn.execute('UPDATE questions SET text=?, options=? WHERE id=?', (text, json.dumps(options), q_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/questions/<q_id>', methods=['DELETE'])
def delete_question(q_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM questions WHERE id=?', (q_id,))
    # Clean up votes for this question to keep DB small? Optional.
    conn.execute('DELETE FROM votes WHERE question_id=?', (q_id,))
    
    active_id = get_active_question_id()
    if active_id == q_id:
        set_active_question_id("")
        
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/questions/reorder', methods=['POST'])
def reorder_questions():
    data = request.json
    ordered_ids = data.get('ordered_ids', [])
    
    conn = get_db_connection()
    for i, q_id in enumerate(ordered_ids):
        conn.execute('UPDATE questions SET sort_order=? WHERE id=?', (i, q_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/questions/<q_id>/activate', methods=['POST'])
def activate_question(q_id):
    set_active_question_id(q_id)
    return jsonify({'success': True})

@app.route('/api/questions/next', methods=['POST'])
def activate_next_question():
    active_id = get_active_question_id()
    questions = get_all_questions()
    
    if not questions:
        set_active_question_id("")
        return jsonify({'success': True})
        
    if not active_id:
        set_active_question_id(questions[0]['id'])
        return jsonify({'success': True})
        
    # Find next question in sequence
    found_current = False
    next_id = None
    for q in questions:
        if found_current:
            next_id = q['id']
            break
        if q['id'] == active_id:
            found_current = True
            
    if next_id:
        set_active_question_id(next_id)
    else:
        # Ended
        set_active_question_id("")
        
    return jsonify({'success': True})

@app.route('/api/questions/<q_id>/votes/count', methods=['GET'])
def get_vote_count(q_id):
    conn = get_db_connection()
    count = conn.execute('SELECT COUNT(*) FROM votes WHERE question_id=?', (q_id,)).fetchone()[0]
    conn.close()
    return jsonify({'count': count})

@app.route('/admin/reset', methods=['POST'])
def reset_question():
    questions = get_all_questions()
    if questions:
        set_active_question_id(questions[0]['id'])
    else:
        set_active_question_id("")
        
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
