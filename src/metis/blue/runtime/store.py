"""Durable dispatch, messages and usage; all state is local and private."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, objective TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, owner_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(run TEXT NOT NULL, id TEXT NOT NULL, prompt TEXT NOT NULL, skill TEXT NOT NULL, dependencies TEXT NOT NULL, resources TEXT NOT NULL, state TEXT NOT NULL, result TEXT, worker TEXT, started REAL, finished REAL, PRIMARY KEY(run,id));
CREATE TABLE IF NOT EXISTS resources(name TEXT PRIMARY KEY, capacity INTEGER NOT NULL CHECK(capacity > 0));
CREATE TABLE IF NOT EXISTS leases(resource TEXT NOT NULL, run TEXT NOT NULL, task TEXT NOT NULL, units INTEGER NOT NULL CHECK(units > 0), PRIMARY KEY(resource,run,task));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, task TEXT, sender TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS usage(run TEXT NOT NULL, task TEXT NOT NULL, source TEXT NOT NULL, event TEXT NOT NULL, model TEXT NOT NULL, input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, measured INTEGER NOT NULL, input_total INTEGER, provenance TEXT NOT NULL, PRIMARY KEY(run,task,source,event));
CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL, resource TEXT NOT NULL, action TEXT NOT NULL, expires REAL NOT NULL, remaining INTEGER NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL, resource TEXT NOT NULL, protocol TEXT NOT NULL, action TEXT NOT NULL, state TEXT NOT NULL, pid INTEGER, started REAL NOT NULL, finished REAL);
'''

USAGE_FIELDS = ('input', 'output', 'cache_read', 'cache_write', 'input_total')
USAGE_COLUMNS = 'run,task,source,event,model,input,output,cache_read,cache_write,measured,input_total,provenance'

def sum_known(values):
    values = list(values)
    return sum(values) if values and all(value is not None for value in values) else None

def usage_values(values, measured=True):
    numbers = {key: values.get(key) for key in USAGE_FIELDS}
    if any(n is not None and (type(n) is not int or not 0 <= n <= 9223372036854775807) for n in numbers.values()):
        raise ValueError('Usage must contain nonnegative integer counts or null')
    if 'input_total' not in values:
        numbers['input_total'] = sum_known(numbers[k] for k in ('input', 'cache_read', 'cache_write'))
    if numbers['input_total'] is not None:
        known_parts = [numbers[k] for k in ('input', 'cache_read', 'cache_write') if numbers[k] is not None]
        if numbers['input_total']>9223372036854775807 or sum(known_parts)>numbers['input_total'] or (len(known_parts)==3 and sum(known_parts)!=numbers['input_total']):
            raise ValueError('Input components disagree with total input')
    if not measured:
        numbers = {key: None for key in USAGE_FIELDS}
    return numbers

def usage_row(run, task, source, event, model, values, measured=True):
    numbers = usage_values(values, measured)
    return (run, task, source, str(event), model, *(numbers[k] for k in USAGE_FIELDS[:4]),
            int(measured), numbers['input_total'], 'reported-v2' if measured else 'synthetic')

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def redact(value):
    text = str(value)
    # Registered secret values never reach storage. Registration remains in this process only.
    for name, secret in os.environ.items():
        if re.search(r'(?:PASSWORD|PASSWD|SSHPASS|TOKEN|SECRET|API_KEY|PRIVATE_KEY)$', name, re.IGNORECASE) and len(secret) >= 4:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'-----BEGIN [\w ]*PRIVATE KEY-----.*?-----END [\w ]*PRIVATE KEY-----', '[REDACTED KEY]', text, flags=re.DOTALL)
    text = re.sub(r'(?i)(\b(?:password|passwd|api[_-]?key|token|secret|authorization|cookie)\b\s*[=:]\s*)([^\s,;]+)', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)\bBearer\s+[\w.\-]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)(https?://)[^\s/@:]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    try:
        structured=json.loads(text)
        sensitive=re.compile(r'^(?:password|passwd|api[_-]?key|secret|(?:access_|refresh_)?token|authorization|cookie|set-cookie|private_key)$',re.IGNORECASE)
        def scrub(value):
            if isinstance(value,dict):
                return {key:'[REDACTED]' if sensitive.fullmatch(key) else scrub(item) for key,item in value.items()}
            if isinstance(value,list):return [scrub(item) for item in value]
            return value
        if isinstance(structured,(dict,list)):
            text=json.dumps(scrub(structured),ensure_ascii=False)
    except (ValueError,TypeError):
        pass
    return text

class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
        self._migrate_usage()
        os.chmod(self.path, 0o600)

    def _migrate_usage(self):
        # Preserve old stored values, but their defaulted zeros cannot be authenticated.
        with self.transaction() as db:
            columns = {row[1]: row for row in db.execute('PRAGMA table_info(usage)')}
            if 'provenance' in columns and 'input_total' in columns and not columns['input'][3]:
                return
            db.execute('ALTER TABLE usage RENAME TO usage_legacy_accounting')
            usage_schema = next(line for line in SCHEMA.splitlines() if line.startswith('CREATE TABLE IF NOT EXISTS usage('))
            db.execute(usage_schema)
            db.execute('INSERT INTO usage (' + USAGE_COLUMNS + ') SELECT run,task,source,event,model,input,output,cache_read,cache_write,measured,NULL,\'legacy-defaults-unknown\' FROM usage_legacy_accounting')
            db.execute('DROP TABLE usage_legacy_accounting')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def new_run(self, objective):
        run, token = uuid.uuid4().hex[:16], secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (run, redact(objective), 'pending', time.time(), digest(token)))
        self.message(run, None, 'user', 'owner', 'request', objective)
        return run, token

    def authorize(self, db, run, token):
        row = db.execute('SELECT owner_hash FROM runs WHERE id=?', (run,)).fetchone()
        if not row or not secrets.compare_digest(row[0], digest(token)):
            raise PermissionError('Owner capability required')

    def configure(self, run, token, capacities):
        with self.transaction() as db:
            self.authorize(db, run, token)
            for name, capacity in capacities.items():
                if type(capacity) is not int or capacity < 1:
                    raise ValueError('Resource capacity must be a positive integer')
                old = db.execute('SELECT capacity FROM resources WHERE name=?', (name,)).fetchone()
                # Resource capacity is shared across runs; never silently change another owner's limit.
                if old and old[0] != capacity:
                    raise ValueError('Capacity already configured for ' + name)
                db.execute('INSERT OR IGNORE INTO resources VALUES(?,?)', (name, capacity))

    def add_tasks(self, run, token, tasks):
        with self.transaction() as db:
            self.authorize(db, run, token)
            known = {r[0]:r[1] for r in db.execute('SELECT name,capacity FROM resources')}
            for task in tasks:
                for resource, units in task.get('resources', {}).items():
                    if resource not in known or type(units) is not int or units < 1 or units > known[resource]:
                        raise ValueError('Unschedulable resource request: ' + resource)
                db.execute('INSERT INTO tasks(run,id,prompt,skill,dependencies,resources,state) VALUES(?,?,?,?,?,?,?)',
                           (run, task['id'], redact(task['prompt']), task['skill'], json.dumps(task.get('depends_on', [])), json.dumps(task.get('resources', {})), 'pending'))
            db.execute('UPDATE runs SET status=? WHERE id=?', ('ready',run))

    def resize(self,run,token,resource,capacity):
        if type(capacity) is not int or capacity<1:
            raise ValueError('Resource capacity must be a positive integer')
        with self.transaction() as db:
            self.authorize(db,run,token)
            used=db.execute('SELECT COALESCE(SUM(units),0) FROM leases WHERE resource=?',(resource,)).fetchone()[0]
            if capacity<used:
                raise ValueError('Cannot shrink below currently leased units')
            db.execute('INSERT INTO resources VALUES(?,?) ON CONFLICT(name) DO UPDATE SET capacity=excluded.capacity',(resource,capacity))
        self.message(run,None,'owner','scheduler','resource-capacity',json.dumps({'resource':resource,'capacity':capacity}))

    def claim(self, run, token, worker):
        """FIFO among ready tasks; acquire the entire resource set atomically."""
        with self.transaction() as db:
            self.authorize(db, run, token)
            rows = db.execute('SELECT * FROM tasks WHERE run=? ORDER BY rowid', (run,)).fetchall()
            states = {r['id']:r['state'] for r in rows}
            for row in rows:
                if row['state'] != 'pending':
                    continue
                deps = json.loads(row['dependencies'])
                if any(states.get(d) in ('failed','blocked','cancelled') for d in deps):
                    db.execute('UPDATE tasks SET state=?,result=? WHERE run=? AND id=?', ('blocked','Dependency did not succeed',run,row['id']))
                    states[row['id']] = 'blocked'
                    continue
                if any(states.get(d) != 'done' for d in deps):
                    continue
                requested = json.loads(row['resources'])
                fits = True
                for name, units in requested.items():
                    capacity = db.execute('SELECT capacity FROM resources WHERE name=?',(name,)).fetchone()[0]
                    used = db.execute('SELECT COALESCE(SUM(units),0) FROM leases WHERE resource=?',(name,)).fetchone()[0]
                    if used + units > capacity:
                        fits = False
                        break
                if not fits:
                    continue
                for name, units in requested.items():
                    db.execute('INSERT INTO leases VALUES(?,?,?,?)',(name,run,row['id'],units))
                db.execute('UPDATE tasks SET state=?,worker=?,started=? WHERE run=? AND id=?', ('running',worker,time.time(),run,row['id']))
                db.execute('UPDATE runs SET status=? WHERE id=?', ('running',run))
                return dict(row)
        return None

    def finish(self, run, token, task, result, state='done'):
        if state not in ('done','failed','blocked','cancelled'):
            raise ValueError('Invalid terminal state')
        with self.transaction() as db:
            self.authorize(db,run,token)
            self._hook('finish_locked')
            if db.execute("SELECT 1 FROM connections WHERE run=? AND task=? AND state!='stopped'",(run,task)).fetchone():
                raise ValueError('Stop active connections before finishing this task')
            changed = db.execute('UPDATE tasks SET state=?,result=?,finished=? WHERE run=? AND id=? AND state=?', (state,redact(result),time.time(),run,task,'running')).rowcount
            if changed != 1:
                raise ValueError('Task is not running')
            db.execute('DELETE FROM leases WHERE run=? AND task=?',(run,task))
        self.message(run,task,task,'owner','result' if state == 'done' else state,result)

    def begin_connection(self,run,task,resource,protocol,action,write,grant):
        """Reserve the consumer before launch, atomically with grant consumption."""
        cid=uuid.uuid4().hex
        with self.transaction() as db:
            lease=db.execute("SELECT l.units FROM leases l JOIN tasks t ON l.run=t.run AND l.task=t.id WHERE l.run=? AND l.task=? AND l.resource=? AND t.state='running'",(run,task,resource)).fetchone()
            if not lease:
                raise PermissionError('The owner must lease this connection resource to a running task first')
            active=db.execute("SELECT COUNT(*) FROM connections WHERE run=? AND task=? AND resource=? AND state!='stopped'",(run,task,resource)).fetchone()[0]
            if active>=lease['units']:raise PermissionError('All leased connection units are in use')
            if write:
                n=db.execute('UPDATE grants SET remaining=remaining-1 WHERE id=? AND run=? AND task=? AND resource=? AND action=? AND expires>? AND remaining>0',(grant or '',run,task,resource,action,time.time())).rowcount
                if n!=1:raise PermissionError('A current owner-issued write grant is required')
            db.execute('INSERT INTO connections VALUES(?,?,?,?,?,?,?,NULL,?,NULL)',(cid,run,task,resource,protocol,action,'starting',time.time()))
        return cid

    def connection_state(self, cid, state, pid=None):
        """Move a connection forward only: ``starting -> running -> stopped``.

        ``running`` also requires that its task is still running and still holds the resource
        lease, so a late or duplicated callback cannot revive a connection after ``finish``.
        """
        if state not in ('running', 'stopped'):
            raise ValueError('Invalid connection state')
        with self.transaction() as db:
            self._hook('connection_state_locked')
            row = db.execute('SELECT c.state, c.run, c.task, c.resource, t.state FROM connections c '
                             'LEFT JOIN tasks t ON t.run=c.run AND t.id=c.task WHERE c.id=?', (cid,)).fetchone()
            if row is None:
                raise ValueError('Unknown connection')
            current, run, task, resource, task_state = row
            if state == 'stopped':
                if current == 'stopped':
                    return
            else:
                if current != 'starting':
                    raise ValueError('Connection cannot become running from ' + str(current))
                leased = db.execute('SELECT 1 FROM leases WHERE run=? AND task=? AND resource=?',
                                    (run, task, resource)).fetchone()
                if task_state != 'running' or not leased:
                    raise ValueError('Connection cannot run without a running task and its lease')
            db.execute('UPDATE connections SET state=?,pid=COALESCE(?,pid),finished=? WHERE id=?',
                       (state, pid, time.time() if state == 'stopped' else None, cid))

    @staticmethod
    def _hook(point):
        """Test seam: called inside lifecycle transactions (no-op in production)."""

    def tasks(self, run):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT * FROM tasks WHERE run=? ORDER BY rowid',(run,))]

    def status(self, run, token, status):
        with self.transaction() as db:
            self.authorize(db,run,token)
            db.execute('UPDATE runs SET status=? WHERE id=?',(status,run))

    def message(self,run,task,sender,recipient,kind,body):
        with self.transaction() as db:
            db.execute('INSERT INTO messages(run,task,sender,recipient,kind,body,created) VALUES(?,?,?,?,?,?,?)', (run,task,sender,recipient,kind,redact(body),time.time()))

    def usage(self,run,task,source,event,model,values,measured=True):
        row=usage_row(run,task,source,event,model,values,measured)
        with self.transaction() as db:
            db.execute('INSERT OR REPLACE INTO usage ('+USAGE_COLUMNS+') VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', row)

    def grant(self,run,token,task,resource,action,reason,ttl=300,uses=1):
        if ttl <= 0 or uses < 1 or not reason.strip() or '*' in (task,resource,action):
            raise ValueError('Grant requires exact task/resource/action, reason, positive TTL and uses')
        gid=uuid.uuid4().hex
        with self.transaction() as db:
            self.authorize(db,run,token)
            if not db.execute('SELECT 1 FROM tasks WHERE run=? AND id=?',(run,task)).fetchone():
                raise ValueError('Unknown task')
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?,?)',(gid,run,task,resource,action,time.time()+ttl,uses,redact(reason)))
        self.message(run,task,'owner',task,'grant',json.dumps({'id':gid,'resource':resource,'action':action,'reason':reason,'ttl':ttl,'uses':uses}))
        return gid

    def consume_grant(self,run,task,resource,action,gid):
        with self.transaction() as db:
            n=db.execute('UPDATE grants SET remaining=remaining-1 WHERE id=? AND run=? AND task=? AND resource=? AND action=? AND expires>? AND remaining>0', (gid,run,task,resource,action,time.time())).rowcount
            if n != 1:
                raise PermissionError('A current owner-issued write grant is required')

    def report(self,run):
        with self.connect() as db:
            result=db.execute('SELECT id,objective,status,created FROM runs WHERE id=?',(run,)).fetchone()
            if not result:
                raise ValueError('Unknown run')
            messages=[dict(r) for r in db.execute('SELECT * FROM messages WHERE run=? ORDER BY id',(run,))]
            records=[dict(r) for r in db.execute('SELECT * FROM usage WHERE run=? ORDER BY task,model,source,event',(run,))]
            connections=[dict(r) for r in db.execute('SELECT * FROM connections WHERE run=? ORDER BY started',(run,))]
        groups={}
        effective=[]
        for row in records:
            item=dict(row)
            if not row['measured'] or row['provenance']!='reported-v2':
                item.update({k:None for k in USAGE_FIELDS})
            item['total']=sum_known((item['input_total'],item['output']))
            effective.append(item)
            groups.setdefault((row['task'],row['model']),[]).append(item)
        fields=USAGE_FIELDS+('total',)
        usage=[]
        for (task,model),rows in groups.items():
            usage.append({'task':task,'model':model,**{k:sum_known(r[k] for r in rows) for k in fields},
                          'measured':int(all(r['measured'] and r['provenance']=='reported-v2' and any(r[k] is not None for k in USAGE_FIELDS) for r in rows)),
                          'events':len(rows),
                          'provenance':sorted({r['provenance'] for r in rows}),
                          'unknown_fields':[k for k in fields if any(r[k] is None for r in rows)]})
        totals={k:sum_known(r[k] for r in effective) for k in fields}
        known_subtotals={k:sum_known(r[k] for r in effective if r[k] is not None) for k in fields}
        calls={m['task'] for m in messages if m['kind']=='dispatch'}
        measured={r['task'] for r in effective if r['measured'] and any(r[k] is not None for k in USAGE_FIELDS)}
        synthetic={r['task'] for r in records if not r['measured']}
        missing=calls-measured-synthetic
        if missing:
            totals={k:None for k in fields}
        coverage={'complete':bool(effective) and not missing and all(r[k] is not None for r in effective for k in fields),
                  'total_complete':bool(effective) and not missing and all(r['total'] is not None for r in effective),
                  'missing_agents':sorted(missing),'synthetic_agents':sorted(synthetic),
                  'legacy_agents':sorted({r['task'] for r in records if r['provenance']=='legacy-defaults-unknown'}),
                  'unknown_events':sum(any(r[k] is None for k in fields) for r in effective)}
        return {'run':dict(result),'tasks':self.tasks(run),'messages':messages,'usage':usage,'totals':totals,
                'known_subtotals':known_subtotals,'usage_coverage':coverage,'connections':connections,
                'legacy_usage':[r for r in records if r['provenance']=='legacy-defaults-unknown']}
