import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('situation shows level, evidence, limitations, state and links without an AI flow',async()=>{
  const out=await build({entryPoints:['src/Situations.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const m={exports:{}}
  new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
  const html=renderToStaticMarkup(createElement(m.exports.SituationCard,{item:{id:'blocked_start:1',status:'active',level:'attention',title:'Старт заблокирован',text:'Основание',grounds:['Жёсткая зависимость'],limitations:['План неполный'],suggestion:'Проверьте инцидент',task_ids:[1],incident_ids:[2],user_ids:[],track_ids:[],as_of:'2030-01-01T08:00:00',delivery_issue:'ROUTE_DISABLED'},onOpenTask(){},onOpenIncident(){},onPlanning(){}}))
  for(const text of ['Требует внимания','Действует','Основания и ограничения','Жёсткая зависимость','План неполный','Задача #1','Инцидент #2','Маршрут события выключен']) assert.ok(html.includes(text),text)
  assert.doesNotMatch(html,/Задать вопрос|Gemini|Запустить анализ/)
})

test('internal situation notifications name the lifecycle event',async()=>{
  const out=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const m={exports:{}}
  new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
  const html=renderToStaticMarkup(createElement(m.exports.NotificationItem,{notification:{id:1,type:'situation_resolved',payload:{title:'Старт задачи'},created_at:'2030-01-01T08:00:00'},onOpen(){},onRead(){},onDelete(){}}))
  assert.ok(html.includes('Ситуация разрешена'))
})
