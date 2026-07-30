1|"""Local HTTP dashboard for starting and observing company-analysis jobs."""
2|
3|from __future__ import annotations
4|
5|import argparse
6|from datetime import datetime
7|from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
8|import json
9|import os
10|from pathlib import Path
11|from typing import Any
12|from urllib.parse import parse_qs, urlparse
13|from zoneinfo import ZoneInfo
14|
15|from company_quality.dashboard_jobs import AnalysisJobService, DashboardJobError
16|
17|
18|_TAIPEI = ZoneInfo("Asia/Taipei")
19|_MAX_BODY = 16_384
20|
21|_INDEX = r"""<!doctype html>
22|<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
23|<title>Company Quality Research</title>
24|<style>
25|:root{--bg:#f4f1e9;--panel:#fffdf8;--ink:#1f2933;--muted:#667085;--line:#d9d2c3;--accent:#6657c7;--ok:#237a4b;--warn:#a46112;--bad:#b42318;--radius:16px}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,"Noto Sans TC",system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:34px 22px 60px}header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:24px}h1{margin:0 0 8px;font-size:30px}h2{font-size:18px;margin:0 0 14px}.muted{color:var(--muted);font-size:13px}.badge{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:7px 11px;font-weight:700}.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:0 8px 24px rgba(55,47,35,.05)}form{display:grid;grid-template-columns:minmax(260px,1fr) 150px 130px;gap:10px}input,select,button{min-height:46px;border-radius:10px;border:1px solid var(--line);font:inherit}input,select{background:white;padding:0 13px;color:var(--ink)}button{background:var(--accent);color:white;border-color:var(--accent);font-weight:800;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}input:focus-visible,select:focus-visible,button:focus-visible{outline:3px solid rgba(102,87,199,.28);outline-offset:2px}.suggestions{position:relative}.suggestion-list{position:absolute;z-index:3;top:49px;left:0;right:0;background:white;border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 24px rgba(31,41,51,.12);overflow:hidden}.suggestion-list button{display:block;width:100%;text-align:left;background:white;color:var(--ink);border:0;border-radius:0;padding:10px 12px}.suggestion-list button:hover{background:#f4f1ff}.hidden{display:none!important}.status-grid,.coverage-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:16px}.metric{background:white;border:1px solid var(--line);border-radius:12px;padding:15px}.metric strong{display:block;font-size:19px;ma... [truncated]
26|</style></head><body><main>
27|<header><div><h1>Company Quality Research</h1><div class="muted">輸入上市／上櫃公司股號或名稱，啟動官方資料 evidence-first 分析</div></div><div class="badge">LOCAL · ANALYSIS ONLY</div></header>
28|<section class="panel"><h2>建立分析</h2><form id="analysis-form"><div class="suggestions"><input id="identifier" autocomplete="off" placeholder="例如：2330 或 台積電" required maxlength="128"><div id="suggestions" class="suggestion-list hidden"></div></div><select id="market"><option value="">自動判斷市場</option><option value="TWSE">上市 TWSE</option><option value="TPEx">上櫃 TPEx</option></select><button id="submit" type="submit">開始分析</button></form><div id="form-error" class="error hidden"></div></section>
29|<section id="job-panel" class="panel hidden" style="margin-top:16px"><h2>分析進度</h2><div class="status-grid"><div class="metric"><span class="muted">公司</span><strong id="company">—</strong></div><div class="metric"><span class="muted">工作狀態</span><strong id="status">—</strong></div><div class="metric"><span class="muted">Generation</span><strong id="generation" style="font-size:13px;word-break:break-all">—</strong></div></div><ol class="timeline"><li data-stage="queued">工作已建立</li><li data-stage="collecting_official_evidence">收集五年官方財報與查核資料</li><li data-stage="research_report_complete">研究報告完成</li></ol><div id="job-error" class="error hidden"></div></section>
30|<section id="result-panel" class="panel result hidden"><h2>研究結果</h2><div id="report-summary"></div><h2 style="margin-top:22px">財報惡化</h2><div id="financial-deterioration"></div><h2 style="margin-top:22px">近期負面新聞</h2><div id="negative-news" class="coverage-grid"></div><h2 style="margin-top:22px">KAM問題</h2><div class="muted">KAM存在本身不等於問題；查核意見、繼續經營、強調事項與會計師異動分開顯示。</div><div id="kam-judgement"></div><h2 style="margin-top:22px">報酬機率</h2><div id="probabilities" class="status-grid"></div><h2 style="margin-top:22px">Evidence Coverage</h2><div id="coverage" class="coverage-grid"></div><h2 style="margin-top:22px">本機財報庫</h2><div id="filing-store" class="coverage-grid"></div><h2 style="margin-top:22px">官方引用證據</h2><div id="evidence-citations"></div><div id="limitations" class="muted" style="margin-top:14px"></div><details style="margin-top:14px"><summary>查看原始結果 JSON</summary><pre id="raw-result"></pre></details></section>
35|</main><script>
36|const form=document.querySelector('#analysis-form'),identifier=document.querySelector('#identifier'),market=document.querySelector('#market'),submit=document.querySelector('#submit'),suggestions=document.querySelector('#suggestions'),formError=document.querySelector('#form-error'),jobPanel=document.querySelector('#job-panel'),resultPanel=document.querySelector('#result-panel');let pollTimer=null,searchTimer=null;
37|const showError=(el,msg)=>{el.textContent=msg;el.classList.toggle('hidden',!msg)};
38|const stageOrder=['queued','collecting_official_evidence','research_report_complete'];
39|function renderJob(job){jobPanel.classList.remove('hidden');document.querySelector('#company').textContent=`${job.security_code} ${job.company_name} · ${job.market} · issuer ${job.issuer_id}`;document.querySelector('#status').textContent=job.status;document.querySelector('#generation').textContent=job.generation_id;document.querySelectorAll('.timeline li').forEach((li,i)=>{const current=Math.max(0,stageOrder.indexOf(job.stage));li.classList.toggle('done',job.status==='succeeded'||i<current);li.classList.toggle('active',job.status!=='failed'&&i===current)});showError(document.querySelector('#job-error'),job.error||'')}
40|function probabilityCard(label,value){const item=value||{status:'unavailable'};const formal=item.status==='formal';const point=formal?`${(Number(item.point)*100).toFixed(1)}%`:'Unavailable';const interval=formal?`90%區間 ${(Number(item.lower)*100).toFixed(1)}%–${(Number(item.upper)*100).toFixed(1)}%`:escapeHtml(item.reason||'尚未正式校準');return `<div class="metric"><span class="muted">${escapeHtml(label)} · ${escapeHtml(item.status)}</span><strong class="${formal?'coverage-ok':'coverage-gap'}">${point}</strong><span class="muted">${interval}</span></div>`}
41|function caseCard(label,value){if(!value)return '';const findings=(value.findings||[]).map(item=>{const materiality=item.materiality==null?'':` · materiality ${(Number(item.materiality)*100).toFixed(0)}%`;return `<li style="margin-bottom:10px"><span class="muted">${escapeHtml(item.kind)} / ${escapeHtml(item.direction)}${materiality}</span><br>${escapeHtml(item.statement)}</li>`}).join('');return `<div class="metric"><span class="muted">${escapeHtml(label)} · ${escapeHtml(value.status)} · confidence ${(Number(value.confidence)*100).toFixed(0)}%</span><strong>${escapeHtml(value.headline)}</strong><ul>${findings}</ul></div>`}
42|function anomalyCard(item){const list=value=>Array.isArray(value)&&value.length?value.join('；'):'目前沒有已准入內容';return `<article class="metric"><span class="muted">${escapeHtml(item.family)} · ${escapeHtml(item.explanation_status)}</span><strong>${escapeHtml(item.statement)}</strong><div class="metric"><span>severity</span><strong>${escapeHtml(item.severity)}</strong></div><div class="metric"><span>confidence</span><strong>${escapeHtml(item.confidence)}</strong></div><div class="metric"><span>evidence</span><strong>${escapeHtml(list(item.evidence))}</strong></div><div class="metric"><span>counterevidence</span><strong>${escapeHtml(list(item.counterevidence))}</strong></div><div class="metric"><span>monitoring</span><strong>${escapeHtml(item.monitoring)}</strong></div><div class="metric"><span>invalidation</span><strong>${escapeHtml(item.invalidation)}</strong></div></article>`}
43|function anomalySection(report){const items=((report&&report.downside&&report.downside.findings)||[]).filter(item=>item.explanation_status);return items.length?items.map(anomalyCard).join(''):'<div class="metric muted">本generation沒有達到30%相對變動與1%公司規模重大性的候選，或核心來源仍不足。</div>'}
44|45|function kamCard(kam){if(!kam)return '<div class="error">KAM判讀尚未產生。</div>';const years=(kam.years||[]).map(year=>`<details style="margin:8px 0"><summary>${escapeHtml(year.period)} · KAM原文 · opinion ${escapeHtml(year.opinion_type||'unknown')}</summary><p>${escapeHtml(year.citation?.verbatim_excerpt||'')}</p><div class="muted">modified opinion: ${year.modified_opinion} · going concern: ${year.going_concern} · emphasis matter: ${year.emphasis_matter} · auditor change: ${year.auditor_change}</div></details>`).join('');const judgement=kam.change_summary?`<div class="metric"><span class="muted">${escapeHtml(kam.status)} · severity ${escapeHtml(kam.severity)} · confidence ${(Number(kam.confidence)*100).toFixed(0)}%</span><strong>${escapeHtml(kam.change_summary)}</strong><ul><li>風險機制：${escapeHtml(kam.risk_mechanism)}</li><li>反證：${escapeHtml(kam.counterevidence)}</li><li>監控：${escapeHtml(kam.monitoring)}</li><li>失效條件：${escapeHtml(kam.invalidation)}</li></ul></div>`:`<div class="metric"><strong class="coverage-gap">partial</strong><span class="muted">${escapeHtml((kam.rejection_reasons||[]).join(', '))}</span></div>`;return judgement+years}
46|function trendValue(value,percent=false){if(value==null)return '—';return percent?`${(Number(value)*100).toFixed(1)}%`:Number(value).toLocaleString()}
47|function financialDeterioration(section){if(!section)return '<div class="error">財報惡化資料不足。</div>';const periods=(section.periods||[]).map(period=>`<details style="margin:8px 0"><summary>${escapeHtml(period.period)} · ${escapeHtml(period.basis)}</summary><div class="coverage-grid">${(period.metrics||[]).map(metric=>`<div class="metric"><span class="muted">${escapeHtml(metric.label)} · ${escapeHtml(metric.direction)}</span><strong>${trendValue(metric.absolute_value)}</strong><span class="muted">比率 ${trendValue(metric.ratio,true)} · 同比 ${trendValue(metric.yoy_change,true)} / ${trendValue(metric.ratio_yoy_change,true)}pp · sequential ${trendValue(metric.sequential_change,true)} / ${trendValue(metric.ratio_sequential_change,true)}pp</span></div>`).join('')}</div></details>`).join('');const items=(section.items||[]).map(item=>`<div class="metric"><span class="muted">severity ${escapeHtml(item.severity)} · confidence ${(Number(item.confidence)*100).toFixed(0)}%</span><strong>${escapeHtml(item.summary)}</strong><h3>證據</h3><ul>${(item.evidence||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul><h3>反證</h3><ul>${(item.counterevidence||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul><h3>監控點</h3><ul>${(item.monitoring||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul><h3>失效條件</h3><ul>${(item.invalidation||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul></div>`).join('');return `<div class="muted">${escapeHtml(section.status)}${section.partial_reason?` · ${escapeHtml(section.partial_reason)}`:''}</div>${items}${periods}`}
48|51|function newsCard(item){return `<article class="metric"><span class="muted">${escapeHtml(item.category)} · ${escapeHtml(item.status)} · ${escapeHtml(item.verification_status)}</span><strong>${escapeHtml(item.event_date)} · ${escapeHtml(item.publisher)}</strong><div class="metric"><span>affected account / cash flow</span><strong>${escapeHtml(item.affected_account)} / ${escapeHtml(item.cash_flow)}</strong></div><div class="metric"><span>realised / hypothetical</span><strong>${escapeHtml(item.impact)}</strong></div><div class="metric"><span>severity / confidence</span><strong>${escapeHtml(item.severity)} / ${escapeHtml(item.confidence)}</strong></div><div class="metric"><span>counterevidence</span><strong>${escapeHtml(item.counterevidence)}</strong></div><div class="metric"><span>monitoring</span><strong>${escapeHtml(item.monitoring)}</strong></div><div class="metric"><span>invalidation</span><strong>${escapeHtml(item.invalidation)}</strong></div><div class="metric"><span>duplicate cluster</span><strong>${escapeHtml(item.duplicate_cluster)}</strong></div><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">原文與citation</a></article>`}
52|function newsSection(result){const news=result.recent_negative_news||{status:'partial',events:[],missing_reasons:['news_not_run']};const cards=(news.events||[]).map(newsCard).join('');const gap=news.status==='partial'?`<div class="metric coverage-gap">partial：${escapeHtml((news.missing_reasons||[]).join('；'))}；缺失不得視為零風險。</div>`:'';return cards+gap||'<div class="metric muted">本generation沒有已准入近期負面新聞。</div>'}
53|function citationCard(item){const location=item.source_format==='pdf'?`第 ${item.page} 頁 · bbox ${(item.coordinate||[]).join(', ')}`:item.locator;return `<details style="margin:8px 0;padding:10px;border:1px solid var(--line);border-radius:10px;background:white"><summary>${escapeHtml(item.period)} · ${escapeHtml(item.source_id)} · ${escapeHtml(location||'')}</summary><p>${escapeHtml(item.verbatim_excerpt)}</p><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">開啟官方來源</a></details>`}
49|function renderResult(result){resultPanel.classList.remove('hidden');const report=result.research_report||null;document.querySelector('#report-summary').innerHTML=report?`<div class="status-grid">${caseCard('下跌風險',report.downside)}${caseCard('上漲潛力',report.upside)}</div><h2 style="margin-top:22px">無法解釋財報異常</h2><div class="coverage-grid">${anomalySection(report)}</div>`:'<div class="error">此工作只有舊版 evidence bundle，請重新建立分析。</div>';document.querySelector('#financial-deterioration').innerHTML=report?financialDeterioration(report.financial_deterioration):'';document.querySelector('#negative-news').innerHTML=newsSection(result);document.querySelector('#kam-judgement').innerHTML=kamCard(result.kam_judgement);document.querySelector('#probabilities').innerHTML=report?probabilityCard('12個月絕對正報酬',report.upside.positive_return_probability)+probabilityCard('12個月跑贏官方指數',report.upside.benchmark_outperform_probability)+probabilityCard('12個月內最大跌幅',report.downside.twelve_month_drawdown_probability):'';const rows=result.source_coverage||[];document.querySelector('#coverage').innerHTML=rows.map(row=>`<div class="metric"><span class="muted">${escapeHtml(row.family)}</span><strong class="${row.available===row.required?'coverage-ok':'coverage-gap'}">${row.available} / ${row.required}</strong><span class="muted">${row.missing_reasons?.length||0} 個缺口</span></div>`).join('');const cache=result.filing_store_stats||{hits:0,misses:0,saved:0,corruptions:0};document.querySelector('#filing-store').innerHTML=[['Local hits',cache.hits],['Online misses',cache.misses],['Saved PDFs',cache.saved],['Corruptions',cache.corruptions]].map(item=>`<div class="metric"><span class="muted">${item[0]}</span><strong>${item[1]}</strong></div>`).join('');document.querySelector('#evidence-citations').innerHTML=report?(report.citations||[]).map(citationCard).join(''):'';document.querySelector('#limitations').innerHTML=report?`<strong>限制</strong><ul>${(report.limitations||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:'';document.querySelector('#raw-result').textContent=JSON.stringify(result,null,2)}
56|const escapeHtml=s=>String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
57|async function poll(jobId){const response=await fetch(`/api/analyses/${jobId}`);const job=await response.json();if(!response.ok)throw new Error(job.error||'查詢工作失敗');renderJob(job);if(job.status==='succeeded'){const rr=await fetch(`/api/analyses/${jobId}/result`);const result=await rr.json();if(!rr.ok)throw new Error(result.error||'讀取結果失敗');renderResult(result);submit.disabled=false;return}if(job.status==='failed'){submit.disabled=false;return}pollTimer=setTimeout(()=>poll(jobId).catch(e=>showError(document.querySelector('#job-error'),e.message)),1500)}
58|form.addEventListener('submit',async event=>{event.preventDefault();clearTimeout(pollTimer);showError(formError,'');resultPanel.classList.add('hidden');submit.disabled=true;try{const response=await fetch('/api/analyses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:identifier.value,market:market.value||null})});const job=await response.json();if(!response.ok)throw new Error(job.error||'建立工作失敗');localStorage.setItem('companyQualityJobId',job.job_id);renderJob(job);poll(job.job_id).catch(e=>showError(document.querySelector('#job-error'),e.message))}catch(error){showError(formError,error.message);submit.disabled=false}});
59|identifier.addEventListener('input',()=>{clearTimeout(searchTimer);const q=identifier.value.trim();if(!q){suggestions.classList.add('hidden');return}searchTimer=setTimeout(async()=>{try{const response=await fetch(`/api/companies/search?q=${encodeURIComponent(q)}`);const rows=await response.json();suggestions.innerHTML=rows.map(row=>`<button type="button" data-code="${escapeHtml(row.security_code)}" data-market="${escapeHtml(row.market)}">${escapeHtml(row.security_code)} · ${escapeHtml(row.short_name)} <span class="muted">${escapeHtml(row.market)}</span></button>`).join('');suggestions.classList.toggle('hidden',!rows.length);suggestions.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{identifier.value=button.dataset.code;market.value=button.dataset.market;suggestions.classList.add('hidden')}))}catch(_){suggestions.classList.add('hidden')}},250)});
60|const savedJobId=localStorage.getItem('companyQualityJobId');if(savedJobId){submit.disabled=true;poll(savedJobId).catch(error=>{localStorage.removeItem('companyQualityJobId');submit.disabled=false;showError(formError,error.message)})}
61|</script></body></html>"""
62|
63|
64|def _public_job(job: dict[str, object]) -> dict[str, object]:
65|    return {key: value for key, value in job.items() if key != "result_path"}
66|
67|
68|def make_server(
69|    service: AnalysisJobService,
70|    *,
71|    host: str = "127.0.0.1",
72|    port: int = 8890,
73|) -> ThreadingHTTPServer:
74|    class Handler(BaseHTTPRequestHandler):
75|        def log_message(self, format: str, *args: object) -> None:
76|            return
77|
78|        def _send_json(self, status: int, payload: object) -> None:
79|            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
80|            self.send_response(status)
81|            self.send_header("Content-Type", "application/json; charset=utf-8")
82|            self.send_header("Content-Length", str(len(body)))
83|            self.send_header("Cache-Control", "no-store")
84|            self.end_headers()
85|            self.wfile.write(body)
86|
87|        def _error(self, status: int, message: str) -> None:
88|            self._send_json(status, {"error": message})
89|
90|        def do_GET(self) -> None:
91|            parsed = urlparse(self.path)
92|            if parsed.path == "/":
93|                body = _INDEX.encode("utf-8")
94|                self.send_response(200)
95|                self.send_header("Content-Type", "text/html; charset=utf-8")
96|                self.send_header("Content-Length", str(len(body)))
97|                self.end_headers()
98|                self.wfile.write(body)
99|                return
100|            if parsed.path == "/api/health":
101|                self._send_json(200, {"status": "ok"})
102|                return
103|            if parsed.path == "/api/companies/search":
104|                query = parse_qs(parsed.query).get("q", [""])[0]
105|                try:
106|                    self._send_json(200, service.search_companies(query))
107|                except Exception as exc:
108|                    self._error(503, f"company search unavailable: {exc}")
109|                return
110|            parts = parsed.path.strip("/").split("/")
111|            if len(parts) in (3, 4) and parts[:2] == ["api", "analyses"]:
112|                try:
113|                    job = service.get_job(parts[2])
114|                    if len(parts) == 3:
115|                        self._send_json(200, _public_job(job))
116|                    elif parts[3] == "result":
117|                        result = service.get_result(parts[2])
118|                        if result is None:
119|                            self._error(409, "analysis result is not ready")
120|                        else:
121|                            self._send_json(200, result)
122|                    else:
123|                        self._error(404, "not found")
124|                except DashboardJobError as exc:
125|                    self._error(404, str(exc))
126|                return
127|            self._error(404, "not found")
128|
129|        def do_POST(self) -> None:
130|            if urlparse(self.path).path != "/api/analyses":
131|                self._error(404, "not found")
132|                return
133|            try:
134|                length = int(self.headers.get("Content-Length", "0"))
135|            except ValueError:
136|                self._error(400, "invalid content length")
137|                return
138|            if length <= 0 or length > _MAX_BODY:
139|                self._error(413, "request body must be 1..16384 bytes")
140|                return
141|            try:
142|                payload: Any = json.loads(self.rfile.read(length))
143|                if not isinstance(payload, dict):
144|                    raise ValueError("JSON object required")
145|                job = service.create_job(
146|                    identifier=payload.get("identifier", ""),
147|                    market=payload.get("market"),
148|                    as_of=datetime.now(_TAIPEI).isoformat(timespec="seconds"),
149|                )
150|                self._send_json(202, _public_job(job))
151|            except (DashboardJobError, ValueError, TypeError) as exc:
152|                if isinstance(exc, DashboardJobError):
153|                    self._send_json(400, exc.payload())
154|                else:
155|                    self._error(400, str(exc))
156|            except Exception as exc:
157|                self._error(503, f"analysis service unavailable: {exc}")
158|
159|    return ThreadingHTTPServer((host, port), Handler)
160|
161|
162|def main() -> int:
163|    parser = argparse.ArgumentParser()
164|    parser.add_argument("--host", default="127.0.0.1")
165|    parser.add_argument("--port", type=int, default=8890)
166|    parser.add_argument(
167|        "--data-root",
168|        type=Path,
169|        default=Path(os.environ.get("COMPANY_QUALITY_DASHBOARD_ROOT", ".scratch/dashboard")),
170|    )
171|    args = parser.parse_args()
172|    service = AnalysisJobService(
173|        database_path=args.data_root / "jobs.sqlite3",
174|        output_root=args.data_root / "analyses",
175|    )
176|    service.start()
177|    server = make_server(service, host=args.host, port=args.port)
178|    print(f"Company Quality Dashboard: http://{args.host}:{server.server_port}")
179|    try:
180|        server.serve_forever()
181|    except KeyboardInterrupt:
182|        pass
183|    finally:
184|        server.server_close()
185|        service.stop()
186|    return 0
187|
188|
189|if __name__ == "__main__":
190|    raise SystemExit(main())
191|
192|
193|__all__ = ["make_server", "main"]
194|