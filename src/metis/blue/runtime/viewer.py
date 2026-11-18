"""Escaped standalone report and a loopback-only authenticated viewer."""
import html
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def render(report):
    def e(value):return html.escape('unknown' if value is None else str(value))
    rows=''.join('<tr>'+''.join('<td>'+e(r.get(k,''))+'</td>' for k in ('task','model','input','cache_read','cache_write','input_total','output','total','measured'))+'</tr>' for r in report['usage'])
    messages=''.join('<details><summary>'+e(m['sender']+' → '+m['recipient']+' · '+m['kind'])+'</summary><pre>'+e(m['body'])+'</pre></details>' for m in report['messages'])
    tasks=''.join('<article><h3>'+e(t['id'])+' <small>'+e(t['state'])+'</small></h3><pre>'+e(t.get('result') or 'Pending')+'</pre></article>' for t in report['tasks'])
    return '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>METIS · Case review</title><style>
body{background:#0b1220;color:#e4edf6;font:16px system-ui;max-width:1100px;margin:48px auto;padding:0 24px}h1{font-size:38px}h2{margin-top:40px;color:#77dbc4}small{color:#9babbe;font-size:14px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #304157;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace}article,details{background:#142135;padding:16px;margin:12px 0;border-radius:8px}summary{cursor:pointer}code{color:#77dbc4}</style><h1>SOC AIエージェント — METIS Blue</h1>'''+ '<p>'+e(report['run']['objective'])+'</p><small>'+e(report['run']['id']+' · '+report['run']['status'])+'</small><h2>Usage</h2><p>'+e(json.dumps(report['totals']))+'</p><p>Known subtotals (may cover different subsets): '+e(json.dumps(report.get('known_subtotals',{})))+'</p><p>Usage coverage: '+e(json.dumps(report.get('usage_coverage',{})))+'</p><p><small>Missing counts are unknown/null; explicit zero stays 0. Prompt total includes cached input and is not added again to its component counts. Synthetic and legacy rows do not establish measured usage. Total coverage and cache-breakdown coverage are separate.</small></p><table><tr><th>Agent</th><th>Model</th><th>Input component</th><th>Cache read</th><th>Cache write</th><th>Prompt total</th><th>Output</th><th>Total</th><th>Provider record</th></tr>'+rows+'</table><details><summary>Preserved legacy usage (unverified)</summary><pre>'+e(json.dumps(report.get('legacy_usage',[]),ensure_ascii=False,indent=2))+'</pre></details><h2>Findings</h2>'+tasks+'<h2>Messages</h2>'+messages+'</html>'


def serve(store,run,port=0):
    token=secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url=urlparse(self.path)
            if url.path!='/' or not secrets.compare_digest(parse_qs(url.query).get('key',[''])[0],token):
                self.send_error(403);return
            body=render(store.report(run)).encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print('Viewer: http://127.0.0.1:'+str(server.server_port)+'/?key='+token,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
