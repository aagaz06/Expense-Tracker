from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
from datetime import datetime, date
import sqlite3, hashlib, csv, io, calendar

app = Flask(__name__)
app.secret_key = 'leaktracker_2024_secret'

DB = 'leaktracker.db'
CATEGORIES = ['Food', 'Transport', 'Entertainment', 'Shopping', 'Health', 'Utilities', 'Other']

# ══════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        monthly_budget REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        date TEXT NOT NULL,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        "limit" REAL NOT NULL,
        UNIQUE(user_id, category),
        FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

# ══════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def get_months(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT strftime('%Y-%m', date) as ym FROM expenses WHERE user_id=? ORDER BY ym DESC",
        (user_id,)).fetchall()
    conn.close()
    months = []
    for r in rows:
        try:
            dt = datetime.strptime(r['ym'], '%Y-%m')
            months.append({'value': r['ym'], 'label': dt.strftime('%B %Y')})
        except: pass
    if not months:
        now = datetime.now()
        months = [{'value': now.strftime('%Y-%m'), 'label': now.strftime('%B %Y')}]
    return months

def calc_health(spent, budget, leaks):
    if budget == 0:
        score = max(0, 60 - len(leaks) * 10)
    else:
        score = max(0, int(100 - (spent/budget)*60 - len(leaks)*8))
    score = min(100, score)
    if score >= 80: return score, 'excellent', 'Excellent'
    elif score >= 60: return score, 'good', 'Good'
    elif score >= 40: return score, 'warning', 'Fair'
    else: return score, 'critical', 'Critical'

def get_leaks(user_id, month):
    conn = get_db()
    leaks = []
    rows = conn.execute('''SELECT category, COUNT(*) as cnt, SUM(amount) as total
        FROM expenses WHERE user_id=? AND strftime('%Y-%m', date)=?
        GROUP BY category HAVING cnt > 8''', (user_id, month)).fetchall()
    for r in rows:
        leaks.append({'title': f'Too many {r["category"]} transactions',
            'desc': f'{r["cnt"]} purchases this month',
            'amount': round(r['total'], 0), 'icon': 'fire',
            'frequency': f'{r["cnt"]} transactions'})
    for b in conn.execute('SELECT * FROM budgets WHERE user_id=?', (user_id,)).fetchall():
        s = conn.execute('''SELECT SUM(amount) as s FROM expenses
            WHERE user_id=? AND category=? AND strftime('%Y-%m', date)=?''',
            (user_id, b['category'], month)).fetchone()
        spent = s['s'] or 0
        if spent > b['limit']:
            leaks.append({'title': f'{b["category"]} over budget',
                'desc': f'Spent Rs.{round(spent)} vs limit Rs.{round(b["limit"])}',
                'amount': round(spent - b['limit'], 0),
                'icon': 'triangle-exclamation', 'frequency': 'Over limit'})
    conn.close()
    return leaks

# ══════════════════════════════════════
#  AUTH
# ══════════════════════════════════════
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        pw = request.form.get('password', '')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email=? AND password=?',
                            (email, hash_pw(pw))).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['email'] = user['email']
            return redirect(url_for('dashboard'))
        flash('Wrong email or password!', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        pw = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        budget = float(request.form.get('monthly_budget', 0) or 0)
        if not username or not email or not pw:
            flash('All fields required!', 'danger')
        elif pw != confirm:
            flash('Passwords do not match!', 'danger')
        elif len(pw) < 6:
            flash('Password must be at least 6 characters!', 'danger')
        else:
            try:
                conn = get_db()
                conn.execute('INSERT INTO users (username,email,password,monthly_budget) VALUES (?,?,?,?)',
                             (username, email, hash_pw(pw), budget))
                conn.commit(); conn.close()
                flash('Account created! Please login.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('Email already registered!', 'danger')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ══════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════
@app.route('/')
@login_required
def dashboard():
    uid = session['user_id']
    months = get_months(uid)
    cur = request.args.get('month', months[0]['value'])
    conn = get_db()

    total_spent = round(conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?",
        (uid, cur)).fetchone()['s'], 2)

    user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    total_budget = user['monthly_budget'] or 0

    leaks = get_leaks(uid, cur)
    score, hclass, hlabel = calc_health(total_spent, total_budget, leaks)

    daily = conn.execute(
        "SELECT strftime('%d',date) as day, SUM(amount) as amount FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=? GROUP BY day ORDER BY day",
        (uid, cur)).fetchall()

    cats = conn.execute(
        "SELECT category, SUM(amount) as amount FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=? GROUP BY category ORDER BY amount DESC",
        (uid, cur)).fetchall()

    recent = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=? ORDER BY date DESC LIMIT 8",
        (uid, cur)).fetchall()

    budgets = []
    for b in conn.execute('SELECT * FROM budgets WHERE user_id=?', (uid,)).fetchall():
        sp = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND category=? AND strftime('%Y-%m',date)=?",
            (uid, b['category'], cur)).fetchone()['s']
        lim = b['limit']
        budgets.append({'category': b['category'], 'spent': round(sp,2), 'limit': lim,
                        'pct': min(100, round(sp/lim*100)) if lim > 0 else 0})
    conn.close()

    return render_template('dashboard.html',
        current_month=cur, available_months=months,
        stats={'total_spent': total_spent, 'total_budget': total_budget,
               'health_score': score, 'health_class': hclass, 'health_label': hlabel,
               'leaks_found': len(leaks)},
        daily_spending=[{'day': r['day'], 'amount': round(r['amount'],2)} for r in daily],
        category_breakdown=[{'name': r['category'], 'amount': round(r['amount'],2)} for r in cats],
        recent_expenses=[dict(r) for r in recent],
        leaks=leaks, budgets=budgets)

# ══════════════════════════════════════
#  EXPENSES
# ══════════════════════════════════════
@app.route('/expenses')
@login_required
def expenses():
    uid = session['user_id']
    months = get_months(uid)
    search = request.args.get('search', '')
    cat = request.args.get('category', '')
    month = request.args.get('month', months[0]['value'])
    sort = request.args.get('sort', 'date_desc')
    order = {'date_desc':'date DESC','date_asc':'date ASC','amount_desc':'amount DESC','amount_asc':'amount ASC'}.get(sort,'date DESC')

    q = "SELECT * FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?"
    p = [uid, month]
    if search: q += " AND description LIKE ?"; p.append(f'%{search}%')
    if cat: q += " AND category=?"; p.append(cat)
    q += f" ORDER BY {order}"

    conn = get_db()
    rows = [dict(r) for r in conn.execute(q, p).fetchall()]
    total = sum(r['amount'] for r in rows)
    conn.close()

    return render_template('expenses.html',
        expenses=rows, categories=CATEGORIES, available_months=months,
        filters={'search':search,'category':cat,'month':month,'sort':sort},
        summary={'total':round(total,2),'count':len(rows),'avg_day':round(total/30,2)},
        today=date.today().isoformat())

@app.route('/expenses/add', methods=['POST'])
@login_required
def add_expense():
    uid = session['user_id']
    desc = request.form.get('description','').strip()
    amt = request.form.get('amount', 0)
    cat = request.form.get('category','Other')
    dt = request.form.get('date', date.today().isoformat())
    note = request.form.get('note','').strip()
    if desc and amt:
        conn = get_db()
        conn.execute('INSERT INTO expenses (user_id,description,amount,category,date,note) VALUES (?,?,?,?,?,?)',
                     (uid, desc, float(amt), cat, dt, note))
        conn.commit(); conn.close()
        flash('✓ Expense added successfully!', 'success')
    else:
        flash('Description and amount are required!', 'danger')
    return redirect(url_for('expenses', month=dt[:7]))

@app.route('/expenses/edit/<int:id>', methods=['POST'])
@login_required
def edit_expense(id):
    uid = session['user_id']
    conn = get_db()
    conn.execute('''UPDATE expenses SET description=?,amount=?,category=?,date=?,note=?
        WHERE id=? AND user_id=?''',
        (request.form.get('description'), float(request.form.get('amount',0)),
         request.form.get('category'), request.form.get('date'),
         request.form.get('note',''), id, uid))
    conn.commit(); conn.close()
    flash('✓ Expense updated!', 'success')
    return redirect(url_for('expenses'))

@app.route('/expenses/delete/<int:id>', methods=['POST'])
@login_required
def delete_expense(id):
    conn = get_db()
    conn.execute('DELETE FROM expenses WHERE id=? AND user_id=?', (id, session['user_id']))
    conn.commit(); conn.close()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))

@app.route('/expenses/export')
@login_required
def export_expenses():
    conn = get_db()
    rows = conn.execute('SELECT description,amount,category,date,note FROM expenses WHERE user_id=? ORDER BY date DESC',
                        (session['user_id'],)).fetchall()
    conn.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Description','Amount','Category','Date','Note'])
    for r in rows: w.writerow([r['description'],r['amount'],r['category'],r['date'],r['note'] or ''])
    resp = make_response(out.getvalue())
    resp.headers['Content-Disposition'] = 'attachment; filename=expenses.csv'
    resp.headers['Content-Type'] = 'text/csv'
    return resp

# ══════════════════════════════════════
#  BUDGETS
# ══════════════════════════════════════
@app.route('/budgets')
@login_required
def budgets():
    uid = session['user_id']
    cur = datetime.now().strftime('%Y-%m')
    conn = get_db()
    rows = conn.execute('SELECT * FROM budgets WHERE user_id=?', (uid,)).fetchall()
    blist = []; tb = 0; ts = 0
    for b in rows:
        sp = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND category=? AND strftime('%Y-%m',date)=?",
            (uid, b['category'], cur)).fetchone()['s']
        lim = b['limit']; tb += lim; ts += sp
        blist.append({'id':b['id'],'category':b['category'],'spent':round(sp,2),'limit':lim,
            'remaining':round(lim-sp,2),'pct':min(100,round(sp/lim*100)) if lim>0 else 0})
    conn.close()
    now = datetime.now()
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day
    overall = {'total':round(tb,2),'spent':round(ts,2),'remaining':round(tb-ts,2),
               'pct':min(100,round(ts/tb*100)) if tb>0 else 0,'days_left':days_left}
    used = [b['category'] for b in blist]
    return render_template('budgets.html', budgets=blist, overall=overall,
                           available_categories=[c for c in CATEGORIES if c not in used])

@app.route('/budgets/add', methods=['POST'])
@login_required
def add_budget():
    uid = session['user_id']
    cat = request.form.get('category')
    lim = request.form.get('limit', 0)
    if cat and lim:
        conn = get_db()
        try:
            conn.execute('INSERT INTO budgets (user_id,category,"limit") VALUES (?,?,?)',
                         (uid, cat, float(lim)))
            conn.commit()
            flash(f'✓ Budget set for {cat}!', 'success')
        except sqlite3.IntegrityError:
            flash(f'Budget for {cat} already exists!', 'danger')
        finally:
            conn.close()
    return redirect(url_for('budgets'))

@app.route('/budgets/edit/<int:id>', methods=['POST'])
@login_required
def edit_budget(id):
    lim = request.form.get('limit', 0)
    conn = get_db()
    conn.execute('UPDATE budgets SET "limit"=? WHERE id=? AND user_id=?',
                 (float(lim), id, session['user_id']))
    conn.commit(); conn.close()
    flash('✓ Budget updated!', 'success')
    return redirect(url_for('budgets'))

@app.route('/budgets/delete/<int:id>', methods=['POST'])
@login_required
def delete_budget(id):
    conn = get_db()
    conn.execute('DELETE FROM budgets WHERE id=? AND user_id=?', (id, session['user_id']))
    conn.commit(); conn.close()
    flash('Budget removed.', 'success')
    return redirect(url_for('budgets'))

# ══════════════════════════════════════
#  ANALYTICS
# ══════════════════════════════════════
@app.route('/analytics')
@login_required
def analytics():
    uid = session['user_id']
    months = get_months(uid)
    cur = request.args.get('month', months[0]['value'])
    conn = get_db()

    row = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s, COUNT(*) as cnt FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?",
        (uid, cur)).fetchone()
    total_spent = round(row['s'], 2); tx_count = row['cnt']

    yr, mn = int(cur[:4]), int(cur[5:])
    lm = f'{yr-1}-12' if mn==1 else f'{yr}-{mn-1:02d}'
    last = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?",
        (uid, lm)).fetchone()['s']
    mom = round((total_spent-last)/last*100,1) if last>0 else 0

    trend = []
    for i in range(5,-1,-1):
        m=mn-i; y=yr
        while m<=0: m+=12; y-=1
        ms=f'{y}-{m:02d}'
        amt=conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?",(uid,ms)).fetchone()['s']
        trend.append({'month':datetime.strptime(ms,'%Y-%m').strftime('%b'),'amount':round(amt,2)})

    cats = conn.execute(
        "SELECT category,SUM(amount) as amount FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=? GROUP BY category ORDER BY amount DESC LIMIT 5",
        (uid,cur)).fetchall()
    mx = max((r['amount'] for r in cats),default=1)
    top_cats = [{'name':r['category'],'amount':round(r['amount'],2),'pct':round(r['amount']/mx*100)} for r in cats]

    dm={0:'Mon',1:'Tue',2:'Wed',3:'Thu',4:'Fri',5:'Sat',6:'Sun'}
    wd={v:0 for v in dm.values()}
    for e in conn.execute("SELECT date,amount FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?",(uid,cur)).fetchall():
        try: wd[dm[datetime.strptime(e['date'],'%Y-%m-%d').weekday()]]+=e['amount']
        except: pass

    top_exp = [dict(r) for r in conn.execute(
        "SELECT description,category,amount FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=? ORDER BY amount DESC LIMIT 6",
        (uid,cur)).fetchall()]
    conn.close()

    return render_template('analytics.html',
        current_month=cur, available_months=months,
        metrics={'total_spent':total_spent,'avg_daily':round(total_spent/30,2),'mom_change':mom,'tx_count':tx_count},
        monthly_trend=trend, top_categories=top_cats,
        weekday_data=[{'day':k,'amount':round(v,2)} for k,v in wd.items()],
        top_expenses=top_exp)

# ══════════════════════════════════════
#  SUGGESTIONS
# ══════════════════════════════════════
@app.route('/suggestions')
@login_required
def suggestions():
    uid = session['user_id']
    cur = datetime.now().strftime('%Y-%m')
    conn = get_db()
    leaks = get_leaks(uid, cur)

    cats = conn.execute(
        "SELECT category,SUM(amount) as amount FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=? GROUP BY category",
        (uid,cur)).fetchall()
    cat_spend = {r['category']:r['amount'] for r in cats}

    tips = {'Food':('Cook at home more','Meal prepping reduces food expenses by up to 40%.','utensils',0.3),
            'Entertainment':('Cancel unused subscriptions','Review streaming & subscription services monthly.','tv',0.4),
            'Transport':('Use public transport','Carpooling or bus saves fuel and parking costs.','bus',0.25),
            'Shopping':('Plan before you buy','A shopping list prevents impulse purchases.','cart-shopping',0.2)}

    saving = [{'title':t,'description':d,'icon':i,'potential_saving':round(cat_spend[c]*r)}
              for c,(t,d,i,r) in tips.items() if c in cat_spend and cat_spend[c]>300]

    alerts = []
    now = datetime.now()
    days_left = calendar.monthrange(now.year,now.month)[1]-now.day
    for b in conn.execute('SELECT * FROM budgets WHERE user_id=?',(uid,)).fetchall():
        sp = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND category=? AND strftime('%Y-%m',date)=?",(uid,b['category'],cur)).fetchone()['s']
        pct = round(sp/b['limit']*100) if b['limit']>0 else 0
        if pct>=70: alerts.append({'category':b['category'],'pct':pct,
            'message':f'Rs.{round(b["limit"]-sp)} remaining for {days_left} days left in month.'})

    total_savings = sum(s['potential_saving'] for s in saving)+sum(l['amount'] for l in leaks)
    user = conn.execute('SELECT monthly_budget FROM users WHERE id=?',(uid,)).fetchone()
    tb = user['monthly_budget'] or 0
    ts = conn.execute("SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND strftime('%Y-%m',date)=?",(uid,cur)).fetchone()['s']
    score,hclass,hlabel = calc_health(ts,tb,leaks)
    conn.close()

    return render_template('suggestions.html',
        leaks=leaks, saving_suggestions=saving, budget_alerts=alerts,
        total_potential_savings=total_savings,
        health={'score':score,'class':hclass,'label':hlabel,
                'message':{'excellent':'Outstanding! Keep it up.','good':'Good habits, small tweaks needed.',
                           'warning':'Some areas need attention.','critical':'Urgent review needed!'}.get(hclass,''),
                'budget_pct':max(0,100-round(ts/tb*100)) if tb>0 else 50,
                'leak_pct':max(0,100-len(leaks)*20),
                'diversity_pct':min(100,len(cat_spend)*15)})

if __name__ == '__main__':
    init_db()
    print("\n✅ LeakTracker is running!")
    print("🌐 Open: http://127.0.0.1:5000\n")
    app.run(debug=True)