"""Local HTTP dashboard for starting and observing company-analysis jobs."""

from __future__ import annotations

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from company_quality.dashboard_jobs import AnalysisJobService, DashboardJobError


_TAIPEI = ZoneInfo("Asia/Taipei")
_MAX_BODY = 16_384

_INDEX = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Company Quality Research</title>
<style>
:root{--bg:#f4f1e9;--panel:#fffdf8;--ink:#1f2933;--muted:#667085;--line:#d9d2c3;--accent:#6657c7;--ok:#237a4b;--warn:#a46112;--bad:#b42318;--radius:16px}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,"Noto Sans TC",system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:34px 22px 60px}header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:24px}h1{margin:0 0 8px;font-size:30px}h2{font-size:18px;margin:0 0 14px}.muted{color:var(--muted);font-size:13px}.badge{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:7px 11px;font-weight:700}.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:0 8px 24px rgba(55,47,35,.05)}form{display:grid;grid-template-columns:minmax(260px,1fr) 150px 130px;gap:10px}input,select,button{min-height:46px;border-radius:10px;border:1px solid var(--line);font:inherit}input,select{background:white;padding:0 13px;color:var(--ink)}button{background:var(--accent);color:white;border-color:var(--accent);font-weight:800;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}input:focus-visible,select:focus-visible,button:focus-visible{outline:3px solid rgba(102,87,199,.28);outline-offset:2px}.suggestions{position:relative}.suggestion-list{position:absolute;z-index:3;top:49px;left:0;right:0;background:white;border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 24px rgba(31,41,51,.12);overflow:hidden}.suggestion-list button{display:block;width:100%;text-align:left;background:white;color:var(--ink);border:0;border-radius:0;padding:10px 12px}.suggestion-list button:hover{background:#f4f1ff}.hidden{display:none!important}.status-grid,.coverage-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:16px}.metric{background:white;border:1px solid var(--line);border-radius:12px;padding:15px}.metric strong{display:block;font-size:19px;margin-top:6px}.timeline{list-style:none;padding:0;margin:14px 0 0}.timeline li{border-left:3px solid var(--line);padding:8px 0 8px 13px;color:var(--muted)}.timeline li.active{border-color:var(--accent);color:var(--ink);font-weight:700}.timeline li.done{border-color:var(--ok);color:var(--ok)}.error{margin-top:14px;padding:12px;border:1px solid #f3b5af;background:#fff2f0;color:var(--bad);border-radius:10px;white-space:pre-wrap}.result{margin-top:16px}.coverage-ok{color:var(--ok)}.coverage-gap{color:var(--warn)}pre{background:#18202a;color:#e7edf3;padding:14px;border-radius:10px;overflow:auto;max-height:330px;font-size:12px}@media(max-width:760px){form,.status-grid,.coverage-grid{grid-template-columns:1fr}header{display:block}.badge{display:inline-block;margin-top:10px}}
</style></head><body><main>
<header><div><h1>Company Quality Research</h1><div class="muted">輸入上市／上櫃公司股號或名稱，啟動官方資料 evidence-first 分析</div></div><div class="badge">LOCAL · ANALYSIS ONLY</div></header>
<section class="panel"><h2>建立分析</h2><form id="analysis-form"><div class="suggestions"><input id="identifier" autocomplete="off" placeholder="例如：2330 或 台積電" required maxlength="128"><div id="suggestions" class="suggestion-list hidden"></div></div><select id="market"><option value="">自動判斷市場</option><option value="TWSE">上市 TWSE</option><option value="TPEx">上櫃 TPEx</option></select><button id="submit" type="submit">開始分析</button></form><div id="form-error" class="error hidden"></div></section>
<section id="job-panel" class="panel hidden" style="margin-top:16px"><h2>分析進度</h2><div class="status-grid"><div class="metric"><span class="muted">公司</span><strong id="company">—</strong></div><div class="metric"><span class="muted">工作狀態</span><strong id="status">—</strong></div><div class="metric"><span class="muted">Generation</span><strong id="generation" style="font-size:13px;word-break:break-all">—</strong></div></div><ol class="timeline"><li data-stage="queued">工作已建立</li><li data-stage="collecting_official_evidence">收集五年官方財報與查核資料</li><li data-stage="research_report_complete">研究報告完成</li></ol><div id="job-error" class="error hidden"></div></section>
<section id="result-panel" class="panel result hidden"><h2>研究結果</h2><div id="report-summary"></div><h2 style="margin-top:22px">財報惡化</h2><div id="financial-deterioration"></div><h2 style="margin-top:22px">近期負面新聞</h2><div id="negative-news" class="coverage-grid"></div><h2 style="margin-top:22px">KAM問題</h2><div class="muted">KAM存在本身不等於問題；查核意見、繼續經營、強調事項與會計師異動分開顯示。</div><div id="kam-judgement"></div><h2 style="margin-top:22px">報酬機率</h2><div id="probabilities" class="status-grid"></div><h2 style="margin-top:22px">Evidence Coverage</h2><div id="coverage" class="coverage-grid"></div><h2 style="margin-top:22px">本機財報庫</h2><div id="filing-store" class="coverage-grid"></div><h2 style="margin-top:22px">官方引用證據</h2><div id="evidence-citations"></div><div id="limitations" class="muted" style="margin-top:14px"></div><details style="margin-top:14px"><summary>查看原始結果 JSON</summary><pre id="raw-result"></pre></details></section>
</main><script>
const form=document.querySelector('#analysis-form'),identifier=document.querySelector('#identifier'),market=document.querySelector('#market'),submit=document.querySelector('#submit'),suggestions=document.querySelector('#suggestions'),formError=document.querySelector('#form-error'),jobPanel=document.querySelector('#job-panel'),resultPanel=document.querySelector('#result-panel');let pollTimer=null,searchTimer=null;
const showError=(el,msg)=>{el.textContent=msg;el.classList.toggle('hidden',!msg)};
const stageOrder=['queued','collecting_official_evidence','research_report_complete'];
function renderJob(job){jobPanel.classList.remove('hidden');document.querySelector('#company').textContent=`${job.security_code} ${job.company_name} · ${job.market} · issuer ${job.issuer_id}`;document.querySelector('#status').textContent=job.status;document.querySelector('#generation').textContent=job.generation_id;document.querySelectorAll('.timeline li').forEach((li,i)=>{const current=Math.max(0,stageOrder.indexOf(job.stage));li.classList.toggle('done',job.status==='succeeded'||i<current);li.classList.toggle('active',job.status!=='failed'&&i===current)});showError(document.querySelector('#job-error'),job.error||'')}
function probabilityCard(label,value){const item=value||{status:'unavailable'};const formal=item.status==='formal';const point=formal?`${(Number(item.point)*100).toFixed(1)}%`:'Unavailable';const interval=formal?`90%區間 ${(Number(item.lower)*100).toFixed(1)}%–${(Number(item.upper)*100).toFixed(1)}%`:escapeHtml(item.reason||'尚未正式校準');return `<div class="metric"><span class="muted">${escapeHtml(label)} · ${escapeHtml(item.status)}</span><strong class="${formal?'coverage-ok':'coverage-gap'}">${point}</strong><span class="muted">${interval}</span></div>`}
function caseCard(label,value){if(!value)return '';const findings=(value.findings||[]).map(item=>{const materiality=item.materiality==null?'':` · materiality ${(Number(item.materiality)*100).toFixed(0)}%`;return `<li style="margin-bottom:10px"><span class="muted">${escapeHtml(item.kind)} / ${escapeHtml(item.direction)}${materiality}</span><br>${escapeHtml(item.statement)}</li>`}).join('');return `<div class="metric"><span class="muted">${escapeHtml(label)} · ${escapeHtml(value.status)} · confidence ${(Number(value.confidence)*100).toFixed(0)}%</span><strong>${escapeHtml(value.headline)}</strong><ul>${findings}</ul></div>`}
function anomalyCard(item){const list=value=>Array.isArray(value)&&value.length?value.join('；'):'目前沒有已准入內容';return `<article class="metric"><span class="muted">${escapeHtml(item.family)} · ${escapeHtml(item.explanation_status)}</span><strong>${escapeHtml(item.statement)}</strong><div class="metric"><span>severity</span><strong>${escapeHtml(item.severity)}</strong></div><div class="metric"><span>confidence</span><strong>${escapeHtml(item.confidence)}</strong></div><div class="metric"><span>evidence</span><strong>${escapeHtml(list(item.evidence))}</strong></div><div class="metric"><span>counterevidence</span><strong>${escapeHtml(list(item.counterevidence))}</strong></div><div class="metric"><span>monitoring</span><strong>${escapeHtml(item.monitoring)}</strong></div><div class="metric"><span>invalidation</span><strong>${escapeHtml(item.invalidation)}</strong></div></article>`}
function anomalySection(report){const items=((report&&report.downside&&report.downside.findings)||[]).filter(item=>item.explanation_status);return items.length?items.map(anomalyCard).join(''):'<div class="metric muted">本generation沒有達到30%相對變動與1%公司規模重大性的候選，或核心來源仍不足。</div>'}
function kamCard(kam){if(!kam)return '<div class="error">KAM判讀尚未產生。</div>';const years=(kam.years||[]).map(year=>`<details style="margin:8px 0"><summary>${escapeHtml(year.period)} · KAM原文 · opinion ${escapeHtml(year.opinion_type||'unknown')}</summary><p>${escapeHtml(year.citation?.verbatim_excerpt||'')}</p><div class="muted">modified opinion: ${year.modified_opinion} · going concern: ${year.going_concern} · emphasis matter: ${year.emphasis_matter} · auditor change: ${year.auditor_change}</div></details>`).join('');const judgement=kam.change_summary?`<div class="metric"><span class="muted">${escapeHtml(kam.status)} · severity ${escapeHtml(kam.severity)} · confidence ${(Number(kam.confidence)*100).toFixed(0)}%</span><strong>${escapeHtml(kam.change_summary)}</strong><ul><li>風險機制：${escapeHtml(kam.risk_mechanism)}</li><li>反證：${escapeHtml(kam.counterevidence)}</li><li>監控：${escapeHtml(kam.monitoring)}</li><li>失效條件：${escapeHtml(kam.invalidation)}</li></ul></div>`:`<div class="metric"><strong class="coverage-gap">partial</strong><span class="muted">${escapeHtml((kam.rejection_reasons||[]).join(', '))}</span></div>`;return judgement+years}
function trendValue(value,percent=false){if(value==null)return '—';return percent?`${(Number(value)*100).toFixed(1)}%`:Number(value).toLocaleString()}
function financialDeterioration(section){if(!section)return '<div class="error">財報惡化資料不足。</div>';const periods=(section.periods||[]).map(period=>`<details style="margin:8px 0"><summary>${escapeHtml(period.period)} · ${escapeHtml(period.basis)}</summary><div class="coverage-grid">${(period.metrics||[]).map(metric=>`<div class="metric"><span class="muted">${escapeHtml(metric.label)} · ${escapeHtml(metric.direction)}</span><strong>${trendValue(metric.absolute_value)}</strong><span class="muted">比率 ${trendValue(metric.ratio,true)} · 同比 ${trendValue(metric.yoy_change,true)} / ${trendValue(metric.ratio_yoy_change,true)}pp · sequential ${trendValue(metric.sequential_change,true)} / ${trendValue(metric.ratio_sequential_change,true)}pp</span></div>`).join('')}</div></details>`).join('');const items=(section.items||[]).map(item=>`<div class="metric"><span class="muted">severity ${escapeHtml(item.severity)} · confidence ${(Number(item.confidence)*100).toFixed(0)}%</span><strong>${escapeHtml(item.summary)}</strong><h3>證據</h3><ul>${(item.evidence||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul><h3>反證</h3><ul>${(item.counterevidence||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul><h3>監控點</h3><ul>${(item.monitoring||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul><h3>失效條件</h3><ul>${(item.invalidation||[]).map(value=>`<li>${escapeHtml(value)}</li>`).join('')}</ul></div>`).join('');return `<div class="muted">${escapeHtml(section.status)}${section.partial_reason?` · ${escapeHtml(section.partial_reason)}`:''}</div>${items}${periods}`}
function newsCard(item){return `<article class="metric"><span class="muted">${escapeHtml(item.category)} · ${escapeHtml(item.status)} · ${escapeHtml(item.verification_status)}</span><strong>${escapeHtml(item.event_date)} · ${escapeHtml(item.publisher)}</strong><div class="metric"><span>affected account / cash flow</span><strong>${escapeHtml(item.affected_account)} / ${escapeHtml(item.cash_flow)}</strong></div><div class="metric"><span>realised / hypothetical</span><strong>${escapeHtml(item.impact)}</strong></div><div class="metric"><span>severity / confidence</span><strong>${escapeHtml(item.severity)} / ${escapeHtml(item.confidence)}</strong></div><div class="metric"><span>counterevidence</span><strong>${escapeHtml(item.counterevidence)}</strong></div><div class="metric"><span>monitoring</span><strong>${escapeHtml(item.monitoring)}</strong></div><div class="metric"><span>invalidation</span><strong>${escapeHtml(item.invalidation)}</strong></div><div class="metric"><span>duplicate cluster</span><strong>${escapeHtml(item.duplicate_cluster)}</strong></div><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">原文與citation</a></article>`}
function newsSection(result){const news=result.recent_negative_news||{status:'partial',events:[],missing_reasons:['news_not_run']};const cards=(news.events||[]).map(newsCard).join('');const gap=news.status==='partial'?`<div class="metric coverage-gap">partial：${escapeHtml((news.missing_reasons||[]).join('；'))}；缺失不得視為零風險。</div>`:'';return cards+gap||'<div class="metric muted">本generation沒有已准入近期負面新聞。</div>'}
function citationCard(item){const location=item.source_format==='pdf'?`第 ${item.page} 頁 · bbox ${(item.coordinate||[]).join(', ')}`:item.locator;return `<details style="margin:8px 0;padding:10px;border:1px solid var(--line);border-radius:10px;background:white"><summary>${escapeHtml(item.period)} · ${escapeHtml(item.source_id)} · ${escapeHtml(location||'')}</summary><p>${escapeHtml(item.verbatim_excerpt)}</p><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">開啟官方來源</a></details>`}
function renderResult(result){resultPanel.classList.remove('hidden');const report=result.research_report||null;document.querySelector('#report-summary').innerHTML=report?`<div class="status-grid">${caseCard('下跌風險',report.downside)}${caseCard('上漲潛力',report.upside)}</div><h2 style="margin-top:22px">無法解釋財報異常</h2><div class="coverage-grid">${anomalySection(report)}</div>`:'<div class="error">此工作只有舊版 evidence bundle，請重新建立分析。</div>';document.querySelector('#financial-deterioration').innerHTML=report?financialDeterioration(report.financial_deterioration):'';document.querySelector('#negative-news').innerHTML=newsSection(result);document.querySelector('#kam-judgement').innerHTML=kamCard(result.kam_judgement);document.querySelector('#probabilities').innerHTML=report?probabilityCard('12個月絕對正報酬',report.upside.positive_return_probability)+probabilityCard('12個月跑贏官方指數',report.upside.benchmark_outperform_probability)+probabilityCard('12個月內最大跌幅',report.downside.twelve_month_drawdown_probability):'';const rows=result.source_coverage||[];document.querySelector('#coverage').innerHTML=rows.map(row=>`<div class="metric"><span class="muted">${escapeHtml(row.family)}</span><strong class="${row.available===row.required?'coverage-ok':'coverage-gap'}">${row.available} / ${row.required}</strong><span class="muted">${row.missing_reasons?.length||0} 個缺口</span></div>`).join('');const cache=result.filing_store_stats||{hits:0,misses:0,saved:0,corruptions:0};document.querySelector('#filing-store').innerHTML=[['Local hits',cache.hits],['Online misses',cache.misses],['Saved PDFs',cache.saved],['Corruptions',cache.corruptions]].map(item=>`<div class="metric"><span class="muted">${item[0]}</span><strong>${item[1]}</strong></div>`).join('');document.querySelector('#evidence-citations').innerHTML=report?(report.citations||[]).map(citationCard).join(''):'';document.querySelector('#limitations').innerHTML=report?`<strong>限制</strong><ul>${(report.limitations||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:'';document.querySelector('#raw-result').textContent=JSON.stringify(result,null,2)}
const escapeHtml=s=>String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
async function poll(jobId){const response=await fetch(`/api/analyses/${jobId}`);const job=await response.json();if(!response.ok)throw new Error(job.error||'查詢工作失敗');renderJob(job);if(job.status==='succeeded'){const rr=await fetch(`/api/analyses/${jobId}/result`);const result=await rr.json();if(!rr.ok)throw new Error(result.error||'讀取結果失敗');renderResult(result);submit.disabled=false;return}if(job.status==='failed'){submit.disabled=false;return}pollTimer=setTimeout(()=>poll(jobId).catch(e=>showError(document.querySelector('#job-error'),e.message)),1500)}
form.addEventListener('submit',async event=>{event.preventDefault();clearTimeout(pollTimer);showError(formError,'');resultPanel.classList.add('hidden');submit.disabled=true;try{const response=await fetch('/api/analyses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:identifier.value,market:market.value||null})});const job=await response.json();if(!response.ok)throw new Error(job.error||'建立工作失敗');localStorage.setItem('companyQualityJobId',job.job_id);renderJob(job);poll(job.job_id).catch(e=>showError(document.querySelector('#job-error'),e.message))}catch(error){showError(formError,error.message);submit.disabled=false}});
identifier.addEventListener('input',()=>{clearTimeout(searchTimer);const q=identifier.value.trim();if(!q){suggestions.classList.add('hidden');return}searchTimer=setTimeout(async()=>{try{const response=await fetch(`/api/companies/search?q=${encodeURIComponent(q)}`);const rows=await response.json();suggestions.innerHTML=rows.map(row=>`<button type="button" data-code="${escapeHtml(row.security_code)}" data-market="${escapeHtml(row.market)}">${escapeHtml(row.security_code)} · ${escapeHtml(row.short_name)} <span class="muted">${escapeHtml(row.market)}</span></button>`).join('');suggestions.classList.toggle('hidden',!rows.length);suggestions.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{identifier.value=button.dataset.code;market.value=button.dataset.market;suggestions.classList.add('hidden')}))}catch(_){suggestions.classList.add('hidden')}},250)});
const savedJobId=localStorage.getItem('companyQualityJobId');if(savedJobId){submit.disabled=true;poll(savedJobId).catch(error=>{localStorage.removeItem('companyQualityJobId');submit.disabled=false;showError(formError,error.message)})}
</script></body></html>"""


def _public_job(job: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in job.items() if key != "result_path"}


def make_server(
    service: AnalysisJobService,
    *,
    host: str = "127.0.0.1",
    port: int = 8890,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._send_json(status, {"error": message})

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = _INDEX.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/health":
                self._send_json(200, {"status": "ok"})
                return
            if parsed.path == "/api/companies/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                try:
                    self._send_json(200, service.search_companies(query))
                except Exception as exc:
                    self._error(503, f"company search unavailable: {exc}")
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) in (3, 4) and parts[:2] == ["api", "analyses"]:
                try:
                    job = service.get_job(parts[2])
                    if len(parts) == 3:
                        self._send_json(200, _public_job(job))
                    elif parts[3] == "result":
                        result = service.get_result(parts[2])
                        if result is None:
                            self._error(409, "analysis result is not ready")
                        else:
                            self._send_json(200, result)
                    else:
                        self._error(404, "not found")
                except DashboardJobError as exc:
                    self._error(404, str(exc))
                return
            self._error(404, "not found")

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/analyses":
                self._error(404, "not found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._error(400, "invalid content length")
                return
            if length <= 0 or length > _MAX_BODY:
                self._error(413, "request body must be 1..16384 bytes")
                return
            try:
                payload: Any = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                job = service.create_job(
                    identifier=payload.get("identifier", ""),
                    market=payload.get("market"),
                    as_of=datetime.now(_TAIPEI).isoformat(timespec="seconds"),
                )
                self._send_json(202, _public_job(job))
            except (DashboardJobError, ValueError, TypeError) as exc:
                if isinstance(exc, DashboardJobError):
                    self._send_json(400, exc.payload())
                else:
                    self._error(400, str(exc))
            except Exception as exc:
                self._error(503, f"analysis service unavailable: {exc}")

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("COMPANY_QUALITY_DASHBOARD_ROOT", ".scratch/dashboard")),
    )
    args = parser.parse_args()
    service = AnalysisJobService(
        database_path=args.data_root / "jobs.sqlite3",
        output_root=args.data_root / "analyses",
    )
    service.start()
    server = make_server(service, host=args.host, port=args.port)
    print(f"Company Quality Dashboard: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["make_server", "main"]
