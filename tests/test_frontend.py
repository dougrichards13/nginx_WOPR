"""Self-contained frontend checks. Optional Chromium smoke test, no npm required.

Run: python3 -m unittest discover -s tests -p test_frontend.py -v
"""
import http.server
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "index.html").read_text()


class FrontendStaticTests(unittest.TestCase):
    def test_no_untrusted_html_sinks_or_remote_dependencies(self):
        for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(",
                          "@import", "<script src=", "fonts.googleapis.com"):
            self.assertNotIn(forbidden, HTML)

    def test_required_contract_and_honest_labels(self):
        for required in ("X-WOPR-Token", "/api/config", "/api/intel", "/api/shutdown",
                         "session_token", "localService", "N/A", "SIMULATION",
                         "NO DATA AVAILABLE", "MICROSOFT LEARN", "STAY OFFLINE"):
            self.assertIn(required, HTML)

    def test_offline_reference_is_substantial(self):
        kb = HTML.split("const WINDOWS_KB=[", 1)[1].split("\n];", 1)[0]
        self.assertGreaterEqual(kb.count("\n["), 30)
        self.assertIn("PowerShell-safe JMESPath", kb)
        self.assertIn("Get-ExecutionPolicy -List", kb)


class QuietHandler(http.server.BaseHTTPRequestHandler):
    page = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.page)

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("chromium"), "Chromium not installed")
class FrontendBrowserTests(unittest.TestCase):
    def run_browser(self, windows):
        config = {"platform": "windows", "session_token": "fixture-token",
                  "feeds_enabled": False, "speech": {"available": True, "engine": "espeak-ng"}}
        # Exercise values that must remain literal text, not markup or handlers.
        stats = {"hostname": "secret-host", "os": "fixture OS", "cpu": {"temp_c": None,
                 "gpu_temp_c": None, "usage_percent": 24, "cores": 2},
                 "memory": {"percent": 30, "used_mb": 300, "total_mb": 1000},
                 "disk": {"percent": 50, "used_gb": 5, "total_gb": 10},
                 "network": {"ip": "192.0.2.44", "interface": "secret-adapter",
                             "rx_rate_kbs": 0, "tx_rate_kbs": None, "connections": 0},
                 "services": {}, "processes": 3, "per_core": [12, 36],
                 "top_processes": [{"name": "secret-process", "cpu_percent": 20, "memory_mb": 22}],
                 "windows_services": [{"name": "Defender", "status": None}],
                 "log_entries": [{"time": "fixture", "msg": '<img src=x onerror="window.pwned=1">'}],
                 "battery": None, "security": None}
        intel = {"feeds": {
            "isc": {"state": "offline", "source": "SANS", "data": None},
            "cisa": {"state": "stale", "source": '<img src=x onerror="window.pwned=1">',
                     "url": "javascript:alert(1)", "data": {"items": [{"cve_id": "<b>fixture</b>"}]}},
            "noaa": {"state": "unavailable"},
            "usgs": {"state": "stale", "data": {"items": [
                {"longitude": 10, "latitude": 20, "magnitude": 4.5, "place": "<svg onload=alert(1)>",
                 "time": "fixture-time"}]}}}}
        prelude = """
window.fixtureRequests=[];
window.fixtureAudioURLs=[];
window.fixtureAudioMode='end';
window.Audio=class{
  constructor(url){this.src=url;window.fixtureAudioURLs.push(url);}
  pause(){}
  play(){
    if(window.fixtureAudioMode==='fail')return Promise.reject(new Error('fixture audio failure'));
    setTimeout(()=>{if(this.onended)this.onended();},5);return Promise.resolve();
  }
};
window.fetch=async function(url,opts={}){
  window.fixtureRequests.push({url:String(url),method:opts.method||'GET',headers:opts.headers,
    body:opts.body});
  let data={};
  if(String(url).startsWith('/api/config')){
    if(!WINDOWS_MODE)return {ok:false,status:404};
    data=CONFIG;
  }else if(String(url).startsWith('/api/stats.json'))data=STATS;
  else if(url==='/api/intel')data=INTEL;
  else data={features:[]};
  return {ok:true,status:200,json:async()=>data,blob:async()=>new Blob(['wav'],{type:'audio/wav'})};
};
""".replace("WINDOWS_MODE", str(windows).lower()).replace("CONFIG", json.dumps(config)).replace(
            "STATS", json.dumps(stats)).replace("INTEL", json.dumps(intel))
        checks = """
setTimeout(async()=>{
  const failures=[],check=(ok,msg)=>{if(!ok)failures.push(msg);};
  try{
    dismissBoot();
    await fetchStats();
    check(!window.pwned,'XSS executed');
    check(!$('threat-log').querySelector('img'),'log created markup');
    check($('cpu-temp').textContent==='N/A','missing temp fabricated');
    check($('rx-rate').textContent==='0.0 KiB/s','zero rate not preserved');
    check($('tx-rate').textContent==='N/A KiB/s','missing rate fabricated');
    check($('per-core').children.length===2,'per-core bars missing');
    updateTelemetryFreshness({timestamp:new Date(Date.now()-60000).toISOString()});
    check($('data-status').textContent.includes('STALE'),'frozen sample marked live');
    updateTelemetryFreshness({timestamp:new Date().toISOString()});
    check($('data-status').textContent.includes('LIVE'),'fresh sample not live');
    $('joshua-input').value='<img src=x onerror="window.pwned=1">';
    voiceEnabled=false;
    $('joshua-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));
    check(!$('terminal-output').querySelector('img'),'terminal created markup');
    if(WINDOWS_MODE){
      check(runtimeConfig?.platform==='windows','Windows detection failed');
      check(!$('feed-consent').hidden,'first-run consent absent');
      check(windowsRespond('azure storage').includes('az storage'),'Azure KB routing');
      check(windowsRespond('Get-ChildItem').includes('LiteralPath'),'PowerShell KB routing');
      check(windowsRespond('login mfa').includes('Never paste'),'login safety missing');
      check(!$('intel-feeds').querySelector('img'),'feed created markup');
      check(!$('intel-feeds').querySelector('a[href^="javascript:"]'),'unsafe link rendered');
      $('map-mode').value='earthquakes';$('map-mode').dispatchEvent(new Event('change'));
      check($('map-title').textContent.includes('REAL PUBLIC EVENTS'),'real map not labeled');
      check(document.querySelector('.map-overlay').hidden,'fake attack counter on real map');
      check(earthquakes.length===1,'normalized USGS events absent');
      await setFeedConsent(false);
      const req=window.fixtureRequests.find(x=>x.method==='POST'&&x.url==='/api/config');
      check(req?.headers['X-WOPR-Token']==='fixture-token','config token absent');
      check(JSON.parse(req.body).feeds_enabled===false,'offline mutation wrong');
    }else{
      check(runtimeConfig===null,'Pi incorrectly Windows');
      check(joshuaRespond('ls').includes('ls -la'),'Linux helper broken');
    }
    $('privacy-toggle').click();
    check(!$('header-hostname').textContent.includes('secret-host'),'host privacy failed');
    check(!$('net-ip').textContent.includes('192.0.2.44'),'address privacy failed');
    check(!$('process-list').textContent.includes('secret-process'),'process privacy failed');
    check($('threat-log').textContent.includes('MASKED'),'log privacy failed');
    $('motion-toggle').click();
    check(document.body.classList.contains('reduced'),'motion preference failed');
    voiceEnabled=true;
    $('voice-speed').value=180;$('voice-pitch').value=22;$('voice-volume').value=65;
    speakJoshua('Fixture speech test');
    await new Promise(r=>setTimeout(r,25));
    if(WINDOWS_MODE){
      const req=window.fixtureRequests.find(x=>x.url==='/api/speak');
      check(req?.method==='POST','Windows speech did not use POST');
      check(req?.headers['X-WOPR-Token']==='fixture-token','speech token absent');
      const payload=JSON.parse(req.body);
      check(payload.speed===180&&payload.pitch===22&&payload.volume===65,'speech controls missing');
      check(window.fixtureAudioURLs.some(x=>x.startsWith('blob:')),'WAV blob not played');
    }else check(window.fixtureAudioURLs.some(x=>x.startsWith('/api/speak?text=')),'Pi CGI speech lost');
    speechActive=true;
    for(let i=0;i<8;i++)speakJoshua('Bounded queue');
    check(speechQueue.length===3,'speech queue unbounded');
    $('voice-stop').click();check(speechQueue.length===0,'speech stop failed');
    window.fixtureAudioMode='fail';speakJoshua('Playback failure');
    await new Promise(r=>setTimeout(r,25));
    check($('voice-status').textContent.includes('UNAVAILABLE'),'speech failure hidden');
    check(!$('browser-voice').hidden,'explicit local fallback absent');
    stopSpeech();
  }catch(e){failures.push(e.stack||e.message);}
  const result=document.createElement('pre');result.id='frontend-test-result';
  result.textContent=failures.length?'FAIL: '+failures.join(' | '):'PASS';
  document.body.appendChild(result);
},100);
""".replace("WINDOWS_MODE", str(windows).lower())
        page = HTML.replace("<script>", "<script>" + prelude, 1).replace(
            "</script>", checks + "</script>", 1)
        handler = type("FixtureHandler", (QuietHandler,), {"page": page.encode()})
        server = http.server.ThreadingHTTPServer(("localhost", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="wopr-browser-") as profile:
                result = subprocess.run(
                    [shutil.which("chromium"), "--headless", "--no-sandbox",
                     "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run",
                     "--no-default-browser-check", "--disable-background-networking",
                     "--user-data-dir=" + profile, "--virtual-time-budget=1500", "--dump-dom",
                     f"http://localhost:{server.server_port}/"],
                    capture_output=True, text=True, timeout=40)
            marker = '<pre id="frontend-test-result">'
            self.assertIn(marker, result.stdout, "Browser script failed: " + result.stderr[-2000:])
            output = result.stdout.rsplit(marker, 1)[1].split("</pre>", 1)[0]
            self.assertEqual(output, "PASS", output)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_windows_contract_and_controls(self):
        self.run_browser(True)

    def test_pi_contract_and_linux_fallback(self):
        self.run_browser(False)


if __name__ == "__main__":
    unittest.main()
