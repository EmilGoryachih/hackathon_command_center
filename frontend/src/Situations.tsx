import {useEffect,useState} from 'react'
import {api,Situation,SituationSettingsData} from './api'
import {Badge,Field,fmtDate} from './ui'

const ISSUES:Record<string,string>={CHAT_NOT_CONFIGURED:'Чат Telegram не настроен',ROUTE_DISABLED:'Маршрут события выключен'}

export function SituationCard({item:s,onOpenTask,onOpenIncident,onPlanning}:{item:Situation;onOpenTask:(id:number)=>void;onOpenIncident:(id:number)=>void;onPlanning?:()=>void}) {
  return <article className={`attention-item situation-card ${s.status==='resolved'?'is-resolved':s.level==='attention'?'needs-attention':'worth-checking'}`}>
    <div className="scan-heading"><strong>{s.title}</strong><Badge kind={s.status==='resolved'?'green':s.level==='attention'?'red':'yellow'}>{s.status==='resolved'?'Разрешена':s.level==='attention'?'Требует внимания':'Стоит проверить'}</Badge></div>
    <p>{s.text}</p>
    <p className="muted">{s.status==='resolved'?'Разрешена':'Действует'} · актуальность: {fmtDate(s.as_of)} МСК{s.first_seen_at?` · обнаружена: ${fmtDate(s.first_seen_at)}`:''}</p>
    {s.status!=='resolved'&&s.suggestion&&<p><b>Что проверить:</b> {s.suggestion}</p>}
    <div className="scan-actions">{s.task_ids.map(id=><button className="small" key={id} onClick={()=>onOpenTask(id)}>Задача #{id}</button>)}{s.incident_ids.map(id=><button className="small" key={id} onClick={()=>onOpenIncident(id)}>Инцидент #{id}</button>)}{s.type==='plan_late'&&onPlanning&&<button className="small" onClick={onPlanning}>Планирование</button>}</div>
    <details><summary>Основания и ограничения</summary><ul>{s.grounds.map((g,i)=><li key={i}>{g}</li>)}</ul>{s.limitations.map((l,i)=><p className="muted" key={i}>{l}</p>)}{s.status==='resolved'&&<p className="muted">Прежние основания сохранены для контекста. Условие правила больше не действует.</p>}</details>
    {s.delivery_issue&&<p className="tone-warn">Telegram: {ISSUES[s.delivery_issue]??s.delivery_issue}. Ситуация сохранена в платформе.</p>}
  </article>
}

export function SituationSettings() {
  const [saved,setSaved]=useState<SituationSettingsData|null>(null)
  const [form,setForm]=useState<SituationSettingsData|null>(null)
  const [error,setError]=useState('')
  const [message,setMessage]=useState('')
  const [busy,setBusy]=useState(false)
  useEffect(()=>{let live=true;api.situationSettings().then(v=>{if(live){setSaved(v);setForm(v)}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[])
  if(!form)return <p role={error?'alert':'status'}>{error||'Загрузка настроек анализатора…'}</p>
  return <section className="card section situation-settings"><h3>Анализатор ситуаций</h3>
    <p className="muted">Правила используют общую серверную аналитику. Ситуации видны в аналитике независимо от рассылки.</p>
    <label className="row"><input type="checkbox" checked={form.enabled} onChange={e=>setForm({...form,enabled:e.target.checked})}/>Аналитические уведомления проекта</label>
    <Field label="Приближение срока (минут, 5–1440)"><input type="number" min="5" max="1440" value={form.near_minutes} onChange={e=>setForm({...form,near_minutes:Number(e.target.value)})}/></Field>
    <Field label="Повторное напоминание (минут, 30–10080)"><input type="number" min="30" max="10080" value={form.reminder_minutes} onChange={e=>setForm({...form,reminder_minutes:Number(e.target.value)})}/></Field>
    <label className="row"><input type="checkbox" checked={form.mention_captains} onChange={e=>setForm({...form,mention_captains:e.target.checked})}/>Уведомлять и отмечать капитанов</label>
    <label className="row"><input type="checkbox" checked={form.mention_participants} onChange={e=>setForm({...form,mention_participants:e.target.checked})}/>Уведомлять и отмечать связанных участников</label>
    <p className="muted">{saved?.policy} Изменение временного порога также обновляет исходное состояние без рассылки. Проверка — каждые 30 секунд.</p>
    <p className="muted">Последняя фоновая проверка: {fmtDate(saved?.checked_at??null)}. Темы пяти событий задаются ниже в Telegram.</p>
    {error&&<p className="error" role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    <button className="primary" disabled={busy} onClick={async()=>{setBusy(true);setError('');setMessage('');try{const {enabled,near_minutes,reminder_minutes,mention_captains,mention_participants}=form;const v=await api.saveSituationSettings({enabled,near_minutes,reminder_minutes,mention_captains,mention_participants});setSaved(v);setForm(v);setMessage('Настройки анализатора сохранены')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>Сохранить анализатор</button>
  </section>
}
