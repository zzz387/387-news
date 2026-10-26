"""Owner-only Codespaces panel. Models and production keys remain in Actions."""
import argparse
import html
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit
import webbrowser
from scripts import review_viewer41 as viewer, trial_control41 as control

PORT=8765
SETTINGS='https://github.com/zzz387/387-news/settings/environments'


def codespace_origin(env=os.environ):
    name=env.get('CODESPACE_NAME','')
    domain=env.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN','app.github.dev')
    if env.get('CODESPACES')!='true' or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+',name):
        raise RuntimeError('CODESPACE_REQUIRED')
    # Only GitHub's supported HTTPS forwarding domain; never trust an arbitrary URL.
    if domain!='app.github.dev': raise RuntimeError('CODESPACE_FORWARDING_DOMAIN_UNSUPPORTED')
    return f'https://{name}-{PORT}.{domain}'


class Access:
    def __init__(self): self.origin=codespace_origin()
    def identity(self):
        user=viewer.gh(['api','user'],True)
        if user.get('login','').casefold()!='zzz387': raise RuntimeError('CODESPACE_OWNER_AUTH_REQUIRED')
        name=os.environ['CODESPACE_NAME']
        space=viewer.gh(['api','user/codespaces/'+name],True)
        if ((space.get('owner') or {}).get('login','').casefold()!='zzz387' or
                (space.get('repository') or {}).get('full_name')!=viewer.REPO):
            raise RuntimeError('CODESPACE_PROVENANCE_INVALID')
    def check(self):
        self.identity()
        name=os.environ['CODESPACE_NAME']
        ports=viewer.gh(['codespace','ports','-c',name,'--json','sourcePort,visibility'],True)
        if not any(str(p.get('sourcePort'))==str(PORT) and p.get('visibility')=='private' for p in ports):
            raise RuntimeError('CODESPACE_PRIVATE_PORT_NOT_VERIFIED')
    def prepare(self):
        self.identity()
        # This can only restrict our own panel port, never make a port public.
        viewer.gh(['codespace','ports','visibility',str(PORT)+':private','-c',os.environ['CODESPACE_NAME']])
        self.check()


def session(directory):
    file=directory/'session.json'
    return json.loads(file.read_text()) if file.exists() else None


def recover(directory,run_id,date):
    """Recover metadata, then protected inspect re-encrypts to the new owner's key."""
    if session(directory): raise ValueError('SAVED_SESSION_ALREADY_EXISTS')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): raise ValueError('RECOVERY_DATE_INVALID')
    run=control.api('GET',f'repos/{viewer.REPO}/actions/runs/{int(run_id)}')
    # A recovery may refer to an incomplete run; it must still have exact owner/branch/workflow provenance.
    check=dict(run,status='completed',conclusion='success')
    viewer.verify_run(check,run['head_sha'])
    jobs=control.api('GET',f'repos/{viewer.REPO}/actions/runs/{int(run_id)}/jobs').get('jobs',[])
    if not any(j.get('name')=='trial' for j in jobs): raise ValueError('RECOVERY_TRIAL_RUN_REQUIRED')
    viewer.owner_key(directory)
    file=directory/'session.json'
    file.write_text(json.dumps({'date':date,'sha':run['head_sha'],'run_id':int(run_id)}))
    file.chmod(0o600)


def safe_error(exc):
    # Never reflect raw CLI stdout/stderr, response bodies, keys or URL tokens.
    match=re.match(r'([A-Z][A-Z0-9_]+)(?: status=(\d{3}|unavailable))?',str(exc))
    return match[0] if match else 'CODESPACE_OPERATION_FAILED'


class Panel(viewer.ReviewServer):
    def __init__(self,directory,access,port=PORT):
        self.directory=Path(directory); self.message='Готово. Gemini при открытии панели не вызывается.'
        self.lock=Lock(); self.busy=False; self.opened=False
        super().__init__({'review.json':b'{}'},'',port=port,external_origin=access.origin,access_check=access.check)
        self.RequestHandlerClass=PanelHandler
    def operate(self,action,form):
        if not self.lock.acquire(blocking=False): return
        self.busy=True
        try:
            if action=='recover':
                recover(self.directory,form.get('run',[''])[0],form.get('date',[''])[0])
                self.message='Сессия восстановлена. Нажмите «Перевыдать архив» для нового ключа или «Продолжить» для незавершённого номера.'
            elif action=='open':
                state=session(self.directory)
                if not state: raise ValueError('TRIAL_SAVED_SESSION_REQUIRED')
                files=viewer.load_review(state['run_id'],state['sha'],state['date'],self.directory)
                temporary=viewer.ReviewServer(files,state['date'])
                try: self.files=temporary.files; self.date=state['date']
                finally: temporary.server_close()
                self.opened=True; self.message='Номер расшифрован только в памяти Codespace. Откройте «Читать номер».'
            elif action in ('start','resume','inspect'):
                if self.opened:
                    self.files={'review.json':b'{}'}; self.opened=False
                result=subprocess.run([sys.executable,'-m','scripts.trial_control41',action,'--key-dir',str(self.directory)],
                                      capture_output=True,text=True,timeout=600)
                if result.returncode:
                    # Extract only our own bounded error code; no traceback or CLI output escapes.
                    codes=re.findall(r'(?:RuntimeError|ValueError): ([A-Z][A-Z0-9_]+(?: status=(?:\d{3}|unavailable))?)',result.stderr)
                    raise RuntimeError(codes[-1] if codes else 'TRIAL_CONTROL_FAILED')
                self.message='Операция завершена. Откройте запуск GitHub; при ожидании нажмите Review deployments → Approve and deploy. Bypass запрещён.'
            elif action=='status':
                state=session(self.directory)
                if not state: self.message='Испытание ещё не запускалось из этой сессии.'
                else:
                    run=control.api('GET',f'repos/{viewer.REPO}/actions/runs/{int(state["run_id"])}')
                    self.message='GitHub: '+str(run.get('status'))+' / '+str(run.get('conclusion') or 'ожидание')
            else: raise ValueError('PANEL_ACTION_INVALID')
        except Exception as exc:
            self.message='Операция остановлена: '+safe_error(exc)+'. Проверьте права GitHub и Settings → Environments. Секреты вводить не нужно.'
        finally: self.busy=False; self.lock.release()


class PanelHandler(viewer.ReviewHandler):
    def send_header(self,name,value):
        if name=='Content-Security-Policy': value=value.replace("form-action 'none'","form-action 'self'")
        super().send_header(name,value)
    def do_GET(self):
        if not self.authorized(): self.send_error(403); return
        prefix='/'+self.server.access_token+'/'
        if urlsplit(self.path).path==prefix+'control/':
            self.render(); return
        if not self.server.opened: self.send_error(404); return
        super().do_GET()
    def do_POST(self):
        if not self.authorized() or self.headers.get('Origin')!=self.server.external_origin:
            self.send_error(403); return
        prefix='/'+self.server.access_token+'/'
        if self.path!=prefix+'control/' or self.headers.get('Content-Type')!='application/x-www-form-urlencoded':
            self.send_error(400); return
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: self.send_error(400); return
        if not 0<length<=2048: self.send_error(413); return
        try: form=parse_qs(self.rfile.read(length).decode('utf-8'),max_num_fields=5)
        except (UnicodeError,ValueError): self.send_error(400); return
        if not secrets.compare_digest(form.get('csrf',[''])[0],self.server.access_token):
            self.send_error(403); return
        action=form.get('action',[''])[0]
        if action not in ('start','resume','inspect','open','status','recover'): self.send_error(400); return
        Thread(target=self.server.operate,args=(action,form),daemon=True).start()
        self.send_response(303); self.send_header('Location',prefix+'control/'); self.send_header('Cache-Control','no-store'); self.end_headers()
    def render(self):
        server=self.server; prefix='/'+server.access_token+'/'
        state=session(server.directory); e=html.escape
        buttons=''.join('<button name="action" value="'+action+'">'+label+'</button>' for action,label in (
            ('start','Запустить испытание'),('status','Проверить состояние / отчёт'),('resume','Продолжить'),
            ('open','Открыть номер'),('inspect','Перевыдать архив без Gemini')))
        run_link=('<p><a href="https://github.com/'+viewer.REPO+'/actions/runs/'+str(int(state['run_id']))+'" target="_blank" rel="noreferrer">Запуск GitHub · Review deployments</a> · Дата '+e(state['date'])+'</p>') if state else ''
        recovery=('' if state else '<details><summary>Восстановить существующее испытание после удаления Codespace</summary><p>Не начинайте новый цикл. Укажите прежнюю дату и ID trial-run со страницы Actions.</p><input name="run" inputmode="numeric" placeholder="ID запуска"><input name="date" type="date"><button name="action" value="recover">Восстановить сессию</button></details>')
        report=''
        if server.opened:
            report='<p><a href="'+prefix+'">Читать номер</a> · <a href="'+prefix+'_review/">12 статей и редакционный отчёт</a></p><pre>'+e(json.dumps(json.loads(server.files['review.json']),ensure_ascii=False,indent=2))+'</pre>'
        body=('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>387 News · испытание</title><style>body{max-width:850px;margin:auto;padding:16px;font:18px/1.6 system-ui;overflow-wrap:anywhere}button,input{padding:14px;margin:6px;max-width:100%;font:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<h1>387 News · закрытое испытание</h1><p>Порт Private. Production не публикуется и не изменяется. Один цикл с продолжениями.</p><p>'+e(server.message)+('</p><p>Операция выполняется; нажмите обновить страницу через минуту.' if server.busy else '')+'</p>'+run_link+
            '<form method="post"><input type="hidden" name="csrf" value="'+server.access_token+'">'+buttons+recovery+'</form>'+report+
            '<p><a href="'+SETTINGS+'" target="_blank" rel="noreferrer">Настройки защищённого environment</a></p>'
            '<p>Если GitHub отказывает в правах, используйте Accounts → GitHub в Codespaces и штатный запрос дополнительных разрешений. Не передавайте ключи в чат. Настройка environment может потребовать владельца.</p></html>').encode()
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'")
        self.end_headers(); self.wfile.write(body)


def open_panel(directory):
    metadata=json.loads((directory/'panel.json').read_text())
    origin=codespace_origin()
    if not metadata['url'].startswith(origin+'/') or not re.fullmatch(r'[A-Za-z0-9_-]{40,}/control/',metadata['url'][len(origin)+1:]):
        raise ValueError('PANEL_URL_INVALID')
    # VS Code's supported browser command opens the private URL in the owner's browser.
    browser=os.getenv('BROWSER')
    if browser: subprocess.run([*shlex.split(browser),metadata['url']],capture_output=True,timeout=30,check=True)
    else: webbrowser.open(metadata['url'])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--serve',action='store_true'); parser.add_argument('--open',action='store_true')
    args=parser.parse_args(); directory=viewer.key_directory()
    if args.open: open_panel(directory); return
    access=Access(); access.identity()
    viewer.owner_key(directory)
    # Bind before visibility verification so Codespaces can discover the port.
    # Nothing is served until Private has been verified.
    server=Panel(directory,access)
    try: access.prepare()
    except Exception:
        server.server_close(); raise
    file=directory/'panel.json'; file.write_text(json.dumps({'url':server.url+'control/'})); file.chmod(0o600)
    # Never print URL tokens or credentials, including to postStart logs.
    print('Приватная панель готова. Terminal → Run Task → 387 News: открыть панель.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); server.files.clear()


if __name__=='__main__':
    try: main()
    except Exception as exc: print('387 News: '+safe_error(exc)+'. См. docs/V41_CODESPACES.md.',file=sys.stderr); sys.exit(1)
