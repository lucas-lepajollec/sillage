# Internal implementation contract
Paths shown to clients are absolute under configured MEDIA_ROOTS (default /media). API errors {detail:string}. No mock provider production.
GET /api/health -> {status,tools:{ffmpeg:bool,ffprobe:bool,mkvextract:bool,ffsubsync:bool},version}
GET /api/browse?path= -> {path,parent:string|null,roots:string[],directories:[{name,path}],files:[{name,path}]}. Blank path selects first root.
POST /api/scan {path,recursive:boolean} -> {episodes:[{path,name,duration:number,tracks:[{id:string,index:number|null,language,format,title,default:boolean,forced:boolean,sdh:boolean,external:boolean,path?:string,supported:boolean}],has_french:boolean,status:string,error?:string}],errors:[{path,error}]}
POST /api/preview {path,track_id} -> {format,cues:[{id:string,start:number,end:number,text:string,translated?:string,warning?:string}],warnings:string[],timing_status:string}; start/end milliseconds.
GET /api/providers -> Provider[] (no api_key; has_key:boolean)
POST /api/providers body Provider + api_key -> sanitized saved provider.
POST /api/providers/models {id?:string,kind:string,base_url?:string,api_key?:string} -> {models:[{id:string,name:string}],truncated:boolean}. Live catalogue GET only, no generation or save. An omitted key reuses the saved id's key only for its unchanged provider kind/normalized endpoint. Results and errors never return the key.
DELETE /api/providers/{id} -> {ok:true}
POST /api/providers/{id}/test -> {ok:true,message:string} genuine call.
Provider: {id?:string,name,kind:'openai'|'anthropic'|'gemini'|'deepseek'|'openrouter'|'ollama'|'custom',base_url:string,model:string,temperature:number|null,batch_size:number,concurrency:number,timeout:number,retries:number,source_language:string,target_language:string,glossary:string,api_key?:string,has_key?:boolean}
GET /api/jobs -> Job[] newest first. Job {id,path,name,track_id,provider_id,status:'queued'|'pausing'|'paused'|'extracting'|'translating'|'validating'|'syncing'|'writing'|'completed'|'error'|'review'|'cancelled'|'interrupted',progress:number(0..100),done:number,total:number,error:string|null,warnings:string[],output:string|null,created_at:string,sync_mode:'preserve'|'offset'|'auto',offset_ms:number,timing_status:string}
POST /api/jobs {items:[{path,track_id}],provider_id,sync_mode:'preserve'|'offset'|'auto',offset_ms:number} -> Job[]
POST /api/jobs/{id}/cancel -> Job
POST /api/jobs/{id}/resume -> Job (resume paused/error/cancelled/interrupted; checkpoints retained)
GET /api/jobs/{id}/preview -> same as preview, translations from checkpoint.
POST /api/jobs/{id}/sync/accept -> Job (only pending auto proposal; finalizes sidecar after consent)
POST /api/jobs/{id}/sync/reject -> Job (publish source timings)
GET /api/jobs/{id}/download -> subtitle file (validated root).
Optional X-Access-Key configured by ACCESS_KEY. Frontend stores in sessionStorage and attaches header; 401 shows login. GET /api/config -> {auth_required:boolean} public.

Job responses may include `adaptive_batch_size` (current conservative per-request ceiling). `Provider.batch_size` is a maximum; observed recovery can reduce actual batches. Existing jobs/checkpoints need no migration.

## Profile edits and in-place recovery (0.0.7)

`POST /api/jobs/reconfigure` accepts `{ids: string[1..500], provider_id: string, restart?: boolean}` (default false). It validates the whole group, then queues existing stopped/queued entries with the selected profile snapshot. Keeping checkpoints across a known language change is rejected; restart explicitly clears checkpoints. Active/in-flight/sync-pending/completed entries, duplicate episode paths and existing target outputs reject the group atomically. The source track remains unchanged. This endpoint can recover already-edited legacy jobs without rediscovery.

Jobs may expose `translation_profile: {name,kind,model,source_language,target_language}`; the encrypted `provider_snapshot`, source/config hashes and internal batch policy never appear in public job responses. Profile runtime limits apply at the next wave; semantic settings remain recorded until explicitly adopted. See [provider lifecycle](providers.md#editing-profiles-and-recovering-existing-jobs).

## Cooperative pause

`POST /api/jobs/{id}/pause` pauses one queued/running job; `POST /api/jobs/pause` takes `{ "ids": ["..."] }` (1–500 distinct IDs) and validates the full selection before mutation. An active worker becomes `pausing` while existing HTTP replies drain; completed replies and validated partial fragments are checkpointed. No new generation/recovery request starts after the cooperative stop check. Extract/sync operations finish their current local step before suspending. Publication in `writing` and completed/sync-review jobs refuse pause.

`paused` is durable and skipped by the queue, including after restart. `POST /api/jobs/{id}/resume` queues the remaining work using existing checkpoints. A pending `pausing` state becomes `paused` at service restart; an abrupt stop can still lose uncheckpointed in-flight replies. New jobs explicitly created later are not globally blocked. Pause in bulk follows the displayed folder/search/filter across pages, capped at500; it is not a scheduler-wide latch. Cancellation remains an immediate abort. Paused jobs still reserve their episode/provider; confirmed inactive-history deletion is allowed and profile adoption preserves pause.

Preview `stats` optionally includes `frame_animation`; jobs expose the same summary as `source_stats`. Counts refer to eligible source events, not HTTP requests or internal recovery fragments. Unsupported frame effects retain original text/timings and warn for review. Old effect checkpoints remain stored but are not rendered; eligible dialogue checkpoints are reused after source-hash validation.
