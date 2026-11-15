"""Authenticated background planning for the dashboard; durable results, bounded queue."""
from contextlib import closing
import json
from typing import Annotated
import uuid
from fastapi import BackgroundTasks, Depends, Header, HTTPException


def install(app, g, plan, request_model):
    boot = uuid.uuid4().hex

    def connection():
        c = g.db()
        c.execute('''CREATE TABLE IF NOT EXISTS recipe_jobs
            (id TEXT PRIMARY KEY, customer TEXT NOT NULL, request_key TEXT NOT NULL,
             digest TEXT NOT NULL, status TEXT NOT NULL, plan_id TEXT, error TEXT,
             created_at TEXT NOT NULL, worker TEXT NOT NULL,
             UNIQUE(customer, request_key))''')
        c.commit()
        return c

    def present(row):
        return {key: row[key] for key in ('id', 'status', 'plan_id', 'error', 'created_at')}

    def build(jid, body, identity):
        try:
            result = plan(body, identity)
            status, pid, error = 'READY', result['id'], None
        except HTTPException as exc:
            status, pid = 'FAILED', None
            error = exc.detail if isinstance(exc.detail, str) else 'Recipe request needs correction.'
        except Exception:
            status, pid, error = 'FAILED', None, 'Recipe planning could not complete. Check the server and try again.'
        # Never echo credentials even if configuration/provider errors contain one.
        import os
        for name, value in os.environ.items():
            if name.endswith(('_KEY', '_TOKEN', '_SECRET')) and len(value) >= 6 and error:
                error = error.replace(value, '[hidden]')
        with closing(connection()) as c:
            c.execute('UPDATE recipe_jobs SET status=?,plan_id=?,error=? WHERE id=?',
                      (status, pid, error[:1200] if error else None, jid))
            c.commit()

    # Resolve the model annotation without dynamic annotation evaluation.
    def start(body, background: BackgroundTasks, identity: Annotated[str, Depends(g.role)],
              request_key: Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=100)]):
        if body.delivery_date < g.core.utc_now().date():
            raise HTTPException(422, 'Delivery date is in the past.')
        if body.autonomy == 'automatic' and identity != 'reviewer' and g.setting('AIMO_RECIPE_AUTONOMY', 'review') != 'automatic':
            raise HTTPException(403, 'Recipe autonomy is buyer-controlled.')
        if body.measurement_mode == 'kitchen' and identity != 'reviewer' and g.setting('AIMO_RECIPE_MEASUREMENTS', 'strict') != 'kitchen':
            raise HTTPException(403, 'Kitchen estimates are buyer-controlled.')
        digest = g.core.snapshot_digest(json.dumps(body.model_dump(mode='json'), sort_keys=True))
        with g._write_lock, closing(connection()) as c:
            c.execute("UPDATE recipe_jobs SET status='FAILED',error='Server restarted before planning finished. Start a new request.' WHERE status='PLANNING' AND worker<>?", (boot,))
            old = c.execute('SELECT * FROM recipe_jobs WHERE customer=? AND request_key=?', (g.buyer(), request_key)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise HTTPException(409, 'This request key belongs to a different meal request.')
                c.commit()
                return present(old)
            if c.execute("SELECT COUNT(*) FROM recipe_jobs WHERE status='PLANNING'").fetchone()[0] >= 4:
                raise HTTPException(429, 'Planning is busy. Wait for an existing basket to finish.')
            jid, now = 'J-' + uuid.uuid4().hex[:16], g.core.utc_now().isoformat()
            c.execute('INSERT INTO recipe_jobs VALUES(?,?,?,?,?,?,?,?,?)',
                      (jid, g.buyer(), request_key, digest, 'PLANNING', None, None, now, boot))
            c.commit()
        background.add_task(build, jid, body, identity)
        return {'id': jid, 'status': 'PLANNING', 'plan_id': None, 'error': None, 'created_at': now}

    start.__annotations__['body'] = request_model
    app.post('/recipe-jobs', status_code=202, operation_id='start_recipe_job')(start)

    @app.get('/recipe-jobs/{jid}', operation_id='get_recipe_job')
    def get(jid: str, identity: Annotated[str, Depends(g.role)]):
        with closing(connection()) as c:
            c.execute("UPDATE recipe_jobs SET status='FAILED',error='Server restarted before planning finished. Start a new request.' WHERE status='PLANNING' AND worker<>?", (boot,))
            c.commit()
            row = c.execute('SELECT * FROM recipe_jobs WHERE id=? AND customer=?', (jid, g.buyer())).fetchone()
        if not row:
            raise HTTPException(404, 'Recipe planning job not found.')
        return present(row)
